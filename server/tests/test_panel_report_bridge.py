"""Agent → panel bridge: *_generate_report tools run the real flow and persist to history."""
from __future__ import annotations

import asyncio

import app.routers.market as market
import app.routers.playbook as playbook
from app.services import (ai_synthesis_service, ivyea_ops_tools,
                          playbook_synthesis_service, sorftime_service)


def test_market_generate_report_persists_to_history(tmp_path, monkeypatch):
    monkeypatch.setattr(market, "_history_db_path", lambda: str(tmp_path / "mh.sqlite3"))

    async def fake_kw(q, m, prog):
        return ({"k": 1}, [])

    monkeypatch.setattr(sorftime_service, "keyword_pipeline", fake_kw)

    async def fake_synth(mode, q, m, data, skip_agent=False):
        assert skip_agent is True            # bridge must not re-enter the agent
        yield ("_attempt", "deepseek")
        yield ("deepseek", "# 市场调研报告\n正文")

    monkeypatch.setattr(ai_synthesis_service, "synthesize", fake_synth)

    res = asyncio.run(ivyea_ops_tools.call_tool("market_generate_report", {"query": "yoga mat"}))
    assert res["ok"] is True
    assert res["result"]["saved_to"] == "market_history"
    hist = market.get_history(_user="bridge")
    assert len(hist) == 1 and hist[0]["query"] == "yoga mat" and hist[0]["report"]


def test_playbook_generate_report_persists_to_history(tmp_path, monkeypatch):
    monkeypatch.setattr(playbook, "_history_db_path", lambda: str(tmp_path / "pb.sqlite3"))

    async def fake_kw(q, m, prog):
        return ({"k": 1}, [])

    monkeypatch.setattr(sorftime_service, "keyword_pipeline", fake_kw)

    async def fake_synth(mode, q, m, price, cost, data, skip_agent=False):
        assert skip_agent is True
        yield ("_attempt", "deepseek")
        yield ("deepseek", "# 打法推荐\n正文")

    monkeypatch.setattr(playbook_synthesis_service, "synthesize", fake_synth)

    res = asyncio.run(ivyea_ops_tools.call_tool("playbook_generate_report", {"query": "yoga mat"}))
    assert res["ok"] is True
    assert res["result"]["saved_to"] == "playbook_history"
    assert len(playbook.get_history(_user="bridge")) == 1


def test_deep_generate_report_persists_to_history(tmp_path, monkeypatch):
    import app.routers.deep_analysis as da
    from app.services import sif_service
    monkeypatch.setattr(da, "_history_db_path", lambda: str(tmp_path / "dh.sqlite3"))

    async def fake_kw(q, c, a):
        return {"top": [{"asin": "B0", "share": 0.1}]}

    monkeypatch.setattr(sif_service, "keyword_competition", fake_kw)

    async def fake_gen(prompt, skip_agent=False):
        assert skip_agent is True
        return "# 关键词竞争分析报告\n正文"

    monkeypatch.setattr(ai_synthesis_service, "generate_text", fake_gen)

    res = asyncio.run(ivyea_ops_tools.call_tool(
        "deep_generate_report", {"tool": "keyword", "query": "yoga mat"}))
    assert res["ok"] is True
    assert res["result"]["saved_to"] == "deep_analysis_history"
    hist = da.get_history(_user="bridge")
    assert len(hist) == 1 and hist[0]["tool"] == "keyword" and hist[0]["report"]


def test_synthesize_skip_agent_excludes_ivyea_agent(monkeypatch):
    monkeypatch.setattr(ai_synthesis_service, "_text_provider_chain", lambda: ["ivyea-agent", "deepseek"])
    monkeypatch.setattr(ai_synthesis_service, "_build_prompt", lambda *a: "p")
    called = {"agent": False}

    async def fake_agent(prompt, failures):
        called["agent"] = True
        yield ("_attempt", "ivyea-agent")

    async def fake_ds(prompt, failures):
        yield ("_attempt", "deepseek")
        yield ("deepseek", "ok")

    monkeypatch.setattr(ai_synthesis_service, "_try_ivyea_agent", fake_agent)
    monkeypatch.setattr(ai_synthesis_service, "_try_deepseek", fake_ds)

    async def run():
        return [(p, c) async for p, c in
                ai_synthesis_service.synthesize("keyword", "q", "US", {}, skip_agent=True)]

    out = asyncio.run(run())
    assert called["agent"] is False
    assert any(p == "deepseek" for p, _ in out)


def test_default_text_chain_leads_with_ivyea_agent():
    # Direction 1: panels default to IvyeaAgent (chain order), even with no config set.
    assert ai_synthesis_service._text_provider_chain()[0] == "ivyea-agent"


def test_new_generate_tools_registered_and_listed():
    names = {t.name for t in ivyea_ops_tools.TOOLS}
    assert {"market_generate_report", "playbook_generate_report"} <= names
    listed = {t["name"] for t in ivyea_ops_tools.list_tools(module="market")["tools"]}
    assert "market_generate_report" in listed
