"""カタログと戦略個体（ランダム・最多取り・位置評価）。"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from random import Random

import pytest

from reversi.agents.catalog import CatalogItem, choose_move as catalog_choose
from reversi.agents.catalog import get, items
from reversi.agents.most_flips import (
    CATEGORY as MOST_FLIPS_CATEGORY,
    DESCRIPTION as MOST_FLIPS_DESCRIPTION,
    DISPLAY_NAME as MOST_FLIPS_DISPLAY_NAME,
    SPECIMEN_ID as MOST_FLIPS_ID,
    choose_move as choose_most_flips,
)
from reversi.agents.position_table import POSITION_SCORES, score_at
from reversi.agents.positional import (
    CATEGORY as POSITIONAL_CATEGORY,
    DESCRIPTION as POSITIONAL_DESCRIPTION,
    DISPLAY_NAME as POSITIONAL_DISPLAY_NAME,
    SPECIMEN_ID as POSITIONAL_ID,
    choose_move as choose_positional,
    own_stone_score,
)
from reversi.agents.random_uniform import (
    CATEGORY,
    DESCRIPTION,
    DISPLAY_NAME,
    SPECIMEN_ID,
    choose_move,
)
from reversi.engine.board import Board, Color, Square, Stone, empty_board
from reversi.engine.rules import (
    Place,
    Position,
    apply_place,
    flips_for,
    initial_position,
    legal_places,
)

_JAPANESE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
_FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "torch",
        "tensorflow",
        "sklearn",
        "onnx",
        "joblib",
        "keras",
        "openrouter",
        "wthor",
    }
)


def _almost_full_white_with_black_on_b1() -> Position:
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
    return Position(board, Color.BLACK)


def _both_sides_cannot_place() -> Position:
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
    return Position(board, Color.BLACK)


def _module_source(name: str) -> str:
    path = Path(__file__).resolve().parents[1] / "src" / "reversi" / "agents" / name
    return path.read_text(encoding="utf-8")


def _imported_roots(source: str) -> set[str]:
    tree = ast.parse(source)
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_catalog_lists_random_uniform_specimen() -> None:
    listed = items()
    assert listed
    ids = [item.specimen_id for item in listed]
    assert len(ids) == len(set(ids))
    assert all(isinstance(item, CatalogItem) for item in listed)
    matches = [item for item in listed if item.display_name == "ランダム (一様)"]
    assert len(matches) >= 1
    item = matches[0]
    assert item.specimen_id == SPECIMEN_ID
    assert item.specimen_id
    assert item.category == "random"
    assert item.category == CATEGORY
    assert item.display_name == DISPLAY_NAME
    assert item.description == DESCRIPTION
    assert item.description.strip()
    assert _JAPANESE.search(item.description)


def test_catalog_selects_by_specimen_id_not_category() -> None:
    item = get(SPECIMEN_ID)
    assert item.specimen_id == SPECIMEN_ID
    assert item.category == "random"
    with pytest.raises(KeyError):
        get("random")
    with pytest.raises(KeyError):
        get("missing-specimen")


def test_random_uniform_picks_one_legal_place_uniformly() -> None:
    position = initial_position()
    places = legal_places(position)
    assert places

    class Picker(Random):
        def __init__(self) -> None:
            super().__init__()
            self.seq: tuple[Square, ...] | None = None

        def choice(self, seq: tuple[Square, ...]) -> Square:
            self.seq = tuple(seq)
            return seq[1]

    rng = Picker()
    move = choose_move(position, rng)
    assert rng.seq == places
    assert move == Place(places[1])
    assert move.square in places


def test_random_uniform_covers_all_opening_legal_places() -> None:
    position = initial_position()
    expected = set(legal_places(position))
    seen: set[Square] = set()
    rng = Random(0)
    for _ in range(200):
        move = choose_move(position, rng)
        assert move is not None
        assert move.square in expected
        seen.add(move.square)
    assert seen == expected


def test_random_does_not_move_when_no_legal_places() -> None:
    assert legal_places(_almost_full_white_with_black_on_b1()) == ()
    assert choose_move(_almost_full_white_with_black_on_b1()) is None
    assert legal_places(_both_sides_cannot_place()) == ()
    assert choose_move(_both_sides_cannot_place()) is None


def test_catalog_dispatches_random_uniform_by_specimen_id() -> None:
    from reversi.agents import choose_move as package_choose

    position = initial_position()
    rng = Random(1)
    from_catalog = catalog_choose(SPECIMEN_ID, position, rng)
    rng = Random(1)
    from_module = choose_move(position, rng)
    rng = Random(1)
    from_package = package_choose(SPECIMEN_ID, position, rng)
    assert from_catalog == from_module
    assert from_package == from_catalog
    assert from_catalog is not None
    with pytest.raises(KeyError):
        catalog_choose("random", position)
    with pytest.raises(KeyError):
        package_choose("random", position)


def test_catalog_listed_specimens_match_choosers() -> None:
    listed_ids = [item.specimen_id for item in items()]
    assert listed_ids
    assert len(listed_ids) == len(set(listed_ids))
    position = initial_position()
    for specimen_id in listed_ids:
        get(specimen_id)
        catalog_choose(specimen_id, position, Random(0))


def test_random_uniform_source_does_not_reference_wthor_or_models() -> None:
    for filename in ("random_uniform.py", "catalog.py"):
        source = _module_source(filename)
        roots = _imported_roots(source)
        assert roots.isdisjoint(_FORBIDDEN_IMPORT_ROOTS)
        assert "wthor" not in roots
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                lowered = node.value.lower()
                assert "ffothello.org" not in lowered
                assert ".wtb" not in lowered


def _item_by_display_name(name: str) -> CatalogItem:
    matches = [item for item in items() if item.display_name == name]
    assert len(matches) == 1
    return matches[0]


_STONE = {
    ".": Stone.EMPTY,
    "B": Stone.BLACK,
    "W": Stone.WHITE,
}


def _position_from_rank8_rows(rows: tuple[str, ...], side: Color) -> Position:
    assert len(rows) == 8 and all(len(row) == 8 for row in rows)
    cells = tuple(tuple(_STONE[ch] for ch in row) for row in reversed(rows))
    return Position(Board(cells), side)

# a1 は 1 枚、d2 は 2 枚裏返す。角 a1 の位置点は中央より高い。
_CORNER_VS_TWO_FLIPS = (
    "........",
    "........",
    "........",
    "...B....",
    "...W....",
    "...W....",
    "........",
    ".WB.....",
)


def test_catalog_lists_most_flips_and_positional() -> None:
    most = _item_by_display_name("ルールベース (最多取り)")
    pos = _item_by_display_name("ルールベース (位置評価)")
    assert most.specimen_id == MOST_FLIPS_ID == "most_flips"
    assert pos.specimen_id == POSITIONAL_ID == "positional"
    assert most.category == pos.category == "rule_based"
    assert most.category == MOST_FLIPS_CATEGORY
    assert pos.category == POSITIONAL_CATEGORY
    assert most.display_name == MOST_FLIPS_DISPLAY_NAME
    assert pos.display_name == POSITIONAL_DISPLAY_NAME
    assert most.display_name != pos.display_name
    assert most.description == MOST_FLIPS_DESCRIPTION
    assert pos.description == POSITIONAL_DESCRIPTION
    assert most.description.strip() and pos.description.strip()
    assert most.description != pos.description
    assert _JAPANESE.search(most.description)
    assert _JAPANESE.search(pos.description)
    assert get(MOST_FLIPS_ID) == most
    assert get(POSITIONAL_ID) == pos
    with pytest.raises(KeyError):
        get("rule_based")


def test_most_flips_picks_max_opponent_flips_not_placed_stone() -> None:
    position = _position_from_rank8_rows(_CORNER_VS_TWO_FLIPS, Color.BLACK)
    places = legal_places(position)
    assert Square.parse("a1") in places
    assert Square.parse("d2") in places
    counts = {
        square.algebraic: len(flips_for(position.board, square, Color.BLACK))
        for square in places
    }
    assert counts["a1"] == 1
    assert counts["d2"] == 2
    assert max(counts.values()) == counts["d2"]
    move = choose_most_flips(position)
    assert move == Place(Square.parse("d2"))
    # 置いた石を足すと全合法手に +1 されるだけなので、比較は裏返し数そのもの。
    assert counts[move.square.algebraic] == max(counts.values())
    via_catalog = catalog_choose(MOST_FLIPS_ID, position)
    assert via_catalog == move


def test_most_flips_tie_breaks_a1_to_h8_order() -> None:
    position = initial_position()
    places = legal_places(position)
    counts = [len(flips_for(position.board, square, Color.BLACK)) for square in places]
    assert counts and len(set(counts)) == 1
    assert [square.algebraic for square in places][0] == "d3"
    move = choose_most_flips(position)
    assert move == Place(Square.parse("d3"))
    assert choose_most_flips(position, Random(99)) == move


def test_most_flips_does_not_move_when_no_legal_places() -> None:
    assert choose_most_flips(_almost_full_white_with_black_on_b1()) is None
    assert choose_most_flips(_both_sides_cannot_place()) is None


def test_position_table_is_fixed_8x8_matching_engine_coordinates() -> None:
    expected = (
        (100, -20, 10, 5, 5, 10, -20, 100),
        (-20, -50, -2, -2, -2, -2, -50, -20),
        (10, -2, -1, -1, -1, -1, -2, 10),
        (5, -2, -1, -1, -1, -1, -2, 5),
        (5, -2, -1, -1, -1, -1, -2, 5),
        (10, -2, -1, -1, -1, -1, -2, 10),
        (-20, -50, -2, -2, -2, -2, -50, -20),
        (100, -20, 10, 5, 5, 10, -20, 100),
    )
    assert POSITION_SCORES == expected
    assert isinstance(POSITION_SCORES, tuple)
    assert all(isinstance(row, tuple) for row in POSITION_SCORES)
    assert score_at(Square.parse("a1")) == 100
    assert score_at(Square.parse("h1")) == 100
    assert score_at(Square.parse("a8")) == 100
    assert score_at(Square.parse("h8")) == 100
    assert score_at(Square.parse("b2")) == -50
    assert score_at(Square.parse("a1")) == POSITION_SCORES[0][0]
    assert score_at(Square.parse("h8")) == POSITION_SCORES[7][7]
    snapshot = tuple(tuple(row) for row in POSITION_SCORES)
    position = initial_position()
    choose_positional(position)
    choose_positional(_position_from_rank8_rows(_CORNER_VS_TWO_FLIPS, Color.BLACK))
    assert POSITION_SCORES == snapshot == expected


def test_positional_maximizes_own_stone_score_after_place() -> None:
    position = _position_from_rank8_rows(_CORNER_VS_TWO_FLIPS, Color.BLACK)
    places = legal_places(position)
    scored = {
        square.algebraic: own_stone_score(
            apply_place(position.board, square, Color.BLACK), Color.BLACK
        )
        for square in places
    }
    assert scored["a1"] > scored["d2"]
    move = choose_positional(position)
    assert move == Place(Square.parse("a1"))
    assert scored[move.square.algebraic] == max(scored.values())
    most = choose_most_flips(position)
    assert most == Place(Square.parse("d2"))
    assert most != move
    via_catalog = catalog_choose(POSITIONAL_ID, position)
    assert via_catalog == move


def test_positional_tie_breaks_a1_to_h8_order() -> None:
    position = initial_position()
    places = legal_places(position)
    scores = [
        own_stone_score(apply_place(position.board, square, Color.BLACK), Color.BLACK)
        for square in places
    ]
    assert scores and len(set(scores)) == 1
    move = choose_positional(position)
    assert move == Place(places[0])
    assert move == Place(Square.parse("d3"))
    assert choose_positional(position, Random(0)) == move


def test_positional_does_not_move_when_no_legal_places() -> None:
    assert choose_positional(_almost_full_white_with_black_on_b1()) is None
    assert choose_positional(_both_sides_cannot_place()) is None


def test_most_flips_and_positional_source_does_not_call_models() -> None:
    for filename in (
        "most_flips.py",
        "positional.py",
        "position_table.py",
        "catalog.py",
    ):
        source = _module_source(filename)
        roots = _imported_roots(source)
        assert roots.isdisjoint(_FORBIDDEN_IMPORT_ROOTS)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                lowered = node.value.lower()
                assert "ffothello.org" not in lowered
                assert ".wtb" not in lowered
                assert "openrouter.ai" not in lowered

