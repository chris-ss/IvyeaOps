"""Config self-check probes + IvyeaAgent upgrade-from-IvyeaOps."""
from __future__ import annotations

import asyncio

from app.services import settings_test as st
from app.services import ai_synthesis_service, ivyea_agent_service as svc


def test_catchall_is_graceful_not_scary(monkeypatch):
    monkeypatch.setattr(st, "_hub_get", lambda k: "")
    # a setting with no online test + a value → soft-ok, never "未知配置项"
    r = asyncio.run(st.test_value("ivyea_agent_auto_start", "True"))
    assert r["ok"] is True and "未知配置项" not in r["detail"]
    # empty → clear "not configured"
    r2 = asyncio.run(st.test_value("whatever_key", ""))
    assert r2["ok"] is False and "未配置" in r2["detail"]


def test_provider_list_validation():
    good = asyncio.run(st.test_value("text_ai_providers", "ivyea-agent,deepseek"))
    assert good["ok"] is True
    bad = asyncio.run(st.test_value("text_ai_providers", "ivyea-agent,bogus"))
    assert bad["ok"] is False and "bogus" in bad["detail"]


def test_text_provider_roundtrip_catches_bad_key(monkeypatch):
    async def fake_gen(provider, prompt):
        if provider == "deepseek":
            return "可用"
        raise RuntimeError("401 unauthorized")
    monkeypatch.setattr(ai_synthesis_service, "generate_text_provider", fake_gen)
    monkeypatch.setattr(st, "_hub_get", lambda k: "sk-x")
    ok = asyncio.run(st.test_value("deepseek_api_key", "sk-x"))
    assert ok["ok"] is True
    bad = asyncio.run(st.test_value("assistant_api_key", "sk-x"))
    assert bad["ok"] is False and "401" in bad["detail"]


def test_self_check_returns_matrix(monkeypatch):
    # only deepseek + text_ai_providers configured
    monkeypatch.setattr(st, "_hub_get",
                        lambda k: "sk-x" if k == "deepseek_api_key"
                        else ("ivyea-agent,deepseek" if k == "text_ai_providers" else ""))

    async def fake_gen(provider, prompt):
        return "可用"
    monkeypatch.setattr(ai_synthesis_service, "generate_text_provider", fake_gen)

    res = asyncio.run(st.self_check())
    assert res["total"] == len(st._SELF_CHECK_KEYS)
    by_key = {r["key"]: r for r in res["results"]}
    assert by_key["deepseek_api_key"]["status"] == "ok"
    assert by_key["text_ai_providers"]["status"] == "ok"
    assert by_key["sorftime_key"]["status"] == "skip"   # not configured
    assert res["ok"] >= 2 and res["skip"] >= 1


def test_upgrade_agent_pip_and_restart(monkeypatch):
    monkeypatch.setattr(svc, "_find_ivyea_cli", lambda: "/root/.local/bin/ivyea")
    monkeypatch.setattr(svc, "_venv_python", lambda cli: "/usr/bin/python")
    versions = iter(["1.0.23", "1.0.24"])
    monkeypatch.setattr(svc, "agent_version", lambda: next(versions))
    ran = []

    def fake_run(cmd, timeout=300.0):
        ran.append(cmd)
        return {"cmd": " ".join(cmd[:4]), "returncode": 0, "stdout": "", "stderr": ""}
    monkeypatch.setattr(svc, "_run_step", fake_run)
    monkeypatch.setattr(svc, "start_local_service", lambda: {"ok": True})

    r = svc.upgrade_agent()
    assert r["ok"] is True and r["before"] == "1.0.23" and r["after"] == "1.0.24"
    assert any("pip" in c for c in ran[0])           # pip -U install
    assert any("service-stop" in c for c in ran[1])  # serve restart


def test_upgrade_agent_no_cli(monkeypatch):
    monkeypatch.setattr(svc, "_find_ivyea_cli", lambda: "")
    r = svc.upgrade_agent()
    assert r["ok"] is False and "未找到" in r["error"]
