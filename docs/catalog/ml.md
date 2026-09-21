# 機械学習 (棋譜)

対局の前に、WTHOR の棋譜と永続化した自対局から **線形モデル** を学習しておく。対局時はその係数で着手直後の盤の価値を見積もり、いちばん高い合法手を選ぶ。対局時にニューラルネットワークの推論は使わない。

## 盤の符号化

8×8 の盤を、黒・白・空の 3 枚の 0/1 平面に写す。長さは \(3\times 8\times 8 = 192\) である。手番は入力に含めない。

## 線形の価値

係数ベクトルを \(\mathbf{w}\)、切片を \(b\)、符号化を \(\mathbf{x}(B)\) とする。黒から見た価値は内積

\[
v(B) = b + \mathbf{w}\cdot \mathbf{x}(B)
\]

である。白番では \(-v\) を最大化する（黒有利为正なので符号を反転する）。同点は a1…h8。

学習は Ridge（L2 正則化つきの線形回帰）である。各局面のラベルは、その対局の最終結果を黒から見て \(+1\) / \(0\) / \(-1\) とした値である。同じ対局の途中盤は、終局まで再生できたものだけを使う。

```python
def value_of(board: Board, model: LinearModel) -> float:
    total = model.bias
    for weight, feature in zip(model.weights, encode(board).as_vector(), strict=True):
        total += weight * feature
    return total
```

対局時は `models/ml.json` を読む。sklearn も PyTorch も import しない。

## 出典

配置と個体の役割は [アーキテクチャ](../ARCHITECTURE.md) のカタログ個体表を見る。
