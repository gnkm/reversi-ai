# コントリビューションガイド

本ドキュメントは、本リポジトリで開発・コントリビューションする際の手順と共通規約を定める。

## Issue とプルリクエスト

- 機能追加は GitHub の **Feature** Issue テンプレートで起票する（振る舞い・検証・Blocked by を含める）。
- PR は関連 Issue に `Closes #N` で紐づける。テンプレートの Verification / Test plan を埋める。
- Issue のクローズは、`verifier` が検証コマンドを通したあとだけとする。
- CI ワークフローを追加・変更したら、README に状況バッジを必ず出す。

## ソフトウェア要求の変更

開発中の要求の正本は [`docs/srs.md`](docs/srs.md) である。シードは [`docs/source-of-truth/`](docs/source-of-truth/) に残し、AI は編集しない。

浮上した判断は次に分ける。

- **設計**（shall を変えない）: Issue と実装 PR だけ。`docs/srs.md` は触らない。
- **穴**（SRS が沈黙して実装が割れる）: Issue を起票し、`docs/srs.md` に TBD を足す PR を出す。決まるまで shall を発明しない。
- **変更**（既存 shall の追加・緩和・撤回）: Issue に対象の要求 ID を書き、`docs/srs.md` の PR を出す。試験が必要なら同じ PR に含める。

shall を変える PR は CODEOWNERS（`docs/srs.md`）のレビューを必須とする。草案の編集は作成者またはエージェントでよい。承認はオーナーが行う。要求 ID は再利用しない。シードの文言まで変える必要があれば、Issue で人間が `docs/source-of-truth/` を直す。

## 起動・試験・lint

対局と学習の起動、試験、検査の**コマンドの正本**は [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) の「起動とコマンド」である。Issue の検証欄と CI も、その節の生コマンドを使う。ラッパ（Makefile 等）は置かない。

動かすもの（対局・学習）は Podman。測るもの（pytest、Vitest、Biome、Ruff、lefthook）はホストである。ホストの `pnpm dev` や `python -m reversi.api` を対局サービスの正にしない。利用者向けの起動と対局操作は [README.md](README.md) を参照する。

### ホストの準備

- ウェブ（Vitest、Biome、Playwright）: Node 24 と pnpm。ルートで `pnpm install`
- 戦略（pytest、Ruff、import-linter、xenon）: Python 3.12 と uv。`uv run --directory strategy` が依存を解決する
- コミット前検査: [`lefthook.yml`](lefthook.yml)（Biome の書式、osv-scanner、gitleaks、import-linter、xenon、dependency-cruiser）。Ruff はフックに含めず、次節のホストコマンドで走らせる

証明書と Podman secret の一度きりの準備は、正本の 8.1 節および [README.md](README.md) の「準備」に従う。

### ホットリロード

対局の入口は運用者と同じである。

```bash
podman-compose up --build
```

ホットリロードが要るときだけ、別スタックを増やさずオーバーレイを足す。

```bash
podman-compose -f compose.yaml -f compose.dev.yaml up --build
```

`compose.dev.yaml` はソースの bind mount と reload だけを足す。secret・公開ポート・サービス名は `compose.yaml` のままにする。配置上の正は [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) である（リポジトリにまだ無い場合は、実装時にその配置どおり置く）。

### 試験と検査（ホスト）

```bash
uv run --directory strategy pytest
uv run --directory strategy lint-imports
uv run --directory strategy xenon --max-absolute C --max-modules B --max-average A src
uv run --directory strategy ruff check src tests
pnpm test
pnpm exec biome check web
pnpm exec depcruise --config .dependency-cruiser.cjs web
```

E2E はアプリを Podman で上げ、Playwright はホストの Google Chrome で `https://127.0.0.1` を叩く。

```bash
podman-compose up --build --wait
pnpm exec playwright test --project=chrome
```

資格情報が無い環境では、生成 AI を試験ダブルのままにする。OpenRouter の secret は CI に渡さない。学習の起動は正本の 8.3 節を使う。ホストの `uv run` を学習の正にしない。

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
