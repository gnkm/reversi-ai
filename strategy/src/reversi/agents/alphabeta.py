"""深さ 6 の Negamax（αβ）で合法手を選ぶ個体。葉は Mobility・Corner・石差。"""

from __future__ import annotations

from random import Random

from reversi.engine.board import BOARD_SIZE, Board, Color, Square, Stone, all_squares
from reversi.engine.rules import (
    Move,
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
    "探索前に合法手を Move Ordering で並べる（角、相手の合法手を減らす手、安全な辺、通常、C、X）。"
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
_CORNER_SET = frozenset(_CORNERS)

# 角が空のときの X / C は後ろへ回す。キーは X または C、値は対応する角。
_X_SQUARES: dict[Square, Square] = {
    Square.parse("b2"): Square.parse("a1"),
    Square.parse("b7"): Square.parse("a8"),
    Square.parse("g2"): Square.parse("h1"),
    Square.parse("g7"): Square.parse("h8"),
}
_C_SQUARES: dict[Square, Square] = {
    Square.parse("a2"): Square.parse("a1"),
    Square.parse("b1"): Square.parse("a1"),
    Square.parse("a7"): Square.parse("a8"),
    Square.parse("b8"): Square.parse("a8"),
    Square.parse("g1"): Square.parse("h1"),
    Square.parse("h2"): Square.parse("h1"),
    Square.parse("g8"): Square.parse("h8"),
    Square.parse("h7"): Square.parse("h8"),
}

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
    "ordered_places",
    "search_stats",
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


def choose_at_depth(
    position: Position,
    depth: int,
    *,
    order: bool = True,
) -> Place | None:
    """指定深さの Negamax で合法手を選ぶ。対局経路は SEARCH_DEPTH を渡す。"""
    place, _value, _nodes = _search_root(position, depth, order)
    return place


def search_stats(
    position: Position,
    depth: int,
    *,
    order: bool = True,
) -> tuple[Place | None, int | None, int]:
    """(手, その Negamax 値, 探索ノード数)。合法手が無ければ値は None。"""
    return _search_root(position, depth, order)


def ordered_places(position: Position) -> tuple[Square, ...]:
    """合法手を Move Ordering の優先で並べる。同一分類では相手の合法手数、a1…h8 の順。"""
    places = legal_places(position)
    if len(places) <= 1:
        return places
    opponent_now = len(
        legal_places(Position(position.board, position.side_to_move.opponent))
    )
    return tuple(
        sorted(places, key=lambda square: _order_key(position, square, opponent_now))
    )


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


def _is_edge(square: Square) -> bool:
    return square.file in (0, BOARD_SIZE - 1) or square.rank in (0, BOARD_SIZE - 1)


def _corner_empty(board: Board, square: Square, related: dict[Square, Square]) -> bool:
    corner = related.get(square)
    return corner is not None and board.stone_at(corner) is Stone.EMPTY


def _order_bucket(
    board: Board,
    square: Square,
    opponent_after: int,
    opponent_now: int,
) -> int:
    """小さいほど先に読む。角→手数減→辺→通常→C→X。"""
    if square in _CORNER_SET:
        return 0
    if _corner_empty(board, square, _X_SQUARES):
        return 5
    if _corner_empty(board, square, _C_SQUARES):
        return 4
    if opponent_after < opponent_now:
        return 1
    if _is_edge(square):
        return 2
    return 3


def _order_key(
    position: Position,
    square: Square,
    opponent_now: int,
) -> tuple[int, int, int]:
    child = play(position, Place(square))
    opponent_after = len(legal_places(child))
    bucket = _order_bucket(position.board, square, opponent_after, opponent_now)
    return (bucket, opponent_after, square.rank * BOARD_SIZE + square.file)


def _moves_to_search(position: Position, order: bool) -> tuple[Move, ...]:
    moves = legal_moves(position)
    if not order or len(moves) <= 1:
        return moves
    return tuple(Place(square) for square in ordered_places(position))


def _search_root(
    position: Position,
    depth: int,
    order: bool,
) -> tuple[Place | None, int | None, int]:
    nodes = [0]
    best_square = None
    best_value: int | None = None
    for square in legal_places(position):
        child = play(position, Place(square))
        value = -_negamax(child, 1, _NEG_INF, _POS_INF, depth, order, nodes)
        if best_value is None or value > best_value:
            best_value = value
            best_square = square
    if best_square is None:
        return None, None, nodes[0]
    return Place(best_square), best_value, nodes[0]


def _negamax(
    position: Position,
    ply: int,
    alpha: int,
    beta: int,
    limit: int,
    order: bool,
    nodes: list[int],
) -> int:
    nodes[0] += 1
    if _is_leaf(position, ply, limit):
        return leaf_score(position.board, position.side_to_move)
    value = _NEG_INF
    for move in _moves_to_search(position, order):
        child = play(position, move)
        child_value = -_negamax(child, ply + 1, -beta, -alpha, limit, order, nodes)
        value = max(value, child_value)
        alpha = max(alpha, value)
        if alpha >= beta:
            break
    return value
