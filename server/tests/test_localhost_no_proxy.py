"""Localhost must bypass a system/VPN proxy so the embedded IvyeaAgent (:8765),
imgflow (:3001) etc. don't 502 through the proxy on Windows/macOS."""
from __future__ import annotations

import os

from app.core.config import _ensure_localhost_no_proxy


def test_adds_localhost_preserving_existing(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "example.com")
    monkeypatch.delenv("no_proxy", raising=False)
    _ensure_localhost_no_proxy()
    val = os.environ["NO_PROXY"]
    assert "example.com" in val            # existing kept
    for h in ("127.0.0.1", "localhost", "::1"):
        assert h in val                    # localhost added
    assert os.environ["no_proxy"] == val   # lowercase mirrored


def test_idempotent_no_duplicates(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    _ensure_localhost_no_proxy()
    _ensure_localhost_no_proxy()
    assert os.environ["NO_PROXY"].split(",").count("127.0.0.1") == 1
