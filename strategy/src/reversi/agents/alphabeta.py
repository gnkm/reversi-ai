"""深さ 6 の Negamax（αβ）で合法手を選ぶ個体。葉は Mobility・Corner・石差。"""

from __future__ import annotations

from random import Random

from reversi.engine.board import Board, Color, Square, all_squares
from reversi.engine.rules import (
    Place,
    Position,
    is_over,
    legal_moves,
    legal_places,
    play,
)

SPECIMEN_ID = "alphabeta"
CATEGORY = "rule_based"
DISPLAY_NAME = "ルールベース (αβ)"
DESCRIPTION = (
    "深さ 6 の Negamax 形式のアルファベータ探索で合法手を選ぶ。"
    "葉の評価は Mobility 差・Corner 差・石数差の一次結合である。"
    "深さを対局中に変えない。対局中に学習済みモデルも OpenRouter も呼ばない。"
)
SEARCH_DEPTH = 6

# score = 50 × Mobility差 + 1000 × Corner差 + 1 × 石数差（W は序盤例の固定値）。
_MOBILITY_WEIGHT = 50
_CORNER_WEIGHT = 1000
_DISC_WEIGHT = 1
_CORNERS: tuple[Square, ...] = (
    Square.parse("a1"),
    Square.parse("a8"),
    Square.parse("h1"),
    Square.parse("h8"),
)

# Mobility 差は高々 64、角差は高々 4。この番兵には届かない。
_NEG_INF = -10_000
_POS_INF = 10_000

__all__ = [
    "CATEGORY",
    "DESCRIPTION",
    "DISPLAY_NAME",
    "SEARCH_DEPTH",
    "SPECIMEN_ID",
    "choose_at_depth",
    "choose_move",
    "leaf_score",
]


def leaf_score(board: Board, color: Color) -> int:
    """color 視点の Mobility 差・Corner 差・石数差の一次結合。"""
    mobility = _mobility_diff(board, color)
    corner = _stone_diff(board, color, _CORNERS)
    disc = _stone_diff(board, color, all_squares())
    return _MOBILITY_WEIGHT * mobility + _CORNER_WEIGHT * corner + _DISC_WEIGHT * disc


def choose_move(position: Position, rng: Random | None = None) -> Place | None:
    """深さ 6 の Negamax で合法手を選ぶ。同点は a1…h8。"""
    del rng
    return choose_at_depth(position, SEARCH_DEPTH)


def choose_at_depth(position: Position, depth: int) -> Place | None:
    """指定深さの Negamax で合法手を選ぶ。対局経路は SEARCH_DEPTH を渡す。"""
    best_square = None
    best_value: int | None = None
    for square in legal_places(position):
        child = play(position, Place(square))
        value = -_negamax(child, 1, _NEG_INF, _POS_INF, depth)
        if best_value is None or value > best_value:
            best_value = value
            best_square = square
    if best_square is None:
        return None
    return Place(best_square)


def _mobility_diff(board: Board, color: Color) -> int:
    own = len(legal_places(Position(board, color)))
    opponent = len(legal_places(Position(board, color.opponent)))
    return own - opponent


def _stone_diff(board: Board, color: Color, squares: tuple[Square, ...]) -> int:
    own = color.stone
    opponent = color.opponent.stone
    total = 0
    for square in squares:
        stone = board.stone_at(square)
        if stone is own:
            total += 1
        elif stone is opponent:
            total -= 1
    return total


def _is_leaf(position: Position, ply: int, limit: int) -> bool:
    return ply >= limit or is_over(position)


def _negamax(
    position: Position,
    ply: int,
    alpha: int,
    beta: int,
    limit: int,
) -> int:
    if _is_leaf(position, ply, limit):
        return leaf_score(position.board, position.side_to_move)
    value = _NEG_INF
    for move in legal_moves(position):
        child = play(position, move)
        child_value = -_negamax(child, ply + 1, -beta, -alpha, limit)
        value = max(value, child_value)
        alpha = max(alpha, value)
        if alpha >= beta:
            break
    return value
