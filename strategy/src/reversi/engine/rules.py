"""合法手・裏返し・パス・終局。連鎖的な追加の裏返しは起きない。"""

from __future__ import annotations

from dataclasses import dataclass

from reversi.engine.board import (
    BOARD_SIZE,
    Board,
    Color,
    Square,
    Stone,
    all_squares,
    initial_board,
)

DIRECTIONS: tuple[tuple[int, int], ...] = (
    (-1, -1),
    (0, -1),
    (1, -1),
    (-1, 0),
    (1, 0),
    (-1, 1),
    (0, 1),
    (1, 1),
)


class IllegalMoveError(ValueError):
    """着手が規則に合わない。盤は変えない。"""


@dataclass(frozen=True, slots=True)
class Place:
    """マスへ打つ。"""

    square: Square


@dataclass(frozen=True, slots=True)
class PassMove:
    """合法手が無く、相手には合法手があるときにだけ適用する。"""


Move = Place | PassMove


@dataclass(frozen=True, slots=True)
class Position:
    """盤と手番。"""

    board: Board
    side_to_move: Color


def initial_position() -> Position:
    return Position(board=initial_board(), side_to_move=Color.BLACK)


def _in_bounds(file: int, rank: int) -> bool:
    return 0 <= file < BOARD_SIZE and 0 <= rank < BOARD_SIZE


def _flips_in_direction(
    board: Board,
    origin: Square,
    color: Color,
    delta: tuple[int, int],
) -> tuple[Square, ...]:
    df, dr = delta
    own = color.stone
    opponent = color.opponent.stone
    seen: list[Square] = []
    file = origin.file + df
    rank = origin.rank + dr
    while _in_bounds(file, rank):
        here = Square(file=file, rank=rank)
        stone = board.stone_at(here)
        if stone is opponent:
            seen.append(here)
            file += df
            rank += dr
            continue
        if stone is own and seen:
            return tuple(seen)
        return ()
    return ()


def flips_for(board: Board, square: Square, color: Color) -> tuple[Square, ...]:
    """置いたマスから直線で挟む相手石。新しい石からの連鎖は含めない。"""
    if board.stone_at(square) is not Stone.EMPTY:
        return ()
    found: list[Square] = []
    for delta in DIRECTIONS:
        found.extend(_flips_in_direction(board, square, color, delta))
    return tuple(found)


def has_place(board: Board, color: Color) -> bool:
    return any(flips_for(board, square, color) for square in all_squares())


def legal_places(position: Position) -> tuple[Square, ...]:
    color = position.side_to_move
    return tuple(
        square
        for square in all_squares()
        if flips_for(position.board, square, color)
    )


def pass_is_legal(position: Position) -> bool:
    side = position.side_to_move
    return (not has_place(position.board, side)) and has_place(
        position.board, side.opponent
    )


def is_over(position: Position) -> bool:
    board = position.board
    return (not has_place(board, Color.BLACK)) and (
        not has_place(board, Color.WHITE)
    )


def legal_moves(position: Position) -> tuple[Move, ...]:
    places = legal_places(position)
    if places:
        return tuple(Place(square) for square in places)
    if pass_is_legal(position):
        return (PassMove(),)
    return ()


def apply_place(board: Board, square: Square, color: Color) -> Board:
    flipped = flips_for(board, square, color)
    if not flipped:
        raise IllegalMoveError(f"{square.algebraic} は合法手ではありません")
    updates = {square: color.stone}
    updates.update(dict.fromkeys(flipped, color.stone))
    return board.replacing(updates)


def play(position: Position, move: Move) -> Position:
    if isinstance(move, PassMove):
        if not pass_is_legal(position):
            raise IllegalMoveError("パスは適用できません")
        return Position(position.board, position.side_to_move.opponent)
    board = apply_place(position.board, move.square, position.side_to_move)
    return Position(board, position.side_to_move.opponent)
