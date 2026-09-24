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

printf '请输入 DeepSeek API Key：'
IFS= read -r -s DEEPSEEK_API_KEY
printf '\n'
if [[ -z "$DEEPSEEK_API_KEY" ]]; then
    printf 'API Key 不能为空\n' >&2
    exit 1
fi
export DEEPSEEK_API_KEY

exec uv run python main.py
