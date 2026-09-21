"""深さ 4 の Negamax（αβ）。Transposition Table（Zobrist）。"""

from __future__ import annotations

from random import Random

from reversi.engine.board import BOARD_SIZE, Board, Color, Square, Stone
from reversi.engine.rules import (
    DIRECTIONS,
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
    "深さ 4 のアルファベータ探索で合法手を選ぶ。"
    "深さを対局中に変えない。対局中に学習済みモデルも OpenRouter も呼ばない。"
)
SEARCH_DEPTH = 4

# score = 50×Mobility差 + 1000×Corner差 − 150×X差 − 80×C差 − 10×Frontier差 + W×石数差。
# W は空きマス数（Game Phase）。40 以上は 1、20〜39 は 5、10〜19 は 20、9 以下は 100。
_MOBILITY_WEIGHT = 50
_CORNER_WEIGHT = 1000
_X_WEIGHT = 150
_C_WEIGHT = 80
_FRONTIER_WEIGHT = 10
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

# 葉は W=100 でも |score| は数万程度。この番兵には届かない。
_NEG_INF = -1_000_000
_POS_INF = 1_000_000

# Transposition Table の Bound。同じ残り深さの結果だけ再利用する（根の選択を変えない）。
_TT_EXACT = "exact"
_TT_LOWER = "lower"
_TT_UPPER = "upper"

# Zobrist 乱数は探索用ハッシュに限る。対局エンジンは 8×8 配列のまま。
_ZOBRIST_SEED = 0xA1B2C3D4E5F60789
_TtTable = dict[tuple[int, int], tuple[int, str]]


def _zobrist_tables(seed: int) -> tuple[tuple[tuple[int, int], ...], int]:
    rng = Random(seed)
    squares = tuple(
        (rng.getrandbits(64), rng.getrandbits(64))
        for _ in range(BOARD_SIZE * BOARD_SIZE)
    )
    return squares, rng.getrandbits(64)


_ZOBRIST_SQUARES, _ZOBRIST_SIDE = _zobrist_tables(_ZOBRIST_SEED)

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
    """color 視点の Mobility・Corner・X/C・Frontier・石数差の一次結合。"""
    mobility = _mobility_diff(board, color)
    corner = _stone_diff(board, color, _CORNERS)
    x_squares = _danger_diff(board, color, _X_SQUARES)
    c_squares = _danger_diff(board, color, _C_SQUARES)
    disc, frontier, empty = _disc_frontier_empty(board, color)
    weight = _disc_weight(empty)
    return (
        _MOBILITY_WEIGHT * mobility
        + _CORNER_WEIGHT * corner
        - _X_WEIGHT * x_squares
        - _C_WEIGHT * c_squares
        - _FRONTIER_WEIGHT * frontier
        + weight * disc
    )


def choose_move(position: Position, rng: Random | None = None) -> Place | None:
    """深さ 4 の Negamax で合法手を選ぶ。同点は a1…h8。"""
    del rng
    return choose_at_depth(position, SEARCH_DEPTH)


def choose_at_depth(
    position: Position,
    depth: int,
    *,
    order: bool = True,
    table: bool = True,
) -> Place | None:
    """指定深さの Negamax で合法手を選ぶ。対局経路は SEARCH_DEPTH を渡す。"""
    place, _value, _nodes = _search_root(position, depth, order, table)
    return place


def search_stats(
    position: Position,
    depth: int,
    *,
    order: bool = True,
    table: bool = True,
) -> tuple[Place | None, int | None, int]:
    """(手, その Negamax 値, 探索ノード数)。合法手が無ければ値は None。"""
    return _search_root(position, depth, order, table)


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


def _disc_weight(empty: int) -> int:
    """空きマス数（Game Phase）に応じた石数差の係数 W。"""
    if empty >= 40:
        return 1
    if empty >= 20:
        return 5
    if empty >= 10:
        return 20
    return 100


def _empty_adjacent(
    cells: tuple[tuple[Stone, ...], ...], file: int, rank: int
) -> bool:
    for delta_file, delta_rank in DIRECTIONS:
        neighbor_file = file + delta_file
        neighbor_rank = rank + delta_rank
        if (
            0 <= neighbor_file < BOARD_SIZE
            and 0 <= neighbor_rank < BOARD_SIZE
            and cells[neighbor_rank][neighbor_file] is Stone.EMPTY
        ):
            return True
    return False


def _disc_frontier_empty(board: Board, color: Color) -> tuple[int, int, int]:
    """石数差・Frontier 差・空きマス数を 1 回の盤面走査で集計する。"""
    own = color.stone
    cells = board.cells
    disc = 0
    frontier = 0
    empty = 0
    for rank, row in enumerate(cells):
        for file, stone in enumerate(row):
            if stone is Stone.EMPTY:
                empty += 1
                continue
            sign = 1 if stone is own else -1
            disc += sign
            if _empty_adjacent(cells, file, rank):
                frontier += sign
    return disc, frontier, empty


def _danger_diff(
    board: Board,
    color: Color,
    related: dict[Square, Square],
) -> int:
    """空き角に紐づく X / C の石の差（自分 − 相手）。角を取っていれば解除。"""
    own = color.stone
    opponent = color.opponent.stone
    total = 0
    for square, corner in related.items():
        if board.stone_at(corner) is not Stone.EMPTY:
            continue
        stone = board.stone_at(square)
        if stone is own:
            total += 1
        elif stone is opponent:
            total -= 1
    return total


def _is_leaf(position: Position, ply: int, limit: int) -> bool:
    # 深さ上限を先に見て、葉での is_over 走査を避ける。
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


def _position_key(position: Position) -> int:
    """盤面 + 手番の Zobrist ハッシュ。空マスは 0。"""
    key = 0
    cells = position.board.cells
    for rank, row in enumerate(cells):
        base = rank * BOARD_SIZE
        for file, stone in enumerate(row):
            if stone is Stone.EMPTY:
                continue
            black_key, white_key = _ZOBRIST_SQUARES[base + file]
            key ^= black_key if stone is Stone.BLACK else white_key
    if position.side_to_move is Color.WHITE:
        key ^= _ZOBRIST_SIDE
    return key


def _tt_probe(
    table: _TtTable,
    key: int,
    remaining: int,
    alpha: int,
    beta: int,
) -> int | None:
    entry = table.get((key, remaining))
    if entry is None:
        return None
    value, bound = entry
    if bound == _TT_EXACT:
        return value
    if bound == _TT_LOWER and value >= beta:
        return value
    if bound == _TT_UPPER and value <= alpha:
        return value
    return None


def _tt_store(
    table: _TtTable,
    key: int,
    remaining: int,
    value: int,
    alpha_orig: int,
    beta: int,
) -> None:
    if value <= alpha_orig:
        bound = _TT_UPPER
    elif value >= beta:
        bound = _TT_LOWER
    else:
        bound = _TT_EXACT
    table[(key, remaining)] = (value, bound)


def _search_root(
    position: Position,
    depth: int,
    order: bool,
    use_table: bool,
) -> tuple[Place | None, int | None, int]:
    nodes = [0]
    table: _TtTable | None = {} if use_table else None
    best_square = None
    best_value: int | None = None
    for square in legal_places(position):
        child = play(position, Place(square))
        value = -_negamax(child, 1, _NEG_INF, _POS_INF, depth, order, nodes, table)
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
    table: _TtTable | None,
) -> int:
    nodes[0] += 1
    remaining = limit - ply
    key = _position_key(position) if table is not None else 0
    if table is not None:
        hit = _tt_probe(table, key, remaining, alpha, beta)
        if hit is not None:
            return hit
    if _is_leaf(position, ply, limit):
        value = leaf_score(position.board, position.side_to_move)
        if table is not None:
            table[(key, remaining)] = (value, _TT_EXACT)
        return value
    alpha_orig = alpha
    value = _NEG_INF
    for move in _moves_to_search(position, order):
        child = play(position, move)
        child_value = -_negamax(
            child, ply + 1, -beta, -alpha, limit, order, nodes, table
        )
        value = max(value, child_value)
        alpha = max(alpha, value)
        if alpha >= beta:
            break
    if table is not None:
        _tt_store(table, key, remaining, value, alpha_orig, beta)
    return value
