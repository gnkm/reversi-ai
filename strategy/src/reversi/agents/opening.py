"""短い定石列に乗っているあいだはそれに従い、外れたら位置評価へ切り替える個体。"""

from __future__ import annotations

from random import Random

from reversi.agents.positional import choose_move as choose_positional
from reversi.engine.board import BOARD_SIZE, Square, all_squares
from reversi.engine.rules import Place, Position, initial_position, legal_places

SPECIMEN_ID = "opening"
CATEGORY = "rule_based"
DISPLAY_NAME = "ルールベース (定石)"
DESCRIPTION = (
    "短い定石列に乗っているあいだはそれに従い、外れたら位置評価に切り替える。"
    "対局中に定石列は増やさない。同点は a1 から h8 の座標順。"
    "対局中に学習済みモデルも OpenRouter も呼ばない。"
)

__all__ = [
    "BOOK_LINES",
    "CATEGORY",
    "DESCRIPTION",
    "DISPLAY_NAME",
    "SPECIMEN_ID",
    "choose_move",
]


def _squares(*names: str) -> tuple[Square, ...]:
    return tuple(Square.parse(name) for name in names)


# 虎・牛・鼠。座標は a1 が黒から見て左下。対局中に増やさない。
BOOK_LINES: tuple[tuple[Square, ...], ...] = (
    _squares("f5", "d6", "c3", "d3", "c4"),
    _squares("f5", "f6", "e6", "d6", "c5"),
    _squares("f5", "f4", "e3", "f6", "d3"),
)


def _apply_symmetry(square: Square, rotations: int, mirrored: bool) -> Square:
    """90 度回転を rotations 回したあと、必要なら左右反転する。"""
    file, rank = square.file, square.rank
    last = BOARD_SIZE - 1
    for _ in range(rotations):
        file, rank = rank, last - file
    if mirrored:
        file = last - file
    return Square(file=file, rank=rank)


def _d4_transforms() -> tuple[dict[Square, Square], ...]:
    """盤の 8 対称。定石座標から実盤座標へ。"""
    return tuple(
        {square: _apply_symmetry(square, rotations, mirrored) for square in all_squares()}
        for rotations in range(4)
        for mirrored in (False, True)
    )


_TRANSFORMS = _d4_transforms()


def _book_candidates(position: Position) -> set[Square]:
    if position.passed:
        return set()
    legal = frozenset(legal_places(position))
    if not legal:
        return set()
    placed = position.placed
    if not placed:
        start = initial_position()
        if position.board != start.board or position.side_to_move != start.side_to_move:
            return set()
    depth = len(placed)
    found: set[Square] = set()
    for transform in _TRANSFORMS:
        for line in BOOK_LINES:
            if depth >= len(line):
                continue
            prefix = tuple(transform[square] for square in line[:depth])
            if prefix != placed:
                continue
            nxt = transform[line[depth]]
            if nxt in legal:
                found.add(nxt)
    return found


def choose_move(position: Position, rng: Random | None = None) -> Place | None:
    """定石の次の合法手。無ければ位置評価と同一。"""
    candidates = _book_candidates(position)
    for square in legal_places(position):
        if square in candidates:
            return Place(square)
    return choose_positional(position, rng)
