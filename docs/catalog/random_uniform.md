# ランダム (一様)

自分の手番で置けるマス（**合法手**）が \(n\) 個あるとき、どれも同じ確率 \(1/n\) で 1 つ選ぶ。棋譜も学習済みの係数も見ない。合法手が 0 個なら着手しない（パスは規則側が扱う）。

## 等確率

さいころの各目が同じ出やすさである、というのと同じである。合法手が \(\{c4, d3, e6, f5\}\) なら、各マスの確率は \(1/4\) である。直前の石の並びや「角が空いている」ことは、確率を変えない。

乱数は暗号用の `SystemRandom` を使う。試験では再現のため、呼び出し側が乱数生成器を渡してよい。

```python
places = legal_places(position)
if not places:
    return None
square = (rng if rng is not None else _RNG).choice(places)
return Place(square)
```

`choice` は列の要素を一様に 1 つ返す。対局中に WTHOR などの棋譜も、学習済みモデルも参照しない。

## 出典

配置と個体の役割は [アーキテクチャ](../ARCHITECTURE.md) のカタログ個体表を見る。
