# アーキテクチャ

実装の置き方とプロセス分割。要求（shall）の正本は `docs/source-of-truth/` と GitHub Issue であり、本ファイルはそれらを変えない。

対象: F021（Issue #22）。後続の実装 Issue は本ファイルと `docs/openapi.yml` に従う。

## 1. 目的

ブラウザからエージェントとリバーシの対局をし、エージェント同士の対局を見る。利用者向けの HTTP と、着手を決める戦略プロセスの JSON を、同じ契約に載せる。

## 2. 実行時のプロセス

二つのプロセスに分ける。

| 役割 | 実装 | 入口 |
| --- | --- | --- |
| 利用者向け | Hono | `/api/*`（文書ルートの `servers`） |
| 戦略 | FastAPI | `/decide`（パス項目の `servers`）。Hono が中継する JSON は同じ `components` |

Hono はブラウザからの対局 API を受け、着手決定を戦略 FastAPI の `/decide` へ中継する。二つのサーバの経路は `docs/openapi.yml` で混ぜない。

## 3. HTTP 契約

対局 API の契約の正本は `docs/openapi.yml`（OpenAPI 3.1）である。少なくとも次を載せる。

- `GET /api/catalog`
- `POST /api/games`
- `POST /api/games/{id}/moves`
- `GET /api/games/{id}/events`（SSE）

カタログ項目（個体 ID、カテゴリ、表示名、説明文）、対局状態（盤、手番、合法手、直前着手、終局、公式スコア、勝敗）、着手指定、違法時の非適用、外部モデル失敗時の継続不能は、同ファイルのスキーマで表す。

ブラウザへ OpenAPI 文書（Swagger UI / ReDoc / `/openapi.json` など）を公開することは要求ではない。実装が生成文書を出してもよいが、差分があれば `docs/openapi.yml` を正とする。

## 4. Pydantic と Zod

TypeScript 側は Zod、Python 側は Pydantic で実行時の形を検証する。どちらも `docs/openapi.yml` の `components` と同じ形にする。フィールド名、列挙、null の位置を契約から広げたり、片方だけ別名にしたりしない。

## 5. 共有パッケージ

初版では TypeScript と Python のあいだで型やスキーマを共有するパッケージを置かない。契約の単一の置き場所は `docs/openapi.yml` であり、各言語のモデルはそこから手で揃える。共有パッケージが必要になったら、その時点の Issue で足す。

## 6. リポジトリ構成

```
docs/
  ARCHITECTURE.md      # 本ファイル
  openapi.yml          # 対局 API の契約（OpenAPI 3.1）
  source-of-truth/     # 要求の正本（人間のみ編集）
    01-seed.md
```

アプリケーション本体（Hono / FastAPI のパッケージ）のディレクトリは、実装 Issue でこの tree に足す。
