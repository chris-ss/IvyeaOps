# Configuration

ops-hub has two configuration layers. Everything not listed here is a code
constant — no other config files exist.

## Layer 1 · Startup env (`server/.env`)

Read once at server boot. Required for ops-hub to start at all. Edit the
file and restart the service to take effect.

| Key | Purpose | Notes |
|---|---|---|
| `OPSHUB_HOST` | Bind address (default `127.0.0.1`) | Don't expose directly; nginx fronts it. |
| `OPSHUB_PORT` | Bind port (default `8001`) | Must match nginx + systemd template. |
| `OPSHUB_DEV` | `1` to allow Vite dev-server CORS and drop `Secure` cookie | Production: `0`. |
| `OPSHUB_SECRET` | itsdangerous signing key for the session cookie | Must be stable; regenerating logs everyone out. |
| `OPSHUB_USER` | Admin username | Single-user; usually `admin`. |
| `OPSHUB_PASSWORD_HASH` | bcrypt hash of admin password | Generate via `python -m app.core.hashpw`. |
| `OPSHUB_ALLOWED_ORIGINS` | Comma-separated origins allowed to POST | Required; CSRF guard rejects others. |
| `OPSHUB_COOKIE_DOMAIN` | Session cookie domain | Empty = host-only (safest). Set `.example.com` for sub-domain sharing. |
| `OPSHUB_DATA_DIR` | Where SQLite, uploads, hub_settings.json live | Defaults to `<repo>/data/`. |
| `OPSHUB_TERMINAL_AUTOCAPTURE` | `1` to keep snapshotting active tmux pane | Default on. |
| `OPSHUB_TERMINAL_AUTOCAPTURE_INTERVAL` | Seconds between snapshots | Default `300`. |

Anything else (`OPSHUB_HERMES_BIN`, `APIMART_KEY`, …) listed in
`.env.example` is *optional* and only used as a fallback when the matching
hub_settings.json entry is empty.

## Layer 2 · Runtime settings (`data/hub_settings.json`)

Edited in the web UI at `系统配置` / Settings. Persisted as JSON; on read
the in-process helper falls back to env (and then a built-in default) when
a key is empty.

Sections in the UI:

- **AI 服务** — Apimart API key + base
- **Sorftime 市场数据** — Sorftime API key
- **Listing 生成服务** — imgflow backend URL
- **GBrain 知识库** — gbrain CLI path, brain root dir, OpenAI key for
  embeddings
- **飞书通知** — webhook OR self-built app (app_id + app_secret + chat_id)
- **CPU 报警阈值** — threshold, sustain, cooldown
- **内嵌服务地址** — `dashboard_url` / `ai_url` / `terminal_url` for the
  iframe pages (Dashboard / AI assistant / Terminal "open in new window")
- **外部集成路径** — see [INTEGRATIONS.md](INTEGRATIONS.md)
- **账号安全** — change password (writes new hash to `password_hash` in
  hub_settings.json, taking precedence over `OPSHUB_PASSWORD_HASH` env)

### Precedence

For any runtime value `X`:

1. `hub_settings.json["X"]` if non-empty → use it
2. Else, the env var listed in `_ENV_MAP` (`OPSHUB_X` or its alias) → use it
3. Else, the built-in default from `_DEFAULTS`

This means: set sensible defaults in `.env` so the system works after a
fresh install, then refine values in the UI.

## Cross-process: cpu_alert cron

`scripts/cpu_alert.py` runs out-of-process via `/etc/cron.d/`. It imports
`app.core.hub_settings` to read the same values the live server sees, so
threshold / channel changes in the UI take effect on the next minute
without restarting anything.

Fallback chain for `cpu_alert.py`:

1. hub_settings.json
2. `OPSHUB_ALERT_*` env vars
3. `/root/.hermes/.env` (Hermes co-located install convenience —
   `FEISHU_APP_ID` etc.). Override via `HERMES_ENV=` env if your Hermes
   install lives elsewhere or you want to disable this fallback entirely.

## Deploy-time templates

`deploy/install.conf` (gitignored) feeds `scripts/render-deploy.sh` which
substitutes `${VAR}` placeholders in:

- `deploy/nginx/ops-hub.conf.template`
- `deploy/systemd/ops-hub.service.template`
- `deploy/cron.d/ops-hub-cpu-alert.template`

Rendered output lands in `deploy/dist/`. The script prints the sudo
commands to install the rendered files into `/etc/`.

The deploy config layer is intentionally separate from `.env` and
hub_settings — `.env` and hub_settings are read by the *application*,
while `install.conf` is read by the *installer*.

## Quick reference: where does X live?

| I want to change… | Edit | Restart needed? |
|---|---|---|
| Admin password | UI → 账号安全 (or re-hash + `.env`) | No |
| Apimart / Sorftime / OpenAI keys | UI → AI 服务 / Sorftime / GBrain | No |
| CPU-alert threshold | UI → CPU 报警阈值 | No (next cron tick) |
| Feishu alert channel | UI → 飞书通知 | No (next cron tick) |
| Embedded iframe URLs | UI → 内嵌服务地址 | Refresh page only |
| External tool paths | UI → 外部集成路径 | No |
| Listen port | `server/.env` `OPSHUB_PORT` + render-deploy.sh | Yes (systemd + nginx reload) |
| Public hostname | `deploy/install.conf` SERVER_NAME + render-deploy.sh | nginx reload |
| Session secret | `server/.env` `OPSHUB_SECRET` | Yes (forces re-login) |
