# 機械学習 (LightGBM)

対局の前に、WTHOR の棋譜と永続化した自対局から **勾配ブースティング**（LightGBM）で学習しておく。対局時はその木の集まりで着手直後の盤の価値を見積もり、いちばん高い合法手を選ぶ。対局時にニューラルネットワークの推論は使わない。

## 木の集まり

勾配ブースティングは、弱い予測器（深さの浅い決定木）を足し合わせて誤差を減らす方法である。1 本の木は「この特徴が閾値を超えたら左、超えないなら右」と盤の 192 次元ベクトルを分岐し、葉に実数値を置く。全体の予測はそれらの和である。

符号化と greedy の形は機械学習 (棋譜) と同じである。黒から見た予測を \(v(B)\) とし、白番では \(-v\) を最大化する。同点は a1…h8。

```python
def value_of(board: Board, model: ValueModel) -> float:
    vector = [float(feature) for feature in encode(board).as_vector()]
    predicted = model.predict([vector])
    return float(predicted[0])
```

対局時は `models/lgbm.txt`（LightGBM のテキスト形式。先頭行は `tree`）を読む。pickle / joblib / ONNX / PyTorch は使わない。線形モデルより分岐で非線形な境界を書けるが、入力の切り方（黒・白・空の 3 平面）は同じである。

## 出典

配置と個体の役割は [アーキテクチャ](../ARCHITECTURE.md) のカタログ個体表を見る。
