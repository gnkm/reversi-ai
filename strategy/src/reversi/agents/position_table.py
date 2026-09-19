"""位置評価の点数表。対局中は変わらない。座標はエンジンと同じ（a1 が [0][0]）。"""

from __future__ import annotations

from reversi.engine.board import BOARD_SIZE, Square

# 行は rank 1→8、列は file a→h。SRS-FUN-025 と同一（表の 1 行目が rank 8）。
POSITION_SCORES: tuple[tuple[int, ...], ...] = (
    (100, -20, 10, 5, 5, 10, -20, 100),
    (-20, -50, -2, -2, -2, -2, -50, -20),
    (10, -2, 1, -1, -1, 1, -2, 10),
    (5, -2, -1, 0, 0, -1, -2, 5),
    (5, -2, -1, 0, 0, -1, -2, 5),
    (10, -2, 1, -1, -1, 1, -2, 10),
    (-20, -50, -2, -2, -2, -2, -50, -20),
    (100, -20, 10, 5, 5, 10, -20, 100),
)

__all__ = [
    "POSITION_SCORES",
    "score_at",
]


def score_at(square: Square) -> int:
    """1 マスの点数。"""
    return POSITION_SCORES[square.rank][square.file]


def _check_table() -> None:
    if len(POSITION_SCORES) != BOARD_SIZE:
        raise ValueError("点数表の行数が 8 ではありません")
    if any(len(row) != BOARD_SIZE for row in POSITION_SCORES):
        raise ValueError("点数表の列数が 8 ではありません")


_check_table()
