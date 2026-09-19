"""ML / RL / NN が共有する盤の入力符号化。engine は読まない。"""

from __future__ import annotations

from dataclasses import dataclass

from reversi.engine.board import BOARD_SIZE, Board, Stone

PLANE_COUNT = 3
VECTOR_SIZE = PLANE_COUNT * BOARD_SIZE * BOARD_SIZE

type Occupancy = tuple[tuple[int, ...], ...]

__all__ = [
    "PLANE_COUNT",
    "VECTOR_SIZE",
    "BoardInput",
    "encode",
]


def _occupancy(board: Board, stone: Stone) -> Occupancy:
    return tuple(
        tuple(1 if cell is stone else 0 for cell in row) for row in board.cells
    )


def _require_plane(plane: Occupancy, name: str) -> None:
    if len(plane) != BOARD_SIZE or any(len(row) != BOARD_SIZE for row in plane):
        raise ValueError(f"{name} の形が 8×8 ではありません")
    if any(cell not in (0, 1) for row in plane for cell in row):
        raise ValueError(f"{name} の値は 0 または 1 です")


@dataclass(frozen=True, slots=True)
class BoardInput:
    """3×8×8 の 0/1。座標は `board.cells` と同じ `[rank][file]`（a1 が `[0][0]`）。"""

    black: Occupancy
    white: Occupancy
    empty: Occupancy

    def __post_init__(self) -> None:
        _require_plane(self.black, "black")
        _require_plane(self.white, "white")
        _require_plane(self.empty, "empty")

    @property
    def planes(self) -> tuple[Occupancy, Occupancy, Occupancy]:
        return (self.black, self.white, self.empty)

    def as_vector(self) -> tuple[int, ...]:
        """黒・白・空の順。各平面は rank が先（a1 が平面の先頭）。"""
        return tuple(cell for plane in self.planes for row in plane for cell in row)


def encode(board: Board) -> BoardInput:
    """同じ盤からは同じ入力になる。手番は含めない。"""
    return BoardInput(
        black=_occupancy(board, Stone.BLACK),
        white=_occupancy(board, Stone.WHITE),
        empty=_occupancy(board, Stone.EMPTY),
    )
