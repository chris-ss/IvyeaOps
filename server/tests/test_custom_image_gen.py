"""Custom image provider: /assistant/image handles BOTH Apimart async (task_id)
and standard OpenAI-compatible sync (b64_json/url) responses."""
from __future__ import annotations

import asyncio
import base64

from app.routers import assistant


def _fake_client(payload: dict, status: int = 200):
    class FakeResp:
        status_code = status
        text = ""

        def json(self):
            return payload

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return FakeResp()

    return FakeClient


def test_sync_openai_response_stashed_as_completed_job(monkeypatch):
    monkeypatch.setattr(assistant, "_image_cfg",
                        lambda: {"model": "dall-e-3", "api_key": "sk", "base_url": "https://x/v1"})
    b64 = base64.b64encode(b"img").decode()
    monkeypatch.setattr(assistant.httpx, "AsyncClient", _fake_client({"data": [{"b64_json": b64}]}))

    res = asyncio.run(assistant.image_submit(assistant.ImageReq(prompt="a cat"), _user="t"))
    tid = res["task_id"]
    assert tid.startswith("sync_")
    job = assistant._EDIT_JOBS[tid]
    assert job["status"] == "completed"
    assert job["images"][0].startswith("data:image/png;base64,")


def test_async_apimart_task_id_preserved(monkeypatch):
    monkeypatch.setattr(assistant, "_image_cfg",
                        lambda: {"model": "gpt-image-2", "api_key": "sk", "base_url": "https://apimart/v1"})
    monkeypatch.setattr(assistant.httpx, "AsyncClient", _fake_client({"data": [{"task_id": "t123"}]}))

    res = asyncio.run(assistant.image_submit(assistant.ImageReq(prompt="a cat"), _user="t"))
    assert res["task_id"] == "t123"  # async path untouched


def test_sync_url_response_supported(monkeypatch):
    monkeypatch.setattr(assistant, "_image_cfg",
                        lambda: {"model": "x", "api_key": "sk", "base_url": "https://x/v1"})
    monkeypatch.setattr(assistant.httpx, "AsyncClient",
                        _fake_client({"data": [{"url": "https://img/a.png"}]}))

    res = asyncio.run(assistant.image_submit(assistant.ImageReq(prompt="p"), _user="t"))
    assert assistant._EDIT_JOBS[res["task_id"]]["images"] == ["https://img/a.png"]
