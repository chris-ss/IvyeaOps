"""IvyeaAgent bridge routes inside IvyeaOps."""
from __future__ import annotations

import importlib
import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException


_ORIGIN = "https://test.example.com"
@pytest.fixture
def ctx(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("IVYEA_OPS_SECRET", "test-secret")
    monkeypatch.setenv("IVYEA_OPS_ALLOWED_ORIGINS", _ORIGIN)
    monkeypatch.setenv("AGENTS_DB_PATH", str(tmp_path / "agents.db"))
    monkeypatch.setenv("IVYEA_AGENT_URL", "127.0.0.1:9876")
    monkeypatch.setenv("IVYEA_AGENT_TOKEN", "secret-token")

    from app.core import config as cfg_mod
    importlib.reload(cfg_mod)
    from app.core import security as sec_mod
    importlib.reload(sec_mod)
    from app.services import ivyea_agent_service as svc_mod
    importlib.reload(svc_mod)
    from app.routers import ivyea_agent as router_mod
    importlib.reload(router_mod)

    return svc_mod, router_mod


class FakeRequest:
    base_url = "http://ops.test/"


def test_status_reports_local_agent_without_leaking_token(ctx, monkeypatch):
    svc, router = ctx
    monkeypatch.setattr(svc, "request_json", lambda *a, **k: {"ok": True, "name": "ivyea-agent"})

    body = router.status()
    assert body["available"] is True
    assert body["base_url"] == "http://127.0.0.1:9876"
    assert body["token_configured"] is True
    assert "secret-token" not in str(body)


def test_bootstrap_manifest_and_provider_routes_proxy(ctx, monkeypatch):
    svc, router = ctx
    monkeypatch.setattr(svc, "bootstrap", lambda: {"ok": True, "urls": {"manifest": "http://x/v1/manifest"}})
    monkeypatch.setattr(svc, "manifest", lambda: {"ok": True, "name": "ivyea-agent"})
    monkeypatch.setattr(svc, "model_providers", lambda: {"ok": True, "providers": [{"id": "openai"}]})
    seen = {}
    monkeypatch.setattr(svc, "provider_models", lambda provider_id, refresh=False: {
        "ok": True,
        "catalog": {"provider_id": provider_id, "refresh": refresh, "models": ["m"]},
    })
    def fake_probe(provider_id, payload):
        seen["probe"] = (provider_id, payload)
        return {"ok": True}

    monkeypatch.setattr(svc, "provider_probe", fake_probe)

    assert router.bootstrap()["urls"]["manifest"].endswith("/v1/manifest")
    assert router.manifest()["name"] == "ivyea-agent"
    assert router.model_providers()["providers"][0]["id"] == "openai"
    assert router.provider_models("openai", refresh=True)["catalog"]["refresh"] is True
    assert router.provider_probe("openai", router.ProviderProbeBody(model="m", timeout=3))["ok"] is True
    assert seen["probe"] == ("openai", {"model": "m", "timeout": 3.0})


def test_chat_routes_forward_payload(ctx, monkeypatch):
    svc, router = ctx
    seen = {}
    def fake_chat(payload):
        seen["chat"] = payload
        return {"ok": True, "text": "hi"}

    def fake_create(payload):
        seen["create"] = payload
        return {"ok": True, "session": {"id": "new"}}

    monkeypatch.setattr(svc, "chat", fake_chat)
    monkeypatch.setattr(svc, "chat_sessions", lambda limit=20: {"ok": True, "sessions": [{"id": "s1"}], "limit": limit})
    monkeypatch.setattr(svc, "chat_session", lambda session_id: {"ok": True, "session": {"id": session_id}})
    monkeypatch.setattr(svc, "chat_create", fake_create)
    monkeypatch.setattr(svc, "ensure_available", lambda: {"available": True})
    monkeypatch.setattr(svc, "chat_stream", lambda payload: iter([b"event: final\ndata: {\"ok\": true, \"text\": \"hi\"}\n\n"]))

    assert router.chat(router.ChatBody(message="你好", session_id="s1", max_steps=6), FakeRequest())["ok"] is True
    assert seen["chat"]["message"] == "你好"
    assert seen["chat"]["session_id"] == "s1"
    assert seen["chat"]["max_steps"] == 6
    assert seen["chat"]["inject_retrieval"] is True
    assert seen["chat"]["ops_bridge"]["base_url"] == "http://ops.test/api/ivyea-agent-bridge"
    assert seen["chat"]["ops_bridge"]["token"]
    assert router.chat_sessions(limit=3)["sessions"][0]["id"] == "s1"
    assert router.chat_session("s1")["session"]["id"] == "s1"
    assert router.chat_create(router.ChatSessionCreateBody(title="新会话"))["session"]["id"] == "new"
    assert seen["create"]["title"] == "新会话"
    streamed = router.chat_stream(router.ChatBody(message="stream"), FakeRequest())
    assert streamed.media_type == "text/event-stream"


def test_retrieval_sync_and_embeddings_proxy(ctx, monkeypatch):
    svc, router = ctx
    monkeypatch.setattr(svc, "retrieval_status", lambda: {"ok": True, "index": {"needs_rebuild": False}})
    monkeypatch.setattr(svc, "retrieval_embeddings", lambda: {"ok": True, "embeddings": {"active_backend": "hash"}})
    monkeypatch.setattr(svc, "retrieval_sync", lambda: {"ok": True, "changed": False})

    assert router.retrieval_status()["index"]["needs_rebuild"] is False
    assert router.retrieval_embeddings()["embeddings"]["active_backend"] == "hash"
    assert router.retrieval_sync()["changed"] is False


def test_knowledge_update_bridge_paths(ctx, monkeypatch):
    svc, _router = ctx
    calls = []

    def fake_request(method, path, payload=None, **_kwargs):
        calls.append((method, path, payload))
        return {"ok": True, "path": path}

    monkeypatch.setattr(svc, "request_json", fake_request)

    assert svc.knowledge_watchlist()["path"] == "/v1/knowledge/watchlist"
    assert svc.knowledge_cards(limit=5)["path"] == "/v1/knowledge/cards?limit=5"
    assert svc.knowledge_search("否词", limit=4)["path"].startswith("/v1/knowledge/search?")
    assert svc.knowledge_files(limit=9)["path"] == "/v1/knowledge/files?limit=9"
    assert svc.knowledge_uploads(limit=7)["path"] == "/v1/knowledge/uploads?limit=7"
    assert svc.knowledge_file("uploads/a.md")["path"].startswith("/v1/knowledge/file?")
    assert svc.knowledge_delete_file("uploads/a.md")["path"].startswith("/v1/knowledge/file?")
    assert svc.knowledge_update_draft({"body": "draft"})["path"] == "/v1/knowledge/update/draft"
    assert svc.knowledge_update_apply({"body": "apply", "confirm": True})["path"] == "/v1/knowledge/update/apply"
    assert svc.knowledge_upload({"filename": "a.md", "content_base64": "YQ=="})["path"] == "/v1/knowledge/upload"
    assert svc.knowledge_upload_apply({"upload_id": "up1", "confirm": True})["path"] == "/v1/knowledge/uploads/apply"
    assert svc.knowledge_import_directory({"root": "/tmp/brain", "confirm": False, "max_files": 3})["path"] == "/v1/knowledge/import-directory"
    assert calls[0] == ("GET", "/v1/knowledge/watchlist", None)
    assert calls[-3] == ("POST", "/v1/knowledge/upload", {"filename": "a.md", "content_base64": "YQ=="})
    assert calls[-2] == ("POST", "/v1/knowledge/uploads/apply", {"upload_id": "up1", "confirm": True})
    assert calls[-1][0] == "POST"
    assert calls[-1][1] == "/v1/knowledge/import-directory"
    assert calls[-1][2]["root"] == "/tmp/brain"
    assert calls[-1][2]["namespace"] == "gbrain"


def test_knowledge_update_routes_forward_payload(ctx, monkeypatch):
    svc, router = ctx
    seen = {}
    monkeypatch.setattr(svc, "knowledge_watchlist", lambda: {"ok": True, "sources": [{"id": "amazon_ads.sponsored_products"}]})
    monkeypatch.setattr(svc, "knowledge_cards", lambda limit=200: {"ok": True, "cards": [{"id": "c"}], "limit": limit})
    monkeypatch.setattr(svc, "knowledge_search", lambda q, limit=8: {"ok": True, "results": [{"id": q}], "limit": limit})
    monkeypatch.setattr(svc, "knowledge_files", lambda limit=500: {"ok": True, "uploads": [], "cards": [], "limit": limit})
    monkeypatch.setattr(svc, "knowledge_uploads", lambda limit=50: {"ok": True, "uploads": [{"id": "up"}], "limit": limit})
    monkeypatch.setattr(svc, "knowledge_file", lambda path: {"ok": True, "file": {"path": path}})
    monkeypatch.setattr(svc, "knowledge_delete_file", lambda path: {"ok": True, "path": path})

    def fake_draft(payload):
        seen["draft"] = payload
        return {"ok": True, "draft": {"action": "create", "card_id": payload["id"]}}

    def fake_apply(payload):
        seen["apply"] = payload
        return {"ok": True, "result": {"applied": payload["confirm"]}}

    monkeypatch.setattr(svc, "knowledge_update_draft", fake_draft)
    monkeypatch.setattr(svc, "knowledge_update_apply", fake_apply)
    monkeypatch.setattr(svc, "knowledge_import_directory", lambda payload: {
        "ok": True,
        "import": {"summary": {"candidate_files": payload["max_files"], "imported": 0}, "confirm": payload["confirm"]},
    })

    assert router.knowledge_watchlist()["sources"][0]["id"] == "amazon_ads.sponsored_products"
    assert router.knowledge_cards(limit=2)["limit"] == 2
    assert router.knowledge_search(q="否词", limit=3)["results"][0]["id"] == "否词"
    assert router.knowledge_files(limit=4)["limit"] == 4
    assert router.knowledge_uploads(limit=5)["uploads"][0]["id"] == "up"
    assert router.knowledge_file(path="uploads/a.md")["file"]["path"] == "uploads/a.md"
    assert router.knowledge_delete_file(path="uploads/a.md")["path"] == "uploads/a.md"
    body = router.KnowledgeUpdateBody(
        id="user.ops-note",
        title="Ops note",
        body="知识更新内容",
        source_url="https://advertising.amazon.com/solutions/products/sponsored-products",
        source_type="official",
        tags=["budget"],
        confirm=True,
        rebuild=False,
    )
    assert router.knowledge_update_draft(body)["draft"]["card_id"] == "user.ops-note"
    assert router.knowledge_update_apply(body)["result"]["applied"] is True
    migrated = router.knowledge_import_directory(router.KnowledgeImportDirectoryBody(max_files=6, confirm=False))
    assert migrated["import"]["summary"]["candidate_files"] == 6
    assert migrated["import"]["confirm"] is False
    assert seen["draft"]["tags"] == ["budget"]
    assert seen["apply"]["confirm"] is True
    assert seen["apply"]["rebuild"] is False


def test_knowledge_upload_route_encodes_file(ctx, monkeypatch):
    svc, router = ctx
    seen = {}

    class FakeUpload:
        filename = "note.md"

        async def read(self, _limit):
            return b"# Note\n\nupload body"

    def fake_upload(payload):
        seen.update(payload)
        return {"ok": True, "upload": {"id": "up1"}}

    monkeypatch.setattr(svc, "knowledge_upload", fake_upload)
    monkeypatch.setattr(svc, "knowledge_upload_apply", lambda payload: {"ok": True, "result": {"applied": payload["confirm"]}})

    try:
        result = asyncio.run(router.knowledge_upload(
            file=FakeUpload(),
            title="Note",
            id="user.note",
            source_url="https://example.com",
            source_type="official",
            confidence="high",
            license="public_summary",
            tags="a,b",
            confirm=False,
            rebuild=False,
        ))
    finally:
        asyncio.set_event_loop(asyncio.new_event_loop())
    assert result["upload"]["id"] == "up1"
    assert seen["filename"] == "note.md"
    assert seen["content_base64"]
    assert seen["tags"] == ["a", "b"]
    assert seen["rebuild"] is False
    assert router.knowledge_upload_apply(router.KnowledgeUploadApplyBody(upload_id="up1", confirm=True))["result"]["applied"] is True


def test_code_bundle_validates_and_forwards_payload(ctx, monkeypatch, tmp_path):
    svc, router = ctx
    seen = {}

    def fake_bundle(payload):
        seen.update(payload)
        return {"ok": True, "bundle": {"mode": "read-only-task-bundle"}}

    monkeypatch.setattr(svc, "code_bundle", fake_bundle)
    monkeypatch.setattr(svc, "code_apply_loop", lambda payload: {
        "ok": True,
        "run": {"mode": "execute" if payload["execute"] else "dry-run"},
    })
    body = router.CodeBundleBody(
        root=str(tmp_path),
        goal="fix tests",
        test_output="failed",
        limit=4,
    )
    result = router.code_bundle(body)
    assert result["bundle"]["mode"] == "read-only-task-bundle"
    assert seen == {"root": str(tmp_path), "goal": "fix tests", "test_output": "failed", "limit": 4}

    loop = router.code_apply_loop(router.CodeApplyLoopBody(
        root=str(tmp_path),
        spec={"ops": []},
        execute=False,
        persist=False,
    ))
    assert loop["run"]["mode"] == "dry-run"


def test_service_management_routes_forward_payload(ctx, monkeypatch):
    svc, router = ctx
    seen = {}
    monkeypatch.setattr(svc, "service_status", lambda host="", port=None: {"ok": True, "service": {"host": host, "port": port}})
    monkeypatch.setattr(svc, "service_logs", lambda lines=80: {"ok": True, "logs": {"lines": ["x"], "limit": lines}})
    def fake_start(payload):
        seen["start"] = payload
        return {"ok": True}

    def fake_stop(payload):
        seen["stop"] = payload
        return {"ok": True}

    def fake_autostart(payload):
        seen["autostart"] = payload
        return {"ok": True}

    monkeypatch.setattr(svc, "service_start", fake_start)
    monkeypatch.setattr(svc, "service_stop", fake_stop)
    monkeypatch.setattr(svc, "service_autostart", fake_autostart)

    assert router.service_status(host="127.0.0.1", port=8765)["service"]["port"] == 8765
    assert router.service_logs(lines=3)["logs"]["limit"] == 3
    assert router.service_start(router.ServiceStartBody(host="127.0.0.1", port=9876, api_token="secret"))["ok"] is True
    assert router.service_stop(router.ServiceStopBody(force=True))["ok"] is True
    assert router.service_autostart(router.ServiceAutostartBody(port=9876))["ok"] is True
    assert seen["start"]["port"] == 9876
    assert seen["start"]["api_token"] == "secret"
    assert seen["stop"]["force"] is True
    assert seen["autostart"]["port"] == 9876


def test_model_config_sync_forwards_settings(ctx, monkeypatch):
    svc, _router = ctx
    calls = []

    def fake_request(method, path, payload=None, **_kwargs):
        calls.append((method, path, payload))
        return {"ok": True, "model": {"model": payload["model"]}}

    monkeypatch.setattr(svc, "request_json", fake_request)
    result = svc.sync_model_settings({
        "ivyea_agent_provider": "openrouter",
        "ivyea_agent_model": "anthropic/claude-sonnet-4.6",
        "ivyea_agent_api_key": "sk-secret",
        "ivyea_agent_base_url": "",
    }, force=True)

    assert result["ok"] is True
    assert calls == [("POST", "/v1/model/configure", {
        "provider": "openrouter",
        "model": "anthropic/claude-sonnet-4.6",
        "api_key": "sk-secret",
    })]


def test_ops_tools_permission_filter_and_bridge_token(ctx):
    _svc, router = ctx
    from app.core.security import current_user
    from app.services import ivyea_ops_tools

    current_user.set({"id": 7, "role": "user", "email": "u@example.com", "permissions": ["listing"]})
    tools = ivyea_ops_tools.list_tools()
    names = {row["name"] for row in tools["tools"]}
    assert "listing_projects" in names
    assert "market_history" in names  # base module
    assert "monitor_snapshot" not in names

    token = ivyea_ops_tools.issue_bridge_token()
    current_user.set(None)
    listed = router.bridge_tools(router.OpsToolsListBody(module="listing"), authorization=f"Bearer {token}")
    assert listed["principal"]["email"] == "u@example.com"
    assert {row["name"] for row in listed["tools"]} >= {"listing_projects"}


def test_unavailable_agent_maps_to_503(ctx, monkeypatch):
    svc, router = ctx
    monkeypatch.setattr(svc, "bootstrap", lambda: (_ for _ in ()).throw(svc.IvyeaAgentUnavailable("down")))

    with pytest.raises(HTTPException) as exc:
        router.bootstrap()
    assert exc.value.status_code == 503
    assert "IvyeaAgent 不可用" in exc.value.detail


def test_service_availability_handles_unreachable(ctx, monkeypatch):
    svc, _router = ctx
    monkeypatch.setattr(svc, "request_json", lambda *a, **k: (_ for _ in ()).throw(svc.IvyeaAgentUnavailable("offline")))

    body = svc.availability()
    assert body["ok"] is False
    assert body["available"] is False
    assert "offline" in body["error"]
