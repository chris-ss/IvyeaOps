"""Client bridge from IvyeaOps to the local IvyeaAgent HTTP API."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from app.core.config import settings as ops_settings
from app.core.proc import no_window_kwargs


DEFAULT_BASE_URL = "http://127.0.0.1:8765"
DEFAULT_TIMEOUT_SECONDS = 5.0
AUTOSTART_COOLDOWN_SECONDS = 20.0
_LAST_START_ATTEMPT = 0.0
_LAST_MODEL_SYNC_SIGNATURE = ""


class IvyeaAgentError(RuntimeError):
    """Base error for IvyeaAgent bridge failures."""


class IvyeaAgentUnavailable(IvyeaAgentError):
    """The local IvyeaAgent service is not reachable."""


def base_url() -> str:
    """Return the configured local IvyeaAgent base URL."""
    from app.core import hub_settings
    raw = (str(hub_settings.get("ivyea_agent_url") or "") or os.getenv("IVYEA_AGENT_URL") or DEFAULT_BASE_URL).strip()
    if not raw:
        raw = DEFAULT_BASE_URL
    if "://" not in raw:
        raw = f"http://{raw}"
    return raw.rstrip("/")


def token_configured() -> bool:
    return bool(_token())


def _find_ivyea_cli() -> str:
    found = shutil.which("ivyea")
    if found:
        return found
    candidates = [
        Path(sys.executable).resolve().parent / "ivyea",
        Path(sys.executable).resolve().parent / "ivyea.exe",
        ops_settings.root_dir / "server" / ".venv" / "bin" / "ivyea",
        ops_settings.root_dir / "server" / ".venv" / "Scripts" / "ivyea.exe",
        Path.home() / ".local" / "bin" / "ivyea",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return ""


def _service_bind() -> tuple[str, int] | None:
    parsed = urllib.parse.urlparse(base_url())
    host = parsed.hostname or "127.0.0.1"
    if host not in {"127.0.0.1", "localhost", "::1"}:
        return None
    port = int(parsed.port or (443 if parsed.scheme == "https" else 80))
    return host, port


def _timeout() -> float:
    raw = (os.getenv("IVYEA_AGENT_TIMEOUT") or "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        return max(1.0, min(float(raw), 60.0))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _token() -> str:
    from app.core import hub_settings
    return (
        str(hub_settings.get("ivyea_agent_token") or "")
        or os.getenv("IVYEA_AGENT_TOKEN")
        or os.getenv("IVYEA_API_TOKEN")
        or ""
    ).strip()


def _url(path: str) -> str:
    if not path.startswith("/") or path.startswith("//") or "://" in path:
        raise ValueError("IvyeaAgent path must be an absolute local API path")
    return urllib.parse.urljoin(base_url() + "/", path.lstrip("/"))


def _decode_json(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8", errors="replace") or "{}")
    except json.JSONDecodeError as exc:
        raise IvyeaAgentError(f"IvyeaAgent returned non-JSON response: {exc}") from exc
    if not isinstance(data, dict):
        raise IvyeaAgentError("IvyeaAgent returned a JSON value that is not an object")
    return data


def request_json(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Call IvyeaAgent and return a JSON object.

    This wrapper intentionally uses stdlib urllib so IvyeaOps does not need a
    new runtime dependency just to talk to the local agent.
    """
    method = method.upper().strip()
    data = None
    headers = {
        "Accept": "application/json",
        "User-Agent": "IvyeaOps-IvyeaAgent-Bridge/1",
    }
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    auth = _token()
    if auth:
        headers["Authorization"] = f"Bearer {auth}"
    req = urllib.request.Request(_url(path), data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout or _timeout()) as resp:
            return _decode_json(resp.read())
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        detail = ""
        if raw:
            try:
                body = _decode_json(raw)
                detail = str(body.get("detail") or body.get("error") or body)
            except IvyeaAgentError:
                detail = raw.decode("utf-8", errors="replace")[:500]
        raise IvyeaAgentError(f"IvyeaAgent HTTP {exc.code}: {detail or exc.reason}") from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
        raise IvyeaAgentUnavailable(str(exc)) from exc


def request_stream(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> Any:
    """Yield raw bytes from an IvyeaAgent streaming endpoint."""
    method = method.upper().strip()
    data = None
    headers = {
        "Accept": "text/event-stream",
        "User-Agent": "IvyeaOps-IvyeaAgent-Bridge/1",
    }
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    auth = _token()
    if auth:
        headers["Authorization"] = f"Bearer {auth}"
    req = urllib.request.Request(_url(path), data=data, headers=headers, method=method)

    def _chunks() -> Any:
        try:
            with urllib.request.urlopen(req, timeout=timeout or _timeout()) as resp:
                while True:
                    chunk = resp.read(4096)
                    if not chunk:
                        break
                    yield chunk
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            detail = raw.decode("utf-8", errors="replace")[:500] if raw else str(exc.reason)
            yield _sse_error(f"IvyeaAgent HTTP {exc.code}: {detail}")
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            yield _sse_error(f"IvyeaAgent 不可用：{exc}")

    return _chunks()


def _sse_error(detail: str) -> bytes:
    return (
        "event: error\n"
        f"data: {json.dumps({'ok': False, 'error': 'bridge_error', 'detail': detail}, ensure_ascii=False)}\n\n"
    ).encode("utf-8")


def availability() -> dict[str, Any]:
    """Best-effort health payload for UI status cards."""
    result: dict[str, Any] = {
        "ok": True,
        "available": False,
        "base_url": base_url(),
        "token_configured": token_configured(),
        "health": None,
        "error": "",
    }
    try:
        result["health"] = request_json("GET", "/health", timeout=2.0)
        result["available"] = bool(isinstance(result["health"], dict) and result["health"].get("ok"))
    except IvyeaAgentError as exc:
        result["ok"] = False
        result["error"] = str(exc)
    return result


def start_local_service() -> dict[str, Any]:
    bind = _service_bind()
    if not bind:
        return {"ok": False, "error": "auto_start_only_supports_localhost", "base_url": base_url()}
    cli = _find_ivyea_cli()
    if not cli:
        return {"ok": False, "error": "ivyea_cli_not_found"}
    host, port = bind
    cmd = [cli, "self", "service-start", "--host", host, "--port", str(port)]
    token = _token()
    env = {**os.environ}
    if token:
        env["IVYEA_API_TOKEN"] = token
        cmd.extend(["--api-token", token])
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ops_settings.root_dir),
            env=env,
            text=True,
            capture_output=True,
            timeout=18,
            **no_window_kwargs(),
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "command": " ".join(cmd)}
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "command": " ".join(cmd[:6]),
        "stdout": (proc.stdout or "")[-2000:],
        "stderr": (proc.stderr or "")[-2000:],
    }


def _venv_python(cli: str) -> str:
    """The python next to the ivyea CLI (its install env), for pip upgrades."""
    parent = Path(cli).resolve().parent
    for name in ("python", "python3", "python.exe"):
        cand = parent / name
        if cand.is_file():
            return str(cand)
    return sys.executable


def agent_version() -> str:
    try:
        h = request_json("GET", "/health", timeout=2.0)
        return str(h.get("version") or "") if isinstance(h, dict) else ""
    except Exception:  # noqa: BLE001
        return ""


def _installed_agent_version(py: str) -> str:
    """Version of the *installed* ivyea_agent package (reflects files on disk),
    independent of whether the serve has restarted to load them."""
    try:
        p = subprocess.run([py, "-c", "import ivyea_agent, sys; sys.stdout.write(ivyea_agent.__version__)"],
                           text=True, capture_output=True, timeout=15, **no_window_kwargs())
        return (p.stdout or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _run_step(cmd: list[str], timeout: float = 300.0) -> dict[str, Any]:
    try:
        p = subprocess.run(cmd, cwd=str(ops_settings.root_dir), text=True,
                           capture_output=True, timeout=timeout, **no_window_kwargs())
        return {"cmd": " ".join(cmd[:4]), "returncode": p.returncode,
                "stdout": (p.stdout or "")[-1500:], "stderr": (p.stderr or "")[-1500:]}
    except Exception as exc:  # noqa: BLE001
        return {"cmd": " ".join(cmd[:4]), "returncode": -1, "error": str(exc)}


def upgrade_agent(progress=None) -> dict[str, Any]:
    """Update the bundled IvyeaAgent (pip -U from git into its venv) and restart
    the local serve so the new code loads. Returns before/after version + logs.

    progress(phase: str, percent: int) is called at each step so a UI can show a
    progress bar instead of blocking silently."""
    def _p(phase: str, pct: int) -> None:
        if progress:
            try:
                progress(phase, pct)
            except Exception:  # noqa: BLE001
                pass

    _p("preparing", 5)
    cli = _find_ivyea_cli()
    if not cli:
        return {"ok": False, "error": "ivyea CLI 未找到（IvyeaAgent 可能未安装）"}
    py = _venv_python(cli)
    repo = (os.getenv("IVYEA_AGENT_REPO") or "https://github.com/Hector-xue/ivyea-agent.git").strip()
    ref = (os.getenv("IVYEA_AGENT_REF") or "main").strip()
    before = _installed_agent_version(py) or agent_version()
    _p("downloading", 25)   # pip install over git can take a while behind a proxy
    # --no-cache-dir + --force-reinstall: pip caches VCS builds, so a plain
    # `pip install -U git+…@main` can silently reinstall a stale build and report
    # "已是最新" even when main moved. Force a fresh pull. --no-deps keeps it fast
    # (the agent's deps are stable; the code is what changes).
    install = _run_step([py, "-m", "pip", "install", "--no-cache-dir",
                         "--force-reinstall", "--no-deps", f"git+{repo}@{ref}"])
    _p("restarting", 80)
    _run_step([cli, "self", "service-stop"], timeout=20.0)   # stop old serve
    restart = start_local_service()                          # start fresh (new code)
    # Read the *installed* version (reflects the files pip just wrote), not the
    # serve's /health — the serve restart can lag on Windows and report the old
    # version, which previously made a real update look like "已是最新".
    after = _installed_agent_version(py) or agent_version()
    ok = install.get("returncode") == 0
    _p("done" if ok else "error", 100)
    return {"ok": ok, "before": before, "after": after, "install": install,
            "restart": restart,
            "note": "" if ok else "升级失败，请查看 install.stderr 或在终端手动 pip 升级。"}


def _agent_is_editable() -> bool:
    """True when IvyeaAgent runs from a source checkout (pip install -e / dev),
    where auto-upgrading would clobber the developer's working tree."""
    try:
        import ivyea_agent
        p = str(Path(ivyea_agent.__file__).resolve())
        return "site-packages" not in p and "dist-packages" not in p
    except Exception:  # noqa: BLE001
        return False


def maybe_sync_agent_on_upgrade() -> None:
    """When IvyeaOps boots on a NEW version, refresh the bundled IvyeaAgent once
    (best-effort, background). The agent is pip-installed @main at IvyeaOps
    install time and otherwise never moves with IvyeaOps updates; this keeps them
    in sync. Skipped for editable/source installs and when auto-start is off."""
    from app.core import hub_settings
    from app.core.version import app_version
    configured = hub_settings.get("ivyea_agent_auto_start")
    auto = configured if isinstance(configured, bool) else \
        os.getenv("IVYEA_AGENT_AUTO_START", "1").lower() not in {"0", "false", "no"}
    if not auto or _agent_is_editable():
        return
    cur = app_version()
    if cur in ("", "dev"):
        return
    marker = ops_settings.data_dir / "agent_sync.json"
    try:
        last = json.loads(marker.read_text(encoding="utf-8")).get("ops_version", "") if marker.exists() else ""
    except Exception:  # noqa: BLE001
        last = ""
    if cur == last:
        return  # already synced for this IvyeaOps version

    def _bg() -> None:
        try:
            res = upgrade_agent()
            marker.write_text(json.dumps({"ops_version": cur, "agent": res.get("after", "")}),
                              encoding="utf-8")
            print(f"[IvyeaOps] agent auto-sync on {cur}: "
                  f"{res.get('before')}->{res.get('after')} ok={res.get('ok')}")
        except Exception as e:  # noqa: BLE001
            print(f"[IvyeaOps] agent auto-sync failed: {e}")

    threading.Thread(target=_bg, daemon=True).start()


def ensure_available() -> dict[str, Any]:
    global _LAST_START_ATTEMPT
    current = availability()
    if current.get("available"):
        try:
            sync_model_settings()
        except IvyeaAgentError:
            pass
        current["auto_start"] = {"attempted": False, "reason": "already_available"}
        return current
    from app.core import hub_settings
    configured_auto = hub_settings.get("ivyea_agent_auto_start")
    auto_start = configured_auto if isinstance(configured_auto, bool) else os.getenv("IVYEA_AGENT_AUTO_START", "1").lower() not in {"0", "false", "no"}
    if not auto_start:
        current["auto_start"] = {"attempted": False, "reason": "disabled"}
        return current
    now = time.time()
    if now - _LAST_START_ATTEMPT < AUTOSTART_COOLDOWN_SECONDS:
        current["auto_start"] = {"attempted": False, "reason": "cooldown"}
        return current
    _LAST_START_ATTEMPT = now
    started = start_local_service()
    refreshed = availability()
    if refreshed.get("available"):
        try:
            sync_model_settings()
        except IvyeaAgentError:
            pass
    refreshed["auto_start"] = {"attempted": True, "result": started}
    return refreshed


def bootstrap() -> dict[str, Any]:
    return request_json("GET", "/v1/system/bootstrap")


def manifest() -> dict[str, Any]:
    return request_json("GET", "/v1/manifest")


def chat(payload: dict[str, Any]) -> dict[str, Any]:
    return request_json("POST", "/v1/chat", payload, timeout=max(_timeout(), 180.0))


def chat_stream(payload: dict[str, Any]) -> Any:
    return request_stream("POST", "/v1/chat/stream", payload, timeout=max(_timeout(), 300.0))


def chat_sessions(limit: int = 20) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit or 20), 100))
    return request_json("GET", f"/v1/chat/sessions?limit={safe_limit}")


def chat_session(session_id: str) -> dict[str, Any]:
    safe_id = urllib.parse.quote(session_id.strip(), safe="")
    return request_json("GET", f"/v1/chat/sessions/{safe_id}")


def chat_session_delete(session_id: str) -> dict[str, Any]:
    safe_id = urllib.parse.quote(session_id.strip(), safe="")
    return request_json("DELETE", f"/v1/chat/sessions/{safe_id}")


def chat_create(payload: dict[str, Any]) -> dict[str, Any]:
    return request_json("POST", "/v1/chat/sessions", payload)


def model_providers() -> dict[str, Any]:
    return request_json("GET", "/v1/model/providers")


def provider_models(provider_id: str, refresh: bool = False) -> dict[str, Any]:
    suffix = "?refresh=1" if refresh else ""
    safe_id = urllib.parse.quote(provider_id.strip(), safe="")
    return request_json("GET", f"/v1/model/providers/{safe_id}/models{suffix}")


def provider_probe(provider_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    safe_id = urllib.parse.quote(provider_id.strip(), safe="")
    return request_json("POST", f"/v1/model/providers/{safe_id}/probe", payload)


def configure_model(payload: dict[str, Any]) -> dict[str, Any]:
    return request_json("POST", "/v1/model/configure", payload, timeout=max(_timeout(), 60.0))


def _agent_provider_payload(settings: dict[str, Any]) -> dict[str, Any] | None:
    provider = str(settings.get("ivyea_agent_provider") or "").strip()
    model = str(settings.get("ivyea_agent_model") or "").strip()
    api_key = str(settings.get("ivyea_agent_api_key") or "").strip()
    base_url = str(settings.get("ivyea_agent_base_url") or "").strip()
    if not any((provider, model, api_key, base_url)):
        return None
    if not provider:
        provider = "custom" if base_url else "deepseek"
    payload = {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
    }
    return {k: v for k, v in payload.items() if v not in ("", None)}


def sync_model_settings(settings: dict[str, Any] | None = None, force: bool = False) -> dict[str, Any]:
    """Best-effort push of the IvyeaAgent model slot from Hub Settings."""
    global _LAST_MODEL_SYNC_SIGNATURE
    if settings is None:
        from app.core import hub_settings
        settings = hub_settings.load()
    payload = _agent_provider_payload(settings)
    if not payload:
        return {"ok": True, "skipped": True, "reason": "ivyea_agent_model_unconfigured"}
    signature = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if not force and signature == _LAST_MODEL_SYNC_SIGNATURE:
        return {"ok": True, "skipped": True, "reason": "unchanged"}
    result = configure_model(payload)
    if result.get("ok"):
        _LAST_MODEL_SYNC_SIGNATURE = signature
    return result


def retrieval_status() -> dict[str, Any]:
    return request_json("GET", "/v1/retrieval/status")


def retrieval_embeddings() -> dict[str, Any]:
    return request_json("GET", "/v1/retrieval/embeddings")


def retrieval_sync() -> dict[str, Any]:
    return request_json("POST", "/v1/retrieval/index", {"sync": True})


def knowledge_watchlist() -> dict[str, Any]:
    return request_json("GET", "/v1/knowledge/watchlist")


def knowledge_cards(limit: int = 200) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit or 200), 1000))
    return request_json("GET", f"/v1/knowledge/cards?limit={safe_limit}")


def knowledge_search(query: str, limit: int = 8) -> dict[str, Any]:
    params = urllib.parse.urlencode({"q": query, "limit": max(1, min(int(limit or 8), 50))})
    return request_json("GET", f"/v1/knowledge/search?{params}")


def knowledge_files(limit: int = 500) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit or 500), 1000))
    return request_json("GET", f"/v1/knowledge/files?limit={safe_limit}")


def knowledge_uploads(limit: int = 50) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit or 50), 200))
    return request_json("GET", f"/v1/knowledge/uploads?limit={safe_limit}")


def knowledge_file(path: str) -> dict[str, Any]:
    params = urllib.parse.urlencode({"path": path})
    return request_json("GET", f"/v1/knowledge/file?{params}")


def knowledge_delete_file(path: str) -> dict[str, Any]:
    params = urllib.parse.urlencode({"path": path})
    return request_json("DELETE", f"/v1/knowledge/file?{params}")


def knowledge_update_draft(payload: dict[str, Any]) -> dict[str, Any]:
    return request_json("POST", "/v1/knowledge/update/draft", payload)


def knowledge_update_apply(payload: dict[str, Any]) -> dict[str, Any]:
    return request_json("POST", "/v1/knowledge/update/apply", payload)


def knowledge_upload(payload: dict[str, Any]) -> dict[str, Any]:
    return request_json("POST", "/v1/knowledge/upload", payload, timeout=max(_timeout(), 60.0))


def knowledge_upload_apply(payload: dict[str, Any]) -> dict[str, Any]:
    return request_json("POST", "/v1/knowledge/uploads/apply", payload, timeout=max(_timeout(), 60.0))


def _legacy_brain_root() -> str:
    from app.core import hub_settings
    configured = str(hub_settings.get("brain_root") or "").strip()
    if configured:
        return configured
    return os.environ.get("IVYEA_OPS_BRAIN_ROOT") or str(Path.home() / "brain")


def knowledge_import_directory(payload: dict[str, Any]) -> dict[str, Any]:
    root = str(payload.get("root") or "").strip() or _legacy_brain_root()
    body = {
        "root": root,
        "namespace": str(payload.get("namespace") or "gbrain"),
        "confirm": bool(payload.get("confirm")),
        "rebuild": payload.get("rebuild") if isinstance(payload.get("rebuild"), bool) else True,
        "max_files": max(1, min(int(payload.get("max_files") or 1000), 5000)),
        "max_file_bytes": max(1024, min(int(payload.get("max_file_bytes") or 5 * 1024 * 1024), 25 * 1024 * 1024)),
    }
    return request_json("POST", "/v1/knowledge/import-directory", body, timeout=max(_timeout(), 120.0))


def code_bundle(payload: dict[str, Any]) -> dict[str, Any]:
    return request_json("POST", "/v1/code/bundle", payload)


def code_apply_loop(payload: dict[str, Any]) -> dict[str, Any]:
    return request_json("POST", "/v1/code/apply-loop", payload)


def service_status(host: str = "", port: int | None = None) -> dict[str, Any]:
    query = ""
    params: dict[str, str] = {}
    if host:
        params["host"] = host
    if port:
        params["port"] = str(int(port))
    if params:
        query = "?" + urllib.parse.urlencode(params)
    return request_json("GET", f"/v1/system/service/status{query}")


def service_logs(lines: int = 80) -> dict[str, Any]:
    return request_json("GET", f"/v1/system/service/logs?lines={max(1, min(int(lines or 80), 500))}")


def service_start(payload: dict[str, Any]) -> dict[str, Any]:
    return request_json("POST", "/v1/system/service/start", payload)


def service_stop(payload: dict[str, Any]) -> dict[str, Any]:
    return request_json("POST", "/v1/system/service/stop", payload)


def service_autostart(payload: dict[str, Any]) -> dict[str, Any]:
    return request_json("POST", "/v1/system/service/autostart", payload)
