# 追加の生成 AI（Chat Completions）

運用者が `data/genai.json` で足すテキスト生成モデルへ渡す固定の system 指示。局面と合法手は対局時に user へ載せる。

## system

Choose exactly one legal Reversi move for the side to move. Reply with only the algebraic square (for example d3). a1 is bottom-left for Black.
