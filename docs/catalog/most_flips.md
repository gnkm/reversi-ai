# ルールベース (最多取り)

各合法手について、その手で裏返る **相手の石の個数** を数える。個数が最大の手を選ぶ。いま置いた自分の石は数えない。同点なら、盤の座標が a1 に近い手を選ぶ（走査順は a1 から h8）。

## 個数の最大化

合法手の集合を \(L\)、マス \(s\) で裏返る相手石の集合を \(F(s)\) とする。選ぶマスは

\[
s^\ast = \arg\max_{s \in L} |F(s)|
\]

である。最大値が並ぶときは、\(L\) を a1…h8 の順に見て、最初に最大へ到達したマスを残す。

```python
best_square = None
best_flips = -1
for square in legal_places(position):
    n = len(flips_for(position.board, square, color))
    if n > best_flips:
        best_flips = n
        best_square = square
```

`>` だけを見ているので、同点では先に現れたマスが残る。`legal_places` は a1…h8 の順である。対局中に学習済みモデルも OpenRouter も呼ばない。

終盤の石数を直接最大化しているわけではない。序盤で多く裏返す手が、角を渡す手になることもある。

## 出典

配置と個体の役割は [アーキテクチャ](../ARCHITECTURE.md) のカタログ個体表を見る。
