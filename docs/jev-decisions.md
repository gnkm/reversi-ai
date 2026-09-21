---
title: Jev Decisions（原子質問）
product: Reversi Agents
version: 0.1.2
status: working
date: 2026-09-20
source: docs/srs.md
srs_version: 0.1.24
architecture: docs/ARCHITECTURE.md
tech_stack: docs/tech-stack.md
---

# Jev Decisions（原子質問）

| 項目 | 内容 |
| --- | --- |
| 文書識別 | reversi-ai-jev-decisions |
| 対象ソフトウェア | Reversi Agents |
| 版 | 0.1.2 |
| 状態 | 現行（設計。要求ではない） |
| 日付 | 2026-09-20 |
| 入力 | [`docs/srs.md`](srs.md) 0.1.24、[`docs/ARCHITECTURE.md`](ARCHITECTURE.md)、[`docs/tech-stack.md`](tech-stack.md) |

本文書は、カタログ個体「生成 AI (Jev)」が使う **OpenRouter Decisions の原子質問** の形である。shall を追加・変更・撤回しない。API の選定（Decisions か Chat Completions か）は [`docs/tech-stack.md`](tech-stack.md) 3.7。配置と役割分担は [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) 4.4。プロンプトの書き方（字義どおり、数え上げをコードへ移す、state を絞る）は [`docs/source-of-truth/jev-prompt-guide.md`](source-of-truth/jev-prompt-guide.md)。シードは AI が編集しない。

## 1 呼出し

- 経路: `POST https://openrouter.ai/api/alpha/decisions`
- モデル: `typesafe/jev-1.13`
- 公式 Python SDK: `OpenRouter(server_url="https://openrouter.ai")` の `client.alpha.decisions.create`
- SDK 既定の `/api/v1` ベースではこの経路は 404 になる
- 認証は戦略コンテナの `/run/secrets/openrouter-api-key` だけを読む
- 1 着手あたり 1 HTTP 呼出し。Hono の戦略中継は 60 秒なので、それより先に失敗させる（実装は 55 秒）
- 合法手が 1 つのときは呼ばない

## 2 質問（優先と段階）

`questions` は ID をキーにした map。カタログ既定の質問は 2 本以上である。型は Noul（角・モビリティ・位置の優先）、Score（石取りの重要度）、Choice（序盤・中盤・終盤）である。`instructions` は `prompts/jev.json` の固定文字列で、合法手数では変えない。合法手のマスを Choice のキーにしない。1 本の「最善手はどれ」Choice を既定にしない。

質問 ID はコード用でありモデルには送られない。モデルに見えるのは各質問の `type`・`instructions`・`criteria` である。

```json
{
  "model": "typesafe/jev-1.13",
  "state": {
    "objective": "Win by having more discs than the opponent at the end of the game.",
    "origin": "board[0][0] is a1 (Black's lower left). Rows are ranks 1-8 toward White, columns are files a-h.",
    "side_to_move": "black",
    "board": [[0, 0], [0, 0]],
    "legal_places": ["d3", "c4", "f5", "e6"]
  },
  "questions": {
    "corner_priority": {
      "type": "noul",
      "instructions": "Should the side to move prioritize occupying corners as a goal this turn?",
      "criteria": {
        "true": "Corners are the right strategic priority now.",
        "false": "Corners are not the right priority this turn."
      }
    },
    "stage": {
      "type": "choice",
      "instructions": "Which phase best describes this position for the side to move?",
      "criteria": {
        "opening": "The opening fight for the center is still going.",
        "midgame": "The fight is about edges, corners, and options.",
        "endgame": "The game is close to finishing and remaining empty squares will soon be filled."
      }
    }
  }
}
```

盤の読み方（`board[0][0]` が a1）は質問文ではなく `state.origin` に置く。質問に `which square` や合法手の列挙を置かない。

## 3 応答

カタログ既定は typed answers を合成する。Noul は 0〜1、Score は criteria の段階数から正規化する。段階 Choice は `probabilities` があれば正規化し、無ければ `choice` を one-hot する。

SDK では `probabilities` と `confidence` は省略可。

```json
{
  "corner_priority": {"type": "noul", "noul": 0.8},
  "mobility_priority": {"type": "noul", "noul": 0.4},
  "position_priority": {"type": "noul", "noul": 0.2},
  "material_importance": {"type": "score", "score": 1.0},
  "stage": {
    "type": "choice",
    "choice": "midgame",
    "probabilities": {"opening": 0.1, "midgame": 0.8, "endgame": 0.1}
  }
}
```

## 4 本個体での受理

- 合法手の点数はコードが着手を適用したあとの盤から付ける（位置評価表の差、モビリティ、石差、角の差。切片は着手後 1 手）
- `jev.py` が typed answers とコードの点数を `prompts/jev.json` の重みで合成し、合法手からちょうど 1 つ選ぶ
- 合法手集合の外は採用しない
- 呼出し失敗・指示ファイルの欠落・合成不能は対局状態を部分適用しない（SRS-FUN-020）
- 失敗時にコード評価だけで指す代替経路は置かない

役割分担は [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) 4.4。

## 5 検証用の合法手 Choice

段階 1–5 の切替（`v2_as_is` / `v2_code0`）に限り、コードが絞った候補を Choice のキーにする経路を残す。カタログの `choose_move` の既定にはしない。この経路の Choice は代数記法のマスをキーにし、`criteria` は `state.places` と同じ言葉にする。全合法手を既定の選択肢にしない。

## 6 出典（参照。正本ではない）

- OpenRouter Decisions: https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-questions-and-answers-request
- OpenRouter Choice 質問: https://openrouter.ai/docs/client-sdks/python/components/decisionschoicequestion
- OpenRouter Choice 答え: https://openrouter.ai/docs/client-sdks/python/components/decisionschoiceanswer
- TypeSafe Choice: https://docs.typesafe.ai/primitives/choice.md
- TypeSafe confidence: https://docs.typesafe.ai/confidence.md

## 7 改訂履歴

| 版 | 日付 | 内容 |
| --- | --- | --- |
| 0.1.2 | 2026-09-20 | カタログ既定を優先の原子質問に戻し、合法手 Choice は検証用とする |
| 0.1.1 | 2026-09-20 | Choice のキーを shortlist に限り、加算合成をやめる |
| 0.1.0 | 2026-09-20 | OpenRouter Decisions の Choice の形を独立文書にする |
