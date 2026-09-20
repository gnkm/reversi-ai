---
title: Jev Decisions（Choice）
product: Reversi Agents
version: 0.1.0
status: working
date: 2026-09-20
source: docs/srs.md
srs_version: 0.1.24
architecture: docs/ARCHITECTURE.md
tech_stack: docs/tech-stack.md
---

# Jev Decisions（Choice）

| 項目 | 内容 |
| --- | --- |
| 文書識別 | reversi-ai-jev-decisions |
| 対象ソフトウェア | Reversi Agents |
| 版 | 0.1.0 |
| 状態 | 現行（設計。要求ではない） |
| 日付 | 2026-09-20 |
| 入力 | [`docs/srs.md`](srs.md) 0.1.24、[`docs/ARCHITECTURE.md`](ARCHITECTURE.md)、[`docs/tech-stack.md`](tech-stack.md) |

本文書は、カタログ個体「生成 AI (Jev)」が使う **OpenRouter Decisions の Choice** の形である。shall を追加・変更・撤回しない。API の選定（Decisions か Chat Completions か）は [`docs/tech-stack.md`](tech-stack.md) 3.7。配置と役割分担は [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) 4.4。プロンプトの書き方（字義どおり、数え上げをコードへ移す、state を絞る）は [`docs/source-of-truth/jev-prompt-guide.md`](source-of-truth/jev-prompt-guide.md)。シードは AI が編集しない。

## 1 呼出し

- 経路: `POST https://openrouter.ai/api/alpha/decisions`
- モデル: `typesafe/jev-1.13`
- 公式 Python SDK: `OpenRouter(server_url="https://openrouter.ai")` の `client.alpha.decisions.create`
- SDK 既定の `/api/v1` ベースではこの経路は 404 になる
- 認証は戦略コンテナの `/run/secrets/openrouter-api-key` だけを読む
- 1 着手あたり 1 HTTP 呼出し。Hono の戦略中継は 60 秒なので、それより先に失敗させる（実装は 55 秒）
- 合法手が 1 つのときは呼ばない

## 2 質問（Choice）

`questions` は ID をキーにした map。本個体の質問は 1 本。`type` は `"choice"`。`instructions` は `prompts/jev.json` の固定文字列で、合法手数では変えない。

Choice の `criteria` は **選択肢 ID → 説明のオブジェクト** である。Score の `criteria` は段階の配列なので混ぜない。本個体の選択肢 ID は代数記法の合法マスである。対局中に増えるのはこのキーと、それに対応する言葉だけである。

質問 ID はコード用でありモデルには送られない。モデルに見えるのは `instructions` と、criteria のキーおよび説明である。本個体では criteria の説明を `state.places` と同じ言葉にする。

```json
{
  "model": "typesafe/jev-1.13",
  "state": {
    "objective": "Win by having more discs than the opponent at the end of the game.",
    "side_to_move": "Black",
    "stage": "opening",
    "places": {
      "d3": "interior square. Occupies a corner: no. Gives a corner next: no. Opponent replies: few. Discs turned: few."
    }
  },
  "questions": {
    "place": {
      "type": "choice",
      "instructions": "Compare the legal places. Each place is written with the same facts. Choose the place that best helps you win.",
      "criteria": {
        "d3": "interior square. Occupies a corner: no. Gives a corner next: no. Opponent replies: few. Discs turned: few."
      }
    }
  }
}
```

`state` に 8×8 の数値盤や `origin` による添字変換は置かない。

## 3 応答

当該 `answers[質問ID]` は次の形である。

| フィールド | 意味 |
| --- | --- |
| `type` | `"choice"` |
| `choice` | 最大確率のキー（代数記法のマス） |
| `probabilities` | 選択肢キーごとの 0〜1 |
| `confidence` | その Choice 答えの尖り（0〜1）。レスポンス全体ではない |

SDK では `probabilities` と `confidence` は省略可。

```json
{
  "type": "choice",
  "choice": "d3",
  "confidence": 0.75,
  "probabilities": {
    "d3": 0.84,
    "c4": 0.16
  }
}
```

## 4 本個体での受理

- `probabilities` が Mapping なのに合法手キーが欠けている、または全ゼロなら合成不能とする。欠けを 0 埋めしてコード評価だけで指す代替経路は置かない
- `probabilities` が無いときは、合法な `choice` から one-hot する
- `confidence` が無いときは 1.0 として合成する
- `choice` が合法手の外なら採用しない
- 呼出し失敗・指示ファイルの欠落・合成不能は対局状態を部分適用しない（SRS-FUN-020）

着手は Choice の `probabilities`（および confidence）と、コードの着手後 1 手評価を `prompts/jev.json` の重みで合成して 1 マス選ぶ。合成の役割分担は [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) 4.4。

## 5 出典（参照。正本ではない）

- OpenRouter Decisions: https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-questions-and-answers-request
- OpenRouter Choice 質問: https://openrouter.ai/docs/client-sdks/python/components/decisionschoicequestion
- OpenRouter Choice 答え: https://openrouter.ai/docs/client-sdks/python/components/decisionschoiceanswer
- TypeSafe Choice: https://docs.typesafe.ai/primitives/choice.md
- TypeSafe confidence: https://docs.typesafe.ai/confidence.md

## 6 改訂履歴

| 版 | 日付 | 内容 |
| --- | --- | --- |
| 0.1.0 | 2026-09-20 | OpenRouter Decisions の Choice の形を独立文書にする |
