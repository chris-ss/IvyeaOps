"""Skill Architect pipeline tests.

The LLM is mocked: we monkeypatch ``ai_synthesis_service.generate_text`` and
branch the canned response on a unique substring of each stage's prompt, so the
full state machine (understand → plan → review → optimize → render →
validate+repair) runs without any network call.
"""
from __future__ import annotations

import asyncio
import json

from app.services import ai_synthesis_service, skill_architect


_GOOD_MD = """---
name: keyword-report
description: Keyword market report
description_zh: 关键词市场报告
category: amazon/market
icon: "\U0001F4CA"
inputs:
  - name: keyword
    label: 关键词
    type: keyword
    required: true
    placeholder: 如 yoga mat
    default: ""
    options: []
tool:
  kind: report
  runtime: mcp
  inputs:
    - name: keyword
      label: 关键词
      type: keyword
      required: true
  output:
    format: markdown
    persist: true
    exportable: true
  sample_params:
    keyword: yoga mat
---

# 关键词市场报告

针对 {{keyword}} 生成市场报告。

## 步骤
1. 调用 mcp_sorftime_keyword_detail，传入 {{keyword}}。
2. 汇总成报告。
"""

_BAD_MD = """---
name: Bad Name
description: x
---

# 缺少 inputs 和 tool 块，name 也非法
"""

_UNDERSTAND = {
    "restated": "做一个关键词市场报告工具",
    "tool_kind": "report",
    "runtime": "mcp",
    "name": "keyword-report",
    "category": "amazon/market",
    "icon": "📊",
    "description": "Keyword market report",
    "description_zh": "关键词市场报告",
    "candidate_inputs": [{"name": "keyword", "label": "关键词", "type": "keyword", "required": True}],
    "output_format": "markdown",
    "clarifications": [],
}

_PLAN = {
    "name": "keyword-report",
    "category": "amazon/market",
    "icon": "📊",
    "description": "Keyword market report",
    "description_zh": "关键词市场报告",
    "tool_kind": "report",
    "runtime": "mcp",
    "inputs": [{"name": "keyword", "label": "关键词", "type": "keyword", "required": True}],
    "steps": ["第1步：调用 mcp_sorftime_keyword_detail"],
    "output_schema": "markdown 报告",
    "mcp_tools_used": ["mcp_sorftime_keyword_detail"],
    "pitfalls": [],
}


def _install_fake(monkeypatch, *, understand=None, render=_GOOD_MD, repair=_GOOD_MD, review=None):
    understand = understand if understand is not None else _UNDERSTAND
    review = review if review is not None else {"issues": [], "must_fix": [], "score": 9}

    async def fake(prompt: str) -> str:
        if "理解需求" in prompt:
            return json.dumps(understand, ensure_ascii=False)
        if "制定一份清晰" in prompt:
            return json.dumps(_PLAN, ensure_ascii=False)
        if "方案评审" in prompt:
            return json.dumps(review, ensure_ascii=False)
        if "根据评审意见优化" in prompt:
            return json.dumps(_PLAN, ensure_ascii=False)
        if "没有通过校验" in prompt:
            return repair
        if "渲染" in prompt:
            return render
        return "{}"

    monkeypatch.setattr(ai_synthesis_service, "generate_text", fake)


# ── validate_skill_md unit ──────────────────────────────────────────────

def test_validate_good():
    fm, body = _parse(_GOOD_MD)
    errors, _ = skill_architect.validate_skill_md(fm, body)
    assert errors == []


def test_validate_catches_problems():
    fm, body = _parse(_BAD_MD)
    errors, _ = skill_architect.validate_skill_md(fm, body)
    joined = " ".join(errors)
    assert "name" in joined
    assert "tool" in joined
    assert "inputs" in joined


def _parse(md: str):
    from app.services import skill_repo
    return skill_repo._parse_skill_md(md)


# ── oneshot happy path ──────────────────────────────────────────────────

def test_oneshot_happy(monkeypatch):
    _install_fake(monkeypatch)
    res = asyncio.run(skill_architect.run_oneshot("一个关键词报告工具", None, None))
    assert res["name"] == "keyword-report"
    assert res["category"] == "amazon/market"
    assert res["validation"]["ok"] is True
    assert res["validation"]["attempts"] == 0
    assert res["frontmatter"]["tool"]["kind"] == "report"
    assert res["plan"]["name"] == "keyword-report"
    # top-level inputs preserved for the legacy visual layer
    assert res["frontmatter"]["inputs"][0]["name"] == "keyword"


# ── clarify → plan two-step ─────────────────────────────────────────────

def test_clarify_then_plan(monkeypatch):
    ambiguous = dict(_UNDERSTAND)
    ambiguous["clarifications"] = [{"question": "针对哪个站点?", "options": ["US", "UK"]}]
    _install_fake(monkeypatch, understand=ambiguous)

    first = asyncio.run(skill_architect.run_plan("含糊需求", None, None, None))
    assert first["stage"] == "clarify"
    assert first["clarifications"][0]["question"] == "针对哪个站点?"

    second = asyncio.run(
        skill_architect.run_plan("含糊需求", None, None, {"针对哪个站点?": "US"})
    )
    assert second["stage"] == "plan"
    assert second["plan"]["name"] == "keyword-report"


# ── validation triggers repair ──────────────────────────────────────────

def test_render_invalid_then_repaired(monkeypatch):
    _install_fake(monkeypatch, render=_BAD_MD, repair=_GOOD_MD)
    res = asyncio.run(skill_architect.generate_and_validate(_PLAN))
    assert res["validation"]["attempts"] == 1
    assert res["validation"]["ok"] is True
    assert res["name"] == "keyword-report"


def test_extract_strips_yaml_fence():
    wrapped = "```yaml\n" + _GOOD_MD + "```"
    out = skill_architect._extract_skill_md(wrapped)
    assert out.startswith("---")
    assert "```" not in out


def test_extract_trims_leading_prose():
    out = skill_architect._extract_skill_md("好的，这是结果：\n\n" + _GOOD_MD)
    assert out.startswith("---")


def test_render_yaml_fenced_is_unwrapped(monkeypatch):
    # The exact bug from the field: model wrapped the whole SKILL.md in ```yaml.
    _install_fake(monkeypatch, render="```yaml\n" + _GOOD_MD + "```")
    res = asyncio.run(skill_architect.generate_and_validate(_PLAN))
    assert res["validation"]["ok"] is True
    assert res["validation"]["attempts"] == 0          # parsed first try, no repair
    assert res["frontmatter"]["tool"]["kind"] == "report"
    assert res["frontmatter"]["inputs"][0]["name"] == "keyword"


# ── prompts are seeded and editable ─────────────────────────────────────

def test_prompts_seeded():
    prompts = skill_architect.list_prompts()
    assert set(prompts) >= {"01_understand", "05_generate", "repair"}
    assert (skill_architect._prompts_dir() / "01_understand.md").exists()
