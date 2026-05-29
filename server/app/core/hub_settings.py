"""Persistent runtime settings stored in {data_dir}/hub_settings.json.

Use hub_settings.get(key) from anywhere in the backend.
Empty stored values fall back to the corresponding env var.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

_DEFAULTS: Dict[str, Any] = {
    # AI — single Apimart key serves two distinct purposes:
    #   1. Image generation (gpt-image-2, /v1/images/generations) — used by Listing module
    #   2. (Optional) Text generation (Claude models, /v1/messages) — only if user opts in
    "apimart_key": "",
    "apimart_base": "https://api.apimart.ai/v1",
    # Comma-separated text-AI fallback chain for market research / ad-audit /
    # AI digest etc. Tried in order. Default skips Apimart because the
    # common Apimart subscription only grants image models — add 'apimart'
    # here only if your key has access to Claude text models.
    # Valid values: hermes, codex, claude, apimart
    "text_ai_providers": "hermes,codex,claude",
    # Hermes LLM — primary model (written to ~/.hermes/.env + config.yaml)
    # provider: deepseek | anthropic | openai | openrouter | google | groq | together | custom
    # Saving any of these auto-syncs into Hermes config; no gateway restart needed.
    "hermes_provider": "",
    "hermes_model": "",
    "hermes_api_key": "",
    "hermes_base_url": "",   # leave empty to use provider default
    # Hermes LLM — fallback model (used when primary is rate-limited / down)
    "hermes_fallback_provider": "",
    "hermes_fallback_model": "",
    "hermes_fallback_api_key": "",
    "hermes_fallback_base_url": "",
    # AI 问答（直连大模型，不走智能体）— leave empty to fall back to
    # the default deepseek→apimart chain.
    "assistant_provider": "",     # deepseek | anthropic | openai | openrouter | ...
    "assistant_model": "",
    "assistant_api_key": "",
    "assistant_base_url": "",
    # AI 生图（默认 Apimart gpt-image-2）— leave empty to use apimart_key.
    "image_model": "",            # default gpt-image-2
    "image_api_key": "",          # empty = reuse apimart_key
    "image_base_url": "",         # empty = reuse apimart_base
    # GBrain 语义检索 embedding — provider key written to ~/.hermes/.env,
    # model/provider pushed via `gbrain config set`. Empty = keyword search only.
    "gbrain_embed_provider": "",  # openai | zhipu | dashscope | minimax | voyage | ollama
    "gbrain_embed_model": "",
    "gbrain_embed_api_key": "",
    # Market data
    "sorftime_key": "",      # sorftime.com — 市场调研、关键词趋势
    "sif_key": "",           # sif.com — 深度分析工具箱（独立账号和 key）
    "sellersprite_key": "",  # sellersprite.com — 竞品关键词分析
    # Listing Generator — imgflow backend
    "imgflow_url": "http://127.0.0.1:3001",
    # GBrain knowledge base
    "gbrain_bin": "",           # empty = use env / auto-detect
    "brain_root": "",           # empty = use env / default /root/brain
    "openai_api_key": "",       # for GBrain embeddings
    # Feishu notifications
    "alert_webhook": "",
    "alert_app_id": "",
    "alert_app_secret": "",
    "alert_chat_id": "",
    # CPU alert thresholds
    "alert_threshold": 80,
    "alert_sustain": 5,
    "alert_cooldown": 30,
    # Embedded service URLs (frontend iframes)
    "dashboard_url": "",
    "terminal_url": "",
    # Account — stores new password hash set via UI (overrides OPSHUB_PASSWORD_HASH)
    "password_hash": "",
    # First-run setup wizard completion flag.
    # False/absent = wizard has not been completed; True = skip wizard on next login.
    "setup_done": False,
    # Auto bug-fix: when a feature/tool operation fails, offer to launch an AI
    # repair flow (hermes in an isolated worktree, review-first). Off by default
    # — when off the frontend interceptor and backend engine never fire.
    "autofix_enabled": False,
    # --- External-integration paths ----------------------------------------
    # Optional: ops-hub works standalone without any of these, but the
    # monitor page and agent picker light up when you point at the right
    # binaries / databases.  Leave empty to fall back to PATH lookup or
    # disable the corresponding feature.
    "hermes_bin": "",            # `hermes` CLI absolute path
    "codex_bin": "",             # `codex` CLI absolute path
    "claude_bin": "",            # `claude` CLI absolute path
    "kiro_cli_bin": "",          # `kiro-cli` CLI absolute path
    "hermes_db": "",             # /root/.hermes/state.db (token-usage)
    "codex_db": "",              # /root/.codex/state_5.sqlite
    "feishu_codex_db": "",       # /root/feishu-codex-relay/.codex-home/state_5.sqlite
    "kiro_gateway_db": "",       # /root/kiro-gateway/usage.db
    "kiro_cli_db": "",           # /root/.local/share/kiro-cli/data.sqlite3
    "kiro_cli_sessions_dir": "", # /root/.kiro/sessions/cli
    "claude_projects_dir": "",   # /root/.claude/projects (jsonl token logs)
    "hermes_node_bin": "",       # /root/.hermes/node/bin (PATH augment for spawns)
    "bun_bin": "",               # /root/.bun/bin (gbrain depends on bun)
}

_ENV_MAP: Dict[str, str] = {
    "apimart_key": "APIMART_KEY",
    "text_ai_providers": "OPSHUB_TEXT_AI_PROVIDERS",
    "sorftime_key": "SORFTIME_KEY",
    "openai_api_key": "OPENAI_API_KEY",
    "gbrain_bin": "OPSHUB_GBRAIN_BIN",
    "brain_root": "OPSHUB_BRAIN_ROOT",
    "alert_webhook": "OPSHUB_ALERT_WEBHOOK",
    "alert_app_id": "OPSHUB_ALERT_APP_ID",
    "alert_app_secret": "OPSHUB_ALERT_APP_SECRET",
    "alert_chat_id": "OPSHUB_ALERT_CHAT_ID",
    "alert_threshold": "OPSHUB_ALERT_THRESHOLD",
    "alert_sustain": "OPSHUB_ALERT_SUSTAIN",
    "alert_cooldown": "OPSHUB_ALERT_COOLDOWN",
    # External integrations
    "hermes_bin": "OPSHUB_HERMES_BIN",
    "codex_bin": "OPSHUB_CODEX_BIN",
    "claude_bin": "OPSHUB_CLAUDE_BIN",
    "kiro_cli_bin": "OPSHUB_KIRO_CLI_BIN",
    "hermes_db": "OPSHUB_HERMES_DB",
    "codex_db": "OPSHUB_CODEX_DB",
    "feishu_codex_db": "OPSHUB_FEISHU_CODEX_DB",
    "kiro_gateway_db": "OPSHUB_KIRO_GATEWAY_DB",
    "kiro_cli_db": "OPSHUB_KIRO_CLI_DB",
    "kiro_cli_sessions_dir": "OPSHUB_KIRO_CLI_SESSIONS_DIR",
    "claude_projects_dir": "OPSHUB_CLAUDE_PROJECTS_DIR",
    "hermes_node_bin": "OPSHUB_HERMES_NODE_BIN",
    "bun_bin": "OPSHUB_BUN_BIN",
}


def _path() -> Path:
    from app.core.config import settings
    return settings.data_dir / "hub_settings.json"


def _read_file() -> Dict[str, Any]:
    p = _path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:
        return {}


def load() -> Dict[str, Any]:
    """Return stored settings merged with defaults for missing keys."""
    stored = _read_file()
    result = dict(_DEFAULTS)
    result.update({k: v for k, v in stored.items() if k in _DEFAULTS})
    return result


def get(key: str, default: Any = None) -> Any:
    """Read one setting; empty/missing falls back to env var then default."""
    val = load().get(key)
    if val is not None and val != "":
        return val
    env_key = _ENV_MAP.get(key)
    if env_key:
        env_val = os.getenv(env_key, "")
        if env_val:
            if isinstance(_DEFAULTS.get(key), int):
                try:
                    return int(env_val)
                except (ValueError, TypeError):
                    pass
            return env_val
    return _DEFAULTS.get(key, default)


def save(updates: Dict[str, Any]) -> Dict[str, Any]:
    """Merge updates and atomically persist; returns full settings."""
    current = load()
    for k, v in updates.items():
        if k in _DEFAULTS:
            current[k] = v
    p = _path()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(p)
    return current
