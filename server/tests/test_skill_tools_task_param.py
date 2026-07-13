"""Skill 商店通用 task 参数：作为「任务要求」独立注入 prompt，不混入参数列表。"""
from __future__ import annotations

import asyncio

from app.routers import skill_tools as st
from app.services import ai_synthesis_service


class _FakeDetail:
    content_body = "按 {{style}} 风格处理。"
    name = "creative/x"
    frontmatter: dict = {}


def test_llm_only_task_becomes_task_section(monkeypatch):
    captured = {}

    async def fake_stream_text(prompt):
        captured["prompt"] = prompt
        yield ("deepseek", "ok")

    monkeypatch.setattr(ai_synthesis_service, "stream_text", fake_stream_text)

    async def go():
        async for _ in st._run_llm_only(_FakeDetail(), {"task": "帮我做一张信息图", "style": "简洁"}):
            pass

    asyncio.run(go())
    p = captured["prompt"]
    assert "## 任务要求\n帮我做一张信息图" in p
    assert "- style: 简洁" in p
    assert "- task:" not in p          # task 不重复出现在参数列表
    assert "按 简洁 风格处理" in p      # {{style}} 已替换


def test_llm_only_without_task_keeps_legacy_shape(monkeypatch):
    captured = {}

    async def fake_stream_text(prompt):
        captured["prompt"] = prompt
        yield ("deepseek", "ok")

    monkeypatch.setattr(ai_synthesis_service, "stream_text", fake_stream_text)

    async def go():
        async for _ in st._run_llm_only(_FakeDetail(), {"style": "简洁"}):
            pass

    asyncio.run(go())
    assert "## 任务要求" not in captured["prompt"]
    assert "- style: 简洁" in captured["prompt"]
