"""Skill Studio HTTP API.

All endpoints require an authenticated session via ``require_user``. Path
components come in through ``{name:path}`` so forward slashes (e.g.
``research/arxiv``) travel transparently; every path is validated inside
the service layer before any filesystem access.

This file is intentionally thin — heavy lifting lives in
``app.services.*``. The router's job is request parsing and response
shaping only.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.security import require_user
from app.services import skill_repo
from app.services import snapshot as snapshot_svc
from app.services import git_import
from app.services import studio_audit
from app.services import trash as trash_svc


router = APIRouter(dependencies=[Depends(require_user)])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class StatsResponse(BaseModel):
    total_skills: int
    total_size_bytes: int
    categories: dict[str, int]         # category → count
    recently_edited: list[skill_repo.SkillMeta]


class ListResponse(BaseModel):
    skills: list[skill_repo.SkillMeta]
    total: int


class FileContentResponse(BaseModel):
    skill_name: str
    path: str                           # relative to the skill dir
    content: str
    size: int
    is_binary: bool


# ---------------------------------------------------------------------------
# GET /api/skill/stats
# ---------------------------------------------------------------------------


@router.get("/stats", response_model=StatsResponse)
def get_stats() -> StatsResponse:
    """Overview: total count, bytes, category histogram, recently edited top 5."""
    metas = skill_repo.list_skills()
    total_bytes = sum(m.size_bytes for m in metas)

    cats: dict[str, int] = {}
    for m in metas:
        key = m.category or "(uncategorized)"
        cats[key] = cats.get(key, 0) + 1

    return StatsResponse(
        total_skills=len(metas),
        total_size_bytes=total_bytes,
        categories=dict(sorted(cats.items(), key=lambda kv: (-kv[1], kv[0]))),
        recently_edited=metas[:5],
    )


# ---------------------------------------------------------------------------
# GET /api/skill/list
# ---------------------------------------------------------------------------


@router.get("/list", response_model=ListResponse)
def list_skills_route(
    q: str | None = Query(None, description="filter by name substring (case-insensitive)"),
    category: str | None = Query(None, description="exact category match"),
    limit: int = Query(500, ge=1, le=2000),
) -> ListResponse:
    """List skills, optionally filtered. Ordering: most recently edited first."""
    metas = skill_repo.list_skills()

    if q:
        needle = q.lower()
        metas = [m for m in metas if needle in m.name.lower()
                 or (m.description and needle in m.description.lower())
                 or (m.description_zh and needle in m.description_zh.lower())]
    if category:
        metas = [m for m in metas if (m.category or "") == category]

    return ListResponse(skills=metas[:limit], total=len(metas))


# ---------------------------------------------------------------------------
# GET /api/skill/{name:path}
# ---------------------------------------------------------------------------


@router.get("/item/{name:path}", response_model=skill_repo.SkillDetail)
def get_skill_route(name: str) -> skill_repo.SkillDetail:
    """Fetch a single skill's full detail (frontmatter + body + linked files)."""
    return skill_repo.get_skill(name)


# ---------------------------------------------------------------------------
# GET /api/skill/file/{name:path}?path=references/notes.md
# ---------------------------------------------------------------------------

# Use a distinct /file/ prefix so the path param doesn't collide with /item/.
# Putting the relative file path in a query string keeps FastAPI's path
# grammar simple and lets us reuse validate_skill_name untouched.


_MAX_FILE_READ_BYTES = 2 * 1024 * 1024  # 2 MB — editor would choke anyway


@router.get("/file/{name:path}", response_model=FileContentResponse)
def get_skill_file(
    name: str,
    path: str = Query(..., description="path relative to the skill directory"),
) -> FileContentResponse:
    """Read a file inside a skill. Binary files return a placeholder body."""
    target = skill_repo._safe_path(name, path)
    if not target.is_file():
        raise HTTPException(404, f"file not found: {path}")

    try:
        size = target.stat().st_size
    except OSError as e:
        raise HTTPException(500, f"stat failed: {e}") from e

    if size > _MAX_FILE_READ_BYTES:
        raise HTTPException(
            413,
            f"file too large to open in editor: {size} bytes "
            f"(> {_MAX_FILE_READ_BYTES} limit)",
        )

    try:
        with target.open("rb") as f:
            raw = f.read()
    except OSError as e:
        raise HTTPException(500, f"read failed: {e}") from e

    is_binary = b"\x00" in raw[:8192]
    if is_binary:
        return FileContentResponse(
            skill_name=name,
            path=path,
            content="[binary file — not displayable]",
            size=size,
            is_binary=True,
        )
    return FileContentResponse(
        skill_name=name,
        path=path,
        content=raw.decode("utf-8", errors="replace"),
        size=size,
        is_binary=False,
    )


# ---------------------------------------------------------------------------
# Write endpoints
# ---------------------------------------------------------------------------


class CreateSkillBody(BaseModel):
    name: str = Field(..., description="forward-slash skill name, e.g. 'research/arxiv'")
    description: str | None = None
    body: str = Field("", description="SKILL.md body (below the frontmatter)")
    frontmatter_extras: dict[str, Any] | None = Field(
        None, description="optional extra frontmatter keys (name is always overridden)"
    )


class UpdateSkillBody(BaseModel):
    frontmatter: dict[str, Any] = Field(..., description="complete frontmatter dict to serialize")
    body: str = Field(..., description="SKILL.md body below the frontmatter")


class WriteFileBody(BaseModel):
    path: str = Field(..., description="relative path inside the skill dir")
    content: str = Field(..., description="UTF-8 file content (max 2 MB)")


class RenameBody(BaseModel):
    new_name: str = Field(..., description="target skill name (may include '/')")


class OkResponse(BaseModel):
    ok: bool = True


@router.post("/item", response_model=skill_repo.SkillMeta, status_code=201)
def create_skill_route(
    body: CreateSkillBody,
    user: str = Depends(require_user),
) -> skill_repo.SkillMeta:
    """Create a new skill. 409 if the name already exists."""
    meta = skill_repo.create_skill(
        name=body.name,
        description=body.description,
        body=body.body,
        frontmatter_extras=body.frontmatter_extras,
    )
    studio_audit.record(
        "skill.create", actor=user, skill_name=body.name,
        details={"description": body.description or ""},
    )
    return meta


@router.put("/item/{name:path}", response_model=skill_repo.SkillMeta)
def update_skill_route(
    name: str,
    body: UpdateSkillBody,
    user: str = Depends(require_user),
) -> skill_repo.SkillMeta:
    """Overwrite SKILL.md frontmatter + body. No implicit snapshot — the UI
    calls the snapshot endpoint explicitly when the user asks."""
    meta = skill_repo.update_skill_md(name, body.frontmatter, body.body)
    studio_audit.record(
        "skill.update", actor=user, skill_name=name,
        details={"body_bytes": len(body.body or "")},
    )
    return meta


@router.post("/item/{name:path}/rename", response_model=skill_repo.SkillMeta)
def rename_skill_route(
    name: str,
    body: RenameBody,
    user: str = Depends(require_user),
) -> skill_repo.SkillMeta:
    """Rename a skill dir (may also move across categories)."""
    meta = skill_repo.rename_skill(name, body.new_name)
    studio_audit.record(
        "skill.rename", actor=user, skill_name=name,
        details={"new_name": body.new_name},
    )
    return meta


@router.delete("/item/{name:path}", response_model=trash_svc.TrashEntry)
def delete_skill_route(
    name: str,
    user: str = Depends(require_user),
) -> trash_svc.TrashEntry:
    """Delete (trash) a skill. 7-day recoverable window."""
    entry = trash_svc.trash_skill(name)
    studio_audit.record(
        "skill.delete", actor=user, skill_name=name,
        details={"trash_id": entry.id},
    )
    return entry


# ---------------------------------------------------------------------------
# File write / delete (for references/templates/scripts)
# ---------------------------------------------------------------------------


@router.put("/file/{name:path}", response_model=skill_repo.FileEntry)
def write_skill_file(
    name: str,
    body: WriteFileBody,
    user: str = Depends(require_user),
) -> skill_repo.FileEntry:
    """Create or overwrite a file inside a skill (NOT SKILL.md)."""
    entry = skill_repo.write_file(name, body.path, body.content)
    studio_audit.record(
        "skill.file_write", actor=user, skill_name=name,
        details={"path": body.path, "size": entry.size},
    )
    return entry


@router.delete("/file/{name:path}", response_model=OkResponse)
def delete_skill_file(
    name: str,
    path: str = Query(..., description="relative path inside the skill dir"),
    user: str = Depends(require_user),
) -> OkResponse:
    """Delete a non-SKILL.md file inside a skill."""
    skill_repo.delete_file(name, path)
    studio_audit.record(
        "skill.file_delete", actor=user, skill_name=name,
        details={"path": path},
    )
    return OkResponse()


# ---------------------------------------------------------------------------
# Snapshots
#
# NOTE on URL shape: we cannot use ``/snapshot/{name:path}/{snapshot_id}/...``
# because the ``{name:path}`` converter is greedy and swallows the
# snapshot_id and action segments. So snapshot endpoints take ``name`` as
# a query parameter and keep the snapshot_id/action in the path instead.
# ---------------------------------------------------------------------------


class CreateSnapshotBody(BaseModel):
    name: str = Field(..., description="skill name")
    label: str | None = Field(None, description="optional human label")


@router.post("/snapshots", response_model=snapshot_svc.SnapshotMeta, status_code=201)
def create_snapshot_route(
    body: CreateSnapshotBody,
    user: str = Depends(require_user),
) -> snapshot_svc.SnapshotMeta:
    """Freeze the current state of a skill. Retention prune runs automatically."""
    meta = snapshot_svc.create_snapshot(body.name, label=body.label)
    studio_audit.record(
        "snapshot.create", actor=user, skill_name=body.name,
        details={"snapshot_id": meta.id, "label": meta.label},
    )
    return meta


@router.get("/snapshots", response_model=list[snapshot_svc.SnapshotMeta])
def list_snapshots_route(
    name: str = Query(..., description="skill name"),
) -> list[snapshot_svc.SnapshotMeta]:
    return snapshot_svc.list_snapshots(name)


@router.get(
    "/snapshots/{snapshot_id}/diff",
    response_model=snapshot_svc.SnapshotDiff,
)
def diff_snapshot_route(
    snapshot_id: str,
    name: str = Query(..., description="skill name"),
    file: str | None = Query(None, description="limit diff to a single file"),
) -> snapshot_svc.SnapshotDiff:
    return snapshot_svc.diff_snapshot(name, snapshot_id, only_path=file)


class RestoreSnapshotBody(BaseModel):
    name: str = Field(..., description="skill name")


@router.post("/snapshots/{snapshot_id}/restore", response_model=dict)
def restore_snapshot_route(
    snapshot_id: str,
    body: RestoreSnapshotBody,
    user: str = Depends(require_user),
) -> dict:
    """Roll the skill back to a snapshot. A pre-restore snapshot is taken
    first so the user can undo the undo."""
    result = snapshot_svc.restore_snapshot(
        body.name, snapshot_id, create_pre_restore_snapshot=True
    )
    studio_audit.record(
        "snapshot.restore", actor=user, skill_name=body.name,
        details=result,
    )
    return result


@router.delete("/snapshots/{snapshot_id}", response_model=OkResponse)
def delete_snapshot_route(
    snapshot_id: str,
    name: str = Query(..., description="skill name"),
    user: str = Depends(require_user),
) -> OkResponse:
    snapshot_svc.delete_snapshot(name, snapshot_id)
    studio_audit.record(
        "snapshot.delete", actor=user, skill_name=name,
        details={"snapshot_id": snapshot_id},
    )
    return OkResponse()


# ---------------------------------------------------------------------------
# GitHub import
# ---------------------------------------------------------------------------


@router.post(
    "/import/github",
    response_model=git_import.GitHubImportResult,
    status_code=201,
)
def import_github_route(
    body: git_import.GitHubImportRequest,
    user: str = Depends(require_user),
) -> git_import.GitHubImportResult:
    """Import a skill from a public GitHub repository via tarball."""
    result = git_import.import_from_github(body)
    studio_audit.record(
        "import.github", actor=user, skill_name=result.imported_name,
        details={
            "source_url": result.source_url,
            "branch": result.branch,
            "snapshot_id": result.snapshot_id,
        },
    )
    return result


# ---------------------------------------------------------------------------
# Trash (recycle bin)
# ---------------------------------------------------------------------------


class TrashRestoreBody(BaseModel):
    target_name: str | None = Field(
        None, description="optional new name if original is taken"
    )


@router.get("/trash", response_model=list[trash_svc.TrashEntry])
def list_trash_route() -> list[trash_svc.TrashEntry]:
    return trash_svc.list_trash()


@router.post("/trash/{trash_id}/restore", response_model=OkResponse)
def restore_trash_route(
    trash_id: str,
    body: TrashRestoreBody | None = None,
    user: str = Depends(require_user),
) -> OkResponse:
    target = body.target_name if body else None
    restored = trash_svc.restore_from_trash(trash_id, target_name=target)
    studio_audit.record(
        "skill.restore_trash", actor=user, skill_name=restored,
        details={"trash_id": trash_id},
    )
    return OkResponse()


@router.delete("/trash/{trash_id}", response_model=OkResponse)
def delete_trash_route(
    trash_id: str,
    user: str = Depends(require_user),
) -> OkResponse:
    trash_svc.delete_permanently(trash_id)
    studio_audit.record(
        "trash.purge", actor=user, skill_name=None,
        details={"trash_id": trash_id, "scope": "single"},
    )
    return OkResponse()


# ---------------------------------------------------------------------------
# Audit log tail
# ---------------------------------------------------------------------------


@router.get("/audit", response_model=list[dict])
def audit_tail_route(
    limit: int = Query(100, ge=1, le=500),
) -> list[dict]:
    return studio_audit.tail(limit=limit)


# ---------------------------------------------------------------------------
# Studio settings
# ---------------------------------------------------------------------------


import json
from app.core.skill_paths import SETTINGS_FILE


_DEFAULT_SETTINGS: dict[str, Any] = {
    "snapshot_retention": 20,          # keep N per-skill snapshots
    "trash_ttl_days": 7,
    "autosave_debounce_ms": 600,
    "theme": "dark",
}


def _load_settings() -> dict[str, Any]:
    if not SETTINGS_FILE.is_file():
        return dict(_DEFAULT_SETTINGS)
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(_DEFAULT_SETTINGS)
    merged = dict(_DEFAULT_SETTINGS)
    if isinstance(data, dict):
        merged.update({k: v for k, v in data.items() if k in _DEFAULT_SETTINGS})
    return merged


def _save_settings(payload: dict[str, Any]) -> dict[str, Any]:
    merged = _load_settings()
    # Only accept known keys to keep the surface area small and prevent
    # arbitrary-write attempts via JSON injection.
    for k, v in (payload or {}).items():
        if k not in _DEFAULT_SETTINGS:
            continue
        merged[k] = v
    SETTINGS_FILE.write_text(
        json.dumps(merged, indent=2, sort_keys=True), encoding="utf-8"
    )
    return merged


@router.get("/settings", response_model=dict)
def get_settings_route() -> dict:
    return _load_settings()


class UpdateSettingsBody(BaseModel):
    snapshot_retention: int | None = Field(None, ge=1, le=200)
    trash_ttl_days: int | None = Field(None, ge=1, le=365)
    autosave_debounce_ms: int | None = Field(None, ge=100, le=10_000)
    theme: str | None = Field(None, pattern=r"^(dark|light)$")


@router.put("/settings", response_model=dict)
def put_settings_route(
    body: UpdateSettingsBody,
    user: str = Depends(require_user),
) -> dict:
    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    merged = _save_settings(payload)
    studio_audit.record(
        "settings.update", actor=user, skill_name=None,
        details={"keys": list(payload.keys())},
    )
    return merged
