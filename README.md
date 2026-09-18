# Reversi AI

AI とリバーシの対戦ができるサービス。AI どうしの対戦を見ることもできる。

## 開発前の準備

### 編集するファイル

| ファイル | すること |
| --- | --- |
| `.cursor/environment.json.template` | `{{INSTALL_CMD}}` と `{{START_CMD}}` を埋め、`.cursor/environment.json` にリネームする |
| `.github/CODEOWNERS.template` | `@owner` と `{{LINT_CONFIG_FILES}}` を埋め、`.github/CODEOWNERS` にリネームする。Free プランなら削除する |
| `.cursorignore` | `{{STACK_SPECIFIC_PATTERNS}}` を自分のスタックの機密パターンに置き換える |
| Feature Issue | 機能名・実証可能な振る舞い・検証コマンド・Blocked by を書く |

## コントリビューション

ブランチ命名とコミット規約は [CONTRIBUTING.md](CONTRIBUTING.md) を参照してください。
