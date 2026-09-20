# リバーシAI開発提案書

## αβ探索＋Mobility評価による深さ6〜8相当AIの実装

## 1. 提案概要

本提案では、現在の探索深さ4のミニマックスAIを上回ることを目的として、**αβ枝刈りを利用した探索アルゴリズム**と、**Mobilityを中心とした局面評価関数**を組み合わせたリバーシAIを開発する。

単純にミニマックスの探索深さを増やすだけでは探索局面数が急激に増加し、計算時間が大きくなる。そのため、本システムでは不要な探索を省略できるαβ枝刈りを導入し、同程度の計算時間で実質的に深さ6〜8程度まで探索できるAIを目標とする。

また、局面評価についても単純な石数差ではなく、合法手数、角、辺、危険マスなどを考慮することで、中盤においてより戦略的な手を選択できるようにする。

---

## 2. 開発目的

本AIの主な目的は以下の通りである。

* 探索深さ4の通常ミニマックスAIに安定して勝てるAIを作る
* αβ枝刈りにより探索効率を向上させる
* Mobilityを重視した局面評価を実装する
* 深さ6〜8相当の探索を実用的な計算時間で実現する
* 将来的な評価関数改善や終盤完全読みへ拡張可能な構造にする

---

## 3. 現状の課題

通常のミニマックス法では、探索深さを増加させるほど探索局面数が指数関数的に増える。

平均合法手数を `b`、探索深さを `d` とすると、探索量は概ね以下となる。

```text
O(b^d)
```

例えば平均合法手数を8と仮定すると、

```text
深さ4 : 8^4  = 4,096
深さ6 : 8^6  = 262,144
深さ8 : 8^8  = 16,777,216
```

となる。

そのため、単純なミニマックスでは深さ6〜8の探索は急激に重くなる。

また、リバーシでは現在の石数が多いことが必ずしも有利ではないため、単純な石数差による評価では適切な手を選べない場合がある。

---

## 4. 提案するAI構成

本AIは以下の構成とする。

```text
ゲーム局面
   ↓
合法手生成
   ↓
Move Ordering
   ↓
αβ探索
   ↓
評価関数
   ├─ Mobility
   ├─ Corner
   ├─ X/C Square
   ├─ Frontier
   ├─ Disc Difference
   └─ Game Phase
   ↓
最善手決定
```

中心となるアルゴリズムは、ミニマックス法を効率化した**αβ探索**とする。

---

## 5. 探索アルゴリズム

### 5.1 αβ枝刈り

αβ枝刈りは、最終的な探索結果に影響しない枝を探索途中で打ち切る手法である。

通常のミニマックスと同じ結果を得ながら、探索する局面数を大幅に削減できる。

基本形は以下とする。

```pseudo
function alphaBeta(board, depth, alpha, beta, player):

    if depth == 0 or gameOver(board):
        return evaluate(board, player)

    moves = generateMoves(board, player)

    if moves is empty:
        return -alphaBeta(
            board,
            depth - 1,
            -beta,
            -alpha,
            opponent(player)
        )

    moves = orderMoves(moves)

    bestScore = -INF

    for move in moves:

        nextBoard = applyMove(board, move, player)

        score = -alphaBeta(
            nextBoard,
            depth - 1,
            -beta,
            -alpha,
            opponent(player)
        )

        bestScore = max(bestScore, score)
        alpha = max(alpha, score)

        if alpha >= beta:
            break

    return bestScore
```

実装上は、ミニマックスよりも簡潔に記述できる**Negamax形式**を採用する。

---

## 6. Move Ordering

αβ枝刈りでは、良い手を先に探索するほど枝刈りが発生しやすい。

そのため合法手を以下の優先順位で並び替える。

```text
1. 角
2. 相手の合法手を大きく減らす手
3. 安全な辺
4. 通常マス
5. Cマス
6. Xマス
```

角は最優先で探索する。

一方、角が空いている場合のXマスやCマスは、相手に角を与える原因となりやすいため、探索順を後ろにする。

例：

```text
Xマス

X . . . . . . X
. X . . . . X .
. . . . . . . .
. . . . . . . .
. . . . . . . .
. . . . . . . .
. X . . . . X .
X . . . . . . X
```

角の斜め隣がXマスとなる。

---

## 7. 評価関数

評価関数は以下の形式を基本とする。

```text
Evaluation =
    Mobility
  + Corner
  + Positional Value
  + Frontier
  + Disc Difference
```

具体例として以下を採用する。

```text
score =
    50   × Mobility差
  + 1000 × Corner差
  - 100  × 危険マス差
  - 10   × Frontier差
  + W    × 石数差
```

ここで `W` はゲーム進行度に応じて変化させる。

---

## 8. Mobility評価

Mobilityとは、現在打つことのできる合法手数を表す。

以下で計算する。

```text
Mobility =
    自分の合法手数
    -
    相手の合法手数
```

または正規化して、

```text
MobilityScore =
100 ×
(selfMoves - opponentMoves)
/
(selfMoves + opponentMoves)
```

とする。

例として、

```text
自分の合法手数 : 8
相手の合法手数 : 3
```

の場合、

```text
MobilityScore

= 100 × (8 - 3) / (8 + 3)

≈ 45
```

となる。

リバーシでは中盤において、単純な石数よりMobilityの方が重要なケースが多いため、本AIでは特に大きな評価要素として扱う。

---

## 9. 角評価

角は一度取得すると基本的に裏返されないため、非常に重要なマスである。

角の位置は以下である。

```text
A1
A8
H1
H8
```

角評価は以下とする。

```text
CornerScore =
1000 ×
(
自分の角数
-
相手の角数
)
```

例えば、

```text
自分 : 2角
相手 : 1角
```

なら、

```text
CornerScore = +1000
```

となる。

---

## 10. Xマス・Cマス評価

角がまだ空いている場合、その周囲に石を置くと相手に角を取られる可能性が高まる。

そのためXマス・Cマスにはペナルティを与える。

例：

```text
Corner : A1

Cマス:
A2
B1

Xマス:
B2
```

評価例：

```text
Xマス : -150
Cマス : -80
```

ただし、角をすでに取得している場合はペナルティを解除する。

---

## 11. Frontier評価

Frontierとは、空きマスに隣接している石である。

Frontier石が多い場合、その石を利用して相手が打てる可能性が増える。

そのため、

```text
FrontierScore =
相手のFrontier数
-
自分のFrontier数
```

として、自分のFrontierが少ない状態を高く評価する。

---

## 12. 石数評価

単純な石数差は序盤・中盤では重要度を低く設定する。

ゲーム終盤になるにつれて石数評価の重みを増加させる。

例えば空きマス数に応じて、

```text
空きマス 40以上
石数Weight = 1

空きマス 20〜39
石数Weight = 5

空きマス 10〜19
石数Weight = 20

空きマス 9以下
石数Weight = 100
```

とする。

これにより、

```text
序盤・中盤
Mobility重視

終盤
最終石数重視
```

という評価が可能になる。

---

## 13. ゲーム進行度別評価

評価関数はゲームフェーズに応じて変更する。

### 序盤

重視する要素：

```text
Mobility
X/Cマス
位置評価
```

石数差の評価は小さくする。

### 中盤

重視する要素：

```text
Mobility
Corner
Frontier
Edge
```

特に相手の合法手を制限することを重視する。

### 終盤

重視する要素：

```text
石数
確定石
Parity
```

さらに空きマスが一定数以下になった場合は、評価関数を使用せず終局まで探索する。

---

## 14. 探索深さ

初期実装では以下を目標とする。

```text
通常探索深さ:
6

性能に余裕がある場合:
7〜8
```

αβ枝刈りとMove Orderingを組み合わせることで、通常の深さ6〜8ミニマックスより少ない探索局面数で同等の探索結果を得ることを目指す。

---

## 15. Iterative Deepening

最終的にはIterative Deepeningの導入も検討する。

探索を以下の順で実行する。

```text
depth 1
↓
depth 2
↓
depth 3
↓
depth 4
↓
depth 5
↓
depth 6
↓
...
```

浅い探索で得られた最善手を、次の探索におけるMove Orderingに使用する。

これによりαβ枝刈りの効率向上が期待できる。

---

## 16. Transposition Table

同じ局面に異なる手順から到達する場合がある。

そこで、一度評価した局面を保存するTransposition Tableを導入する。

```text
Key:
盤面 + 手番

Value:
評価値
探索深さ
Bound情報
```

盤面のハッシュにはZobrist Hashを使用することを想定する。

処理例：

```text
局面生成
   ↓
Hash計算
   ↓
Transposition Table検索
   ↓
存在する
  → 保存済み結果を利用

存在しない
  → 通常探索
```

これにより重複探索を削減できる。

---

## 17. 終盤完全読み

空きマスが少なくなった場合は、評価関数ではなく終局まで完全探索する。

例えば、

```text
空きマス <= 10
```

の場合、

```text
現在局面
↓
終局までαβ探索
↓
最終石数差
```

を計算する。

評価値は、

```text
自分の石数
-
相手の石数
```

とする。

これにより終盤の読み間違いを防止する。

---

## 18. 実装段階

実装は以下の順序で進める。

### Phase 1

αβ枝刈りを実装する。

目標：

```text
Minimax Depth 4
↓
AlphaBeta Depth 6
```

### Phase 2

Mobility評価を導入する。

```text
Evaluation =
Mobility
+
Corner
+
Disc Difference
```

### Phase 3

Move Orderingを実装する。

優先順位：

```text
Corner
↓
Mobility改善手
↓
Edge
↓
Normal
↓
C
↓
X
```

### Phase 4

評価関数を強化する。

追加要素：

```text
Frontier
X/Cマス
Game Phase
```

### Phase 5

Transposition Tableを導入する。

### Phase 6

終盤完全読みを導入する。

---

## 19. 評価方法

AIの強さは対局結果によって評価する。

比較対象：

```text
AI-A
Minimax Depth 4
石数評価

AI-B
AlphaBeta Depth 6
Mobility評価

AI-C
AlphaBeta Depth 8
Mobility + Corner + Frontier
```

各組み合わせで先手・後手を入れ替えて複数回対局する。

例：

```text
100試合

先手50試合
後手50試合
```

測定項目：

```text
勝率
平均石数差
平均探索局面数
平均思考時間
最大思考時間
```

---

## 20. 目標性能

本プロジェクトでは以下を目標とする。

```text
探索深さ:
6〜8

Depth 4 Minimaxに対する勝率:
70%以上を目標

通常局面の思考時間:
実用的な範囲

終盤:
可能な範囲で完全読み
```

特に、探索深さだけに依存せず、評価関数によってDepth 4 Minimaxより高品質な手を選択できることを目標とする。

---

## 21. 最終構成

最終的なAI構成は以下を想定する。

```text
Reversi AI
│
├─ Negamax
│   └─ Alpha-Beta Pruning
│
├─ Move Ordering
│   ├─ Corner
│   ├─ Mobility
│   ├─ Edge
│   └─ X/C penalty
│
├─ Evaluation
│   ├─ Mobility
│   ├─ Corner
│   ├─ Frontier
│   ├─ Disc Difference
│   └─ Game Phase
│
├─ Transposition Table
│   └─ Zobrist Hash
│
└─ Endgame Solver
    └─ Exact Search
```

---

## 22. 今後の発展

本AI完成後は、以下の改良が考えられる。

```text
Iterative Deepening
Aspiration Window
Principal Variation Search
Killer Move
History Heuristic
Stable Disc評価
Parity評価
Pattern Evaluation
Opening Book
```

さらに高度なAIでは、評価関数の重みを固定値で設定するのではなく、

```text
自己対戦
↓
対局データ収集
↓
評価関数の重み最適化
```

によって自動学習することも可能である。

---

## 23. 結論

本提案では、探索深さ4の通常ミニマックスAIを上回るため、

```text
αβ枝刈り
+
Move Ordering
+
Mobility中心の評価関数
```

を基本構成として採用する。

まずはDepth 6のαβ探索を実装し、その後評価関数と探索最適化を段階的に追加する。

最終的には、

```text
Alpha-Beta
+
Depth 6〜8
+
Mobility Evaluation
+
Move Ordering
+
Transposition Table
+
Endgame Exact Search
```

という構成を目指す。

この構成により、単純な深さ4ミニマックスよりも高い探索性能と局面評価能力を持つ、より実戦的なリバーシAIの実現を目指す。
