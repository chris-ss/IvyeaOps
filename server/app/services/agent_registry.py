"""Agent registry: static catalog + runtime discovery.

We support a small fixed set out of the box (hermes, codex, claude-code,
kiro-cli). Adding a new agent is two steps:

  1. Drop a new entry into AGENT_DEFS below.
  2. Restart ops-hub. discover_agents() will probe and persist.

Each AgentDef captures everything pty_manager and the chat/SSE router need
to know to launch and converse with the binary:

  - bin / fallback_paths : how to find the executable.
  - models               : the model list shown to the user (static, with an
                           optional dynamic merge from kiro-gateway).
  - resume_strategy      : how to wake a dormant session.
  - cli_args / chat_args : argv templates for the two modes.
  - prompt_regex         : where the binary's interactive prompt ends, so we
                           can chunk PTY output into "assistant turns".

Discovery is best-effort. A missing binary is recorded as enabled=False so
the UI can grey-out the card without breaking other agents.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.services import agent_session_service as svc

# ---------------------------------------------------------------------------
# Optional legacy gateway config. Leave unset by default: the old local
# kiro gateway on :8000 has been retired.
# ---------------------------------------------------------------------------
KIRO_GATEWAY_URL = os.environ.get("OPSHUB_KIRO_GATEWAY", "").strip()
KIRO_GATEWAY_KEY = os.environ.get("OPSHUB_KIRO_GATEWAY_KEY", "hermes2024")


def _list_kiro_models() -> list[str]:
    """Best-effort fetch of available models from a legacy kiro-style gateway.

    When no legacy gateway is configured we simply return an empty list.
    """
    if not KIRO_GATEWAY_URL:
        return []
    try:
        r = httpx.get(
            f"{KIRO_GATEWAY_URL}/v1/models",
            headers={"Authorization": f"Bearer {KIRO_GATEWAY_KEY}"},
            timeout=2.5,
        )
        if r.status_code != 200:
            return []
        data = r.json().get("data", [])
        return [m["id"] for m in data if isinstance(m, dict) and "id" in m]
    except Exception:
        return []


_KIRO_MODELS_FALLBACK = []


# ---------------------------------------------------------------------------
# Agent definitions
# ---------------------------------------------------------------------------
@dataclass
class AgentDef:
    id: str
    display_name: str
    bin_candidates: list[str]
    default_model: str | None
    static_models: list[str] = field(default_factory=list)
    use_kiro_models: bool = False  # merge in kiro-gateway model catalog
    # CLI mode — interactive PTY argv. {workdir}/{model} expanded at launch time.
    cli_args: list[str] = field(default_factory=list)
    # Chat mode — non-interactive one-shot argv (preferred when supported).
    # If None, chat falls back to "write into the session PTY".
    chat_args: list[str] | None = None
    # When True, do NOT auto-append --model/-m to the chat-mode argv.  Some
    # agents (hermes) silently fail when given a model via the -z flag and
    # we must rely on their persisted default instead.
    chat_skip_model: bool = False
    # Regex patterns (re.MULTILINE | re.DOTALL) to strip from the final
    # accumulated chat-mode output.  Used to drop banners / footers / shell
    # prompt artifacts that the agent prints alongside its actual reply.
    chat_strip_patterns: list[str] = field(default_factory=list)
    # Optional regex with a (?P<answer>...) capture group.  When set, only
    # the captured group is kept as the assistant message; everything else
    # is discarded.  Used for codex which dumps a session header / footer
    # around the actual model response.
    chat_extract_pattern: str | None = None
    # How to wake a dormant session:
    #   "flag"   : add resume_flag to argv; resume_id arg gives the session id.
    #   "prompt" : prepend a context message to first user input.
    #   "none"   : no native support; we always prompt-inject.
    resume_strategy: str = "prompt"
    resume_flag: str | None = None  # e.g. "--resume" / "--resume-id"
    # Used to detect when the agent is ready for the next user message.
    prompt_regex: str = r"\n[$#>] $"
    env: dict[str, str] = field(default_factory=dict)
    # Anything the renderer might want to know, surfaced in caps.
    caps_extra: dict[str, Any] = field(default_factory=dict)


AGENT_DEFS: dict[str, AgentDef] = {
    # ---- Hermes Agent ---------------------------------------------------
    "hermes": AgentDef(
        id="hermes",
        display_name="Hermes",
        # First candidate (if any) comes from hub_settings.hermes_bin at
        # discovery time; PATH lookup ("hermes") is the documented fallback.
        bin_candidates=["hermes"],
        default_model="gpt-5.4",
        static_models=[
            "gpt-5.4",
            "gpt-5.5",
            "anthropic/claude-sonnet-4.6",
            "anthropic/claude-sonnet-4.5",
            "anthropic/claude-haiku-4.5",
            "anthropic/claude-opus-4.5",
            "anthropic/claude-opus-4.6",
            "anthropic/claude-opus-4.7",
            "anthropic/deepseek-3.2",
            "anthropic/qwen3-coder-next",
            "anthropic/glm-5",
        ],
        # Interactive: just `hermes chat`. We pass --model when given.
        cli_args=["chat"],
        # One-shot: `hermes -z PROMPT` is the documented oneshot flag.
        # NOTE: hermes silently swallows output when given `-m MODEL` together
        # with `-z` (we tested both `-m anthropic/...` and `-m claude-...`).
        # Skip the model flag in chat mode and let hermes use its persisted
        # default; the user can switch via `hermes model` interactively.
        chat_args=["-z", "{prompt}"],
        chat_skip_model=True,
        resume_strategy="flag",
        resume_flag="--resume",
        prompt_regex=r"hermes ?[>›❯]\s*$",
        caps_extra={"supports_oneshot": True, "supports_resume": True},
    ),
    # ---- Codex (OpenAI) -------------------------------------------------
    "codex": AgentDef(
        id="codex",
        display_name="Codex",
        bin_candidates=["codex"],
        default_model="gpt-5.5",
        # gpt-5.5 is what `codex` ships with for ChatGPT-account users; the
        # other listed names are forbidden in that mode but can be unlocked
        # via api-key login.  Keep them visible so users on api-key auth
        # still see the picker.
        static_models=["gpt-5.5", "gpt-5", "gpt-5-codex", "o3", "o4-mini", "codex-mini"],
        cli_args=[],  # `codex` alone enters interactive mode
        # `codex exec` is the non-interactive variant.
        chat_args=["exec", "{prompt}"],
        resume_strategy="flag",
        resume_flag="resume",  # `codex resume --last`
        prompt_regex=r"\n[›❯>]\s*$",
        # codex exec prints a session header (reasoning summaries / session id),
        # the user's echoed prompt, then `codex\n<reply>\ntokens used\n<n>`,
        # and finally repeats the reply.  Extract just the first model reply.
        chat_extract_pattern=r"\ncodex(?:[^\n]*)?\n(?P<answer>.+?)(?:\ntokens used\n|\Z)",
        caps_extra={"supports_oneshot": True, "supports_resume": True},
    ),
    # ---- Claude Code ----------------------------------------------------
    # The binary is a multi-platform wrapper that picks the linux-x64 native
    # binary at runtime. Calling the wrapper through node fails when run from
    # a non-shell (we saw "could not find native binary" earlier) so we point
    # straight at the platform binary.
    "claude": AgentDef(
        id="claude",
        display_name="Claude Code",
        # Per-install: the npm package's claude.exe shim is an error stub when
        # the postinstall didn't run, so users typically have to point at the
        # platform-specific binary directly. Configure via hub_settings.claude_bin.
        bin_candidates=["claude"],
        default_model="claude-sonnet-4.5",
        static_models=[
            "claude-sonnet-4.5",
            "claude-sonnet-4.6",
            "claude-haiku-4.5",
            "claude-opus-4.5",
            "claude-opus-4.6",
            "claude-opus-4.7",
        ],
        cli_args=[],
        # `claude -p <prompt>` prints the answer and exits.
        chat_args=["-p", "{prompt}"],
        resume_strategy="flag",
        resume_flag="--resume",
        prompt_regex=r"\n[>❯]\s*$",
        env={},
        caps_extra={"supports_oneshot": True, "supports_resume": True},
    ),
    # ---- Kiro CLI -------------------------------------------------------
    "kiro": AgentDef(
        id="kiro",
        display_name="Kiro CLI",
        bin_candidates=["kiro-cli"],
        default_model="claude-sonnet-4.5",
        static_models=[],
        use_kiro_models=True,  # exact same gateway as the agent itself uses
        # `kiro-cli chat` is the chat subcommand.
        cli_args=["chat"],
        # `kiro-cli chat --no-interactive "<prompt>"` prints the answer.
        chat_args=["chat", "--no-interactive", "--trust-all-tools", "{prompt}"],
        resume_strategy="flag",
        resume_flag="--resume-id",
        prompt_regex=r"\n[>❯]\s*$",
        # kiro chat prints a security banner, the prompt arrow `> `, and a
        # "▸ Credits: ..." footer around the actual answer.  Drop them.
        chat_strip_patterns=[
            r"^All tools are now trusted[\s\S]*?security/[^\n]*\n+",
            r"\n+\s*▸ Credits:[^\n]*",
            r"^>\s+",
        ],
        caps_extra={"supports_oneshot": True, "supports_resume": True},
    ),
}


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def _resolve_bin(candidates: list[str]) -> str | None:
    for c in candidates:
        if os.path.isabs(c) and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
        # Fall back to PATH lookup for relative names.
        if not os.path.isabs(c):
            found = shutil.which(c)
            if found:
                return found
    return None


# Per-agent hub_settings key holding a user-configured absolute path.
_INTEGRATION_KEYS = {
    "hermes": "hermes_bin",
    "codex":  "codex_bin",
    "claude": "claude_bin",
    "kiro":   "kiro_cli_bin",
}


def _candidates_for(adef: "AgentDef") -> list[str]:
    """Prepend a hub_settings override (if set) to the static candidate list."""
    from app.core import hub_settings as _hs
    extra: list[str] = []
    key = _INTEGRATION_KEYS.get(adef.id)
    if key:
        v = (_hs.get(key) or "").strip()
        if v:
            extra.append(v)
    return [*extra, *adef.bin_candidates]


def discover_agents() -> list[dict[str, Any]]:
    """Probe each defined agent, persist its projection, return runtime info.

    Called from app lifespan. Cheap enough to call again on demand if the
    user installs a new binary at runtime.
    """
    svc.init_db()
    kiro_models = _list_kiro_models()
    discovered: list[dict[str, Any]] = []
    for adef in AGENT_DEFS.values():
        bin_path = _resolve_bin(_candidates_for(adef))
        models = list(adef.static_models)
        if adef.use_kiro_models:
            # Use kiro-gateway models when defined; fall back to static list
            # if the gateway is unreachable so the picker stays usable.
            models = kiro_models or list(_KIRO_MODELS_FALLBACK)
        caps = {
            "cli": True,
            "chat": adef.chat_args is not None,
            "resume": adef.resume_strategy != "none",
            "binary_found": bin_path is not None,
            **adef.caps_extra,
        }
        svc.upsert_agent(
            agent_id=adef.id,
            display_name=adef.display_name,
            binary_path=bin_path or "",
            default_model=adef.default_model,
            models=models,
            caps=caps,
            enabled=bin_path is not None,
        )
        discovered.append(
            {
                "id": adef.id,
                "display_name": adef.display_name,
                "binary_path": bin_path or "",
                "default_model": adef.default_model,
                "models": models,
                "caps": caps,
                "enabled": bin_path is not None,
            }
        )
    return discovered


def get_agent_def(agent_id: str) -> AgentDef:
    if agent_id not in AGENT_DEFS:
        raise KeyError(f"unknown agent: {agent_id}")
    return AGENT_DEFS[agent_id]


def list_agents() -> list[dict[str, Any]]:
    """Cheap read for the picker — returns the persisted projection."""
    rows = svc.list_agents_db()
    if not rows:
        # First boot before discovery — fall back to live probe.
        return discover_agents()
    return rows


def build_argv(
    agent_id: str,
    *,
    mode: str,
    model: str | None = None,
    prompt: str | None = None,
    resume_id: str | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Construct the argv + env extension for spawning an agent.

    mode = 'cli'  -> interactive PTY launch.
    mode = 'chat' -> one-shot non-interactive call (subprocess.Popen).
    """
    adef = get_agent_def(agent_id)
    # Honor hub_settings.<agent>_bin override (same logic as discover_agents),
    # otherwise systemd's narrow PATH causes the spawn path to disagree with
    # the discovery path — fine at boot, broken on first user message.
    bin_path = _resolve_bin(_candidates_for(adef))
    if not bin_path:
        raise RuntimeError(f"agent binary missing: {agent_id}")
    if mode == "cli":
        argv = [bin_path, *adef.cli_args]
    elif mode == "chat":
        if adef.chat_args is None:
            raise RuntimeError(f"agent {agent_id} has no chat-mode args defined")
        argv = [bin_path]
        for a in adef.chat_args:
            argv.append(a.replace("{prompt}", prompt or ""))
    else:
        raise ValueError(f"bad mode: {mode}")

    if model and adef.id != "hermes":
        # Most agents take --model; hermes uses -m and may already have one
        # in argv (we let the user-side model flow win).
        # In chat mode some agents must skip the model flag entirely.
        if not (mode == "chat" and adef.chat_skip_model):
            argv.extend(["--model", model])
    elif model and adef.id == "hermes":
        if not (mode == "chat" and adef.chat_skip_model):
            argv.extend(["-m", model])

    if resume_id and adef.resume_strategy == "flag" and adef.resume_flag:
        if adef.id == "codex":
            # `codex resume <id>` — subcommand form, not a flag. The
            # previous `--last` hardcode ignored the actual id; we now
            # pass the session id explicitly so users get the rollout
            # they picked from the sidebar.
            argv = [bin_path, "resume", resume_id]
        else:
            argv.extend([adef.resume_flag, resume_id])

    env = dict(adef.env)
    return argv, env
