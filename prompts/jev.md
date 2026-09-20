# 生成 AI (Jev)

`typesafe/jev-1.13` の Decisions API に渡す固定の指示。モデル識別子はコード側の定数のまま。合法手は対局時に `{square}` へ埋め込む。

## instructions

Choose exactly one legal Reversi move for the side to move. Each option is an algebraic square. a1 is bottom-left for Black.

## option

Place a stone on {square}.
