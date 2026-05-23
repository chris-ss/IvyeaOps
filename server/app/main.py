"""ops-hub FastAPI backend entry point."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.skill_paths import (
    SKILLS_ROOT,
    ensure_studio_dirs,
    studio_paths_summary,
)
from app.routers import ad_audit, agent_hub, amazon, auth, brain, health, monitor, news, skill, terminal
from app.routers import listing as listing_router
from app.routers import market as market_router
from app.routers import hub_settings as hub_settings_router
from app.routers import projects as projects_router
from app.routers import git as git_router
from app.routers import setup as setup_router


# Methods that can mutate state; anything not in this set is exempt from the
# Origin check (GET/HEAD/OPTIONS are considered safe per RFC 9110 §9.2.1).
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    # Skill Studio directories: we provision our own state dir
    # (~/.hermes/skill-studio/) but intentionally NEVER touch SKILLS_ROOT —
    # that's Hermes' territory. If it doesn't exist we just warn; the Skill
    # Studio API will surface a clear error on first call.
    ensure_studio_dirs()
    if not SKILLS_ROOT.exists():
        print(f"[ops-hub] WARNING skills root missing: {SKILLS_ROOT}")
    for key, value in studio_paths_summary().items():
        print(f"[ops-hub] {key}: {value}")

    # Best-effort: sweep expired trash entries on startup. Failure here must
    # never block the server from coming up — the API will retry on demand.
    try:
        from app.services.trash import purge_expired
        purged = purge_expired()
        if purged:
            print(f"[ops-hub] purged {purged} expired trash entries")
    except Exception as e:
        print(f"[ops-hub] trash purge skipped: {e}")

    # Best-effort: sweep expired ASIN audit artifacts (30-day retention).
    try:
        from app.services.asin_audit import sweep_expired as _sweep_audits
        n = _sweep_audits()
        if n:
            print(f"[ops-hub] purged {n} expired audit dirs")
    except Exception as e:
        print(f"[ops-hub] audit sweep skipped: {e}")

    # Rescue ghost "running" jobs left behind by a prior crash/restart:
    # _live_jobs is empty on boot, so anything status=running on disk is stale.
    try:
        from app.services.asin_audit import sweep_stale_running
        n = sweep_stale_running()
        if n:
            print(f"[ops-hub] marked {n} stale running jobs as failed")
    except Exception as e:
        print(f"[ops-hub] stale running sweep skipped: {e}")

    # Same pair of sweeps for ad-audit jobs.
    try:
        from app.services.ad_audit import sweep_expired as _sweep_ad
        n = _sweep_ad()
        if n:
            print(f"[ops-hub] purged {n} expired ad-audit dirs")
    except Exception as e:
        print(f"[ops-hub] ad-audit expired sweep skipped: {e}")

    try:
        from app.services.ad_audit import sweep_stale_running as _sweep_ad_stale
        n = _sweep_ad_stale()
        if n:
            print(f"[ops-hub] marked {n} stale ad-audit jobs as failed")
    except Exception as e:
        print(f"[ops-hub] ad-audit stale sweep skipped: {e}")

    # Brain chat/upload metadata DB is local SQLite; initialize eagerly so
    # schema problems are visible at boot, while keeping the service lightweight.
    try:
        from app.services.brain_chat_service import init_db as _init_brain_chat
        _init_brain_chat()
        print("[ops-hub] brain chat DB ready")
    except Exception as e:
        print(f"[ops-hub] brain chat DB init skipped: {e}")

    # Multi-agent hub: schema + agent discovery + PTY reaper.  All best-effort
    # so a misconfigured agent (e.g. missing binary) never blocks server boot.
    try:
        from app.services import agent_session_service as _agent_db
        from app.services import agent_registry as _agent_reg
        from app.services.pty_manager import manager as _pty_mgr

        _agent_db.init_db()
        agents = _agent_reg.discover_agents()
        ok = sum(1 for a in agents if a.get("enabled"))
        print(f"[ops-hub] agent registry: {ok}/{len(agents)} enabled")
        _pty_mgr.start_background_tasks()
    except Exception as e:
        print(f"[ops-hub] agent hub init skipped: {e}")

    print(f"[ops-hub] starting on {settings.host}:{settings.port}")
    print(f"[ops-hub] data dir: {settings.data_dir}")
    print(f"[ops-hub] dev_mode: {settings.dev_mode}")

    # Terminal subsystem:
    # (1) legacy tmux auto-capture for the old shared terminal page
    # (2) new live multi-terminal session manager for the native workbench
    try:
        terminal.start_autocapture()
    except Exception as e:
        print(f"[ops-hub] terminal auto-capture not started: {e}")
    try:
        terminal.init_live_sessions()
        print("[ops-hub] live terminal sessions ready")
    except Exception as e:
        print(f"[ops-hub] live terminal init skipped: {e}")

    # systemd integration: announce READY and start the watchdog ping
    # loop. Both are no-ops when running outside systemd (NOTIFY_SOCKET
    # / WATCHDOG_USEC absent), so dev workflows are unaffected.
    from app.services.watchdog import notify_ready, notify_status, watchdog_loop
    notify_ready()
    notify_status("ready")
    _watchdog_task = asyncio.create_task(watchdog_loop(), name="sd-watchdog")

    yield
    _watchdog_task.cancel()
    try:
        await _watchdog_task
    except (asyncio.CancelledError, Exception):
        pass
    try:
        await terminal.stop_autocapture()
    except Exception as e:
        print(f"[ops-hub] terminal auto-capture stop error: {e}")
    try:
        await terminal.shutdown_live_sessions()
    except Exception as e:
        print(f"[ops-hub] live terminal shutdown error: {e}")
    try:
        from app.services.pty_manager import manager as _pty_mgr
        await _pty_mgr.shutdown()
    except Exception as e:
        print(f"[ops-hub] pty manager shutdown error: {e}")
    print("[ops-hub] stopped")


app = FastAPI(
    title="ops-hub",
    description="Personal Amazon operations hub",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS: only needed in dev mode when Vite dev server (5174) calls us at 8001.
# In production the SPA is served by FastAPI itself, same origin.
if settings.dev_mode:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5174", "http://127.0.0.1:5174"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# --- CSRF: Origin allow-list for state-changing /api/* requests ---
# Cookie-based sessions are vulnerable to CSRF, so we require that unsafe
# requests carry an Origin header pointing at one of our trusted hosts. In
# dev_mode we extend the list with the Vite dev server origins automatically.
_ALLOWED = set(settings.allowed_origins)
if settings.dev_mode:
    _ALLOWED.update({"http://localhost:5174", "http://127.0.0.1:5174"})


@app.middleware("http")
async def _origin_guard(request: Request, call_next):
    # Only guard API writes; GETs and non-API routes (SPA) are unaffected.
    if request.method in _UNSAFE_METHODS and request.url.path.startswith("/api/"):
        # Native app requests (no browser CSRF risk) — skip origin check.
        ua = request.headers.get("user-agent", "")
        if "OpsHubAndroid" in ua:
            return await call_next(request)

        origin = request.headers.get("origin")
        # Fall back to Referer when Origin is absent (some older browsers or
        # form submissions strip Origin on same-origin POSTs).
        if not origin:
            referer = request.headers.get("referer", "")
            if referer:
                # Strip path: keep scheme://host[:port].
                from urllib.parse import urlsplit

                parts = urlsplit(referer)
                if parts.scheme and parts.netloc:
                    origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in _ALLOWED:
            return JSONResponse(
                status_code=403,
                content={"detail": "origin not allowed"},
            )
    return await call_next(request)

# --- API routes (prefixed /api) ---
# IMPORTANT: must be registered BEFORE the SPA catch-all below.
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(amazon.router, prefix="/api/amazon", tags=["amazon"])
app.include_router(ad_audit.router, prefix="/api/ad-audit", tags=["ad-audit"])
app.include_router(monitor.router, prefix="/api/monitor", tags=["monitor"])
app.include_router(skill.router, prefix="/api/skill", tags=["skill"])
app.include_router(news.router, prefix="/api/news", tags=["news"])
app.include_router(brain.router, prefix="/api/brain", tags=["brain"])
app.include_router(listing_router.router, prefix="/api/listing", tags=["listing"])
app.include_router(terminal.router, prefix="/api/terminal", tags=["terminal"])
app.include_router(agent_hub.router, prefix="/api", tags=["agent-hub"])
app.include_router(market_router.router, prefix="/api/market", tags=["market"])
app.include_router(hub_settings_router.router, prefix="/api", tags=["settings"])
app.include_router(projects_router.router, prefix="/api", tags=["projects"])
app.include_router(git_router.router, prefix="/api", tags=["git"])
app.include_router(setup_router.router, prefix="/api", tags=["setup"])


# --- Frontend: serve React SPA (client/dist) ---
# Strategy:
#   /assets/*           -> static files (JS/CSS chunks hashed by Vite)
#   /favicon.ico        -> static file if exists
#   everything else     -> index.html (SPA fallback for React Router)
_CLIENT_DIST = Path(__file__).resolve().parents[2] / "client" / "dist"


if _CLIENT_DIST.exists():
    _ASSETS = _CLIENT_DIST / "assets"
    if _ASSETS.exists():
        app.mount("/assets", StaticFiles(directory=_ASSETS), name="assets")

    @app.get("/favicon.ico", include_in_schema=False)
    async def _favicon() -> FileResponse:
        fp = _CLIENT_DIST / "favicon.ico"
        if fp.is_file():
            return FileResponse(fp)
        raise HTTPException(status_code=404)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa_fallback(full_path: str) -> FileResponse:
        # Don't fall back for /api/* — those should 404 cleanly.
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(status_code=404)
        # Serve any real file in dist root (e.g. robots.txt), otherwise
        # fall back to index.html so React Router handles the URL.
        candidate = _CLIENT_DIST / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        index = _CLIENT_DIST / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=404, detail="frontend not built")
        return FileResponse(index, headers={"Cache-Control": "no-cache, must-revalidate"})
