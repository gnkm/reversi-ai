# アーキテクチャ

実装の置き方とプロセス分割。要求（shall）の正本は `docs/source-of-truth/` と GitHub Issue であり、本ファイルはそれらを変えない。

対象: F001（対局エンジン）、F002（ランダム個体）、F006（戦略 API）、F008（Issue #9、盤の入力符号化）、F009（WTHOR 棋譜）、F021（Issue #22）。後続の実装 Issue は本ファイルと `docs/openapi.yml` に従う。

## 1. 目的

ブラウザからエージェントとリバーシの対局をし、エージェント同士の対局を見る。利用者向けの HTTP と、着手を決める戦略プロセスの JSON を、同じ契約に載せる。

## 2. 実行時のプロセス

二つのプロセスに分ける。

| 役割 | 実装 | 入口 |
| --- | --- | --- |
| 利用者向け | Hono | `/api/*`（文書ルートの `servers`） |
| 戦略 | FastAPI | `/decide`（パス項目の `servers`）。Hono が中継する JSON は同じ `components` |

Hono はブラウザからの対局 API を受け、着手決定を戦略 FastAPI の `/decide` へ中継する。二つのサーバの経路は `docs/openapi.yml` で混ぜない。

Hono がまだ無いあいだ、戦略 FastAPI（F006、`reversi.api`）が同じ `components` の JSON でカタログと 1 局の開始・着手を公開する。進行中の局はメモリ上で同時 1。盤の規則は engine、個体の着手は catalog に任せ、api はそれらを再実装しない。`reversi.api` は `reversi.train` を import しない。

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

## 6. 対局エンジン

8×8 リバーシの規則は `strategy/src/reversi/engine/` に置く。対局と学習が同じ関数を呼ぶ。ビットボードは使わない。

| ファイル | 責務 |
| --- | --- |
| `board.py` | 盤・マス・初期配置・代数表記 |
| `rules.py` | 合法手・裏返し・パス・終局 |
| `score.py` | 石数と公式スコア |

代数表記の a1 は黒から見て左下である。列 a–h は左から右、行 1–8 は黒側から白側。内部配列は `board[rank-1][file-a]`（`[0][0]` が a1）。

合法手は相手石を 1 個以上挟む空マスだけである。挟んだ石をすべて裏返し、連鎖的な追加の裏返しは起きない。合法手が無い側にだけパスが適用される。双方が着手不能なら、64 マスが埋まっていなくても終局する。

公式スコアは石数が多い側の勝ちである。引き分けは 32–32。勝ちが決まったとき空マスは勝者に加算する。

## 7. 戦略個体

選択単位は個体でありカテゴリではない。カタログと個体は `strategy/src/reversi/agents/` に置く。

| ファイル | 責務 |
| --- | --- |
| `catalog.py` | 個体の識別・カテゴリ・表示名・説明文の一覧。選択は個体 ID |
| `random_uniform.py` | 手番の合法手を等確率で 1 つ選ぶ。合法手が無ければ着手しない |

カテゴリ `random` は「ランダム」である。表示名「ランダム (一様)」の個体は、対局中に WTHOR も学習済みモデルも参照しない。

## 8. 盤の入力符号化

ML / RL / NN が共有する盤の入力は `strategy/src/reversi/encode.py` に一つ置く。`engine` はこれを読まない。エージェント実装と学習が同じ関数を呼ぶ。

符号化は黒・白・空の 3 平面 × 8×8 の 0/1 である。座標はエンジンと同じ（`[rank][file]`、a1 が `[0][0]`）。手番は盤の入力に含めない。数値目標は置かない。

## 9. 学習棋譜（WTHOR）

学習入力は `strategy/src/reversi/train/wthor.py` が読む。原本は `data/wthor/` の `.wtb` であり、HTTP の静的ファイルとしては出さない。リポジトリには入れない。

ヘッダの盤サイズが 0 または 8 のファイルだけを 8×8 として扱う。それ以外と、8×8 規則で再生できないレコードは学習入力に含めない。再生は対局エンジンと同じ関数を呼ぶ。WTHOR はパスを符号に持たないので、合法手が無い側ではエンジンのパスを挿入する。

## 10. 戦略 API（FastAPI）

1 局の HTTP は `strategy/src/reversi/api/` に置く。Pydantic の形は `docs/openapi.yml` の `components` と同じである。

| ファイル | 責務 |
| --- | --- |
| `schemas.py` | カタログ・対局・着手・問題の JSON |
| `errors.py` | RFC 9457 の Problem と違法着手の 409 |
| `session.py` | メモリ上の同時 1 局。開始は既存を置き換える |
| `app.py` | `GET /api/catalog`、`POST /api/games`、着手 |

違法な着手は盤に適用しない。エージェント対エージェントは人手の着手を待たず終局まで進む。

## 11. リポジトリ構成

```
docs/
  ARCHITECTURE.md      # 本ファイル
  openapi.yml          # 対局 API の契約（OpenAPI 3.1）
  source-of-truth/     # 要求の正本（人間のみ編集）
    01-seed.md
data/
  wthor/               # WTHOR 原本。.wtb は Git に入れない。HTTP で出さない。
strategy/
  src/reversi/engine/
    board.py
    rules.py
    score.py
  src/reversi/agents/
    catalog.py
    random_uniform.py
  src/reversi/encode.py
  src/reversi/train/
    wthor.py
  src/reversi/api/
    app.py
    errors.py
    schemas.py
    session.py
  tests/
    test_engine.py
    test_agents.py
    test_encode.py
    test_wthor.py
    test_api.py
```

利用者向け Hono のディレクトリは、実装 Issue でこの tree に足す。
