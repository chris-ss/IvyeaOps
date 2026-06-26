"""On Windows, mirror the WinINET system proxy (Clash/VPN) into HTTP_PROXY so
httpx uses the same path the browser does — apimart etc. are only reachable
through the proxy, direct sockets time out."""
from __future__ import annotations

import os
import urllib.request

import app.core.config as cfg


def _clear(monkeypatch):
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(k, raising=False)


def test_mirrors_system_proxy_on_windows(monkeypatch):
    monkeypatch.setattr(cfg.os, "name", "nt")
    _clear(monkeypatch)
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {"http": "127.0.0.1:7890"})
    cfg._inherit_system_proxy()
    assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:7890"
    assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:7890"


def test_explicit_proxy_wins(monkeypatch):
    monkeypatch.setattr(cfg.os, "name", "nt")
    _clear(monkeypatch)
    monkeypatch.setenv("HTTP_PROXY", "http://explicit:1")
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {"http": "127.0.0.1:7890"})
    cfg._inherit_system_proxy()
    assert os.environ["HTTP_PROXY"] == "http://explicit:1"


def test_noop_on_posix(monkeypatch):
    monkeypatch.setattr(cfg.os, "name", "posix")
    _clear(monkeypatch)
    cfg._inherit_system_proxy()
    assert os.environ.get("HTTP_PROXY") is None
