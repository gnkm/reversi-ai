# アーキテクチャ

実装の置き方。要求（shall）の正本は `docs/source-of-truth/` と GitHub Issue であり、本ファイルはそれらを変えない。

対象: F001（対局エンジン）。

## 1. 対局エンジン

8×8 リバーシの規則は `strategy/src/reversi/engine/` に置く。対局と学習が同じ関数を呼ぶ。ビットボードは使わない。

| ファイル | 責務 |
| --- | --- |
| `board.py` | 盤・マス・初期配置・代数表記 |
| `rules.py` | 合法手・裏返し・パス・終局 |
| `score.py` | 石数と公式スコア |

代数表記の a1 は黒から見て左下である。列 a–h は左から右、行 1–8 は黒側から白側。内部配列は `board[rank-1][file-a]`（`[0][0]` が a1）。

合法手は相手石を 1 個以上挟む空マスだけである。挟んだ石をすべて裏返し、連鎖的な追加の裏返しは起きない。合法手が無い側にだけパスが適用される。双方が着手不能なら、64 マスが埋まっていなくても終局する。

公式スコアは石数が多い側の勝ちである。引き分けは 32–32。勝ちが決まったとき空マスは勝者に加算する。

## 2. リポジトリ構成

```
docs/
  ARCHITECTURE.md
  source-of-truth/
    01-seed.md
strategy/
  src/reversi/engine/
    board.py
    rules.py
    score.py
  tests/
    test_engine.py
```
