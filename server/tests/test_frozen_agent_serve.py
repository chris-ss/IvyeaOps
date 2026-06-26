"""Frozen build (Windows x64 exe / macOS .app): the bundled agent runs from the
exe via `<exe> agent-serve`, with no separate pip/Python install."""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from app.services import ivyea_agent_service as svc

_SERVER_DIR = Path(__file__).resolve().parents[1]   # server/


def test_frozen_start_local_service_uses_exe(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/opt/IvyeaOps/IvyeaOpsServer", raising=False)
    monkeypatch.setattr(svc, "_service_bind", lambda: ("127.0.0.1", 8765))
    monkeypatch.setattr(svc, "_token", lambda: "")
    captured = {}

    class FakePopen:
        def __init__(self, cmd, **kw):
            captured["cmd"] = cmd
            self.pid = 999

    monkeypatch.setattr(svc.subprocess, "Popen", FakePopen)
    r = svc.start_local_service()
    assert r["ok"] is True and r["frozen"] is True and r["pid"] == 999
    assert captured["cmd"][:2] == ["/opt/IvyeaOps/IvyeaOpsServer", "agent-serve"]
    assert "--port" in captured["cmd"]


def test_frozen_upgrade_is_bundled(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    r = svc.upgrade_agent()
    assert r["bundled"] is True and "随 IvyeaOps" in r["note"]


def test_frozen_installed_version_imports(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert svc._installed_agent_version("")   # imports ivyea_agent → non-empty


def test_agent_serve_entry_mode_runs_the_agent():
    """`ivyeaops_server.py agent-serve` boots the bundled agent's HTTP serve."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    p = subprocess.Popen(
        [sys.executable, "ivyeaops_server.py", "agent-serve", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(_SERVER_DIR), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        ok = False
        for _ in range(40):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                    ok = bool(json.loads(r.read()).get("ok"))
                    break
            except Exception:
                time.sleep(0.3)
        assert ok, "agent-serve mode did not answer /health"
    finally:
        p.terminate()
        try:
            p.wait(timeout=5)
        except Exception:
            p.kill()
