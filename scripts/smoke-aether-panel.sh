#!/usr/bin/env bash
set -euo pipefail
root=$(pwd)
scratch=$(mktemp -d)
panel_pid=''
cleanup() {
  if [ -n "$panel_pid" ]; then kill "$panel_pid" 2>/dev/null || true; wait "$panel_pid" 2>/dev/null || true; fi
  rm -rf "$scratch"
}
trap cleanup EXIT
export XUI_DB_FOLDER="$scratch/db"
export XUI_LOG_FOLDER="$scratch/log"
export XUI_BIN_FOLDER="$root/x-ui"
export XUI_PORT=20953
export XUI_INIT_WEB_BASE_PATH=/
export XUI_ENABLE_FAIL2BAN=false
export XUI_AETHER_BINARY="$root/x-ui/aether"
mkdir -p "$XUI_DB_FOLDER" "$XUI_LOG_FOLDER"
./artifacts/x-ui >"$scratch/panel.log" 2>&1 &
panel_pid=$!
for attempt in $(seq 1 30); do
  if curl --fail --silent http://127.0.0.1:20953/ >"$scratch/page.html"; then
    grep -qi '<html' "$scratch/page.html"
    printf 'Panel installed and served its login page on loopback port 20953.\n'
    exit 0
  fi
  if ! kill -0 "$panel_pid" 2>/dev/null; then printf 'Panel exited before readiness.\n' >&2; exit 1; fi
  sleep 1
done
printf 'Panel HTTP startup timed out.\n' >&2
exit 1
