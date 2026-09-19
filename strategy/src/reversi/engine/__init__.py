"""8×8 リバーシの規則。対局と学習が同じ関数を呼ぶ。"""

from reversi.engine.board import (
    BOARD_SIZE,
    Board,
    Color,
    Square,
    Stone,
    all_squares,
    initial_board,
)
from reversi.engine.rules import (
    IllegalMoveError,
    PassMove,
    Place,
    Position,
    apply_place,
    flips_for,
    has_place,
    initial_position,
    is_over,
    legal_moves,
    legal_places,
    pass_is_legal,
    play,
)
from reversi.engine.score import Score, official_score, stone_counts

__all__ = [
    "BOARD_SIZE",
    "Board",
    "Color",
    "IllegalMoveError",
    "PassMove",
    "Place",
    "Position",
    "Score",
    "Square",
    "Stone",
    "all_squares",
    "apply_place",
    "flips_for",
    "has_place",
    "initial_board",
    "initial_position",
    "is_over",
    "legal_moves",
    "legal_places",
    "official_score",
    "pass_is_legal",
    "play",
    "stone_counts",
]
