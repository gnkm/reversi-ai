"""盤・マス・初期配置・代数表記。a1 は黒から見て左下。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

BOARD_SIZE = 8
FILES = "abcdefgh"
RANKS = "12345678"


class Stone(StrEnum):
    """1 マスの石。"""

    EMPTY = "empty"
    BLACK = "black"
    WHITE = "white"


class Color(StrEnum):
    """手番の色。黒が先手。"""

    BLACK = "black"
    WHITE = "white"

    @property
    def opponent(self) -> Color:
        if self is Color.BLACK:
            return Color.WHITE
        return Color.BLACK

    @property
    def stone(self) -> Stone:
        return Stone(self.value)


@dataclass(frozen=True, slots=True, order=True)
class Square:
    """0 始まりのファイル（a=0）とランク（1=0）。a1 が (0, 0)。"""

    file: int
    rank: int

    def __post_init__(self) -> None:
        if not 0 <= self.file < BOARD_SIZE or not 0 <= self.rank < BOARD_SIZE:
            raise ValueError("マスが盤外です")

    @property
    def algebraic(self) -> str:
        return f"{FILES[self.file]}{RANKS[self.rank]}"

    @classmethod
    def parse(cls, text: str) -> Square:
        if len(text) != 2 or text[0] not in FILES or text[1] not in RANKS:
            raise ValueError(f"代数表記が不正です: {text!r}")
        return cls(file=FILES.index(text[0]), rank=RANKS.index(text[1]))


@dataclass(frozen=True, slots=True)
class Board:
    """8×8。`cells[rank-1][file-a]`。"""

    cells: tuple[tuple[Stone, ...], ...]

    def __post_init__(self) -> None:
        if len(self.cells) != BOARD_SIZE:
            raise ValueError("盤の行数が 8 ではありません")
        if any(len(row) != BOARD_SIZE for row in self.cells):
            raise ValueError("盤の列数が 8 ではありません")

    def stone_at(self, square: Square) -> Stone:
        return self.cells[square.rank][square.file]

    def replacing(self, updates: Mapping[Square, Stone]) -> Board:
        rows = list(self.cells)
        changed: dict[int, list[Stone]] = {}
        for square, stone in updates.items():
            row = changed.get(square.rank)
            if row is None:
                row = list(self.cells[square.rank])
                changed[square.rank] = row
            row[square.file] = stone
        for rank, row in changed.items():
            rows[rank] = tuple(row)
        return Board(tuple(rows))


# 64 マスは不変。探索中に Square を都度作らない。
SQUARES: tuple[tuple[Square, ...], ...] = tuple(
    tuple(Square(file=file, rank=rank) for file in range(BOARD_SIZE))
    for rank in range(BOARD_SIZE)
)
_ALL_SQUARES: tuple[Square, ...] = tuple(square for row in SQUARES for square in row)


def all_squares() -> tuple[Square, ...]:
    return _ALL_SQUARES


def empty_board() -> Board:
    blank = tuple(Stone.EMPTY for _ in range(BOARD_SIZE))
    return Board(tuple(blank for _ in range(BOARD_SIZE)))


def initial_board() -> Board:
    """白 d4・e5、黒 e4・d5。"""
    return empty_board().replacing(
        {
            Square.parse("d4"): Stone.WHITE,
            Square.parse("e5"): Stone.WHITE,
            Square.parse("e4"): Stone.BLACK,
            Square.parse("d5"): Stone.BLACK,
        }
    )
