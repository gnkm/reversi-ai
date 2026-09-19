# AGENTS.md

Cursor Cloud Agents 向けの作業ルール。アプリ固有のルールはプロジェクト側で追記する。

## 編集禁止（読み取り専用）

- `docs/source-of-truth/` 配下はシードの正本。AI は読んでよいが、編集・削除・リネーム・移動は禁止。
- フロントマターに `ai.editable: false`（または `ai_editable: false`）があるファイルも同様。
- 内容変更が必要なら Issue で人間に依頼し、自分では触らない。

## ソフトウェア要求（`docs/srs.md`）

開発中のソフトウェア要求の正本は `docs/srs.md` である。シードは `docs/source-of-truth/` に残す。

- 設計（言語、配置、層数など、shall を変えない判断）では `docs/srs.md` を編集しない。
- shall の追加・変更・撤回、または新しい TBD は、対象 Issue を読んでから `docs/srs.md` を編集する。実装だけの PR に混ぜない。
- 要求 ID は再利用しない。版を上げ、改訂履歴に 1 行足す。
- シードに無い数値や義務を shall として発明しない。決まらなければ TBD にする。

## タスク管理

- タスクと完了基準は **GitHub Issue** のみ。着手前に対象 Issue を読む（`gh issue view`）。
- Issue の **Blocked by** に未完了の依存がある場合は着手しない。
- セッション引き継ぎは Issue / PR の本文とコメントで行う。リポジトリ内の progress ファイルは使わない。

## 完了の定義

- Issue のクローズは、`verifier` が Issue の **検証** 欄のコマンドを実行して通ったあとだけ。
- 自分で完了と主張した直後は `verifier` を起動する。

## 調査

- ウェブ調査は親が直接 scrape / WebFetch / Firecrawl せず、`web-reader` に委譲する。

## CI バッジ

- CI ワークフロー（`.github/workflows/`）を追加・変更したら、README 先頭付近にそのワークフローの状況バッジを必ず出す。無ければ追加する。
- 例: `![CI](https://github.com/<owner>/<repo>/actions/workflows/<file>.yml/badge.svg)`
