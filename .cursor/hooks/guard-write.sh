#!/usr/bin/env bash
# .cursor/hooks/guard-write.sh
# docs/source-of-truth/ へのエージェントによる書き込み・削除をブロックする。
#
# 読み取りは許可する。シェル経由の改変は guard-shell.sh 側で見る。
# hooks.json 側で failClosed: true を付けること（既定はフェイルオープン）。
#
# 依存: jq
set -euo pipefail

input=$(cat)

deny() {
  jq -n --arg u "$1" --arg a "$2" \
    '{permission: "deny", user_message: $u, agent_message: $a}'
  exit 0
}

is_protected_path() {
  local p="$1"
  [[ -z "$p" || "$p" == "null" ]] && return 1
  p="${p#./}"
  case "$p" in
    docs/source-of-truth|docs/source-of-truth/*|*/docs/source-of-truth|*/docs/source-of-truth/*)
      return 0
      ;;
  esac
  return 1
}

while IFS= read -r path; do
  [[ -z "$path" ]] && continue
  if is_protected_path "$path"; then
    deny \
      "docs/source-of-truth/ は読み取り専用です。編集はブロックされました: $path" \
      "Do not edit, delete, rename, or move files under docs/source-of-truth/. Reading is allowed. Ask a human if changes are needed."
  fi
done < <(printf '%s' "$input" | jq -r '
  [
    .file_path? // empty,
    .tool_input.path? // empty,
    .tool_input.file_path? // empty,
    .tool_input.target_notebook? // empty
  ]
  | map(select(type == "string" and . != ""))
  | unique
  | .[]
')

echo '{"permission":"allow"}'
