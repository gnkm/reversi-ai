#!/usr/bin/env bash
# .cursor/hooks/audit.sh
# エージェントのイベントを JSON Lines で記録する。
#
# 出力先は .cursorignore と .gitignore の両方に入れること。
# ツールの引数と出力は機密として扱う。
#
# 依存: jq
set -euo pipefail

input=$(cat)

jq -c --arg ts "$(date -Iseconds)" '{timestamp: $ts} + .' <<< "$input" \
  >> "${CURSOR_PROJECT_DIR:-.}/.cursor-audit.jsonl"

echo '{}'
