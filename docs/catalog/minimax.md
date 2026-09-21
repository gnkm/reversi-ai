# ルールベース (ミニマックス)

現在の手番側を根として、深さ 4 の **ミニマックス** で合法手を選ぶ。根を深さ 0 とし、着手またはパス 1 回で深さを 1 増やす。深さ 4 に達した局面、または終局した局面を **葉** とする。葉の点数は、位置評価と同じ点数表で、根の手番側の石の合計から相手の合計を引いた値である。根の手番側は点数を最大化し、相手は最小化する。深さを対局中に変えない。

## ゲーム木

合法手を枝、局面を節点とみなした図を **ゲーム木** という。深さ 4 までしか降りないので、終局まで読むわけではない。葉では次の関数で点数を付ける。

\[
v(B) = \sum_{s:\,B(s)=\text{根側}} w(s) - \sum_{s:\,B(s)=\text{相手}} w(s)
\]

\(w(s)\) は位置評価の点数表である。自分の石だけを足す位置評価個体とは、相手の石を引く点が違う。

```python
def leaf_score(board: Board, root_color: Color) -> int:
    own = root_color.stone
    opponent = root_color.opponent.stone
    total = 0
    for square in all_squares():
        stone = board.stone_at(square)
        if stone is own:
            total += score_at(square)
        elif stone is opponent:
            total -= score_at(square)
    return total
```

根では各合法手を 1 手進め、相手番の最小値を取る。同点は a1…h8 で先に最大となった手。

```python
for square in legal_places(position):
    child = play(position, Place(square))
    value = _min_value(child, 1, root_color, _NEG_INF, _POS_INF)
    if best_value is None or value > best_value:
        best_value = value
        best_square = square
```

実装は内部節点で αβ 枝刈りを入れる。これは「選ぶ手が同じになる省略」であり、葉の点数と深さ 4 は変えない。対局中に学習済みモデルも OpenRouter も呼ばない。

## 出典

配置と個体の役割は [アーキテクチャ](../ARCHITECTURE.md) のカタログ個体表を見る。
