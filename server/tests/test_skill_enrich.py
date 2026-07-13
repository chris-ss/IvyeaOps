"""AI 工具化（enrich）：文档型 skill → Tool Spec 提案，审核制、不改名。"""
from __future__ import annotations

import asyncio

from app.services import ai_synthesis_service, skill_architect

_GOOD_MD = """---
name: renamed-by-model
description: Analyze competitor listings
description_zh: 竞品 Listing 分析
category: creative
icon: "◇"
inputs:
  - name: asin
    label: 产品ASIN
    type: asin
    required: true
tool:
  kind: report
  runtime: llm-only
  inputs:
    - name: asin
      label: 产品ASIN
      type: asin
      required: true
  output:
    format: markdown
    persist: true
    exportable: true
  sample_params:
    asin: B0EXAMPLE1
---
## 使用参数
- {{asin}}：要分析的产品

## 执行步骤
1. 分析 {{asin}} 的 Listing
"""

_BAD_MD = """---
description: missing everything else
---
正文
"""


def test_enrich_keeps_original_name(monkeypatch):
    async def fake_gen(prompt):
        return _GOOD_MD

    monkeypatch.setattr(ai_synthesis_service, "generate_text", fake_gen)
    res = asyncio.run(skill_architect.enrich_and_validate("creative/foo-skill", "---\nname: foo-skill\n---\ndoc"))
    # 模型试图改名 renamed-by-model，必须被压回原名
    assert res["frontmatter"]["name"] == "foo-skill"
    assert res["name"] == "creative/foo-skill"
    assert res["validation"]["ok"] is True
    assert res["validation"]["attempts"] == 0
    assert len(res["frontmatter"]["inputs"]) == 1
    assert res["frontmatter"]["tool"]["kind"] == "report"


def test_enrich_invalid_first_pass_gets_repaired(monkeypatch):
    calls = {"n": 0}

    async def fake_gen(prompt):
        calls["n"] += 1
        return _BAD_MD if calls["n"] == 1 else _GOOD_MD

    monkeypatch.setattr(ai_synthesis_service, "generate_text", fake_gen)
    res = asyncio.run(skill_architect.enrich_and_validate("creative/foo-skill", "---\nname: foo-skill\n---\ndoc"))
    assert res["validation"]["ok"] is True
    assert res["validation"]["attempts"] == 1
    assert res["frontmatter"]["name"] == "foo-skill"


def test_enrich_endpoint_404_for_missing_skill():
    from fastapi import HTTPException

    from app.routers import skill_tools as st

    try:
        asyncio.run(st.enrich_tool(st.EnrichBody(skill_name="no/such-skill-xyz")))
        raise AssertionError("should have raised")
    except HTTPException as e:
        assert e.status_code == 404
