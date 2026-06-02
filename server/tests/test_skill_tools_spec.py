"""Tool Spec parsing tests for the visual layer (skill_tools).

Verifies the enrichment: the `tool:` block is read authoritatively, inputs
resolve in the right precedence, and legacy skills (no tool block) still work.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.routers import skill_tools as st


def _detail(frontmatter, body, name="amazon/keyword-report"):
    return SimpleNamespace(
        name=name,
        category=frontmatter.get("category"),
        description=frontmatter.get("description"),
        description_zh=frontmatter.get("description_zh"),
        frontmatter=frontmatter,
        content_body=body,
    )


def test_tool_spec_is_read():
    fm = {
        "name": "keyword-report",
        "description": "x",
        "category": "amazon/market",
        "inputs": [{"name": "keyword", "label": "关键词", "type": "keyword", "required": True}],
        "tool": {
            "kind": "report",
            "runtime": "mcp",
            "inputs": [{"name": "keyword", "label": "关键词", "type": "keyword", "required": True}],
            "output": {"format": "markdown", "persist": True, "exportable": True},
            "sample_params": {"keyword": "yoga mat"},
        },
    }
    meta = st._build_meta(_detail(fm, "针对 {{keyword}} 生成报告"), pinned=False)
    assert meta.kind == "report"
    assert meta.runtime == "mcp"
    assert meta.output_format == "markdown"
    assert meta.exportable is True
    assert meta.sample_params == {"keyword": "yoga mat"}
    assert meta.has_execution is True
    assert meta.inputs[0]["name"] == "keyword"


def test_tool_inputs_take_precedence_over_body():
    fm = {
        "name": "t", "description": "x",
        "tool": {"kind": "transform", "inputs": [{"name": "text", "type": "textarea"}]},
    }
    # body also has a different {{var}} — tool.inputs must win
    meta = st._build_meta(_detail(fm, "use {{other}} here"), pinned=False)
    assert [i["name"] for i in meta.inputs] == ["text"]
    assert meta.kind == "transform"


def test_legacy_skill_without_tool_block():
    fm = {"name": "old", "description": "x"}
    meta = st._build_meta(_detail(fm, "step 1: do {{asin}}"), pinned=False)
    assert meta.kind is None
    assert meta.runtime is None
    assert meta.output_format == "markdown"
    assert meta.exportable is False
    # falls back to body {{var}} scraping
    assert meta.inputs[0]["name"] == "asin"
    assert meta.has_execution is True
