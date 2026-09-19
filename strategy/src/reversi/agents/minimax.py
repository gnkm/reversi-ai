"""深さ 4 のミニマックスで合法手を選ぶ個体。葉は位置評価表の差。"""

from __future__ import annotations

from random import Random

from reversi.agents.position_table import score_at
from reversi.engine.board import Board, Color, all_squares
from reversi.engine.rules import (
    Place,
    Position,
    is_over,
    legal_moves,
    legal_places,
    play,
)

SPECIMEN_ID = "minimax"
CATEGORY = "rule_based"
DISPLAY_NAME = "ルールベース (ミニマックス)"
DESCRIPTION = (
    "深さ 4 のミニマックスで合法手を選ぶ。"
    "葉の評価は位置評価の点数表で、根の手番側の石の点数合計から相手の点数合計を引いた値である。"
    "深さを対局中に変えない。対局中に学習済みモデルも OpenRouter も呼ばない。"
)
SEARCH_DEPTH = 4

# 点数表は [-50, 100]。64 マスでもこの番兵には届かない。
_NEG_INF = -10_000
_POS_INF = 10_000

__all__ = [
    "CATEGORY",
    "DESCRIPTION",
    "DISPLAY_NAME",
    "SEARCH_DEPTH",
    "SPECIMEN_ID",
    "choose_move",
    "leaf_score",
]


def leaf_score(board: Board, root_color: Color) -> int:
    """根の手番側の石の点数合計から相手の点数合計を引く。"""
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


def choose_move(position: Position, rng: Random | None = None) -> Place | None:
    """深さ 4 のミニマックスで合法手を選ぶ。同点は a1…h8。"""
    del rng
    root_color = position.side_to_move
    best_square = None
    best_value: int | None = None
    for square in legal_places(position):
        child = play(position, Place(square))
        value = _min_value(child, 1, root_color, _NEG_INF, _POS_INF)
        if best_value is None or value > best_value:
            best_value = value
            best_square = square
    if best_square is None:
        return None
    return Place(best_square)


def _is_leaf(position: Position, depth: int) -> bool:
    return depth >= SEARCH_DEPTH or is_over(position)


def _max_value(
    position: Position,
    depth: int,
    root_color: Color,
    alpha: int,
    beta: int,
) -> int:
    if _is_leaf(position, depth):
        return leaf_score(position.board, root_color)
    value = _NEG_INF
    for move in legal_moves(position):
        child_value = _min_value(
            play(position, move),
            depth + 1,
            root_color,
            alpha,
            beta,
        )
        value = max(value, child_value)
        alpha = max(alpha, value)
        if alpha >= beta:
            break
    return value


def _min_value(
    position: Position,
    depth: int,
    root_color: Color,
    alpha: int,
    beta: int,
) -> int:
    if _is_leaf(position, depth):
        return leaf_score(position.board, root_color)
    value = _POS_INF
    for move in legal_moves(position):
        child_value = _max_value(
            play(position, move),
            depth + 1,
            root_color,
            alpha,
            beta,
        )
        value = min(value, child_value)
        beta = min(beta, value)
        if alpha >= beta:
            break
    return value
