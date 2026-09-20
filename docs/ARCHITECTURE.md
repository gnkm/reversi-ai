---
title: アーキテクチャ
product: Reversi Agents
version: 0.1.14
status: working
date: 2026-09-20
source: docs/srs.md
srs_version: 0.1.24
tech_stack: docs/tech-stack.md
tech_stack_version: 0.2.16
---

# アーキテクチャ

| 項目 | 内容 |
| --- | --- |
| 文書識別 | reversi-ai-architecture |
| 対象ソフトウェア | Reversi Agents |
| 版 | 0.1.14 |
| 状態 | 現行（設計。要求ではない） |
| 日付 | 2026-09-20 |
| 入力 | [`docs/srs.md`](srs.md) 0.1.24、[`docs/tech-stack.md`](tech-stack.md) 0.2.16 |

本文書は**配置と層**の設計正本である。ソフトウェア要求の正本は [`docs/srs.md`](srs.md) であり、本文書は shall を追加・変更・撤回しない。言語・ライブラリ・コンテナの選定は [`docs/tech-stack.md`](tech-stack.md) を正とする。ディレクトリ名は tech-stack 2.3 と一致させ、ファイル単位の置き場と目的は本文書を正とする。

パスは初版の目標配置である。まだリポジトリに無いものは実装時に作る。言語名のディレクトリ（例: `python/`）は置かない。

## 1 実行時の配置

ブラウザが話す相手は TypeScript。着手と学習の中身は Python。SRS の論理図（1.3.2）は置き換えない。

```mermaid
flowchart LR
  chrome[Google Chrome]
  hono["web/server Hono HTTPS"]
  ui["web/ui 静的成果物"]
  py["strategy FastAPI Pod 内"]
  engine[reversi.engine]
  agents[reversi.agents]
  sqlite[(data/games.sqlite)]
  models[models/]
  secret["Podman secret"]
  or[OpenRouter]
  train[reversi.train]

  chrome -->|HTTPS 同一オリジン| hono
  hono --> ui
  hono -->|Pod 内 HTTP| py
  py --> engine
  py --> agents
  agents --> engine
  agents -->|生成 AI のみ| or
  agents --> models
  py --> sqlite
  secret --> py
  train --> engine
  train --> models
```

| プロセス | 公開 | 目的 |
| --- | --- | --- |
| `web` コンテナ（Hono） | ホスト `127.0.0.1` のみ HTTPS | UI 配信、Origin 照合、SSE、戦略プロセスへ中継 |
| `strategy` コンテナ（FastAPI） | Pod 内のみ。ホストへ出さない | 規則、全エージェントの着手、進行中 1 局、終局の永続化、OpenRouter。torch は入れない |
| 学習（`podman-compose run --rm train`） | 待ち受けしない。`up` の常時起動対象外 | 学習用イメージ（`train` グループを焼く）。ML / LightGBM / RL / NN の書き出し |

同時対局は 1。進行中の局は戦略プロセスのメモリ上。終局だけ SQLite へ書く。

## 2 層と依存の向き

矢印は import してよい向き。逆向きと循環は禁止する。

```
web/ui ──HTTP──► web/server ──HTTP──► reversi.api ──► reversi.agents ──► reversi.engine
                                      reversi.train ──► reversi.engine
                                      reversi.train ──► reversi.agents（自己対局に必要な範囲）
```

| 契約 | 検査 |
| --- | --- |
| `web/ui` は `web/server` を import しない。逆も禁止 | dependency-cruiser |
| `reversi.api` → `reversi.agents` → `reversi.engine` の一方向 | import-linter |
| 対局経路（`api` / `agents` / `engine`）は `reversi.train` を import しない | import-linter |
| `reversi.engine` は `reversi.encode` を import しない | import-linter |
| ブラウザは戦略プロセスに直接接続しない | 配備（compose）。検査は Origin と待ち受け |

`reversi.encode` は対局規則ではない入力符号化である。`agents` と `train` が共有し、`engine` は読まない。符号化は黒・白・空の 3 平面 × 8×8 の 0/1 である。座標はエンジンと同じ（`[rank][file]`、a1 が `[0][0]`）。手番は盤の入力に含めない。数値目標は置かない。

## 3 リポジトリの tree

コメントは、そのパスの**目的**である。製品コードの詳細な**機能**は [4](#4-モジュールの機能) に書く。

```
reversi-ai/
├── README.md                          # 製品の入口。運用コマンドの正本。CI バッジを置く
├── AGENTS.md                          # エージェント作業ルール（要求正本・編集禁止）
├── CONTRIBUTING.md                    # Issue / PR / ブランチ / コミット規約。試験・lint・E2E の正本
├── LICENSE
├── compose.yaml                       # Podman Compose。同一 Pod に web と strategy。学習は train
├── compose.dev.yaml                   # 開発用オーバーレイ。bind mount と reload だけを足す
├── package.json                       # ウェブアプリ（UI + Hono）の依存とスクリプト
├── pnpm-lock.yaml
├── biome.json                         # TS/JSON/CSS の書式と認知的複雑度ゲート
├── .dependency-cruiser.cjs            # web/ui と web/server の相互 import 禁止
├── lefthook.yml                       # コミット前: Biome, gitleaks, osv-scanner, 層検査
├── .gitignore                         # data/, .venv, node_modules, .env を除外
│
├── docs/
│   ├── srs.md                         # ソフトウェア要求の正本（shall）
│   ├── tech-stack.md                  # 言語・ライブラリ・コンテナの選定
│   ├── ARCHITECTURE.md                # 本ファイル。配置と層
│   ├── openapi.yml                    # 対局 API の契約（OpenAPI 3.1）
│   ├── benchmarks/
│   │   ├── round-robin.json           # 総当たり基準結果。数値の正本
│   │   ├── round-robin.md             # GitHub 閲覧用。JSON から生成
│   │   └── render.py                  # round-robin.md を JSON から書く
│   └── source-of-truth/
│       └── 01-seed.md                 # シード。AI は編集禁止
│
├── web/                               # 利用者向けウェブアプリ。ブラウザが話す相手
│   ├── Containerfile                  # UI をビルドし Hono で HTTPS 提供
│   ├── ui/                            # React。カタログ画面と盤面画面
│   │   ├── index.html                 # SPA の文書。文言は日本語
│   │   ├── vite.config.ts             # 開発サーバ。本番は Hono が静的配信
│   │   ├── tsconfig.json
│   │   └── src/
│   │       ├── main.tsx               # エントリ。React をマウント
│   │       ├── App.tsx                # 経路: / と /game
│   │       ├── api.ts                 # 同一オリジンの fetch / EventSource
│   │       ├── types.ts               # 画面が扱う対局状態・カタログの型
│   │       ├── catalog.ts             # カテゴリ併記・カード選中・対戦要約
│   │       ├── pages/
│   │       │   ├── CatalogPage.tsx    # セグメント・石ボタン・カード選択と開始
│   │       │   └── GamePage.tsx       # 盤中心の横並び。手番、終局、カタログへ戻る
│   │       └── components/
│   │           ├── Board.tsx          # 盤・座標・合法手と直前着手の印
│   │           └── CatalogList.tsx    # 個体カード。表示名と説明文、クリックで選ぶ
│   └── server/                        # Hono。利用者向けオリジン
│       ├── tsconfig.json
│       └── src/
│           ├── index.ts               # HTTPS 待ち受け。証明書は mkcert
│           ├── app.ts                 # 経路と静的ファイル
│           ├── origin.ts              # Origin 不一致の状態変更を 403
│           ├── schemas.ts             # 中継 JSON の Zod。Python の Pydantic と形を揃える
│           ├── strategy.ts            # Pod 内の FastAPI へ HTTP 中継。部分適用しない
│           └── sse.ts                 # エージェント対エージェントの盤面更新
│
├── strategy/                          # 戦略プロセス。着手と学習
│   ├── Containerfile                  # 対局 (strategy) と学習 (train) のターゲット。prompts/ を載せる
│   ├── pyproject.toml                 # パッケージ reversi、Ruff、import-linter
│   ├── uv.lock
│   ├── src/reversi/
│   │   ├── __init__.py
│   │   ├── encode.py                  # 盤の入力符号化。ML / RL / NN と学習が共有
│   │   ├── engine/                    # 対局規則の正。ビットボードは使わない
│   │   │   ├── __init__.py
│   │   │   ├── board.py               # 8×8 の石状態と座標（a1 は黒から見て左下）
│   │   │   ├── rules.py               # 合法手・裏返し・パス・終局
│   │   │   └── score.py               # 公式スコアと勝敗
│   │   ├── agents/                    # カタログ個体の着手。train を import しない
│   │   │   ├── __init__.py
│   │   │   ├── catalog.py             # 個体 ID・表示名・説明・カテゴリの登録
│   │   │   ├── extra_genai.py         # data/config.toml から生成 AI 個体を足す
│   │   │   ├── position_table.py      # FUN-025 の点数表。ミニマックスと定石外れが共有
│   │   │   ├── random_uniform.py      # ランダム (一様)
│   │   │   ├── most_flips.py          # ルールベース (最多取り)
│   │   │   ├── positional.py          # ルールベース (位置評価)
│   │   │   ├── minimax.py             # ルールベース (ミニマックス) 深さ 4
│   │   │   ├── opening.py             # ルールベース (定石) 虎・牛・鼠
│   │   │   ├── ml.py                  # 機械学習 (棋譜)。係数 JSON の積和のみ
│   │   │   ├── lgbm.py                # 機械学習 (LightGBM)。ネイティブテキストを読む
│   │   │   ├── rl.py                  # 強化学習 (自己対局)。線形重み。NN も OpenRouter も使わない
│   │   │   ├── nn.py                  # ニューラルネットワーク (棋譜)。ONNX CPU
│   │   │   ├── prompt.py              # prompts/ の Markdown と JSON を読む
│   │   │   ├── jev.py                 # 生成 AI (Jev)。Decisions の原子質問を合成
│   │   │   └── chat_completions.py    # 追加の生成 AI。Chat Completions の構造化出力
│   │   ├── api/                       # 内部 FastAPI。ブラウザからは到達させない
│   │   │   ├── __init__.py
│   │   │   ├── app.py                 # アプリ組み立てと待ち受け
│   │   │   ├── errors.py              # RFC 9457 の Problem と違法着手の 409
│   │   │   ├── schemas.py             # 中継 JSON の Pydantic
│   │   │   ├── routes.py              # カタログ取得、対局開始、着手、状態
│   │   │   ├── session.py             # 進行中 1 局（メモリ）
│   │   │   ├── persist.py             # 終局を SQLite へ書く
│   │   │   └── openrouter_key.py      # /run/secrets/openrouter-api-key を読む
│   │   └── train/                     # 学習。対局経路からは import しない
│   │       ├── __init__.py
│   │       ├── wthor.py               # .wtb を読む。8×8 以外は捨てる
│   │       ├── examples.py            # WTHOR と永続化対局から教師あり学習例を集める
│   │       ├── ml.py                  # scikit-learn → models/ml.json
│   │       ├── lgbm.py                # LightGBM → models/lgbm.txt
│   │       ├── rl.py                  # NumPy 線形 TD → models/rl.json
│   │       └── nn.py                  # PyTorch CPU → models/nn.onnx
│   └── tests/                         # pytest。規則とエージェントの正
│       ├── test_engine.py
│       ├── test_agents.py
│       ├── test_encode.py
│       ├── test_wthor.py
│       ├── test_api.py                # カタログと 1 局の開始・着手・違法拒否
│       ├── test_persist.py
│       └── test_layers.py             # ML / LightGBM / RL が NN ランタイムを import しないこと
│
├── models/                            # 学習成果物。原本棋譜は置かない。Git 管理する
│   ├── ml.json                        # ML 対局時の係数
│   ├── lgbm.txt                       # LightGBM 対局時のネイティブテキスト
│   ├── rl.json                        # RL 対局時の重み
│   └── nn.onnx                        # NN 対局時の順伝播
│
├── prompts/                           # 生成 AI の固定指示。戦略プロセスが対局時に読む
│   ├── jev.json                       # 生成 AI (Jev) の原子質問と合成の重み
│   └── chat-completions.md            # 追加の生成 AI の Chat Completions 指示（構造化出力）
│
├── e2e/                               # Playwright。対象はマシン上の Google Chrome
│   ├── playwright.config.ts
│   ├── catalog.spec.ts                # カタログ → 盤面、日本語 UI
│   └── game.spec.ts                   # 手番表示、合法手の印
│
└── data/                              # 運用者ローカル。Git 管理外
    ├── games.sqlite                   # 終局棋譜（SRS-DAT-004 の項目）
    ├── config.toml                    # 追加する生成 AI のモデル名・呼称・パラメータ
    ├── wthor/                         # WTHOR 原本。読み取り専用。再配布しない
    └── certs/                         # mkcert の PEM。Hono へファイルとして渡す
```

次は製品の実行には載らないが、同じリポジトリにある。

```
reversi-ai/
├── .github/
│   ├── CODEOWNERS                     # shall・検査閾値・エージェント規則のレビュー必須
│   ├── pull_request_template.md
│   └── ISSUE_TEMPLATE/
├── .vscode/                           # Biome / Ruff の推奨
└── .cursor/                           # エージェント向けフックとルール
```

`web/server` の単体試験（Origin 拒否、中継が部分適用しないこと）は `web/server/src/` に Vitest で併置する（例: `origin.test.ts`、`strategy.test.ts`）。

## 4 モジュールの機能

### 4.1 `web/ui`

カタログ画面（`/`）と盤面画面（`/game`）の 2 経路。状態は画面ローカル（`useState` / `useReducer`）。OpenRouter の鍵も WTHOR 原本も持たない。表示は Hono が返した対局状態と、カタログの表示名・説明文に限る。`dangerouslySetInnerHTML` を置かない。見た目のライブラリは入れない。色・半径・余白は CSS 変数に集約する。

| ファイル | 機能 |
| --- | --- |
| `CatalogPage.tsx` | 対局モードはセグメント、利用者対エージェントの石色は石ボタン。個体はカードをクリックして選ぶ。エージェント対エージェントは黒スロットと白スロットを先に選びカードで埋める。対戦要約と開始はスクロールしても使える位置。`<select>` は置かない |
| `CatalogList.tsx` | 表示名 heading と説明文のカード。カテゴリを小さく併記してグルーピングする。選中は枠とチェック。`aria-pressed` |
| `catalog.ts` | カテゴリの日本語、グルーピング、対戦要約 |
| `GamePage.tsx` | Chrome 前提の横並び。左に大きな盤、右に石アイコン・表示名・公式石数と手番文。人間手番はマス指定を POST する。パスは盤の近く。終局は勝敗バナーとカタログへ戻る。エージェント対エージェントは SSE を購読する |
| `Board.tsx` | 8×8 を CSS Grid で描く。a1 は黒から見て左下。利用者手番に合法手の印、直前着手の印。石は CSS の radial-gradient と影 |
| `moveInterval.ts` | 着手間隔（秒）の入力。未設定は 1 秒。開始 API へ渡す値に使う |
| `api.ts` | `GET /api/catalog`、`POST /api/games`、`POST /api/games/:id/moves`、`GET /api/games/:id/events` |

### 4.2 `web/server`

利用者向けの唯一のオリジン。盤の合法手計算は持たない。人間の着手指定は戦略プロセスへ渡し、違法なら盤面を変えず再指定できる応答をそのまま返す。

| ファイル | 機能 |
| --- | --- |
| `index.ts` | コンテナ内は `0.0.0.0` で HTTPS。ホストへ出す口は compose の `127.0.0.1` だけ。平文 HTTP を既定にしない |
| `origin.ts` | 状態変更 POST の `Origin` が自オリジンと一致しなければ 403 |
| `strategy.ts` | FastAPI 呼出し。失敗時は部分適用せず、継続不能を UI へ返す |
| `sse.ts` | 戦略プロセスが進めた盤面を Server-Sent Events で流す |
| `schemas.ts` | 対局状態・着手・カタログ項目の形。`strategy` の Pydantic と揃える |

公開する経路（設計。要求ではない）:

| 経路 | 役割 |
| --- | --- |
| `GET /`, `GET /game` | SPA |
| `GET /api/catalog` | カタログ一覧 |
| `POST /api/games` | 対局開始 |
| `POST /api/games/:id/moves` | 人間の着手 |
| `GET /api/games/:id/events` | 盤面の SSE |

### 4.3 `strategy` — `reversi.engine`

対局の正しさの正本。対局と学習（自己対局・WTHOR 再生）が同じ関数を呼ぶ。8×8 の配列（または同等の明示的な 64 マス）。ビットボードは使わない。

代数表記の a1 は黒から見て左下である。列 a–h は左から右、行 1–8 は黒側から白側。内部配列は `board[rank-1][file-a]`（`[0][0]` が a1）。

合法手は相手石を 1 個以上挟む空マスだけである。挟んだ石をすべて裏返し、連鎖的な追加の裏返しは起きない。合法手が無い側にだけパスが適用される。双方が着手不能なら、64 マスが埋まっていなくても終局する。

公式スコアは石数が多い側の勝ちである。引き分けは 32–32。勝ちが決まったとき空マスは勝者に加算する。

| ファイル | 機能 |
| --- | --- |
| `board.py` | 石の色、空マス、座標変換、初期配置（白 d4・e5、黒 e4・d5、黒先手） |
| `rules.py` | 合法手、挟み裏返し（連鎖しない）、パス、双方着手不能で終局 |
| `score.py` | 勝者への空マス加算、引き分け 32–32 |

### 4.4 `strategy` — `reversi.agents`

選択単位は個体でありカテゴリではない。カタログ個体は 1 ファイル 1 方針とする。いずれも合法手の中からちょうど 1 手を返す（合法手が無ければ着手しない）。ルールベースの同点は a1…h8 の座標順。

| ファイル | カタログ表示名 | 機能 |
| --- | --- | --- |
| `catalog.py` | （登録） | 個体 ID・カテゴリ・表示名・説明文。追加の生成 AI をここで合成する |
| `random_uniform.py` | ランダム (一様) | 合法手の一様乱択。対局中に WTHOR も学習済みモデルも参照しない |
| `most_flips.py` | ルールベース (最多取り) | 裏返す相手石が最大の手 |
| `positional.py` | ルールベース (位置評価) | 着手直後の自石点数合計が最大の手 |
| `minimax.py` | ルールベース (ミニマックス) | 深さ 4。葉は位置評価表の差。アルファベータは同一の葉評価になる範囲で可 |
| `opening.py` | ルールベース (定石) | 虎・牛・鼠の 3 列と 8 対称。外れは位置評価 |
| `ml.py` | 機械学習 (棋譜) | `models/ml.json` の積和。onnxruntime / PyTorch を import しない |
| `lgbm.py` | 機械学習 (LightGBM) | `models/lgbm.txt` を LightGBM ネイティブ形式で読む。onnxruntime / PyTorch / joblib / pickle を import しない |
| `rl.py` | 強化学習 (自己対局) | `models/rl.json`。NN 推論も OpenRouter も使わない |
| `nn.py` | ニューラルネットワーク (棋譜) | `models/nn.onnx` を onnxruntime CPU で順伝播し、合法手へマスク |
| `prompt.py` | （指示ファイル） | `prompts/` の Markdown と JSON を対局時に読む。欠落は継続不能 |
| `jev.py` | 生成 AI (Jev) | `typesafe/jev-1.13` の Decisions API。1 着手 1 呼出しで 2 問以上の原子質問を送り、typed answers とコード特徴を合成する。指示は `prompts/jev.json`。合法手の外を採用しない |
| `chat_completions.py` | 生成 AI (〈呼称〉) | 運用者が与えたテキスト生成モデル ID。固定の system は `prompts/chat-completions.md`。応答は JSON Schema を Pydantic で検証する |

カテゴリ `random` は「ランダム」である。`position_table.py` は FUN-025 の点数表だけを持つ。`extra_genai.py` は `data/config.toml` を読む（対局者向けウィザードは置かない）。Jev は同一 `state` に対する 2 問以上の原子質問（Noul / Score / Choice）を 1 HTTP 呼出しで送り、`jev.py` がモデルの typed answers（noul 確率・score・choice の probabilities）と、コードが計算した特徴（角・X・C・辺、反転数、相手の着手可能数、角を渡すか）を `prompts/jev.json` の重みで合成して、合法手からちょうど 1 つ選ぶ。同点は a1…h8。反転数やリスト長は Jev に数えさせない。盤の読み方（`board[0][0]` が a1）は質問文ではなく `state` に置く。固定の質問文と重みは `prompts/jev.json` に置き、`strategy/src` には埋め込まない。JSON を変えてイメージを作り直すか、開発時の bind（`./prompts:/prompts`）を更新すると、次の着手呼出しからその指示を使う。Chat Completions の指示は散文なので `prompts/chat-completions.md` のままである。`prompts/` に JSON と Markdown が混在してよい。日本語の注釈は本節に置き、質問ファイルは JSONC にしない。

### 4.5 `strategy` — `reversi.api`

Pod 内 HTTP。TLS は Hono が担う。

| ファイル | 機能 |
| --- | --- |
| `app.py` | アプリ組み立てと待ち受け。F006 ではカタログ・対局開始・着手の経路もここ |
| `errors.py` | RFC 9457 の Problem と違法着手の 409 |
| `schemas.py` | 中継 JSON の Pydantic。`docs/openapi.yml` の `components` と同じ形 |
| `routes.py` | カタログ、対局開始、着手適用、状態取得。エージェント対エージェントは開始後に終局まで進める |
| `session.py` | 進行中 1 局。同時対局は 1。エージェント対エージェントは開始 API の `move_interval_seconds`（省略時は待たない）を下限として、1 手を盤に適用してから次を適用する |
| `persist.py` | 終局時に対局モード、黒と白の主体、着手列、終局面、公式スコア、勝敗を書く。個人識別子の列は作らない |
| `openrouter_key.py` | secret ファイルだけを読む。環境変数へコピーしない |

### 4.6 `strategy` — `reversi.train`

対局サービスとは別プロセスで走らせる。対局時エンジンを自己対局と棋譜再生に使う。

| ファイル | 機能 |
| --- | --- |
| `wthor.py` | `.wtb` を読む。ヘッダの盤サイズが 0 または 8 のファイルだけを 8×8 として扱う。再生できないレコードは捨てる。WTHOR はパスを持たないので、合法手が無い側ではエンジンのパスを挿入する。原本を HTTP で出さない |
| `examples.py` | WTHOR と永続化対局から、Ridge と LightGBM が共有する教師あり学習例を集める |
| `ml.py` | sklearn で学習し、対局用の係数 JSON を書く |
| `lgbm.py` | LightGBM で学習し、対局用のネイティブテキストを書く |
| `rl.py` | 自己対局の線形 TD。WTHOR を使わない |
| `nn.py` | PyTorch CPU で学習し ONNX へ出す |

学習済みの小さい成果物は `models/` に含め、再学習なしで初版カタログが揃うようにする。再生は対局エンジンと同じ関数を呼ぶ。

## 5 プロセス間の JSON

対局 API の契約の正本は [`docs/openapi.yml`](openapi.yml)（OpenAPI 3.1）である。Hono はブラウザ向け `/api/*`、戦略 FastAPI はパス項目の `/decide` を待ち受ける。二つのサーバの経路は同ファイルで混ぜない。

TypeScript 側は Zod（`web/server/src/schemas.ts`）、Python 側は Pydantic（`strategy/src/reversi/api/schemas.py`）で実行時の形を検証する。どちらも `docs/openapi.yml` の `components` と同じ形にする。フィールド名、列挙、null の位置を契約から広げたり、片方だけ別名にしたりしない。共有パッケージは初版では置かない。規則の実装は `strategy/` に一つだけ置く。

ブラウザへ OpenAPI 文書（Swagger UI / ReDoc / `/openapi.json` など）を公開することは要求ではない。実装が生成文書を出してもよいが、差分があれば `docs/openapi.yml` を正とする。

含める項目の目安（要求ではなく中継の設計）:

- カタログ: 個体 ID、カテゴリ、表示名、説明文
- 対局状態: 盤 64 マス、手番、合法手、直前着手、終局、公式スコア、勝敗
- 着手指定: 座標（違法なら適用せず、再指定可能）
- 対局開始: 任意の `move_interval_seconds`（エージェント対エージェントの適用間隔。省略時は待たない）
- 障害: 外部モデル失敗時は部分盤面を返さず、継続不能を表す

## 6 データと秘密

| 置き場 | 中身 | Git |
| --- | --- | --- |
| `models/*.json`, `models/lgbm.txt`, `models/nn.onnx` | 対局時に読む学習成果物 | 含める |
| `prompts/*.md`, `prompts/*.json` | 生成 AI の固定指示。戦略イメージへ COPY し、Compose では bind | 含める |
| `data/games.sqlite` | 終局棋譜。`.wtb` ではない | 含めない |
| `data/wthor/` | WTHOR 原本 | 含めない。再配布しない |
| `data/config.toml` | 追加生成 AI のモデル名・呼称・パラメータ | 含めない |
| `data/certs/` | mkcert の証明書 | 含めない |
| Podman secret `openrouter-api-key` | OpenRouter の API キー | リポジトリにも `.env` にも置かない |

戦略コンテナだけが secret を `/run/secrets/openrouter-api-key` として読む。Hono のコンテナには渡さない。

## 7 置かないもの

tech-stack 第 5 節に加え、配置として次を置かない。

- `python/`、`frontend/`、`backend/` など言語名や曖昧な層名
- ブラウザから `strategy` への直接接続用ポート
- アカウント表、セッション Cookie 用ストア
- ルートの pnpm workspace（初版はルート `package.json` がウェブアプリ）
- 対局・学習の正として、ホストの `pnpm dev` や `python -m reversi.api` を置くこと
- ルートの Makefile / Justfile で起動を包むこと

## 8 起動とコマンド

動かすもの（対局・学習）は Podman。測るもの（pytest、Vitest、Biome、Ruff、lefthook）はホスト。根拠は [`docs/tech-stack.md`](tech-stack.md) 3.11 と 4.8。

運用コマンド（準備、`up` / `down`、学習の一発起動、成果物を読ませる再起動）の正本は [`README.md`](../README.md) である。試験・lint・E2E の正本は [`CONTRIBUTING.md`](../CONTRIBUTING.md) である。本文書は配置と待ち受けの契約だけを書く。

起動の実装は Python の `podman-compose` である。プラグインの `podman compose`（docker-compose）は `secrets.external` を扱えず使わない。コンソールスクリプトやルートの pnpm から Python を叩く入口は置かない。ホストの `uv run` を学習の正にしない。実行時に `uv sync` しない。

### 8.1 対局 Pod

| サービス | 入口（`CMD`） | 待ち受け |
| --- | --- | --- |
| `web` | ビルド済み UI を出す Hono（`node`） | コンテナ内は `0.0.0.0`。ホストへは `127.0.0.1` のみ |
| `strategy` | `python -m reversi.api` | Pod 内のみ。ホストへ公開しない。コンテナ内は `8000` でよい |

`train` は対局の `up` に載せない（コマンド列の正は README。`web` と `strategy` を明示する）。学習は待ち受けせず、`podman-compose run --rm train python -m reversi.train.*` で入口を指定する。

web コンテナが Pod 内で `0.0.0.0:3000` を聞くのはよい。戦略コンテナが Pod 内で `0.0.0.0:8000` を聞くのもよい。禁止するのはホストへの `0.0.0.0` である。

ホットリロードは別スタックを増やさず `compose.dev.yaml` のオーバーレイだけを足す。secret・公開ポート・サービス名は `compose.yaml` のままにする。コマンド列は CONTRIBUTING。

### 8.2 学習イメージ

学習用イメージは `strategy/Containerfile` の `train` ターゲットである。`uv sync --frozen --no-dev --group train` を焼く。対局用 `strategy` に torch は入れない。再学習なしでも初版カタログは動く。書き出した成果物を既に動いている対局が読むなら、README のとおり再起動する。

## 9 改訂履歴

| 版 | 日付 | 内容 |
| --- | --- | --- |
| 0.1.14 | 2026-09-20 | 対局の `up` は `web` と `strategy` を明示し、`train` を載せない |
| 0.1.13 | 2026-09-20 | 運用コマンド列の正を README へ委譲し、第 8 節は待ち受けと `CMD` と `train` を `up` に載せないことに限る |
| 0.1.12 | 2026-09-20 | Jev は原子質問を 1 呼出しで送り、`jev.py` が typed answers とコード特徴を合成する |
| 0.1.11 | 2026-09-20 | カタログをカード選択にし、盤面を盤中心の横並びに揃える |
| 0.1.10 | 2026-09-20 | 機械学習 (LightGBM) をカタログに載せ、ネイティブテキスト成果物を `models/lgbm.txt` とする |
| 0.1.9 | 2026-09-20 | 追加の生成 AI を `data/config.toml` と構造化出力に置き、自由文パースを既定にしない |
| 0.1.8 | 2026-09-20 | エージェント対エージェントの着手間隔を戦略プロセスの適用待ちとし、開始 API へ渡す |
| 0.1.7 | 2026-09-20 | 学習を `train` イメージに分け、対局用 strategy から torch を外す |
| 0.1.6 | 2026-09-20 | 生成 AI の固定指示を `prompts/` に置き、strategy イメージが読む |
| 0.1.5 | 2026-09-20 | 起動の正を `podman-compose` に揃え、文書表の日付をフロントマターと一致させる |
| 0.1.4 | 2026-09-20 | 総当たり基準結果を `docs/benchmarks/` に置く |
| 0.1.3 | 2026-09-20 | web はコンテナ内で `0.0.0.0` を聞き、ホストへ出す口は `127.0.0.1` のままにする |
| 0.1.2 | 2026-09-19 | Biome の検査対象を CI と同じ `web` にする |
| 0.1.1 | 2026-09-19 | 対局と学習の起動を Podman に揃え、試験はホストとするコマンドを書く |
| 0.1.0 | 2026-09-19 | tech-stack 0.2.7 を入力に、ディレクトリとファイルの配置を初稿とする |
