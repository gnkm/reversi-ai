# ニューラルネットワーク (棋譜)

対局の前に、WTHOR と永続化した対局から **教師あり** でネットワークを学習しておく。対局時は ONNX の順伝播だけで 64 マスの点数（ロジット）を出し、合法手の外は選ばない。学習は PyTorch、対局は onnxruntime の CPU 実行である。

## 方針ネット

入力は黒・白・空の \(1\times 3\times 8\times 8\)。これを 192 次元に平坦化し、隠れ層（既定 32 ユニット、ReLU）を経て 64 次元のロジットへ写す。ロジット \(z_s\) はマス \(s\) の「選ばれやすさ」の実数である。学習の損失は交差エントロピーで、教師は棋譜がその局面で実際に置いたマスである。

対局時は合法手 \(L\) にマスクして

\[
s^\ast = \arg\max_{s \in L} z_s
\]

を選ぶ。同点は a1…h8。合法手が無ければ着手しない。

```python
def masked_place(position: Position, logits: tuple[float, ...]) -> Place | None:
    best_square = None
    best_logit: float | None = None
    for square in legal_places(position):
        logit = logits[square_index(square)]
        if best_logit is None or logit > best_logit:
            best_logit = logit
            best_square = square
    if best_square is None:
        return None
    return Place(best_square)
```

`square_index` は a1 を 0、h8 を 63 とする。機械学習 (棋譜) が「着手後の盤の価値」を回帰するのに対し、こちらは「今の盤から置くマス」を分類する。

## 出典

配置と個体の役割は [アーキテクチャ](../ARCHITECTURE.md) のカタログ個体表を見る。
