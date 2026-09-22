"""対局エンジンの規則: 初期配置・座標・合法手・裏返し・パス・終局・公式スコア。"""

from __future__ import annotations

import pytest

from reversi.engine.board import Board, Color, Square, Stone, empty_board, initial_board
from reversi.engine.rules import (
    IllegalMoveError,
    PassMove,
    Place,
    Position,
    count_places,
    flips_for,
    initial_position,
    is_over,
    legal_moves,
    legal_places,
    pass_is_legal,
    play,
)
from reversi.engine.score import official_score, stone_counts

_STONE = {
    ".": Stone.EMPTY,
    "B": Stone.BLACK,
    "W": Stone.WHITE,
}


def board_from_diagram(diagram: str) -> Board:
    """上段が 8 行目の 8×8 図。`.` / `B` / `W`。行番号とファイル見出しは無視する。"""
    rows: list[str] = []
    for raw in diagram.strip().splitlines():
        line = raw.strip()
        if not line or line[0] in "aA":
            continue
        parts = line.split()
        if parts[0] in "12345678":
            cells = parts[1]
        else:
            cells = parts[0]
        rows.append(cells)
    if len(rows) != 8 or any(len(row) != 8 for row in rows):
        raise AssertionError(f"8×8 の図が必要です: {rows!r}")
    cells = tuple(
        tuple(_STONE[ch] for ch in rank_line) for rank_line in reversed(rows)
    )
    return Board(cells)


def algebraic_set(squares: tuple[Square, ...]) -> set[str]:
    return {square.algebraic for square in squares}


def test_initial_placement_and_black_to_move() -> None:
    position = initial_position()
    board = position.board
    assert board.stone_at(Square.parse("d4")) is Stone.WHITE
    assert board.stone_at(Square.parse("e5")) is Stone.WHITE
    assert board.stone_at(Square.parse("e4")) is Stone.BLACK
    assert board.stone_at(Square.parse("d5")) is Stone.BLACK
    assert position.side_to_move is Color.BLACK
    occupied = [
        square.algebraic
        for square in (
            Square.parse("d4"),
            Square.parse("e5"),
            Square.parse("e4"),
            Square.parse("d5"),
        )
    ]
    assert occupied == ["d4", "e5", "e4", "d5"]
    counts = stone_counts(initial_board())
    assert counts.black == 2
    assert counts.white == 2
    assert counts.empty == 60


def test_a1_is_bottom_left_from_black() -> None:
    a1 = Square.parse("a1")
    h1 = Square.parse("h1")
    a8 = Square.parse("a8")
    assert a1.file == 0 and a1.rank == 0
    assert a1.algebraic == "a1"
    assert h1.file == 7 and h1.rank == 0
    assert a8.file == 0 and a8.rank == 7
    # 黒から見て近くが 1 行、左が a。白側へ向かうとランクが増える。
    assert a1.rank < a8.rank
    assert a1.file < h1.file
    board = initial_board()
    # 黒の手前側（1–4 行）に白 d4、奥側（5 行）に白 e5。
    assert board.stone_at(Square.parse("d4")).value == "white"
    assert Square.parse("d4").rank < Square.parse("d5").rank


def test_initial_legal_moves() -> None:
    places = legal_places(initial_position())
    assert algebraic_set(places) == {"c4", "d3", "e6", "f5"}
    assert not pass_is_legal(initial_position())
    assert not is_over(initial_position())
    assert all(isinstance(move, Place) for move in legal_moves(initial_position()))


def test_legal_move_must_flip_at_least_one_opponent() -> None:
    position = initial_position()
    empty = Square.parse("a1")
    occupied = Square.parse("d4")
    assert position.board.stone_at(empty) is Stone.EMPTY
    assert flips_for(position.board, empty, Color.BLACK) == ()
    with pytest.raises(IllegalMoveError):
        play(position, Place(empty))
    with pytest.raises(IllegalMoveError):
        play(position, Place(occupied))
    with pytest.raises(IllegalMoveError):
        play(position, PassMove())


def test_place_flips_all_sandwiched_discs_in_a_line() -> None:
    board = board_from_diagram(
        """
        8 ........
        7 ........
        6 ........
        5 ........
        4 ..BWW...
        3 ........
        2 ........
        1 ........
        """
    )
    position = Position(board, Color.BLACK)
    result = play(position, Place(Square.parse("f4")))
    assert result.board.stone_at(Square.parse("f4")) is Stone.BLACK
    assert result.board.stone_at(Square.parse("d4")) is Stone.BLACK
    assert result.board.stone_at(Square.parse("e4")) is Stone.BLACK
    assert result.board.stone_at(Square.parse("c4")) is Stone.BLACK
    assert result.side_to_move is Color.WHITE


def test_no_chained_extra_flips() -> None:
    """置いたマスからの挟みだけ裏返す。裏返した石が新たに挟んでも連鎖しない。"""
    board = board_from_diagram(
        """
        8 ........
        7 ........
        6 ...B....
        5 ...W....
        4 ...WB...
        3 ........
        2 ........
        1 ........
        """
    )
    position = Position(board, Color.BLACK)
    result = play(position, Place(Square.parse("c4")))
    assert result.board.stone_at(Square.parse("c4")) is Stone.BLACK
    assert result.board.stone_at(Square.parse("d4")) is Stone.BLACK
    assert result.board.stone_at(Square.parse("e4")) is Stone.BLACK
    # d5 は d4 が裏返ったあとに d6 と挟めるが、着手マス c4 からの直線ではない。
    assert result.board.stone_at(Square.parse("d5")) is Stone.WHITE
    assert result.board.stone_at(Square.parse("d6")) is Stone.BLACK


def test_flips_in_all_eight_directions() -> None:
    board = board_from_diagram(
        """
        8 ........
        7 .B.B.B..
        6 ..WWW...
        5 .BW.WB..
        4 ..WWW...
        3 .B.B.B..
        2 ........
        1 ........
        """
    )
    position = Position(board, Color.BLACK)
    result = play(position, Place(Square.parse("d5")))
    for square in (
        "c4",
        "d4",
        "e4",
        "c5",
        "e5",
        "c6",
        "d6",
        "e6",
    ):
        assert result.board.stone_at(Square.parse(square)) is Stone.BLACK
    assert result.board.stone_at(Square.parse("d5")) is Stone.BLACK


def test_pass_only_when_side_has_no_place() -> None:
    # a1 のみ空。b1 が黒、他は白。黒には合法手が無く、白は a1 に打てる。
    board = empty_board().replacing(
        {
            Square.parse("b1"): Stone.BLACK,
            **{
                Square(file=file, rank=rank): Stone.WHITE
                for rank in range(8)
                for file in range(8)
                if not (file == 0 and rank == 0) and not (file == 1 and rank == 0)
            },
        }
    )
    black_to_move = Position(board, Color.BLACK)
    white_to_move = Position(board, Color.WHITE)
    assert legal_places(black_to_move) == ()
    assert pass_is_legal(black_to_move)
    assert legal_moves(black_to_move) == (PassMove(),)
    after_pass = play(black_to_move, PassMove())
    assert after_pass.board == board
    assert after_pass.side_to_move is Color.WHITE
    assert algebraic_set(legal_places(white_to_move)) == {"a1"}
    assert not pass_is_legal(white_to_move)
    with pytest.raises(IllegalMoveError):
        play(white_to_move, PassMove())


def test_game_over_when_both_cannot_place_even_if_empty_remain() -> None:
    board = empty_board().replacing(
        {
            Square.parse("a1"): Stone.EMPTY,
            Square.parse("h8"): Stone.EMPTY,
            **{
                Square(file=file, rank=rank): Stone.WHITE
                for rank in range(8)
                for file in range(8)
                if (file, rank) not in {(0, 0), (7, 7)}
            },
        }
    )
    position = Position(board, Color.BLACK)
    assert legal_places(position) == ()
    assert not pass_is_legal(position)
    assert is_over(position)
    assert legal_moves(position) == ()
    with pytest.raises(IllegalMoveError):
        play(position, PassMove())
    counts = stone_counts(board)
    assert counts.empty == 2
    score = official_score(board)
    assert score.white == 64
    assert score.black == 0


def test_official_score_adds_empty_to_winner() -> None:
    # 黒 34・白 29・空 1 → 黒勝ち 35–29
    updates = {
        Square(file=file, rank=rank): Stone.BLACK
        for rank in range(8)
        for file in range(8)
    }
    # 白 29 個
    whites = list(
        Square(file=file, rank=rank)
        for rank in range(8)
        for file in range(8)
    )[:29]
    for square in whites:
        updates[square] = Stone.WHITE
    empty = Square.parse("h8")
    updates[empty] = Stone.EMPTY
    # 残りは黒。64-29-1=34 黒。
    board = empty_board().replacing(updates)
    counts = stone_counts(board)
    assert (counts.black, counts.white, counts.empty) == (34, 29, 1)
    score = official_score(board)
    assert score.black == 35
    assert score.white == 29


def test_official_score_draw_is_32_32() -> None:
    updates = {
        Square(file=file, rank=rank): Stone.BLACK if file < 4 else Stone.WHITE
        for rank in range(8)
        for file in range(8)
    }
    board = empty_board().replacing(updates)
    counts = stone_counts(board)
    assert counts.black == 32
    assert counts.white == 32
    assert official_score(board).black == 32
    assert official_score(board).white == 32

    # 石数が同じで空きがある引き分けも 32–32
    tied_with_empty = empty_board().replacing(
        {
            Square.parse("a1"): Stone.BLACK,
            Square.parse("b1"): Stone.BLACK,
            Square.parse("a2"): Stone.WHITE,
            Square.parse("b2"): Stone.WHITE,
        }
    )
    counts = stone_counts(tied_with_empty)
    assert counts.black == counts.white
    assert counts.empty > 0
    score = official_score(tied_with_empty)
    assert score.black == 32
    assert score.white == 32


def test_count_places_matches_legal_places() -> None:
    position = initial_position()
    for _ in range(12):
        assert count_places(position.board, Color.BLACK) == len(
            legal_places(Position(position.board, Color.BLACK))
        )
        assert count_places(position.board, Color.WHITE) == len(
            legal_places(Position(position.board, Color.WHITE))
        )
        places = legal_places(position)
        if not places:
            if is_over(position):
                break
            position = play(position, PassMove())
            continue
        position = play(position, Place(places[0]))


def test_opening_place_uniquely_flips_one_disc() -> None:
    position = initial_position()
    next_position = play(position, Place(Square.parse("c4")))
    assert next_position.board.stone_at(Square.parse("c4")) is Stone.BLACK
    assert next_position.board.stone_at(Square.parse("d4")) is Stone.BLACK
    assert next_position.board.stone_at(Square.parse("e4")) is Stone.BLACK
    assert next_position.board.stone_at(Square.parse("d5")) is Stone.BLACK
    assert next_position.board.stone_at(Square.parse("e5")) is Stone.WHITE
    assert next_position.side_to_move is Color.WHITE
