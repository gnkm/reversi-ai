# 生成 AI (Jev)

OpenRouter 上の Jev（モデル識別子 `typesafe/jev-1.13`）を Decisions API で呼ぶ。モデルに「どのマスが最善か」は問わない。どの目標を優先するか（角、モビリティ、位置、石取り、序盤〜終盤の段階）を原子質問で答えさせ、着手後の盤の点数はコードが付けて合成する。対局中に WTHOR は参照しない。

## 手順

1. 合法手が 0 個なら着手しない。1 個ならその手を置き、外部呼出しをしない。
2. 2 個以上なら、固定の質問文と重み（`prompts/jev.json`）を読み、1 回の HTTP 呼出しで原子質問を送る。
3. 各合法手を 1 手適用した盤について、コードが 4 つの量を付ける。切片は着手後 1 手であり、相手の応手は探索しない。
   - 位置: 位置評価表の差
   - モビリティ: 自分の合法手数 − 相手の合法手数
   - 石取り: 石数差
   - 角: 角の石数差
4. 合法手のあいだで各量を 0 と 1 のあいだに引き伸ばす。
5. Jev の答え（優先の強さ）と段階の重みを係数にして一次結合し、最大のマスを選ぶ。同点は a1…h8。

失敗（資格情報が無い、応答が壊れている、合法手の外、など）のときは、コード評価だけで指す代替経路は置かない。対局は継続不能になる。

カタログの既定はこの優先合成である。検証用に、答えを定数にした構成や、コード最善だけ、合法手 Choice などの切替はあるが、カタログの `choose_move` の既定にはしない。

```python
places = legal_places(position)
if not places:
    return None
if len(places) == 1:
    return Place(places[0])
square = _resolve_square(position, places)
if square not in places:
    raise ExternalModelError("合法手の外です")
return Place(square)
```

## 出典

配置と個体の役割は [アーキテクチャ](../ARCHITECTURE.md) のカタログ個体表を見る。原子質問の形は [Jev Decisions](../jev-decisions.md) を見る。
