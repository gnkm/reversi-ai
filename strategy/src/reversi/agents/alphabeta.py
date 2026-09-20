"""深さ 6 の Negamax（αβ）で合法手を選ぶ個体。葉は位置評価表の差。"""

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

SPECIMEN_ID = "alphabeta"
CATEGORY = "rule_based"
DISPLAY_NAME = "ルールベース (αβ)"
DESCRIPTION = (
    "深さ 6 の Negamax 形式のアルファベータ探索で合法手を選ぶ。"
    "葉の評価は位置評価の点数表で、根の手番側の石の点数合計から相手の点数合計を引いた値である。"
    "深さを対局中に変えない。対局中に学習済みモデルも OpenRouter も呼ばない。"
)
SEARCH_DEPTH = 6

# 点数表は [-50, 100]。64 マスでもこの番兵には届かない。
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
    """深さ 6 の Negamax で合法手を選ぶ。同点は a1…h8。"""
    del rng
    return choose_at_depth(position, SEARCH_DEPTH)


def choose_at_depth(position: Position, depth: int) -> Place | None:
    """指定深さの Negamax で合法手を選ぶ。対局経路は SEARCH_DEPTH を渡す。"""
    root_color = position.side_to_move
    best_square = None
    best_value: int | None = None
    for square in legal_places(position):
        child = play(position, Place(square))
        value = -_negamax(child, 1, root_color, _NEG_INF, _POS_INF, depth)
        if best_value is None or value > best_value:
            best_value = value
            best_square = square
    if best_square is None:
        return None
    return Place(best_square)


def _is_leaf(position: Position, ply: int, limit: int) -> bool:
    return ply >= limit or is_over(position)


def _signed_leaf(position: Position, root_color: Color) -> int:
    score = leaf_score(position.board, root_color)
    if position.side_to_move is root_color:
        return score
    return -score


def _negamax(
    position: Position,
    ply: int,
    root_color: Color,
    alpha: int,
    beta: int,
    limit: int,
) -> int:
    if _is_leaf(position, ply, limit):
        return _signed_leaf(position, root_color)
    value = _NEG_INF
    for move in legal_moves(position):
        child = play(position, move)
        child_value = -_negamax(child, ply + 1, root_color, -beta, -alpha, limit)
        if child_value > value:
            value = child_value
        if value > alpha:
            alpha = value
        if alpha >= beta:
            break
    return value
