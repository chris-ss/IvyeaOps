#!/usr/bin/env bash
set -euo pipefail

SESSION_NAME="main"

# Clear stale AI endpoint overrides that can outlive gateway migrations.
# Legacy ttyd reuses a long-lived tmux server, so we remove these both from
# the current shell and from tmux's global environment before attaching.
CLEAR_VARS=(
  ANTHROPIC_BASE_URL
  OPENAI_BASE_URL
  OPENAI_API_BASE
)

for var_name in "${CLEAR_VARS[@]}"; do
  unset "$var_name" || true
  tmux set-environment -gu "$var_name" >/dev/null 2>&1 || true
done

# If a proxy var still points at the retired localhost:8000 bridge, clear it too.
for proxy_var in HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy; do
  proxy_value="${!proxy_var-}"
  case "$proxy_value" in
    http://localhost:8000*|http://127.0.0.1:8000*)
      unset "$proxy_var" || true
      tmux set-environment -gu "$proxy_var" >/dev/null 2>&1 || true
      ;;
  esac
done

if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
  tmux set-option -g mouse on
  tmux set-option -g history-limit 50000
  exec tmux attach-session -t "$SESSION_NAME"
fi

exec tmux new-session -s "$SESSION_NAME" \; set-option -g mouse on \; set-option -g history-limit 50000
