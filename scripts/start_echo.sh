#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
export NAPCAT_WS_URL="${NAPCAT_WS_URL:-ws://127.0.0.1:3001/}"

printf '请输入 NapCat WebSocket Token：'
IFS= read -r -s NAPCAT_ACCESS_TOKEN
printf '\n'
if [[ -z "$NAPCAT_ACCESS_TOKEN" ]]; then
    printf 'Token 不能为空\n' >&2
    exit 1
fi
export NAPCAT_ACCESS_TOKEN

exec uv run python main.py
