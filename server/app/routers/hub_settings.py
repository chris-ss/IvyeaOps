"""GET /api/settings  ·  PATCH /api/settings  ·  GET /api/settings/health"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core import hub_settings as _hs
from app.core.security import require_user

router = APIRouter()

_SECRET_KEYS: List[str] = [
    "apimart_key", "sorftime_key", "sif_key", "sellersprite_key",
    "alert_app_secret", "alert_webhook", "openai_api_key",
]

# Keys that, when changed, require syncing into Hermes config.
_HERMES_SYNC_KEYS = {"sorftime_key", "sif_key", "sellersprite_key"}


class SettingsPatch(BaseModel):
    settings: Dict[str, Any]


class TestRequest(BaseModel):
    key: str
    value: str | None = None


@router.get("/settings")
async def get_settings(_u: str = Depends(require_user)):
    return {"settings": _hs.load(), "secret_keys": _SECRET_KEYS}


@router.patch("/settings")
async def patch_settings(body: SettingsPatch, _u: str = Depends(require_user)):
    updated = _hs.save(body.settings)
    # Sync data-source keys into Hermes config if any relevant key was touched.
    if _HERMES_SYNC_KEYS & body.settings.keys():
        try:
            from app.services.hermes_config_sync import on_settings_saved
            on_settings_saved(updated)
        except Exception:
            pass  # non-fatal — settings are saved regardless
    return {"settings": updated, "secret_keys": _SECRET_KEYS}


@router.post("/settings/test")
async def test_setting(body: TestRequest, _u: str = Depends(require_user)):
    """Probe one config key with the provided (or stored) value."""
    from app.services import settings_test
    return await settings_test.test_value(body.key, body.value)


@router.post("/settings/autodetect")
async def autodetect_settings(_u: str = Depends(require_user)):
    """Scan the host for known integration paths and return suggestions."""
    from app.services import settings_test
    return settings_test.autodetect()


@router.get("/settings/health")
async def settings_health(_u: str = Depends(require_user)):
    """Quick connectivity / existence check for every configured service."""
    cfg = _hs.load()

    async def _check_http(url: str, timeout: float = 3.0) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as c:
                r = await c.get(url)
            return {"ok": r.status_code < 500, "detail": f"HTTP {r.status_code}"}
        except httpx.ConnectError:
            return {"ok": False, "detail": "连接被拒绝（服务未启动）"}
        except Exception as e:
            return {"ok": False, "detail": str(e)[:120]}

    def _check_key(key: str, label: str) -> Dict[str, Any]:
        val = cfg.get(key, "")
        if val:
            return {"ok": True, "detail": f"已配置（{label}）"}
        return {"ok": False, "detail": "未配置"}

    def _check_bin(path: str) -> Dict[str, Any]:
        if not path:
            return {"ok": False, "detail": "未配置路径"}
        p = Path(path)
        if p.exists():
            return {"ok": True, "detail": str(p)}
        # Try auto-detect common locations
        import shutil
        name = p.name
        found = shutil.which(name)
        if found:
            return {"ok": True, "detail": f"自动发现 {found}"}
        return {"ok": False, "detail": f"未找到：{path}"}

    def _check_runner(name: str) -> Dict[str, Any]:
        from app.services.runners import _find_bin
        p = _find_bin(name)
        if p:
            return {"ok": True, "detail": p}
        return {"ok": False, "detail": "未安装"}

    imgflow_url = (cfg.get("imgflow_url") or "http://127.0.0.1:3001").rstrip("/")
    gbrain_bin = cfg.get("gbrain_bin") or ""
    if not gbrain_bin:
        gbrain_bin = __import__("os").environ.get("OPSHUB_GBRAIN_BIN", "/usr/local/bin/gbrain")

    brain_root = cfg.get("brain_root") or ""
    if not brain_root:
        brain_root = __import__("os").environ.get("OPSHUB_BRAIN_ROOT") or str(Path.home() / "brain")

    imgflow_result, = await asyncio.gather(_check_http(imgflow_url + "/"))

    from app.core import integrations as _integ
    return {
        "apimart":   _check_key("apimart_key", "API Key 已设置"),
        "sorftime":  _check_key("sorftime_key", "API Key 已设置"),
        "imgflow":   imgflow_result,
        "gbrain_bin": _check_bin(gbrain_bin),
        "brain_root": {
            "ok": Path(brain_root).exists(),
            "detail": brain_root if Path(brain_root).exists() else f"目录不存在：{brain_root}",
        },
        "openai":    _check_key("openai_api_key", "API Key 已设置"),
        "runners": {
            "hermes": _check_runner("hermes"),
            "codex":  _check_runner("codex"),
            "claude": _check_runner("claude"),
        },
        "integrations": _integ.all_status(),
    }
