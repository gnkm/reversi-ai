"""盤の入力符号化: 同じ盤からは同じ明示的入力。engine は encode を読まない。"""

from __future__ import annotations

import ast
from pathlib import Path

from reversi.encode import VECTOR_SIZE, BoardInput, encode
from reversi.engine.board import Square, Stone, empty_board, initial_board


def _engine_source_files() -> tuple[Path, ...]:
    engine_dir = Path(__file__).resolve().parents[1] / "src" / "reversi" / "engine"
    return tuple(sorted(engine_dir.glob("*.py")))


def test_same_board_yields_same_vector() -> None:
    first = initial_board()
    second = initial_board()
    assert first is not second
    assert encode(first) == encode(second)
    assert encode(first).as_vector() == encode(second).as_vector()


def test_initial_board_encoding_is_explicit() -> None:
    encoded = encode(initial_board())
    d4 = Square.parse("d4")
    e4 = Square.parse("e4")
    d5 = Square.parse("d5")
    e5 = Square.parse("e5")

    assert encoded.white[d4.rank][d4.file] == 1
    assert encoded.white[e5.rank][e5.file] == 1
    assert encoded.black[e4.rank][e4.file] == 1
    assert encoded.black[d5.rank][d5.file] == 1

    occupied = {d4.algebraic, e4.algebraic, d5.algebraic, e5.algebraic}
    for rank in range(8):
        for file in range(8):
            square = Square(file=file, rank=rank)
            if square.algebraic in occupied:
                assert encoded.empty[rank][file] == 0
            else:
                assert encoded.empty[rank][file] == 1
                assert encoded.black[rank][file] == 0
                assert encoded.white[rank][file] == 0

    vector = encoded.as_vector()
    assert len(vector) == VECTOR_SIZE
    assert vector.count(1) == 64
    # 黒平面（offset 0）に e4・d5、白平面（offset 64）に d4・e5。
    assert vector[e4.rank * 8 + e4.file] == 1
    assert vector[d5.rank * 8 + d5.file] == 1
    assert vector[64 + d4.rank * 8 + d4.file] == 1
    assert vector[64 + e5.rank * 8 + e5.file] == 1


def test_a1_is_first_cell_in_each_plane() -> None:
    board = empty_board().replacing({Square.parse("a1"): Stone.BLACK})
    encoded = encode(board)
    assert encoded.black[0][0] == 1
    assert encoded.as_vector()[0] == 1
    board = empty_board().replacing({Square.parse("h8"): Stone.WHITE})
    encoded = encode(board)
    assert encoded.white[7][7] == 1
    assert encoded.as_vector()[64 + 63] == 1


def test_different_boards_yield_different_inputs() -> None:
    assert encode(empty_board()) != encode(initial_board())
    moved = initial_board().replacing({Square.parse("c4"): Stone.BLACK})
    assert encode(moved) != encode(initial_board())


def test_each_square_is_one_hot() -> None:
    encoded = encode(initial_board())
    for rank in range(8):
        for file in range(8):
            total = (
                encoded.black[rank][file]
                + encoded.white[rank][file]
                + encoded.empty[rank][file]
            )
            assert total == 1


def test_engine_does_not_import_encode() -> None:
    for path in _engine_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "reversi.encode"
                    assert not alias.name.startswith("reversi.encode.")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert module != "reversi.encode"
                assert not module.startswith("reversi.encode.")
                if module == "reversi":
                    assert all(alias.name != "encode" for alias in node.names)


def test_board_input_is_hashable() -> None:
    encoded = encode(initial_board())
    assert hash(encoded) == hash(BoardInput(
        black=encoded.black,
        white=encoded.white,
        empty=encoded.empty,
    ))
