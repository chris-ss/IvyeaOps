# External integrations

ops-hub runs standalone. The features below are *optional*: configure
them only if you've installed the corresponding tool on the same host.

All integration paths are configured via:

- the web UI at `系统配置 → 外部集成路径`, **or**
- the matching `OPSHUB_*` env in `server/.env` as a fallback.

The UI's **系统健康状态** panel shows which integrations are live.

## What each integration enables

### Hermes (`hermes_bin`, `hermes_db`, `hermes_node_bin`)

[Hermes Agent](https://github.com/anthropics/hermes) — gateway for Claude
API requests with cron jobs, MCP servers, message history.

- `hermes_bin` lets the workbench Agent picker pick "hermes" as the
  runner for ASIN audits, ad audits, news digests, brain chat.
- `hermes_db` (`/root/.hermes/state.db`) feeds the token-usage monitor
  with per-session token / model rows.
- `hermes_node_bin` (`/root/.hermes/node/bin`) is prepended to the spawn
  PATH so Hermes can find its bundled `node` and child CLIs.

The News page also calls `hermes cronjob run <id>` to refresh the AI
digest; that needs only `hermes_bin`.

### Codex (`codex_bin`, `codex_db`, `feishu_codex_db`)

[OpenAI Codex CLI](https://github.com/openai/codex). The agent picker
exposes it alongside Hermes / Claude. `codex_db` (and the variant
`feishu_codex_db` for a Feishu-relay sidecar install) feeds token usage.

### Claude Code (`claude_bin`, `claude_projects_dir`)

[Claude Code CLI](https://docs.claude.com/en/docs/claude-code).

- `claude_bin` — point at the platform binary, not the `claude.exe`
  shim. Common locations:
  - `/root/.hermes/node/lib/node_modules/@anthropic-ai/claude-code/node_modules/@anthropic-ai/claude-code-linux-x64/claude`
  - `/usr/local/bin/claude` (when installed via the official installer)
- `claude_projects_dir` (`~/.claude/projects`) — Claude Code's per-project
  jsonl session logs; token monitor reads them.

### Kiro (`kiro_cli_bin`, `kiro_gateway_db`, `kiro_cli_db`, `kiro_cli_sessions_dir`)

[Kiro CLI](https://kiro.dev/). Optional alternative agent runner.

- `kiro_cli_bin` — agent picker entry.
- `kiro_gateway_db` — locally-hosted Kiro Gateway usage stats.
- `kiro_cli_db` + `kiro_cli_sessions_dir` — token estimation for CLI
  sessions (no exact token counter; we estimate from `context_usage_percentage`).

### GBrain / Bun (`bun_bin`)

GBrain is a Bun-linked knowledge-base CLI. Setting `bun_bin`
(`/root/.bun/bin`) prepends it to the gbrain spawn PATH so the bun
runtime is discoverable. The gbrain executable itself is configured
under `GBrain 知识库` (key `gbrain_bin`).

## Adding a new integration

1. Add the key to `_DEFAULTS` and `_ENV_MAP` in
   `server/app/core/hub_settings.py`.
2. Add a getter to `server/app/core/integrations.py` (or extend
   `extra_path_dirs()` if it's a PATH augmentation).
3. Add the field to the TypeScript types in
   `client/src/api/settings.ts` and a `<Field>` in
   `client/src/pages/workbench/HubSettings.tsx`.
4. Add a row to `all_status()` in integrations.py and a corresponding
   row in the HealthPanel `rows[]` so the status panel picks it up.

The pattern is intentionally repetitive — one place per layer — but it
keeps every integration discoverable without dynamic dispatch.

## Removing the integration noise entirely

If you don't run any of the above and want a cleaner UI:

1. Leave all paths empty (the default). The agent picker will only show
   runners whose binary is on `PATH`; the monitor will show "(unconfigured)"
   for each token-source row.
2. Optional: hide the "外部集成路径" section by removing the corresponding
   `<Section>` block from `HubSettings.tsx`. The backend still accepts
   the keys via API so you can re-enable them later.
