#!/usr/bin/env bash
# .cursor/hooks/guard-shell.sh
# 機密ファイルを参照するコマンドと、保護ブランチへの直接 push をブロックする。
#
# 文字列マッチなので回避されうる。これは補完であって境界ではない。
# hooks.json 側で failClosed: true を付けること（既定はフェイルオープン）。
#
# 依存: jq
set -euo pipefail

input=$(cat)
cmd=$(printf '%s' "$input" | jq -r '.command // ""')
sandboxed=$(printf '%s' "$input" | jq -r '.sandbox // "unknown"')

deny_user() {
  jq -n --arg m "$1" '{permission: "deny", user_message: $m}'
  exit 0
}

deny_agent() {
  jq -n --arg m "$1" '{permission: "deny", agent_message: $m}'
  exit 0
}

# 機密ファイルを参照するコマンド
if printf '%s' "$cmd" | grep -qE '(\.env([^.a-zA-Z]|$)|id_rsa|id_ed25519|\.aws/|\.config/gcloud|\.ssh/|\.pem\b|\.tfvars\b|kubeconfig)'; then
  deny_user "機密ファイルを参照するコマンドをブロックしました"
fi

# git commit --no-verify（フック回避）
# 直前の空白を必須にして引数位置に限定する。単なる部分一致にすると、
# コミットメッセージに含まれる -n（例: finish-floor-not-stripped）で正常なコミットが止まる。
# -n の短縮形は束ねられる（-nm）ため、単一ハイフンは n を含む束も見る。
if printf '%s' "$cmd" | grep -qE 'git[[:space:]]+commit([[:space:]].*)?[[:space:]](-[a-zA-Z]*n[a-zA-Z]*|--no-verify)([[:space:]]|$)'; then
  deny_agent "git commit --no-verify は禁止されています。lefthook を通してコミットしてください。"
fi

# 保護ブランチへの直接 push
# ブランチ名を ref 全体として照合する。直前は空白・コロン・プラス（強制 push）だけを許し、
# 直後は空白・コロン・行末に限る。語頭一致にすると feature/main-menu や main-page で誤検出する。
# refs/heads/ 付きの完全形も見る。refspec を省いた git push は文字列から判断できないため対象外。
if printf '%s' "$cmd" | grep -qE 'git[[:space:]]+push([[:space:]].*)?[[:space:]:+](refs/heads/)?(main|master|release/[^[:space:]:]*)([[:space:]]|:|$)'; then
  deny_agent "保護ブランチへの直接 push は禁止されています。feature ブランチと PR を使ってください。"
fi

# docs/source-of-truth/ へのシェル経由の改変をブロックする。
# パスがコマンド文字列に含まれるだけでは拒否しない（コミットメッセージ等の誤検知を避ける）。
# 破壊的コマンドがコマンド位置にあるとき、またはリダイレクト先が保護パスのときだけ拒否する。
if printf '%s' "$cmd" | grep -qE '(^|[^[:alnum:]_-])docs/source-of-truth([/[:space:]"'\'']|$)'; then
  if printf '%s' "$cmd" | grep -qE '(^|[;&|]|&&|\|\|)[[:space:]]*(rm|rmdir|unlink|mv|cp|mkdir|touch|truncate|chmod|chown|ln|install|dd|shred|sed[[:space:]]+-[^[:space:]]*i|perl[[:space:]]+-[^[:space:]]*i|git[[:space:]]+(rm|mv|checkout|restore|reset|clean))([[:space:]]|$)'; then
    deny_agent "docs/source-of-truth/ は読み取り専用です。シェルでの改変・削除・移動は禁止されています。読み取りのみ許可します。"
  fi
  # tee は引数より後ろに保護パスがあるときだけ拒否する（| tee /tmp への読み出しコピーは許可）。
  if printf '%s' "$cmd" | grep -qE '(>|>>|[|][[:space:]]*tee([[:space:]]|$)).*docs/source-of-truth'; then
    deny_agent "docs/source-of-truth/ への書き込みリダイレクトは禁止されています。"
  fi
fi

# サンドボックス外での実行を記録する（ブロックはしない）
if [ "$sandboxed" = "false" ]; then
  printf '%s UNSANDBOXED: %s\n' "$(date -Iseconds)" "$cmd" \
    >> "${CURSOR_PROJECT_DIR:-.}/.cursor-audit.log"
fi

echo '{"permission":"allow"}'
