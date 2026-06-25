"""Application configuration loaded from environment variables (.env)."""
from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

from dotenv import load_dotenv


def _detect_root() -> Path:
    """Return the IvyeaOps runtime root for source and frozen exe builds."""
    explicit = os.getenv("IVYEA_OPS_ROOT", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    if getattr(sys, "frozen", False):
        # PyInstaller one-file/one-folder builds run from the packaged exe.
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]  # repo root


_ROOT = _detect_root()
load_dotenv(_ROOT / "server" / ".env")


def _ensure_localhost_no_proxy() -> None:
    """Make every localhost HTTP call bypass a system/VPN proxy.

    On Windows/macOS with a proxy (Clash/V2Ray/corporate), httpx honours
    HTTP(S)_PROXY/ALL_PROXY and routes 127.0.0.1 (the embedded IvyeaAgent :8765,
    imgflow :3001, server-terminal, …) through the proxy, which returns 502 for
    localhost. urllib already skips it, which is why those calls silently worked
    while httpx-based ones (probes, agent panel synthesis) failed with 502.
    Augmenting NO_PROXY fixes httpx, requests and urllib at once; external hosts
    (DeepSeek, Sorftime, …) still use the proxy."""
    locals_ = ["127.0.0.1", "localhost", "::1", "0.0.0.0"]
    existing: list[str] = []
    for var in ("NO_PROXY", "no_proxy"):
        for h in (os.environ.get(var) or "").split(","):
            h = h.strip()
            if h and h not in existing:
                existing.append(h)
    merged = ",".join(existing + [h for h in locals_ if h not in existing])
    os.environ["NO_PROXY"] = merged
    os.environ["no_proxy"] = merged


_ensure_localhost_no_proxy()


class Settings:
    # --- Runtime paths ---
    root_dir: Path = _ROOT

    # --- Networking ---
    host: str = os.getenv("IVYEA_OPS_HOST", "127.0.0.1")
    port: int = int(os.getenv("IVYEA_OPS_PORT", "8001"))
    dev_mode: bool = os.getenv("IVYEA_OPS_DEV", "0") == "1"

    # --- Security ---
    # On first run if IVYEA_OPS_SECRET is absent we generate an ephemeral one.
    # For production: set it in .env so sessions survive process restarts.
    secret_key: str = os.getenv("IVYEA_OPS_SECRET", "") or secrets.token_urlsafe(32)

    # A single user (personal hub). Username is arbitrary.
    admin_user: str = os.getenv("IVYEA_OPS_USER", "admin")
    # bcrypt hash, NOT plaintext. Generate with: python -m app.core.hashpw
    admin_password_hash: str = os.getenv("IVYEA_OPS_PASSWORD_HASH", "")

    def __init__(self):
        # Auto-hash plaintext ADMIN_PASSWORD if no hash is set
        if not self.admin_password_hash:
            plain = os.getenv("ADMIN_PASSWORD", "")
            if plain:
                try:
                    import bcrypt
                    self.admin_password_hash = bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()
                except Exception:
                    pass

    session_cookie_name: str = "ivyea_ops_session"
    session_max_age_seconds: int = 60 * 60 * 24 * 7  # 7 days
    # Empty default = host-only cookie (safest). Set to e.g. ".example.com"
    # only if you want the session shared across subdomains via auth_request.
    cookie_domain: str = os.getenv("IVYEA_OPS_COOKIE_DOMAIN", "")

    # CSRF: comma-separated list of origins permitted to make state-changing
    # requests to /api/*. Requests whose Origin header is missing or not in
    # this list get rejected with 403. Safe methods (GET/HEAD/OPTIONS) are
    # exempt. Default covers the production host; override in .env for others.
    allowed_origins: list[str] = [
        o.strip()
        for o in os.getenv(
            "IVYEA_OPS_ALLOWED_ORIGINS",
            "",
        ).split(",")
        if o.strip()
    ]

    # --- Data ---
    data_dir: Path = Path(os.getenv("IVYEA_OPS_DATA_DIR", str(_ROOT / "data")))

    # --- Terminal session auto-capture ---
    # Periodically snapshot the tmux pane in the background so the user
    # doesn't have to click the manual "save" button. SHA1-dedups against
    # the last stored row, so an idle terminal won't bloat the DB.
    terminal_autocapture_enabled: bool = (
        os.getenv("IVYEA_OPS_TERMINAL_AUTOCAPTURE", "1").lower()
        not in ("", "0", "false", "no")
    )
    terminal_autocapture_interval: int = int(
        os.getenv("IVYEA_OPS_TERMINAL_AUTOCAPTURE_INTERVAL", "300")
    )


settings = Settings()
