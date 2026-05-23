"""Integration tests for /api/skill write endpoints (POST/PUT/DELETE).

The CSRF origin guard fires on unsafe methods — tests supply an Origin
header matching the allowed_origins list we seed via env.
"""
from __future__ import annotations

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
    from app.routers import skill as skill_router_mod
    importlib.reload(skill_router_mod)
    from app import main as main_mod
    importlib.reload(main_mod)

    from app.core import security as sec_mod
    main_mod.app.dependency_overrides[sec_mod.require_user] = lambda: "tester"

    with TestClient(main_mod.app) as c:
        yield c, skills


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_create_skill_then_fetch(client):
    c, skills = client
    r = c.post(
        "/api/skill/item",
        json={"name": "my-skill", "description": "test skill", "body": "hello\n"},
        headers=_HDR,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "my-skill"
    assert (skills / "my-skill" / "SKILL.md").is_file()

    # Round-trip via the read endpoint.
    r = c.get("/api/skill/item/my-skill")
    assert r.status_code == 200
    detail = r.json()
    assert detail["description"] == "test skill"
    assert "hello" in detail["content_body"]
    assert detail["frontmatter"]["name"] == "my-skill"


def test_create_nested_name(client):
    c, skills = client
    r = c.post(
        "/api/skill/item",
        json={"name": "research/new-one", "description": "d"},
        headers=_HDR,
    )
    assert r.status_code == 201, r.text
    assert (skills / "research" / "new-one" / "SKILL.md").is_file()


def test_create_duplicate_conflicts(client):
    c, _ = client
    r1 = c.post("/api/skill/item", json={"name": "dup"}, headers=_HDR)
    assert r1.status_code == 201
    r2 = c.post("/api/skill/item", json={"name": "dup"}, headers=_HDR)
    assert r2.status_code == 409


def test_create_rejects_bad_name(client):
    c, _ = client
    for bad in ["", "UPPER", "../x", ".hidden", "x/..", "1leading"]:
        r = c.post("/api/skill/item", json={"name": bad}, headers=_HDR)
        assert r.status_code == 400, f"{bad!r} slipped through: {r.text}"


def test_create_frontmatter_extras_cannot_override_name(client):
    c, skills = client
    r = c.post(
        "/api/skill/item",
        json={
            "name": "safe-skill",
            "frontmatter_extras": {"name": "injected", "version": "2.0"},
        },
        headers=_HDR,
    )
    assert r.status_code == 201
    text = (skills / "safe-skill" / "SKILL.md").read_text()
    assert "name: safe-skill" in text
    assert "name: injected" not in text
    assert "version: '2.0'" in text or "version: \"2.0\"" in text or "version: 2.0" in text


# ---------------------------------------------------------------------------
# Update (overwrite SKILL.md)
# ---------------------------------------------------------------------------


def test_update_skill_replaces_frontmatter_and_body(client):
    c, skills = client
    c.post("/api/skill/item", json={"name": "editme"}, headers=_HDR)

    r = c.put(
        "/api/skill/item/editme",
        json={
            "frontmatter": {"name": "editme", "description": "new desc"},
            "body": "new body line 1\nnew body line 2\n",
        },
        headers=_HDR,
    )
    assert r.status_code == 200, r.text

    got = c.get("/api/skill/item/editme").json()
    assert got["description"] == "new desc"
    assert "new body line 1" in got["content_body"]


def test_update_missing_skill_404s(client):
    c, _ = client
    r = c.put(
        "/api/skill/item/ghost",
        json={"frontmatter": {"name": "ghost"}, "body": "x"},
        headers=_HDR,
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Rename
# ---------------------------------------------------------------------------


def test_rename_skill(client):
    c, skills = client
    c.post("/api/skill/item", json={"name": "old-name"}, headers=_HDR)

    r = c.post(
        "/api/skill/item/old-name/rename",
        json={"new_name": "new-name"},
        headers=_HDR,
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "new-name"
    assert not (skills / "old-name").exists()
    assert (skills / "new-name" / "SKILL.md").is_file()


def test_rename_across_categories(client):
    c, skills = client
    c.post("/api/skill/item", json={"name": "research/source"}, headers=_HDR)

    r = c.post(
        "/api/skill/item/research/source/rename",
        json={"new_name": "mlops/destination"},
        headers=_HDR,
    )
    assert r.status_code == 200
    assert (skills / "mlops" / "destination" / "SKILL.md").is_file()
    assert not (skills / "research" / "source").exists()


def test_rename_conflicts(client):
    c, _ = client
    c.post("/api/skill/item", json={"name": "alpha"}, headers=_HDR)
    c.post("/api/skill/item", json={"name": "beta"}, headers=_HDR)

    r = c.post("/api/skill/item/alpha/rename", json={"new_name": "beta"}, headers=_HDR)
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Delete (trash)
# ---------------------------------------------------------------------------


def test_delete_skill_moves_to_trash(client):
    c, skills = client
    c.post("/api/skill/item", json={"name": "trashme"}, headers=_HDR)
    assert (skills / "trashme").exists()

    r = c.delete("/api/skill/item/trashme", headers=_HDR)
    assert r.status_code == 200, r.text
    entry = r.json()
    assert entry["original_name"] == "trashme"
    assert not (skills / "trashme").exists()

    # Confirm the trash entry folder exists under STUDIO_ROOT.
    from app.core import skill_paths as sp
    trash_dir = sp.TRASH_DIR / entry["id"]
    assert trash_dir.is_dir()


def test_delete_missing_skill_404s(client):
    c, _ = client
    r = c.delete("/api/skill/item/ghost", headers=_HDR)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# File write / delete
# ---------------------------------------------------------------------------


def test_write_and_read_linked_file(client):
    c, _ = client
    c.post("/api/skill/item", json={"name": "with-refs"}, headers=_HDR)

    r = c.put(
        "/api/skill/file/with-refs",
        json={"path": "references/notes.md", "content": "hello refs\n"},
        headers=_HDR,
    )
    assert r.status_code == 200, r.text
    assert r.json()["path"] == "references/notes.md"

    r2 = c.get("/api/skill/file/with-refs", params={"path": "references/notes.md"})
    assert r2.status_code == 200
    assert r2.json()["content"].strip() == "hello refs"


def test_write_file_rejects_SKILL_md_path(client):
    c, _ = client
    c.post("/api/skill/item", json={"name": "protect"}, headers=_HDR)

    r = c.put(
        "/api/skill/file/protect",
        json={"path": "SKILL.md", "content": "injected"},
        headers=_HDR,
    )
    assert r.status_code == 400


def test_write_file_rejects_traversal(client):
    c, _ = client
    c.post("/api/skill/item", json={"name": "trav"}, headers=_HDR)

    r = c.put(
        "/api/skill/file/trav",
        json={"path": "../../escape.txt", "content": "x"},
        headers=_HDR,
    )
    assert r.status_code in (400, 403)


def test_delete_linked_file(client):
    c, _ = client
    c.post("/api/skill/item", json={"name": "delfile"}, headers=_HDR)
    c.put(
        "/api/skill/file/delfile",
        json={"path": "references/a.md", "content": "a"},
        headers=_HDR,
    )

    r = c.delete(
        "/api/skill/file/delfile",
        params={"path": "references/a.md"},
        headers=_HDR,
    )
    assert r.status_code == 200
    # Missing now.
    r2 = c.get("/api/skill/file/delfile", params={"path": "references/a.md"})
    assert r2.status_code == 404


def test_delete_SKILL_md_forbidden(client):
    c, _ = client
    c.post("/api/skill/item", json={"name": "keepmd"}, headers=_HDR)
    r = c.delete(
        "/api/skill/file/keepmd",
        params={"path": "SKILL.md"},
        headers=_HDR,
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# CSRF guard
# ---------------------------------------------------------------------------


def test_write_without_origin_header_is_rejected(client):
    c, _ = client
    r = c.post("/api/skill/item", json={"name": "ghost"})  # no Origin header
    assert r.status_code == 403
    assert "origin" in r.text.lower()


def test_write_with_wrong_origin_is_rejected(client):
    c, _ = client
    r = c.post(
        "/api/skill/item",
        json={"name": "ghost"},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Audit integration
# ---------------------------------------------------------------------------


def test_audit_log_records_create_and_update(client):
    c, _ = client
    c.post("/api/skill/item", json={"name": "audited"}, headers=_HDR)
    c.put(
        "/api/skill/item/audited",
        json={"frontmatter": {"name": "audited"}, "body": "v2"},
        headers=_HDR,
    )

    from app.services import studio_audit
    events = studio_audit.tail(limit=20)
    types = [(e["event_type"], e["skill_name"]) for e in events]
    assert ("skill.update", "audited") in types
    assert ("skill.create", "audited") in types
