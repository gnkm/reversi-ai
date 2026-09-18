#!/usr/bin/env bash
# .cursor/hooks/guard-read.sh
# 機密ファイルの読み取りをブロックする。
#
# これは補完であって境界ではない。決定論的な境界は sandbox.json と egress 制御で作る。
# hooks.json 側で failClosed: true を付けること（既定はフェイルオープン）。
#
# 依存: jq
set -euo pipefail

input=$(cat)
path=$(printf '%s' "$input" | jq -r '.file_path // ""')

deny() {
  jq -n --arg m "$1" '{permission: "deny", user_message: $m}'
  exit 0
}

case "$path" in
  */.env|*/.env.*) 
    case "$path" in
      */.env.template|*/.env.example) ;;
      *) deny "機密ファイルへのアクセスをブロックしました: $path" ;;
    esac
    ;;
  */id_rsa*|*/id_ed25519*|*.pem|*.key|*.p12|*.pfx) deny "鍵ファイルへのアクセスをブロックしました: $path" ;;
  */.aws/*|*/.config/gcloud/*|*/.azure/*|*/.kube/*) deny "クラウド認証情報へのアクセスをブロックしました: $path" ;;
  */credentials.json|*/secrets.json|*/secrets.yaml|*/.netrc) deny "機密ファイルへのアクセスをブロックしました: $path" ;;
  *.tfvars|*.tfstate|*.tfstate.backup) deny "インフラ状態ファイルへのアクセスをブロックしました: $path" ;;
esac

echo '{"permission":"allow"}'
