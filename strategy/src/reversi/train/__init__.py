"""学習入力。WTHOR の 8×8 棋譜だけを読む。"""

from reversi.train.wthor import (
    DEFAULT_WTHOR_DIR,
    TrainingGame,
    decode_8x8_move,
    encode_8x8_move,
    replay,
    training_games,
)

__all__ = [
    "DEFAULT_WTHOR_DIR",
    "TrainingGame",
    "decode_8x8_move",
    "encode_8x8_move",
    "replay",
    "training_games",
]
