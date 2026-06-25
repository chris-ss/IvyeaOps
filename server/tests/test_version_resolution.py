"""app_version() prefers the git tag on a checkout, so a stale VERSION file
never makes a freshly-pulled server think it is behind."""
from __future__ import annotations

import app.core.version as v


def test_prefers_git_tag_over_version_file(monkeypatch):
    v._CACHED = None
    monkeypatch.setattr(v, "_git_tag", lambda root: "v9.9.9")
    assert v.app_version() == "v9.9.9"


def test_falls_back_to_version_file_without_git(monkeypatch, tmp_path):
    v._CACHED = None
    (tmp_path / "VERSION").write_text("v1.2.3", encoding="utf-8")
    monkeypatch.setattr(v, "runtime_root", lambda: tmp_path)
    monkeypatch.setattr(v, "_git_tag", lambda root: "")
    assert v.app_version() == "v1.2.3"


def test_dev_when_nothing_available(monkeypatch, tmp_path):
    v._CACHED = None
    monkeypatch.setattr(v, "runtime_root", lambda: tmp_path)
    monkeypatch.setattr(v, "_git_tag", lambda root: "")
    assert v.app_version() == "dev"
