"""Integration tests for snapshot/import/trash/audit endpoints (B3)."""
from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


_ORIGIN = "https://test.example.com"
_HDR = {"Origin": _ORIGIN}


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    skills = tmp_path / "skills"
    studio = tmp_path / "skill-studio"
    skills.mkdir()
    studio.mkdir()
    monkeypatch.setenv("OPSHUB_SKILLS_ROOT", str(skills))
    monkeypatch.setenv("OPSHUB_STUDIO_ROOT", str(studio))
    monkeypatch.setenv("OPSHUB_SECRET", "test-secret")
    monkeypatch.setenv("OPSHUB_ALLOWED_ORIGINS", _ORIGIN)

    import importlib
    from app.core import config as cfg_mod
    importlib.reload(cfg_mod)
    from app.core import skill_paths as sp_mod
    importlib.reload(sp_mod)
    sp_mod.ensure_studio_dirs()
    from app.services import skill_repo as sr_mod
    importlib.reload(sr_mod)
    from app.services import snapshot as snap_mod
    importlib.reload(snap_mod)
    from app.services import trash as trash_mod
    importlib.reload(trash_mod)
    from app.services import studio_audit as audit_mod
    importlib.reload(audit_mod)
    from app.services import git_import as gi_mod
    importlib.reload(gi_mod)
    from app.routers import skill as skill_router_mod
    importlib.reload(skill_router_mod)
    from app import main as main_mod
    importlib.reload(main_mod)

    from app.core import security as sec_mod
    main_mod.app.dependency_overrides[sec_mod.require_user] = lambda: "tester"

    with TestClient(main_mod.app) as c:
        yield c, skills


def _seed(c: TestClient, name: str = "subject") -> None:
    c.post(
        "/api/skill/item",
        json={"name": name, "description": "d", "body": "original\n"},
        headers=_HDR,
    )


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------


def test_snapshot_create_and_list(client):
    c, _ = client
    _seed(c)
    r = c.post("/api/skill/snapshots", json={"name": "subject", "label": "v1"}, headers=_HDR)
    assert r.status_code == 201, r.text
    snap = r.json()
    assert snap["label"] == "v1"

    r2 = c.get("/api/skill/snapshots", params={"name": "subject"})
    assert r2.status_code == 200
    ids = [s["id"] for s in r2.json()]
    assert snap["id"] in ids


def test_snapshot_diff_and_restore(client):
    c, skills = client
    _seed(c)
    s1 = c.post(
        "/api/skill/snapshots", json={"name": "subject", "label": "s1"}, headers=_HDR
    ).json()

    # Mutate
    c.put(
        "/api/skill/item/subject",
        json={"frontmatter": {"name": "subject", "description": "d"}, "body": "changed\n"},
        headers=_HDR,
    )

    # Diff shows the change
    r = c.get(f"/api/skill/snapshots/{s1['id']}/diff", params={"name": "subject"})
    assert r.status_code == 200, r.text
    diff = r.json()
    paths = [f["path"] for f in diff["files"]]
    assert "SKILL.md" in paths

    # Restore
    r = c.post(
        f"/api/skill/snapshots/{s1['id']}/restore",
        json={"name": "subject"},
        headers=_HDR,
    )
    assert r.status_code == 200
    result = r.json()
    assert result["restored_from"] == s1["id"]
    assert result["pre_restore_snapshot_id"] is not None

    # Content reverted.
    detail = c.get("/api/skill/item/subject").json()
    assert "original" in detail["content_body"]


def test_snapshot_delete(client):
    c, _ = client
    _seed(c)
    s1 = c.post(
        "/api/skill/snapshots", json={"name": "subject", "label": "x"}, headers=_HDR
    ).json()

    r = c.delete(
        f"/api/skill/snapshots/{s1['id']}", params={"name": "subject"}, headers=_HDR
    )
    assert r.status_code == 200
    listed = c.get("/api/skill/snapshots", params={"name": "subject"}).json()
    assert all(s["id"] != s1["id"] for s in listed)


# ---------------------------------------------------------------------------
# GitHub import (monkeypatched fetcher)
# ---------------------------------------------------------------------------


def _build_tar(entries):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content, kind in entries:
            if kind == "dir":
                info = tarfile.TarInfo(name=name)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                tar.addfile(info)
            else:
                data = content if isinstance(content, bytes) else content.encode()
                info = tarfile.TarInfo(name=name)
                info.size = len(data)
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_import_github_happy_path(client, monkeypatch):
    c, skills = client
    tar = _build_tar([
        ("my-skill-main/", None, "dir"),
        ("my-skill-main/SKILL.md",
         b"---\nname: imported\ndescription: d\n---\n\nbody\n", "file"),
    ])

    # Monkeypatch the default fetcher so no real HTTP happens.
    from app.services import git_import
    monkeypatch.setattr(git_import, "_default_fetcher", lambda _url: tar)

    r = c.post(
        "/api/skill/import/github",
        json={"repo": "me/my-skill", "branch": "main"},
        headers=_HDR,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["imported_name"] == "my-skill"
    assert body["snapshot_id"] is not None
    assert (skills / "my-skill" / "SKILL.md").is_file()


def test_import_rejects_bad_repo(client):
    c, _ = client
    r = c.post(
        "/api/skill/import/github",
        json={"repo": "not a repo", "branch": "main"},
        headers=_HDR,
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Trash
# ---------------------------------------------------------------------------


def test_trash_list_restore_purge(client):
    c, skills = client
    _seed(c, name="vanisher")

    # Delete → moves to trash
    r = c.delete("/api/skill/item/vanisher", headers=_HDR)
    trash_id = r.json()["id"]

    # List shows it
    listed = c.get("/api/skill/trash").json()
    assert any(e["id"] == trash_id for e in listed)

    # Restore brings it back
    r = c.post(f"/api/skill/trash/{trash_id}/restore", headers=_HDR)
    assert r.status_code == 200
    assert (skills / "vanisher" / "SKILL.md").is_file()

    # Trash is empty again
    assert c.get("/api/skill/trash").json() == []


def test_trash_restore_with_custom_target(client):
    c, skills = client
    _seed(c, name="conflicted")
    r = c.delete("/api/skill/item/conflicted", headers=_HDR)
    trash_id = r.json()["id"]

    # Create a new skill with the original name.
    _seed(c, name="conflicted")

    # Default restore collides (409)
    r = c.post(f"/api/skill/trash/{trash_id}/restore", headers=_HDR)
    assert r.status_code == 409

    # With target_name it succeeds.
    r = c.post(
        f"/api/skill/trash/{trash_id}/restore",
        json={"target_name": "conflicted-v2"},
        headers=_HDR,
    )
    assert r.status_code == 200
    assert (skills / "conflicted-v2" / "SKILL.md").is_file()


def test_trash_permanent_delete(client):
    c, _ = client
    _seed(c, name="purgeable")
    r = c.delete("/api/skill/item/purgeable", headers=_HDR)
    trash_id = r.json()["id"]

    r = c.delete(f"/api/skill/trash/{trash_id}", headers=_HDR)
    assert r.status_code == 200
    assert c.get("/api/skill/trash").json() == []


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def test_audit_endpoint_tails_events(client):
    c, _ = client
    _seed(c, name="logged")
    c.post("/api/skill/snapshots", json={"name": "logged", "label": "x"}, headers=_HDR)
    c.delete("/api/skill/item/logged", headers=_HDR)

    r = c.get("/api/skill/audit", params={"limit": 50})
    assert r.status_code == 200
    events = r.json()
    types = {(e["event_type"], e["skill_name"]) for e in events}
    assert ("skill.create", "logged") in types
    assert ("snapshot.create", "logged") in types
    assert ("skill.delete", "logged") in types
