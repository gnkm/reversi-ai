"""石数と公式スコア。引き分けは 32–32。空きは勝者へ加算する。"""

from __future__ import annotations

from dataclasses import dataclass

from reversi.engine.board import BOARD_SIZE, Board, Stone

BOARD_CELLS = BOARD_SIZE * BOARD_SIZE


@dataclass(frozen=True, slots=True)
class Score:
    """黒と白の点数。"""

    black: int
    white: int


@dataclass(frozen=True, slots=True)
class StoneCounts:
    """盤上の内訳。"""

    black: int
    white: int
    empty: int


def stone_counts(board: Board) -> StoneCounts:
    black = 0
    white = 0
    empty = 0
    for row in board.cells:
        for stone in row:
            if stone is Stone.BLACK:
                black += 1
            elif stone is Stone.WHITE:
                white += 1
            else:
                empty += 1
    return StoneCounts(black=black, white=white, empty=empty)


def official_score(board: Board) -> Score:
    """終局の公式スコア。石数が同じなら 32–32。多い側に空きを足す。"""
    counts = stone_counts(board)
    if counts.black > counts.white:
        return Score(black=counts.black + counts.empty, white=counts.white)
    if counts.white > counts.black:
        return Score(black=counts.black, white=counts.white + counts.empty)
    return Score(black=BOARD_CELLS // 2, white=BOARD_CELLS // 2)
