"""Sync ops-hub data-source keys into Hermes config + register MCP servers.

Called whenever hub_settings are saved. Idempotent — safe to call repeatedly.

Responsibilities:
  1. Sorftime / SIF key  → update mcp_servers.sorftime.url query param AND
                            mcp_servers.sif_mcp.headers.Authorization
  2. SellerSprite key    → add/update mcp_servers.sellersprite (stdio MCP)
  3. If a key is cleared → leave the MCP entry but blank the credential so
                            Hermes will skip it gracefully (don't delete the
                            entry to avoid losing other config the user set).
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict

import yaml  # PyYAML — available in the ops-hub venv


_HERMES_CFG = Path.home() / ".hermes" / "config.yaml"
_MCP_SCRIPT  = Path(__file__).resolve().parents[2] / "tools" / "sellersprite_mcp.py"


# ── YAML helpers (round-trip preserving comments as best as PyYAML can) ──────

def _load() -> Dict[str, Any]:
    if not _HERMES_CFG.exists():
        return {}
    try:
        return yaml.safe_load(_HERMES_CFG.read_text("utf-8")) or {}
    except Exception:
        return {}


def _save(cfg: Dict[str, Any]) -> None:
    _HERMES_CFG.parent.mkdir(parents=True, exist_ok=True)
    tmp = _HERMES_CFG.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.dump(cfg, allow_unicode=True, default_flow_style=False), "utf-8")
    tmp.replace(_HERMES_CFG)


# ── Sync functions ────────────────────────────────────────────────────────────

def sync_sorftime_sif(key: str) -> None:
    """Update Sorftime URL + SIF Bearer token in hermes config."""
    cfg = _load()
    mcp = cfg.setdefault("mcp_servers", {})

    # Sorftime: key goes in URL query string
    sorftime = mcp.setdefault("sorftime", {})
    if key:
        old_url = sorftime.get("url", "")
        # Replace or set ?key= param
        base = re.sub(r"\?.*$", "", old_url) or "https://mcp.sorftime.com"
        sorftime["url"] = f"{base}?key={key}"
    sorftime.setdefault("timeout", 180)
    sorftime.setdefault("connect_timeout", 60)

    # SIF MCP: key goes in Authorization header
    sif = mcp.setdefault("sif_mcp", {})
    sif["url"] = "https://mcp.sif.com/mcp"
    sif.setdefault("timeout", 120)
    sif.setdefault("connect_timeout", 60)
    if key:
        sif.setdefault("headers", {})["Authorization"] = f"Bearer {key}"

    _save(cfg)


def sync_sellersprite(key: str) -> None:
    """Register sellersprite stdio MCP in hermes config."""
    cfg  = _load()
    mcp  = cfg.setdefault("mcp_servers", {})
    entry = mcp.setdefault("sellersprite", {})

    script = str(_MCP_SCRIPT)
    python  = _python_bin()
    entry["command"] = python
    entry["args"]    = [script]
    entry["env"]     = {"SELLERSPRITE_KEY": key} if key else {}
    entry.setdefault("timeout", 30)

    _save(cfg)


def _python_bin() -> str:
    """Return the Python interpreter that can run the MCP server."""
    # Prefer the same interpreter running this module.
    return os.environ.get("OPSHUB_PYTHON", "python3")


# ── Public entry point ────────────────────────────────────────────────────────

def on_settings_saved(updates: Dict[str, Any]) -> None:
    """Called after hub_settings.save() with the full updated settings dict."""
    sorftime_key    = (updates.get("sorftime_key")    or "").strip()
    sif_key         = (updates.get("sif_key")         or "").strip()
    sellersprite_key = (updates.get("sellersprite_key") or "").strip()

    # SIF and Sorftime share one key; prefer sif_key override if explicitly set
    effective_sorftime_sif = sif_key or sorftime_key
    if effective_sorftime_sif or "sorftime_key" in updates or "sif_key" in updates:
        try:
            sync_sorftime_sif(effective_sorftime_sif)
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning("hermes sorftime/sif sync failed: %s", exc)

    if "sellersprite_key" in updates:
        try:
            sync_sellersprite(sellersprite_key)
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning("hermes sellersprite sync failed: %s", exc)
