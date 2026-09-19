"""着手直後の自分の石の点数合計が最大の合法手を選ぶ個体。"""

from __future__ import annotations

from random import Random

from reversi.agents.position_table import score_at
from reversi.engine.board import Board, Color, all_squares
from reversi.engine.rules import Place, Position, apply_place, legal_places

SPECIMEN_ID = "positional"
CATEGORY = "rule_based"
DISPLAY_NAME = "ルールベース (位置評価)"
DESCRIPTION = (
    "着手直後の自分の色の石があるマスの点数合計が最大の合法手を選ぶ。"
    "点数表は対局中に変わらない。同点は a1 から h8 の座標順。"
    "対局中に学習済みモデルも OpenRouter も呼ばない。"
)

__all__ = [
    "CATEGORY",
    "DESCRIPTION",
    "DISPLAY_NAME",
    "SPECIMEN_ID",
    "choose_move",
    "own_stone_score",
]


def own_stone_score(board: Board, color: Color) -> int:
    """自分の色の石があるマスの点数合計。"""
    own = color.stone
    total = 0
    for square in all_squares():
        if board.stone_at(square) is own:
            total += score_at(square)
    return total


def choose_move(position: Position, rng: Random | None = None) -> Place | None:
    """着手後の自分の石の点数合計が最大の合法手。同点は a1…h8。"""
    del rng
    color = position.side_to_move
    best_square = None
    best_score: int | None = None
    for square in legal_places(position):
        after = apply_place(position.board, square, color)
        score = own_stone_score(after, color)
        if best_score is None or score > best_score:
            best_score = score
            best_square = square
    if best_square is None:
        return None
    return Place(best_square)
