# コントリビューションガイド

本ドキュメントは、本リポジトリで開発・コントリビューションする際の手順と共通規約を定める。

## Issue とプルリクエスト

- 機能追加は GitHub の **Feature** Issue テンプレートで起票する（振る舞い・検証・Blocked by を含める）。
- PR は関連 Issue に `Closes #N` で紐づける。テンプレートの Verification / Test plan を埋める。
- Issue のクローズは、`verifier` が検証コマンドを通したあとだけとする。
- CI ワークフローを追加・変更したら、README に状況バッジを必ず出す。

## Git ブランチ命名規則

ブランチ名は **`<type>/<short-description>`** 形式で記述する。
`<type>` は [Conventional Commits](https://www.conventionalcommits.org/) のタイプに揃える。

| プレフィックス | 用途 |
| --- | --- | --- |
| `feat/` | 機能追加 |
| `fix/` | バグ修正 |
| `chore/` | ビルド・ツール・設定変更、依存更新など |
| `docs/` | ドキュメントのみの変更 |
| `refactor/` | 振る舞いを変えないリファクタリング |
| `test/` | テスト追加・修正 |
| `perf/` | パフォーマンス改善 |

ルール:

- すべて **小文字**、単語区切りはハイフン (`-`) を使う。アンダースコア・キャメルケースは使わない。
- スコープは **目的が一目で分かる** 短い英語にする (例: `answer-agent`, `director`, `evaluation`, `similarity`, `cli`)。
- `main` から派生し、レビュー → マージ後にブランチは削除する。
- 派生先 (`base`) を `main` 以外に設定する場合 (Stacked PR) は、PR 説明にその旨と上流ブランチを明記する。

## コミットメッセージ規約

[Conventional Commits](https://www.conventionalcommits.org/) に準拠する。

```
<type>(<scope>): <subject>

[optional body]

[optional footer]
```

- `<type>` はブランチ命名と同じプレフィックス (`feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `perf`)。
- `<scope>` は任意。モジュール名やレイヤー名 (例: `agent`, `director`, `evaluation`, `similarity`, `cli`, `config`) を入れると履歴が読みやすい。
- `<subject>` は **日本語可**、命令形で簡潔に。末尾にピリオドは付けない。
- 本文 (body) では「なぜその変更が必要か」を書く。「何をしたか」はコードの差分から読めるので最小限で良い。
- 1 コミット 1 論点。レビュー時にコミット単位で読めることを意識する。
