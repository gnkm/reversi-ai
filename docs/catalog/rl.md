# 強化学習 (自己対局)

自分自身と何度も対局して得た **線形の方針** で合法手を選ぶ。WTHOR は使わない。対局時にニューラルネットワークの推論も OpenRouter も使わない。

## 自己対局と TD(0)

強化学習では、外から正解の手を与えず、対局の結果（報酬）から価値の見積もりを更新する。ここでの算法は線形の **TD(0)**（Temporal Difference。1 歩先の見積もりで今の見積もりを直す）である。

盤 \(B\) の特徴を \(\boldsymbol{\phi}(B)\)（黒・白・空の 192 次元）、重みを \(\mathbf{w}\)、切片を \(b\) とする。価値は

\[
v(B) = b + \mathbf{w}\cdot \boldsymbol{\phi}(B)
\]

である。自己対局中は確率 \(\varepsilon\) でランダムな合法手を混ぜ（ε-greedy）、残りは greedy である。1 局が終わると、各局面について

\[
\delta = u - v(B),\qquad
\mathbf{w} \leftarrow \mathbf{w} + \alpha\,\delta\,\boldsymbol{\phi}(B),\qquad
b \leftarrow b + \alpha\,\delta
\]

と更新する。\(u\) は次の局面の \(v\)、終局では報酬（黒勝ち \(+1\)、白勝ち \(-1\)、引き分け \(0\)）である。既定は 400 局、\(\alpha = 0.001\)、\(\varepsilon = 0.1\) である。

対局時は学習済みの \(\mathbf{w}, b\) で着手直後の価値がいちばん高い合法手を選ぶ。白番では符号を反転する。同点は a1…h8。`models/rl.json` を読む。

```python
def value_of(board: Board, policy: LinearPolicy) -> float:
    total = policy.bias
    for rank, row in enumerate(board.cells):
        base = rank * 8
        for file, stone in enumerate(row):
            index = base + file
            if stone is Stone.BLACK:
                total += policy.weights[index]
            elif stone is Stone.WHITE:
                total += policy.weights[64 + index]
            else:
                total += policy.weights[128 + index]
    return total
```

各マスは黒・白・空のどれか一つなので、立っている平面の重みだけを足せば内積になる。

## 出典

配置と個体の役割は [アーキテクチャ](../ARCHITECTURE.md) のカタログ個体表を見る。
