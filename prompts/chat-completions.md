# 追加の生成 AI（Chat Completions）

運用者が `config.toml` で足すテキスト生成モデルへ渡す固定の system 指示。局面と合法手は対局時に user へ載せる。応答は JSON オブジェクトとして検証する。

## system

Choose exactly one legal Reversi move for the side to move. Reply with a JSON object {"square":"<algebraic>"} and no other text. Example: {"square":"d3"}. a1 is bottom-left for Black.
