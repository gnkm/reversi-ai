"""カタログと戦略個体（ランダム・最多取り・位置評価・ミニマックス・αβ・定石・機械学習・LightGBM・強化学習・ニューラルネットワーク・生成 AI）。"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from random import Random
from types import SimpleNamespace

import pytest

from reversi.agents import (
    alphabeta,
    chat_completions,
    extra_genai,
    jev,
    minimax,
    most_flips,
    opening,
    positional,
)
from reversi.agents.catalog import CatalogItem, get, items
from reversi.agents.catalog import choose_move as catalog_choose
from reversi.agents.position_table import POSITION_SCORES, score_at
from reversi.agents.random_uniform import (
    CATEGORY,
    DESCRIPTION,
    DISPLAY_NAME,
    SPECIMEN_ID,
    choose_move,
)
from reversi.encode import VECTOR_SIZE
from reversi.engine.board import (
    BOARD_SIZE,
    Board,
    Color,
    Square,
    Stone,
    all_squares,
    empty_board,
)
from reversi.engine.rules import (
    PassMove,
    Place,
    Position,
    apply_place,
    flips_for,
    initial_position,
    is_over,
    legal_moves,
    legal_places,
    pass_is_legal,
    play,
)
from reversi.engine.score import official_score, stone_counts

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


def test_catalog_descriptions_are_at_most_100_unicode_points() -> None:
    for item in items():
        assert item.description.strip(), item.specimen_id
        assert _JAPANESE.search(item.description), item.specimen_id
        assert len(item.description) <= 100, (item.specimen_id, len(item.description))


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
        if specimen_id == jev.SPECIMEN_ID or specimen_id.startswith("genai:"):
            continue
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
    assert most.specimen_id == most_flips.SPECIMEN_ID == "most_flips"
    assert pos.specimen_id == positional.SPECIMEN_ID == "positional"
    assert most.category == pos.category == "rule_based"
    assert most.category == most_flips.CATEGORY
    assert pos.category == positional.CATEGORY
    assert most.display_name == most_flips.DISPLAY_NAME
    assert pos.display_name == positional.DISPLAY_NAME
    assert most.display_name != pos.display_name
    assert most.description == most_flips.DESCRIPTION
    assert pos.description == positional.DESCRIPTION
    assert most.description.strip() and pos.description.strip()
    assert most.description != pos.description
    assert _JAPANESE.search(most.description)
    assert _JAPANESE.search(pos.description)
    assert get(most_flips.SPECIMEN_ID) == most
    assert get(positional.SPECIMEN_ID) == pos
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
    move = most_flips.choose_move(position)
    assert move == Place(Square.parse("d2"))
    # 置いた石を足すと全合法手に +1 されるだけなので、比較は裏返し数そのもの。
    assert counts[move.square.algebraic] == max(counts.values())
    via_catalog = catalog_choose(most_flips.SPECIMEN_ID, position)
    assert via_catalog == move


def test_most_flips_tie_breaks_a1_to_h8_order() -> None:
    position = initial_position()
    places = legal_places(position)
    counts = [len(flips_for(position.board, square, Color.BLACK)) for square in places]
    assert counts and len(set(counts)) == 1
    assert places[0].algebraic == "d3"
    move = most_flips.choose_move(position)
    assert move == Place(Square.parse("d3"))
    assert most_flips.choose_move(position, Random(99)) == move


def test_most_flips_does_not_move_when_no_legal_places() -> None:
    assert most_flips.choose_move(_almost_full_white_with_black_on_b1()) is None
    assert most_flips.choose_move(_both_sides_cannot_place()) is None


def test_position_table_is_fixed_8x8_matching_engine_coordinates() -> None:
    expected = (
        (100, -20, 10, 5, 5, 10, -20, 100),
        (-20, -50, -2, -2, -2, -2, -50, -20),
        (10, -2, 1, -1, -1, 1, -2, 10),
        (5, -2, -1, 0, 0, -1, -2, 5),
        (5, -2, -1, 0, 0, -1, -2, 5),
        (10, -2, 1, -1, -1, 1, -2, 10),
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
    assert score_at(Square.parse("c3")) == 1
    assert score_at(Square.parse("d4")) == 0
    assert score_at(Square.parse("c6")) == 1
    assert score_at(Square.parse("a1")) == POSITION_SCORES[0][0]
    assert score_at(Square.parse("h8")) == POSITION_SCORES[7][7]
    snapshot = tuple(tuple(row) for row in POSITION_SCORES)
    position = initial_position()
    positional.choose_move(position)
    positional.choose_move(_position_from_rank8_rows(_CORNER_VS_TWO_FLIPS, Color.BLACK))
    assert POSITION_SCORES == snapshot == expected


def test_positional_maximizes_own_stone_score_after_place() -> None:
    position = _position_from_rank8_rows(_CORNER_VS_TWO_FLIPS, Color.BLACK)
    places = legal_places(position)
    scored = {
        square.algebraic: positional.own_stone_score(
            apply_place(position.board, square, Color.BLACK), Color.BLACK
        )
        for square in places
    }
    assert scored["a1"] > scored["d2"]
    move = positional.choose_move(position)
    assert move == Place(Square.parse("a1"))
    assert scored[move.square.algebraic] == max(scored.values())
    most = most_flips.choose_move(position)
    assert most == Place(Square.parse("d2"))
    assert most != move
    via_catalog = catalog_choose(positional.SPECIMEN_ID, position)
    assert via_catalog == move


def test_positional_tie_breaks_a1_to_h8_order() -> None:
    position = initial_position()
    places = legal_places(position)
    scores = [
        positional.own_stone_score(
            apply_place(position.board, square, Color.BLACK), Color.BLACK
        )
        for square in places
    ]
    assert scores and len(set(scores)) == 1
    move = positional.choose_move(position)
    assert move == Place(places[0])
    assert move == Place(Square.parse("d3"))
    assert positional.choose_move(position, Random(0)) == move


def test_positional_does_not_move_when_no_legal_places() -> None:
    assert positional.choose_move(_almost_full_white_with_black_on_b1()) is None
    assert positional.choose_move(_both_sides_cannot_place()) is None


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


def test_catalog_lists_jev_generative_ai_specimen() -> None:
    item = _item_by_display_name("生成 AI (Jev)")
    assert item.specimen_id == jev.SPECIMEN_ID == "jev"
    assert item.category == jev.CATEGORY == "generative_ai"
    assert item.display_name == jev.DISPLAY_NAME
    assert item.description == jev.DESCRIPTION
    assert item.description.strip()
    assert _JAPANESE.search(item.description)
    assert "OpenRouter" in item.description
    assert "Jev" in item.description
    assert jev.MODEL_ID == "typesafe/jev-1.13"
    assert get(jev.SPECIMEN_ID) == item
    with pytest.raises(KeyError):
        get("generative_ai")


def test_jev_picks_legal_place_from_decisions_double(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    position = initial_position()
    places = legal_places(position)
    assert places

    def pick_second(_position, legal):
        return legal[1]

    monkeypatch.setattr(jev, "_call_openrouter", pick_second)
    move = jev.choose_move(position)
    assert move == Place(places[1])
    assert move.square in places
    via_catalog = catalog_choose(jev.SPECIMEN_ID, position)
    assert via_catalog == move


def test_jev_does_not_adopt_place_outside_legal_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    position = initial_position()
    places = legal_places(position)
    illegal = Square.parse("a1")
    assert illegal not in places

    def pick_illegal(_position, _legal):
        return illegal

    monkeypatch.setattr(jev, "_call_openrouter", pick_illegal)
    with pytest.raises(jev.ExternalModelError, match="合法手"):
        jev.choose_move(position)
    with pytest.raises(jev.ExternalModelError):
        catalog_choose(jev.SPECIMEN_ID, position)


def test_jev_call_failure_is_unplayable_not_a_legal_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    position = initial_position()

    def boom(_position, _legal):
        raise jev.ExternalModelError("試験用の失敗")

    monkeypatch.setattr(jev, "_call_openrouter", boom)
    with pytest.raises(jev.ExternalModelError, match="失敗"):
        jev.choose_move(position)


def test_jev_does_not_move_when_no_legal_places(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = {"n": 0}

    def should_not_run(_position, _legal):
        called["n"] += 1
        raise AssertionError("合法手が無い局面で OpenRouter を呼んではいけない")

    monkeypatch.setattr(jev, "_call_openrouter", should_not_run)
    assert jev.choose_move(_almost_full_white_with_black_on_b1()) is None
    assert jev.choose_move(_both_sides_cannot_place()) is None
    assert called["n"] == 0


def test_jev_skips_openrouter_when_one_legal_place(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = {"n": 0}

    def should_not_run(_position, _legal):
        called["n"] += 1
        raise AssertionError("合法手が 1 つのとき OpenRouter を呼んではいけない")

    monkeypatch.setattr(jev, "_call_openrouter", should_not_run)
    white_only = Position(_almost_full_white_with_black_on_b1().board, Color.WHITE)
    places = legal_places(white_only)
    assert len(places) == 1
    move = jev.choose_move(white_only)
    assert move == Place(places[0])
    assert called["n"] == 0


def test_jev_source_uses_jev_model_and_skips_wthor() -> None:
    source = _module_source("jev.py")
    assert "typesafe/jev-1.13" in source
    assert "https://openrouter.ai" in source
    assert "Choose exactly one legal Reversi" not in source
    assert "Place a stone on" not in source
    assert "more discs" not in source
    roots = _imported_roots(source)
    assert "wthor" not in roots
    assert "reversi" in roots or "openrouter" in roots
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"getenv", "putenv"}
        ):
            raise AssertionError("jev.py は環境変数から鍵を読んではいけない")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            lowered = node.value.lower()
            assert "ffothello.org" not in lowered
            assert ".wtb" not in lowered
            assert "openrouter_api_key" not in lowered


def _jev_parsed(
    *,
    corner: float = 0.0,
    mobility: float = 0.0,
    position: float = 0.0,
    material: float = 0.0,
    stage: str = "midgame",
) -> jev._Parsed:
    return jev._Parsed(
        noul={
            "corner_priority": corner,
            "mobility_priority": mobility,
            "position_priority": position,
        },
        material=material,
        stage={
            key: 1.0 if key == stage else 0.0
            for key in ("opening", "midgame", "endgame")
        },
    )


def _jev_choice_parsed(
    places: Sequence[Square],
    *,
    focused: str | None = None,
    confidence: float = 1.0,
) -> jev._ChoiceParsed:
    keys = [square.algebraic for square in places]
    if focused is None:
        each = 1.0 / float(len(keys))
        probabilities = dict.fromkeys(keys, each)
    else:
        probabilities = {key: 1.0 if key == focused else 0.0 for key in keys}
    return jev._ChoiceParsed(probabilities=probabilities, confidence=confidence)


def _disc_diff_after(position: Position, square: Square) -> int:
    after = apply_place(position.board, square, position.side_to_move)
    own = position.side_to_move.stone
    opp = position.side_to_move.opponent.stone
    total = 0
    for cell in all_squares():
        stone = after.stone_at(cell)
        if stone is own:
            total += 1
        elif stone is opp:
            total -= 1
    return total


def test_jev_combines_typed_answers_into_legal_place() -> None:
    position = initial_position()
    places = legal_places(position)
    spec = jev._load_spec()
    assert len(spec.questions) >= 2
    parsed = _jev_parsed(
        corner=0.2, mobility=0.5, position=0.1, material=0.4, stage="opening"
    )
    square = jev._select_square(position, places, parsed, spec)
    assert square in places
    assert square == places[0]
    assert square == Square.parse("d3")


def test_jev_composite_prefers_corner_when_priority_is_high() -> None:
    position = _position_from_rank8_rows(_CORNER_VS_TWO_FLIPS, Color.BLACK)
    places = legal_places(position)
    assert Square.parse("a1") in places
    spec = jev._load_spec()
    parsed = _jev_parsed(corner=1.0, stage="midgame")
    square = jev._select_square(position, places, parsed, spec)
    assert square == Square.parse("a1")
    assert square in places
    after_a1 = apply_place(position.board, Square.parse("a1"), Color.BLACK)
    after_d2 = apply_place(position.board, Square.parse("d2"), Color.BLACK)
    assert after_a1.stone_at(Square.parse("a1")) is Stone.BLACK
    assert after_d2.stone_at(Square.parse("a1")) is Stone.EMPTY


def test_jev_material_priority_picks_post_move_disc_lead() -> None:
    position = _position_from_rank8_rows(_CORNER_VS_TWO_FLIPS, Color.BLACK)
    places = legal_places(position)
    a1 = Square.parse("a1")
    d2 = Square.parse("d2")
    assert a1 in places and d2 in places
    assert _disc_diff_after(position, d2) > _disc_diff_after(position, a1)
    spec = jev._load_spec()
    square = jev._select_square(
        position, places, _jev_parsed(material=1.0, stage="endgame"), spec
    )
    assert square == d2
    assert square in places


def test_jev_selection_depends_on_post_move_evaluation() -> None:
    position = _position_from_rank8_rows(_CORNER_VS_TWO_FLIPS, Color.BLACK)
    places = legal_places(position)
    spec = jev._load_spec()
    corner = jev._select_square(position, places, _jev_parsed(corner=1.0), spec)
    material = jev._select_square(
        position, places, _jev_parsed(material=1.0, stage="endgame"), spec
    )
    assert corner == Square.parse("a1")
    assert material == Square.parse("d2")
    assert corner != material
    metrics = jev._after_metrics(position, places)
    assert metrics[corner].corners > metrics[material].corners
    assert metrics[material].material > metrics[corner].material
    one_ply = {
        square: (
            1.0 if square in jev._CORNERS else 0.0,
            float(len(flips_for(position.board, square, Color.BLACK))),
        )
        for square in places
    }
    assert one_ply[corner][0] == 1.0
    assert one_ply[material][1] > one_ply[corner][1]


def test_jev_questions_do_not_scale_with_legal_places() -> None:
    spec = jev._load_spec()
    opening = legal_places(initial_position())
    white_only = Position(_almost_full_white_with_black_on_b1().board, Color.WHITE)
    one = legal_places(white_only)
    assert len(opening) >= 2
    assert len(one) == 1
    assert len(spec.questions) >= 2
    names = set(spec.questions)
    assert names.isdisjoint(square.algebraic for square in opening)
    assert names.isdisjoint(square.algebraic for square in one)
    assert "move" not in names
    opening_state = jev._board_state(initial_position(), opening, spec)
    one_state = jev._board_state(white_only, one, spec)
    assert set(opening_state.keys()) == set(one_state.keys())


def test_jev_rejects_out_of_range_stage_probabilities() -> None:
    spec = jev._load_spec()
    answers = {
        "corner_priority": {"noul": 0.2},
        "mobility_priority": {"noul": 0.4},
        "position_priority": {"noul": 0.1},
        "material_importance": {"score": 1.0},
        "stage": {
            "type": "choice",
            "choice": "opening",
            "probabilities": {"opening": -0.5, "midgame": 0.5, "endgame": 1.0},
        },
    }
    with pytest.raises(jev.ExternalModelError, match="合成できません"):
        jev._answers_from_response(SimpleNamespace(answers=answers), spec)
    answers["stage"] = {
        "type": "choice",
        "choice": "opening",
        "probabilities": {"opening": 1.5, "midgame": 0.0, "endgame": 0.0},
    }
    with pytest.raises(jev.ExternalModelError, match="合成できません"):
        jev._answers_from_response(SimpleNamespace(answers=answers), spec)


def test_jev_combines_choice_and_code_into_legal_place() -> None:
    position = initial_position()
    places = legal_places(position)
    spec = jev._load_spec()
    assert spec.question_id
    parsed = _jev_choice_parsed(places)
    square = jev._select_square(position, places, parsed, spec)
    assert square in places
    assert square == places[0]
    assert square == Square.parse("d3")


def test_jev_margin_zero_matches_code_best_despite_fake_choice() -> None:
    position = initial_position()
    places = legal_places(position)
    spec = replace(jev._load_spec(), margin=0.0)
    stage = jev._stage_of(position.board, spec)
    metrics = jev._after_metrics(position, places, spec)
    scores = jev._code_scores(places, metrics, spec, stage)
    code_best = jev._best_square(places, scores)
    focused = places[1].algebraic
    assert focused != code_best.algebraic
    square = jev._select_square(
        position, places, _jev_choice_parsed(places, focused=focused), spec
    )
    assert square == code_best
    again = jev._select_square(position, places, _jev_choice_parsed(places), spec)
    assert again == code_best == Square.parse("d3")


def test_jev_choice_keys_are_shortlist_only() -> None:
    position = initial_position()
    places = legal_places(position)
    spec = jev._load_spec()
    stage = jev._stage_of(position.board, spec)
    metrics = jev._after_metrics(position, places, spec)
    scores = jev._code_scores(places, metrics, spec, stage)
    _best, shortlist = jev._shortlist(places, scores, spec)
    assert len(shortlist) >= 2
    assert len(shortlist) <= spec.shortlist_size
    assert set(shortlist) < set(places)
    lines = jev._place_lines(position, shortlist, spec)
    questions = jev._decision_questions(spec, lines)
    criteria = questions[spec.question_id]["criteria"]
    assert set(criteria) == {square.algebraic for square in shortlist}
    assert Square.parse("e6") in places
    assert "e6" not in criteria


def test_jev_low_confidence_returns_code_best() -> None:
    position = initial_position()
    places = legal_places(position)
    spec = jev._load_spec()
    stage = jev._stage_of(position.board, spec)
    metrics = jev._after_metrics(position, places, spec)
    scores = jev._code_scores(places, metrics, spec, stage)
    code_best = jev._best_square(places, scores)
    _best, shortlist = jev._shortlist(places, scores, spec)
    other = next(square for square in shortlist if square != code_best)
    high = jev._select_square(
        position, places, _jev_choice_parsed(places, focused=other.algebraic), spec
    )
    low = jev._select_square(
        position,
        places,
        _jev_choice_parsed(places, focused=other.algebraic, confidence=0.0),
        spec,
    )
    assert high == other
    assert low == code_best
    assert spec.confidence_threshold > 0.0


def test_jev_spec_drops_synthesis_weights() -> None:
    spec = json.loads(jev.PROMPT_PATH.read_text(encoding="utf-8"))
    selection = spec["selection"]
    for key in ("shortlist_size", "margin", "confidence_threshold"):
        assert key in selection
    weights = spec.get("weights", {})
    assert "jev" not in weights
    assert "confidence" not in weights
    assert "code" not in weights
    loaded = jev._load_spec()
    assert not hasattr(loaded, "w_jev")
    assert not hasattr(loaded, "w_confidence")
    source = _module_source("jev.py")
    assert "w_jev" not in source
    assert "_combined_score" not in source


def test_jev_choice_probability_on_corner_picks_that_square() -> None:
    position = _position_from_rank8_rows(_CORNER_VS_TWO_FLIPS, Color.BLACK)
    places = legal_places(position)
    assert Square.parse("a1") in places
    spec = jev._load_spec()
    parsed = _jev_choice_parsed(places, focused="a1")
    square = jev._select_square(position, places, parsed, spec)
    assert square == Square.parse("a1")
    assert square in places
    after_a1 = apply_place(position.board, Square.parse("a1"), Color.BLACK)
    after_d2 = apply_place(position.board, Square.parse("d2"), Color.BLACK)
    assert after_a1.stone_at(Square.parse("a1")) is Stone.BLACK
    assert after_d2.stone_at(Square.parse("a1")) is Stone.EMPTY


def test_jev_choice_outside_shortlist_does_not_override_code_best() -> None:
    position = _position_from_rank8_rows(_CORNER_VS_TWO_FLIPS, Color.BLACK)
    places = legal_places(position)
    a1 = Square.parse("a1")
    d2 = Square.parse("d2")
    assert a1 in places and d2 in places
    spec = jev._load_spec()
    stage = jev._stage_of(position.board, spec)
    metrics = jev._after_metrics(position, places, spec)
    scores = jev._code_scores(places, metrics, spec, stage)
    _best, shortlist = jev._shortlist(places, scores, spec)
    assert a1 in shortlist
    assert d2 not in shortlist
    even = jev._select_square(position, places, _jev_choice_parsed(places), spec)
    focused = jev._select_square(
        position, places, _jev_choice_parsed(places, focused="d2"), spec
    )
    assert even == a1
    assert focused == a1
    assert metrics[d2].material > metrics[a1].material
    assert len(flips_for(position.board, d2, Color.BLACK)) > len(
        flips_for(position.board, a1, Color.BLACK)
    )


def test_jev_state_uses_word_facts_not_numeric_board() -> None:
    position = _position_from_rank8_rows(_CORNER_VS_TWO_FLIPS, Color.BLACK)
    places = legal_places(position)
    spec = jev._load_spec()
    lines = jev._place_lines(position, places, spec)
    state = jev._decision_state(position, spec, lines)
    questions = jev._decision_questions(spec, lines)
    assert "board" not in state
    assert "origin" not in state
    assert set(state["places"]) == {square.algebraic for square in places}
    payload = questions[spec.question_id]
    assert payload["type"] == "choice"
    assert payload["instructions"] == spec.instructions
    assert payload["criteria"] == state["places"]
    a1 = state["places"]["a1"]
    assert spec.kind_words["corner"] in a1
    assert spec.yes_no["true"] in a1
    for text in state["places"].values():
        assert not re.search(r"\d", text)


def test_jev_questions_keep_type_when_legal_places_change() -> None:
    spec = jev._load_spec()
    opening = legal_places(initial_position())
    white_only = Position(_almost_full_white_with_black_on_b1().board, Color.WHITE)
    one = legal_places(white_only)
    assert len(opening) >= 2
    assert len(one) == 1
    opening_lines = jev._place_lines(initial_position(), opening, spec)
    one_lines = jev._place_lines(white_only, one, spec)
    opening_q = jev._decision_questions(spec, opening_lines)
    one_q = jev._decision_questions(spec, one_lines)
    assert set(opening_q) == set(one_q) == {spec.question_id}
    assert spec.question_id not in {square.algebraic for square in opening}
    assert (
        opening_q[spec.question_id]["type"]
        == one_q[spec.question_id]["type"]
        == "choice"
    )
    assert opening_q[spec.question_id]["instructions"] == spec.instructions
    assert one_q[spec.question_id]["instructions"] == spec.instructions
    assert set(opening_q[spec.question_id]["criteria"]) == {
        square.algebraic for square in opening
    }
    assert set(one_q[spec.question_id]["criteria"]) == {
        square.algebraic for square in one
    }
    opening_state = jev._decision_state(initial_position(), spec, opening_lines)
    one_state = jev._decision_state(white_only, spec, one_lines)
    assert set(opening_state.keys()) == set(one_state.keys())
    assert "board" not in opening_state


def test_jev_does_not_delegate_to_minimax_choose_move(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _module_source("jev.py")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "minimax" not in alias.name.split(".")
                assert alias.asname != "minimax"
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert "minimax" not in module.split(".")
            for alias in node.names:
                assert alias.name != "minimax"
                assert alias.asname != "minimax"
    called = {"n": 0}

    def boom(*_args: object, **_kwargs: object) -> None:
        called["n"] += 1
        raise AssertionError("カタログのミニマックス個体へ委譲してはいけない")

    monkeypatch.setattr(minimax, "choose_move", boom)
    monkeypatch.setattr(jev, "_call_openrouter", lambda _position, legal: legal[0])
    position = initial_position()
    places = legal_places(position)
    move = jev.choose_move(position)
    assert move == Place(places[0])
    assert called["n"] == 0


def test_jev_rejects_out_of_range_place_probabilities() -> None:
    spec = jev._load_spec()
    position = initial_position()
    places = legal_places(position)
    chosen = places[0].algebraic
    invalid = {square.algebraic: 0.0 for square in places}
    invalid[chosen] = -0.1
    answers = {
        spec.question_id: {
            "type": "choice",
            "choice": chosen,
            "probabilities": invalid,
            "confidence": 1.0,
        }
    }
    with pytest.raises(jev.ExternalModelError, match="合成できません"):
        jev._answers_from_response(SimpleNamespace(answers=answers), spec, places)
    invalid[chosen] = 1.5
    answers[spec.question_id]["probabilities"] = invalid
    with pytest.raises(jev.ExternalModelError, match="合成できません"):
        jev._answers_from_response(SimpleNamespace(answers=answers), spec, places)


def test_jev_incomplete_probabilities_are_unplayable() -> None:
    spec = jev._load_spec()
    position = _position_from_rank8_rows(_CORNER_VS_TWO_FLIPS, Color.BLACK)
    places = legal_places(position)
    chosen = Square.parse("d2").algebraic
    assert Square.parse("a1") in places
    payload = {
        spec.question_id: {
            "type": "choice",
            "choice": chosen,
            "confidence": 1.0,
        }
    }
    payload[spec.question_id]["probabilities"] = {}
    with pytest.raises(jev.ExternalModelError, match="合成できません"):
        jev._answers_from_response(SimpleNamespace(answers=payload), spec, places)
    payload[spec.question_id]["probabilities"] = {chosen: 1.0}
    with pytest.raises(jev.ExternalModelError, match="合成できません"):
        jev._answers_from_response(SimpleNamespace(answers=payload), spec, places)
    payload[spec.question_id]["probabilities"] = {
        square.algebraic: 0.0 for square in places
    }
    with pytest.raises(jev.ExternalModelError, match="合成できません"):
        jev._answers_from_response(SimpleNamespace(answers=payload), spec, places)


def test_jev_missing_probabilities_use_choice() -> None:
    spec = jev._load_spec()
    position = initial_position()
    places = legal_places(position)
    chosen = Square.parse("c4")
    answers = {
        spec.question_id: {
            "type": "choice",
            "choice": chosen.algebraic,
            "confidence": 1.0,
        }
    }
    parsed = jev._answers_from_response(SimpleNamespace(answers=answers), spec, places)
    assert parsed.choice == chosen.algebraic
    assert jev._select_square(position, places, parsed, spec) == chosen


def test_jev_buckets_cover_thirty_three_places_and_twenty_one_flips() -> None:
    spec = jev._load_spec()
    for count in range(65):
        assert jev._bucket_label(count, spec.opponent_buckets) in {
            "few",
            "some",
            "many",
        }
    for count in range(1, 65):
        assert jev._bucket_label(count, spec.flip_buckets) in {"few", "some", "many"}
    assert jev._bucket_label(33, spec.opponent_buckets) == "many"
    assert jev._bucket_label(21, spec.flip_buckets) == "many"
    assert spec.opponent_buckets["many"][1] == 64
    assert spec.flip_buckets["many"][1] == 64


def test_jev_same_position_and_parsed_answers_repeat_the_square() -> None:
    position = initial_position()
    places = legal_places(position)
    spec = jev._load_spec()
    parsed = _jev_choice_parsed(places, focused=places[1].algebraic)
    first = jev._select_square(position, places, parsed, spec)
    second = jev._select_square(position, places, parsed, spec)
    assert first == second
    lines = jev._place_lines(position, places, spec)
    again = jev._place_lines(position, places, spec)
    assert lines == again
    assert jev._decision_state(position, spec, lines) == jev._decision_state(
        position, spec, again
    )
    assert jev._decision_questions(spec, lines) == jev._decision_questions(spec, again)


def test_jev_logs_candidate_code_probability_and_selection(
    capsys: pytest.CaptureFixture[str],
) -> None:
    position = initial_position()
    places = legal_places(position)
    spec = jev._load_spec()
    parsed = _jev_choice_parsed(places, focused=places[1].algebraic)
    square = jev._select_square(position, places, parsed, spec)
    err = capsys.readouterr().err
    lines = [line for line in err.splitlines() if line.startswith("jev candidate ")]
    assert len(lines) == len(places)
    selected_count = 0
    for line, place in zip(lines, places, strict=True):
        assert f"square={place.algebraic}" in line
        assert "code=" in line
        assert "position=" in line
        assert "mobility=" in line
        assert "material=" in line
        assert "corners=" in line
        assert "probability=" in line
        assert "confidence=" in line
        if place == square:
            assert "selected=true" in line
            selected_count += 1
        else:
            assert "selected=false" in line
    assert selected_count == 1


def test_jev_stage1_configs_switch_without_adding_catalog_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    position = _position_from_rank8_rows(_CORNER_VS_TWO_FLIPS, Color.BLACK)
    places = legal_places(position)
    a1 = Square.parse("a1")
    d2 = Square.parse("d2")
    assert a1 in places and d2 in places
    called = {"n": 0}

    def boom(*_args: object, **_kwargs: object) -> Square:
        called["n"] += 1
        raise AssertionError("コードだけの構成は OpenRouter を呼んではいけない")

    monkeypatch.setattr(jev, "_call_openrouter", boom)
    with jev.stage1_config("v2_jev0"):
        even = jev.choose_move(position)
        focused_spec = jev._spec_for_config(jev._load_spec(), "v2_jev0")
        even_sel = jev._select_square(
            position, places, _jev_choice_parsed(places), focused_spec
        )
        d2_sel = jev._select_square(
            position, places, _jev_choice_parsed(places, focused="d2"), focused_spec
        )
    assert even is not None
    assert even.square == even_sel == d2_sel == a1
    assert called["n"] == 0

    with jev.stage1_config("v1_constant"):
        first = jev.choose_move(position)
        second = jev.choose_move(position)
    assert first is not None and second is not None
    assert first == second
    assert first.square in places
    assert called["n"] == 0

    spec = jev._load_spec()
    code0 = jev._spec_for_config(spec, "v2_code0")
    as_is = jev._spec_for_config(spec, "v2_as_is")
    assert code0.shortlist_size == 64
    assert code0.margin > spec.margin
    assert code0.confidence_threshold == 0.0
    assert as_is.shortlist_size == spec.shortlist_size
    assert as_is.margin == spec.margin
    assert (
        jev._select_square(
            position, places, _jev_choice_parsed(places, focused="d2"), code0
        )
        == d2
    )
    assert (
        jev._select_square(
            position, places, _jev_choice_parsed(places, focused="d2"), as_is
        )
        == a1
    )
    assert jev._select_square(position, places, _jev_choice_parsed(places), as_is) == a1

    names = [item.display_name for item in items()]
    assert names.count("生成 AI (Jev)") == 1
    for extra in jev.STAGE1_CONFIG_NAMES:
        assert extra not in names
    assert get(jev.SPECIMEN_ID).display_name == "生成 AI (Jev)"


def test_jev_stage1_jev0_does_not_need_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(jev, "SECRET_PATH", tmp_path / "missing")
    monkeypatch.setattr(
        jev,
        "_call_openrouter",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("jev: 0 は OpenRouter を呼んではいけない")
        ),
    )
    position = initial_position()
    with jev.stage1_config("v2_jev0"):
        move = jev.choose_move(position)
    assert move is not None
    assert move.square in legal_places(position)
    with jev.stage1_config("v1_constant"):
        constant = jev.choose_move(position)
    assert constant is not None
    assert constant.square in legal_places(position)


def test_jev_stage1_code0_failure_is_unplayable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(_position: Position, _places: Sequence[Square]) -> Square:
        raise jev.ExternalModelError("試験用の失敗")

    monkeypatch.setattr(jev, "_call_openrouter", boom)
    position = initial_position()
    with (
        jev.stage1_config("v2_code0"),
        pytest.raises(jev.ExternalModelError, match="失敗"),
    ):
        jev.choose_move(position)
    with (
        jev.stage1_config("v2_as_is"),
        pytest.raises(jev.ExternalModelError, match="失敗"),
    ):
        jev.choose_move(position)


def test_jev_stage1_unknown_config_is_rejected() -> None:
    with pytest.raises(ValueError, match="未知"), jev.stage1_config("v3_shortlist"):
        pass
    assert jev._active_stage1_config == jev.DEFAULT_STAGE1_CONFIG


def test_jev_stage1_baseline_is_stronger_code_only_config() -> None:
    weaker = {"name": "v1_constant", "points": 1.0, "stone_diff": 40, "wins": 1}
    stronger = {"name": "v2_jev0", "points": 4.0, "stone_diff": -10, "wins": 4}
    loud = {"name": "v2_code0", "points": 99.0, "stone_diff": 99, "wins": 99}
    current = {"name": "v2_as_is", "points": 0.0, "stone_diff": 0, "wins": 0}
    assert jev.select_stage1_baseline([weaker, stronger, loud, current]) == "v2_jev0"
    tied_v1 = {"name": "v1_constant", "points": 3.0, "stone_diff": 10, "wins": 3}
    tied_v2 = {"name": "v2_jev0", "points": 3.0, "stone_diff": 10, "wins": 3}
    assert jev.select_stage1_baseline([tied_v2, tied_v1, loud, current]) == "v2_jev0"


def test_jev_stage1_record_names_code_only_baseline() -> None:
    root = Path(__file__).resolve().parents[2] / "docs" / "benchmarks"
    candidates = sorted(root.glob("jev-stage1*.json"))
    assert candidates, "段階 1 の記録 JSON が docs/benchmarks/ に無い"
    data = json.loads(candidates[-1].read_text(encoding="utf-8"))
    configs = data["configs"]
    names = {row["name"] for row in configs}
    required = set(jev.STAGE1_CONFIG_NAMES)
    assert required <= names
    assert data.get("baseline") in names
    assert data["baseline"] in jev.STAGE1_CODE_ONLY
    for row in configs:
        assert "wins" in row or "stone_diff" in row or "points" in row
    assert jev.select_stage1_baseline(configs) == data["baseline"]
    assert [item.display_name for item in items()].count("生成 AI (Jev)") == 1


def test_jev_stage2_record_has_three_methods_and_confidence_bins() -> None:
    root = Path(__file__).resolve().parents[2] / "docs" / "benchmarks"
    records = sorted(root.glob("jev-stage2*.json"))
    assert records, "段階 2 のオフライン評価 JSON が docs/benchmarks/ に無い"
    data = json.loads(records[-1].read_text(encoding="utf-8"))
    methods = {row["name"] for row in data["methods"]}
    assert {"code_best", "jev_all", "shortlist"} <= methods
    for row in data["methods"]:
        for key in ("match_rate", "mean_loss", "blunder_rate"):
            assert key in row
    assert "confidence_bins" in data
    assert data["confidence_bins"]
    for row in data["confidence_bins"]:
        assert "match_rate" in row and "mean_loss" in row
    assert [item.display_name for item in items()].count("生成 AI (Jev)") == 1


def test_jev_stage3_record_has_per_change_loss_and_holdout() -> None:
    root = Path(__file__).resolve().parents[2] / "docs" / "benchmarks"
    records = sorted(root.glob("jev-stage3*.json"))
    assert records, "段階 3 のオフライン評価 JSON が docs/benchmarks/ に無い"
    data = json.loads(records[-1].read_text(encoding="utf-8"))
    trials = data["trials"]
    assert trials, "試行が空"
    for row in trials:
        for key in ("change", "mean_loss_before", "mean_loss_after", "accepted"):
            assert key in row, key
    accepted = data["accepted_changes"]
    assert isinstance(accepted, list)
    holdout = data.get("holdout")
    assert holdout, "別局面での確認が無い"
    spec = json.loads(jev.PROMPT_PATH.read_text(encoding="utf-8"))
    blob = json.dumps(spec, ensure_ascii=False).lower()
    loaded = jev._load_spec()
    if "instructions_reference_stage_and_side" in accepted:
        assert "`stage`" in loaded.instructions
        assert "`side_to_move`" in loaded.instructions
        assert not loaded.places_in_state
    else:
        assert loaded.places_in_state
    if "drop_objective" in accepted:
        assert "objective" not in spec
        assert loaded.objective == ""
    else:
        assert "more discs" in str(spec.get("objective", "")).lower()
    if "gives_corner_newly" in accepted:
        assert loaded.gives_corner_newly
        assert "newly lets the opponent take a corner" in blob
    else:
        assert not loaded.gives_corner_newly
        assert "newly lets the opponent take a corner" not in blob
    if "add_takes_edge" not in accepted:
        assert "occupies an edge" not in blob
    if "add_stable_increase" not in accepted:
        assert "stable discs increase" not in blob
    if "add_reply_change" not in accepted:
        assert "opponent replies vs now" not in blob
    assert [item.display_name for item in items()].count("生成 AI (Jev)") == 1


def test_jev_stage4_record_has_grid_and_conclusion() -> None:
    root = Path(__file__).resolve().parents[2] / "docs" / "benchmarks"
    records = sorted(root.glob("jev-stage4*.json"))
    assert records, "段階 4 の記録 JSON が docs/benchmarks/ に無い"
    data = json.loads(records[-1].read_text(encoding="utf-8"))
    rows = data["grid"]
    assert rows, "格子が空"
    zeros = [row for row in rows if row["margin"] == 0]
    assert zeros, "margin=0 が無い"
    baseline = data["baseline_mean_loss"]
    for row in zeros:
        assert row["mean_loss"] == baseline
    assert data.get("margin_zero_mean_loss") == baseline
    assert "beats_baseline" in data
    if data["beats_baseline"]:
        chosen = data["chosen"]
        for key in ("shortlist_size", "margin", "confidence_threshold"):
            assert key in chosen
        assert data.get("return_to_stage3") is False
        assert chosen["mean_loss"] < baseline
        matched = [
            row
            for row in rows
            if row["shortlist_size"] == chosen["shortlist_size"]
            and row["margin"] == chosen["margin"]
            and row["confidence_threshold"] == chosen["confidence_threshold"]
        ]
        assert matched
        assert matched[0]["mean_loss"] == chosen["mean_loss"]
    else:
        assert data.get("return_to_stage3") is True
        assert data.get("chosen") is None
    spec = json.loads(jev.PROMPT_PATH.read_text(encoding="utf-8"))
    selection = spec["selection"]
    for key in ("shortlist_size", "margin", "confidence_threshold"):
        assert key in selection
    assert [item.display_name for item in items()].count("生成 AI (Jev)") == 1


def test_jev_stage4_margin_zero_matches_code_best_on_recorded_positions() -> None:
    root = Path(__file__).resolve().parents[2] / "docs" / "benchmarks"
    records = sorted(root.glob("jev-stage4*.json"))
    assert records, "段階 4 の記録 JSON が docs/benchmarks/ に無い"
    data = json.loads(records[-1].read_text(encoding="utf-8"))
    positions = data["positions"]
    assert positions, "局面が無い"
    spec = replace(jev._load_spec(), margin=0.0)
    losses: list[int] = []
    for row in positions:
        position = _position_from_rank8_rows(tuple(row["board"]), Color(row["side_to_move"]))
        places = legal_places(position)
        focused = places[-1].algebraic
        chosen = jev._select_square(
            position, places, _jev_choice_parsed(places, focused=focused), spec
        )
        stage = jev._stage_of(position.board, spec)
        metrics = jev._after_metrics(position, places, spec)
        scores = jev._code_scores(places, metrics, spec, stage)
        code_best = jev._best_square(places, scores)
        assert chosen == code_best
        assert chosen.algebraic == row["code_best"]
        losses.append(row["best_value"] - row["values"][chosen.algebraic])
    assert sum(losses) / len(losses) == data["baseline_mean_loss"]


def test_jev_stage5_record_has_paired_acceptance() -> None:
    root = Path(__file__).resolve().parents[2] / "docs" / "benchmarks"
    records = sorted(root.glob("jev-stage5*.json"))
    assert records, "段階 5 の対局記録 JSON が docs/benchmarks/ に無い"
    data = json.loads(records[-1].read_text(encoding="utf-8"))
    for key in ("games", "win_rate", "mean_stone_diff", "paired", "accepted"):
        assert key in data, key
    assert data["paired"] is True
    assert data.get("complete") is True
    assert isinstance(data["accepted"], bool)
    assert data["games"] == len(data["game_records"])
    assert data["games"] == 2 * len(data["starts"])
    assert data["games"] >= 2
    pairs = data["paired_results"]
    assert len(pairs) == len(data["starts"])
    for row in pairs:
        assert row["black"]["candidate_color"] == "black"
        assert row["white"]["candidate_color"] == "white"
        assert row["black"]["start_index"] == row["white"]["start_index"]
    if data["accepted"]:
        assert data["mean_stone_diff"] > 0
        assert data["win_rate"] >= data.get("baseline_win_rate", 0)
        spec = json.loads(jev.PROMPT_PATH.read_text(encoding="utf-8"))
        chosen = data["candidate"]
        assert spec["selection"]["shortlist_size"] == chosen["shortlist_size"]
        assert spec["selection"]["margin"] == chosen["margin"]
        assert spec["selection"]["confidence_threshold"] == chosen["confidence_threshold"]
    else:
        assert data.get("return_to_stage3_and_4") is True
        assert data.get("catalog_policy") == "code_only_v2_jev0"
    assert jev.DEFAULT_STAGE1_CONFIG not in jev.STAGE1_CODE_ONLY
    assert jev.DEFAULT_STAGE1_CONFIG == "v1_priority"
    assert [item.display_name for item in items()].count("生成 AI (Jev)") == 1


def test_jev_catalog_default_calls_openrouter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = {"n": 0}

    def spy(_position, legal):
        called["n"] += 1
        return legal[0]

    monkeypatch.setattr(jev, "_call_openrouter", spy)
    position = initial_position()
    move = jev.choose_move(position)
    via_catalog = catalog_choose(jev.SPECIMEN_ID, position)
    assert move is not None
    assert via_catalog == move
    assert called["n"] >= 1
    assert jev.DEFAULT_STAGE1_CONFIG not in jev.STAGE1_CODE_ONLY


def test_jev_gives_corner_newly_does_not_mark_all_when_opponent_already_has_corner() -> None:
    rows = (
        "........",
        "........",
        "........",
        "...BW...",
        "...WB...",
        "W.......",
        "B.......",
        "........",
    )
    position = _position_from_rank8_rows(rows, Color.BLACK)
    places = legal_places(position)
    assert len(places) >= 2
    opponent = Position(position.board, Color.WHITE)
    assert any(place.algebraic in {"a1", "h1", "a8", "h8"} for place in legal_places(opponent))
    spec = jev._load_spec()
    newly = replace(spec, gives_corner_newly=True)
    flags = [jev._gives_corner(position, square, newly) for square in places]
    assert flags
    assert not all(flags)
    if spec.gives_corner_newly:
        production = [jev._gives_corner(position, square, spec) for square in places]
        assert not all(production)


def _black_feature_index(square: Square) -> int:
    return square.rank * 8 + square.file


def _linear_policy(black_squares: dict[str, float], bias: float = 0.0):
    from reversi.agents.rl import LinearPolicy

    weights = [0.0] * VECTOR_SIZE
    for algebraic, value in black_squares.items():
        square = Square.parse(algebraic)
        weights[_black_feature_index(square)] = value
    return LinearPolicy(
        weights=tuple(float(value) for value in weights),
        bias=float(bias),
    )


def test_rl_policy_rejects_non_finite_values() -> None:
    from reversi.agents.rl import LinearPolicy

    with pytest.raises(ValueError, match="有限"):
        LinearPolicy(tuple(0.0 for _ in range(VECTOR_SIZE)), float("nan"))
    inf_weights = [0.0] * VECTOR_SIZE
    inf_weights[0] = float("inf")
    with pytest.raises(ValueError, match="有限"):
        LinearPolicy(tuple(inf_weights), 0.0)


def test_catalog_lists_rl_self_play() -> None:
    from reversi.agents import rl

    item = _item_by_display_name("強化学習 (自己対局)")
    assert item.specimen_id == rl.SPECIMEN_ID == "rl"
    assert item.category == rl.CATEGORY == "reinforcement_learning"
    assert item.display_name == rl.DISPLAY_NAME
    assert item.description == rl.DESCRIPTION
    assert item.description.strip()
    assert "自己対局" in item.description
    assert "強化学習" in item.description
    assert _JAPANESE.search(item.description)
    assert get(rl.SPECIMEN_ID) == item
    with pytest.raises(KeyError):
        get("reinforcement_learning")


def test_catalog_lists_rl_search_without_replacing_greedy_rl() -> None:
    from reversi.agents import rl, rl_search

    greedy = _item_by_display_name("強化学習 (自己対局)")
    assert greedy.specimen_id == rl.SPECIMEN_ID == "rl"
    assert greedy.display_name == "強化学習 (自己対局)"
    item = _item_by_display_name("強化学習 (自己対局＋読み)")
    assert item.specimen_id == rl_search.SPECIMEN_ID == "rl_search"
    assert item.category == rl_search.CATEGORY == "reinforcement_learning"
    assert item.display_name == rl_search.DISPLAY_NAME
    assert item.description == rl_search.DESCRIPTION
    assert "自己対局" in item.description
    assert "数手先" in item.description
    assert _JAPANESE.search(item.description)
    assert len(item.description) <= 100
    assert get(rl_search.SPECIMEN_ID) == item
    names = [listed.display_name for listed in items()]
    assert names.count("強化学習 (自己対局)") == 1
    assert names.count("強化学習 (自己対局＋読み)") == 1
    rl_like = [listed for listed in items() if listed.category == "reinforcement_learning"]
    assert len(rl_like) >= 2
    assert rl_search.SEARCH_DEPTH == 4
    assert rl_search.DEFAULT_MODEL_PATH == rl.DEFAULT_MODEL_PATH
    assert rl.choose_move is not rl_search.choose_move


def test_rl_greedy_maximizes_black_value() -> None:
    from reversi.agents import rl

    position = initial_position()
    policy = _linear_policy({"c4": 4.0, "d3": 1.0})
    move = rl.choose_move(position, policy=policy)
    assert move == Place(Square.parse("c4"))
    assert move.square in legal_places(position)
    via_catalog = catalog_choose(rl.SPECIMEN_ID, position)
    assert via_catalog is not None
    assert via_catalog.square in legal_places(position)


def test_rl_white_minimizes_black_value() -> None:
    from reversi.agents import rl
    from reversi.agents.rl import LinearPolicy

    after_black = play(initial_position(), Place(Square.parse("d3")))
    assert after_black.side_to_move is Color.WHITE
    places = legal_places(after_black)
    assert len(places) >= 2
    policy = LinearPolicy(tuple(float(index) for index in range(VECTOR_SIZE)), 0.0)
    move = rl.choose_move(after_black, policy=policy)
    assert move is not None
    scored = {
        square: rl.value_of(
            apply_place(after_black.board, square, Color.WHITE),
            policy,
        )
        for square in places
    }
    best = min(scored.values())
    expected = next(square for square in places if scored[square] == best)
    assert move.square == expected
    assert scored[move.square] == best


def test_rl_tie_breaks_a1_to_h8_order() -> None:
    from reversi.agents import rl

    position = initial_position()
    places = legal_places(position)
    policy = _linear_policy({})
    values = [
        rl.value_of(apply_place(position.board, square, Color.BLACK), policy)
        for square in places
    ]
    assert values and len(set(values)) == 1
    move = rl.choose_move(position, Random(0), policy=policy)
    assert move == Place(places[0])
    assert move == Place(Square.parse("d3"))


def test_rl_does_not_move_when_no_legal_places() -> None:
    from reversi.agents import rl

    policy = _linear_policy({"a1": 1.0})
    assert rl.choose_move(_almost_full_white_with_black_on_b1(), policy=policy) is None
    assert rl.choose_move(_both_sides_cannot_place(), policy=policy) is None


def test_rl_default_policy_plays_only_legal_moves_to_the_end() -> None:
    from reversi.agents import rl

    assert rl.DEFAULT_MODEL_PATH.is_file()
    policy = rl.load_policy(rl.DEFAULT_MODEL_PATH)
    assert len(policy.weights) == VECTOR_SIZE
    position = initial_position()
    while not is_over(position):
        if pass_is_legal(position):
            position = play(position, PassMove())
            continue
        move = rl.choose_move(position, policy=policy)
        assert move is not None
        assert move.square in legal_places(position)
        position = play(position, move)
    assert is_over(position)


def test_rl_source_does_not_import_nn_or_openrouter() -> None:
    source = _module_source("rl.py")
    roots = _imported_roots(source)
    assert roots.isdisjoint(_FORBIDDEN_IMPORT_ROOTS)
    assert "torch" not in roots
    assert "onnxruntime" not in roots
    assert "openrouter" not in roots
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            lowered = node.value.lower()
            assert "ffothello.org" not in lowered
            assert ".wtb" not in lowered
            assert "openrouter.ai" not in lowered


def test_rl_training_does_not_read_wthor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from reversi.train import wthor
    from reversi.train.rl import train_and_write

    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("強化学習は WTHOR を読んではならない")

    monkeypatch.setattr(wthor, "training_games", boom)
    monkeypatch.setattr(wthor, "replay", boom)
    out = tmp_path / "rl.json"
    policy = train_and_write(out, games=2, seed=1, alpha=0.001, epsilon=0.5)
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["algorithm"] == "linear_td"
    assert len(loaded["weights"]) == VECTOR_SIZE
    assert len(policy.weights) == VECTOR_SIZE
    from reversi.agents.rl import load_policy

    assert load_policy(out).weights == policy.weights


def test_rl_td_update_moves_weights_toward_terminal_reward() -> None:
    import numpy as np

    from reversi.train.rl import _features, _td_update

    board = initial_position().board
    phi = _features(board)
    zeros = np.zeros(VECTOR_SIZE, dtype=np.float64)
    alpha = 0.5
    toward_win, bias_win = _td_update(zeros.copy(), 0.0, (board,), 1.0, alpha)
    np.testing.assert_allclose(toward_win, alpha * phi)
    assert bias_win == pytest.approx(alpha)

    toward_loss, bias_loss = _td_update(zeros.copy(), 0.0, (board,), -1.0, alpha)
    np.testing.assert_allclose(toward_loss, -alpha * phi)
    assert bias_loss == pytest.approx(-alpha)

    later = empty_board()
    updated, _ = _td_update(zeros.copy(), 0.0, (board, later), 1.0, alpha)
    # 先頭局面の TD 目標は次局面の価値 0 なので動かず、終端報酬は末局面だけに乗る。
    np.testing.assert_allclose(updated, alpha * _features(later))


def _rl_eval_module():
    import importlib.util

    path = Path(__file__).resolve().parents[2] / "docs" / "benchmarks" / "rl_eval.py"
    spec = importlib.util.spec_from_file_location("rl_eval_stage0", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rl_openings_are_reproducible_with_seed() -> None:
    from reversi.agents import rl as rl_agent

    module = _rl_eval_module()
    first = module.make_openings(Random(module.SEED), 12)
    second = module.make_openings(Random(module.SEED), 12)
    assert first == second
    other = module.make_openings(Random(module.SEED + 1), 12)
    assert first != other
    assert len(first) == 12
    plies = {int(row["opening_plies"]) for row in first}
    assert plies <= set(module.OPENING_PLIES)
    assert plies & {4, 5, 6, 7, 8}
    root = Path(__file__).resolve().parents[2] / "docs" / "benchmarks"
    openings = sorted(root.glob("rl-openings*.json"))
    assert openings, "開始局面 JSON が docs/benchmarks/ に無い"
    payload = json.loads(openings[-1].read_text(encoding="utf-8"))
    positions = payload["positions"] if isinstance(payload, dict) else payload
    assert len(positions) >= 100
    assert payload["seed"] == module.SEED
    regenerated = module.make_openings(Random(payload["seed"]), len(positions))
    assert regenerated == positions
    assert module.resolve_openings(openings[-1], payload["seed"], len(positions)) == positions
    assert [item.display_name for item in items()].count("強化学習 (自己対局)") == 1
    assert rl_agent.SPECIMEN_ID == "rl"
    assert rl_agent.DISPLAY_NAME == "強化学習 (自己対局)"
    assert rl_agent.CATEGORY == "reinforcement_learning"


def test_rl_eval_rejects_openings_seed_or_count_mismatch(tmp_path: Path) -> None:
    module = _rl_eval_module()
    path = tmp_path / "rl-openings.json"
    positions = module.make_openings(Random(7), 8)
    path.write_text(
        json.dumps(module.openings_payload(positions, 7), ensure_ascii=False),
        encoding="utf-8",
    )
    assert module.resolve_openings(path, 7, 8) == positions
    assert module.resolve_openings(path, 7, 4) == positions[:4]
    with pytest.raises(SystemExit, match="seed"):
        module.resolve_openings(path, 8, 8)
    with pytest.raises(SystemExit, match="足りない"):
        module.resolve_openings(path, 7, 9)
    missing = tmp_path / "missing.json"
    created = module.resolve_openings(missing, 11, 5)
    assert created == module.make_openings(Random(11), 5)
    assert json.loads(missing.read_text(encoding="utf-8"))["seed"] == 11


def test_rl_stage0_baseline_has_metrics() -> None:
    from reversi.agents import rl as rl_agent

    root = Path(__file__).resolve().parents[2] / "docs" / "benchmarks"
    candidates = sorted(root.glob("rl-stage0*.json"))
    assert candidates, "段階 0 の基準線 JSON が docs/benchmarks/ に無い"
    data = json.loads(candidates[-1].read_text(encoding="utf-8"))
    for key in ("win_rate", "mean_stone_diff", "ci95", "opponents", "n_games"):
        assert key in data, key
    assert data["n_games"] >= 200
    assert data["n_games"] == len(data["game_records"])
    wins = sum(1 for row in data["game_records"] if row["result"] == "win")
    draws = sum(1 for row in data["game_records"] if row["result"] == "draw")
    losses = sum(1 for row in data["game_records"] if row["result"] == "loss")
    n = data["n_games"]
    assert data["wins"] == wins
    assert data["draws"] == draws
    assert data["losses"] == losses
    assert data["win_rate"] == pytest.approx((wins + 0.5 * draws) / n)
    assert data["mean_stone_diff"] == pytest.approx(
        sum(int(row["stone_diff"]) for row in data["game_records"]) / n
    )
    assert "win_rate" in data["ci95"]
    assert "mean_stone_diff" in data["ci95"]
    win_ci = data["ci95"]["win_rate"]
    assert "low" in win_ci and "high" in win_ci
    if win_ci.get("crosses_even"):
        assert win_ci["note"] == "この局数では区別できない"
        assert "差がない" not in (win_ci["note"] or "")
    else:
        assert win_ci.get("note") in {None, ""}
    opponent_ids = {row["specimen_id"] for row in data["opponents"]}
    assert opponent_ids == {"random_uniform", "positional", "minimax"}
    for row in data["opponents"]:
        assert "win_rate" in row and "mean_stone_diff" in row and "ci95" in row
        assert row["n_games"] >= 2
    assert data["candidate"]["specimen_id"] == rl_agent.SPECIMEN_ID == "rl"
    assert data["candidate"]["display_name"] == rl_agent.DISPLAY_NAME
    assert data["learning_curve"]
    point = data["learning_curve"][0]
    assert "win_rate" in point and "mean_stone_diff" in point
    script = (root / "rl_eval.py").read_text(encoding="utf-8")
    tree = ast.parse(script)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
            imported.add(node.module)
    assert "wthor" not in imported
    assert "openrouter" not in imported
    assert "torch" not in imported
    assert "onnx" not in imported
    assert "onnxruntime" not in imported
    assert all("wthor" not in name and "openrouter" not in name for name in imported)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            lowered = node.value.lower()
            assert "ffothello.org" not in lowered
            assert ".wtb" not in lowered
            assert "openrouter.ai" not in lowered
    assert [item.display_name for item in items()].count("強化学習 (自己対局)") == 1


def test_rl_value_of_matches_feature_dot_product() -> None:
    from reversi.agents import rl
    from reversi.encode import encode

    weights = [0.0] * VECTOR_SIZE
    weights[_black_feature_index(Square.parse("d4"))] = 0.3
    weights[64] = 0.7
    weights[128 + 1] = -0.4
    policy = rl.LinearPolicy(tuple(weights), 0.05)
    for board in (initial_position().board, empty_board()):
        expected = policy.bias
        for weight, feature in zip(
            policy.weights, encode(board).as_vector(), strict=True
        ):
            expected += weight * feature
        assert rl.value_of(board, policy) == pytest.approx(expected)
        assert rl.perspective_value(board, Color.BLACK, policy) == pytest.approx(
            expected
        )
        assert rl.perspective_value(board, Color.WHITE, policy) == pytest.approx(
            -expected
        )


def _file_leaf(board: Board, color: Color) -> int:
    """c 列の自石を好み、相手石を嫌う。差し替え葉の大小を見るための整数。"""
    total = 0
    for square in all_squares():
        stone = board.stone_at(square)
        if square.file != 2:
            continue
        if stone is color.stone:
            total += 10
        elif stone is color.opponent.stone:
            total -= 10
    return total


def _brute_negamax(position: Position, remaining: int) -> int:
    if remaining == 0 or is_over(position):
        return _file_leaf(position.board, position.side_to_move)
    best = -10_000
    for move in legal_moves(position):
        best = max(best, -_brute_negamax(play(position, move), remaining - 1))
    return best


def test_alphabeta_custom_leaf_matches_brute_force_and_adds_no_bonus() -> None:
    position = initial_position()
    for depth in (1, 2):
        place, value, _nodes = alphabeta.search_stats(
            position, depth, evaluate=_file_leaf
        )
        assert place is not None
        best_square = None
        best_value: int | None = None
        for square in legal_places(position):
            child = play(position, Place(square))
            child_value = -_brute_negamax(child, depth - 1)
            if best_value is None or child_value > best_value:
                best_value = child_value
                best_square = square
        assert place == Place(best_square)
        assert value == best_value
        assert type(value) is int
    default_place, default_value, _nodes = alphabeta.search_stats(position, 1)
    assert type(default_value) is int
    assert default_place == alphabeta.choose_at_depth(position, 1)


def test_rl_search_depth_one_matches_greedy_and_plays_legal() -> None:
    from reversi.agents import rl, rl_search

    policy = _linear_policy({"c4": 4.0, "d3": 1.0})
    for position in (
        initial_position(),
        play(initial_position(), Place(Square.parse("d3"))),
    ):
        searched = rl_search.choose_at_depth(position, 1, policy=policy)
        greedy = rl.greedy_place(position, policy)
        assert searched == greedy
        assert searched is not None
        assert searched.square in legal_places(position)
    white_leaf = rl_search.leaf_score(
        initial_position().board, Color.WHITE, policy
    )
    black_leaf = rl_search.leaf_score(
        initial_position().board, Color.BLACK, policy
    )
    assert white_leaf == pytest.approx(-black_leaf)
    source = _module_source("rl_search.py")
    roots = _imported_roots(source)
    assert roots.isdisjoint(_FORBIDDEN_IMPORT_ROOTS)
    assert "torch" not in roots
    assert "onnxruntime" not in roots
    assert "openrouter" not in roots
    assert "wthor" not in roots
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            lowered = node.value.lower()
            assert "ffothello.org" not in lowered
            assert ".wtb" not in lowered
            assert "openrouter.ai" not in lowered
    position = initial_position()
    while not is_over(position):
        if pass_is_legal(position):
            position = play(position, PassMove())
            continue
        move = rl_search.choose_at_depth(position, 1, policy=policy)
        assert move is not None
        assert move.square in legal_places(position)
        position = play(position, move)
    assert is_over(position)


def test_same_depth_position_leaf_and_rl_leaf_can_play() -> None:
    """同じ深さの αβ で、葉が位置評価表の個体と葉が線形 v の個体を対局できる。"""
    from reversi.agents import rl_search

    start = initial_position()
    position = start
    depth = 1
    rl_is_black = True
    while not is_over(position):
        places = legal_places(position)
        if not places:
            position = play(position, PassMove())
            continue
        is_rl = (position.side_to_move is Color.BLACK) == rl_is_black
        if is_rl:
            move = rl_search.choose_at_depth(position, depth)
        else:
            move = alphabeta.choose_at_depth(
                position, depth, evaluate=minimax.leaf_score
            )
        assert move is not None
        assert move.square in places
        position = play(position, move)
    assert is_over(position)
    assert official_score(position.board) is not None
    assert stone_counts(position.board).black + stone_counts(position.board).white == 64


def test_rl_eval_ci_notes_when_interval_crosses_even() -> None:
    module = _rl_eval_module()
    even = module.mean_and_ci95([0.0, 1.0] * 20)
    assert even["crosses_even"] is True
    assert even["note"] == module.EVEN_NOTE
    assert "差がない" not in even["note"]
    lopsided = module.mean_and_ci95([1.0] * 40)
    assert lopsided["crosses_even"] is False
    assert lopsided["note"] is None


def test_rl_training_snapshots_can_be_evaluated(tmp_path: Path) -> None:
    from reversi.agents.rl import load_policy
    from reversi.train.rl import train_and_write

    module = _rl_eval_module()
    snaps = tmp_path / "snaps"
    out = tmp_path / "rl.json"
    train_and_write(
        out,
        games=4,
        seed=3,
        alpha=0.001,
        epsilon=0.5,
        snapshot_every=2,
        snapshot_dir=snaps,
    )
    files = sorted(snaps.glob("games-*.json"))
    assert [path.name for path in files] == ["games-00002.json", "games-00004.json"]
    load_policy(files[0])
    openings = module.make_openings(Random(0), 2)
    policy = load_policy(out)
    summary, games = module.evaluate_policy(
        policy,
        openings,
        seed=0,
        workers=1,
        opponent_ids=("random_uniform", "positional"),
    )
    assert summary["n_games"] == 8
    assert len(games) == 8
    assert {row["opponent"] for row in games} == {"random_uniform", "positional"}
    assert summary["ci95"]["win_rate"]["low"] <= summary["win_rate"]
    assert summary["win_rate"] <= summary["ci95"]["win_rate"]["high"]
    loaded = module.load_snapshot_policies(snaps)
    assert [games_trained for games_trained, _path, _policy in loaded] == [2, 4]
    first_summary, _ = module.evaluate_policy(
        loaded[0][2],
        openings,
        seed=0,
        workers=1,
        opponent_ids=("positional",),
    )
    assert first_summary["n_games"] == 4
    assert first_summary["opponents"]


def _linear_ml_model(black_squares: dict[str, float], bias: float = 0.0):
    from reversi.agents.ml import LinearModel

    weights = [0.0] * VECTOR_SIZE
    for algebraic, value in black_squares.items():
        square = Square.parse(algebraic)
        weights[_black_feature_index(square)] = value
    return LinearModel(
        weights=tuple(float(value) for value in weights),
        bias=float(bias),
    )


def _write_wtb(path: Path, games: tuple[tuple[Square, ...], ...]) -> Path:
    from reversi.train.wthor import RECORD_SIZE_8X8, encode_8x8_move

    header = bytearray(16)
    header[4:8] = len(games).to_bytes(4, "little")
    header[12] = 8
    payload = bytearray()
    for squares in games:
        rec = bytearray(RECORD_SIZE_8X8)
        for index, square in enumerate(squares):
            rec[8 + index] = encode_8x8_move(square)
        payload.extend(rec)
    path.write_bytes(bytes(header) + bytes(payload))
    return path


def _play_record(
    black, white
) -> tuple[Position, tuple[dict[str, str], ...], tuple[Square, ...]]:
    position = initial_position()
    moves: list[dict[str, str]] = []
    squares: list[Square] = []
    while not is_over(position):
        if pass_is_legal(position):
            position = play(position, PassMove())
            moves.append({"type": "pass"})
            continue
        chooser = black if position.side_to_move is Color.BLACK else white
        move = chooser(position)
        assert move is not None
        position = play(position, move)
        moves.append({"type": "place", "square": move.square.algebraic})
        squares.append(move.square)
    return position, tuple(moves), tuple(squares)


def test_catalog_lists_ml_kifu() -> None:
    from reversi.agents import ml

    item = _item_by_display_name("機械学習 (棋譜)")
    assert item.specimen_id == ml.SPECIMEN_ID == "ml"
    assert item.category == ml.CATEGORY == "machine_learning"
    assert item.display_name == ml.DISPLAY_NAME
    assert item.description == ml.DESCRIPTION
    assert item.description.strip()
    assert "WTHOR" in item.description
    assert "永続化" in item.description
    assert "ニューラルネットワーク" in item.description
    assert _JAPANESE.search(item.description)
    assert get(ml.SPECIMEN_ID) == item
    with pytest.raises(KeyError):
        get("machine_learning")


def test_ml_value_is_coefficient_dot_product() -> None:
    from reversi.agents import ml
    from reversi.encode import encode

    model = _linear_ml_model({"d5": 2.5, "e4": -1.0}, bias=0.5)
    board = initial_position().board
    expected = 0.5
    vector = encode(board).as_vector()
    for weight, feature in zip(model.weights, vector, strict=True):
        expected += weight * feature
    assert ml.value_of(board, model) == pytest.approx(expected)


def test_ml_greedy_maximizes_black_value() -> None:
    from reversi.agents import ml

    position = initial_position()
    model = _linear_ml_model({"c4": 4.0, "d3": 1.0})
    move = ml.choose_move(position, model=model)
    assert move == Place(Square.parse("c4"))
    assert move.square in legal_places(position)
    via_catalog = catalog_choose(ml.SPECIMEN_ID, position)
    assert via_catalog is not None
    assert via_catalog.square in legal_places(position)


def test_ml_white_minimizes_black_value() -> None:
    from reversi.agents import ml
    from reversi.agents.ml import LinearModel

    after_black = play(initial_position(), Place(Square.parse("d3")))
    assert after_black.side_to_move is Color.WHITE
    places = legal_places(after_black)
    assert len(places) >= 2
    model = LinearModel(tuple(float(index) for index in range(VECTOR_SIZE)), 0.0)
    move = ml.choose_move(after_black, model=model)
    assert move is not None
    scored = {
        square: ml.value_of(
            apply_place(after_black.board, square, Color.WHITE),
            model,
        )
        for square in places
    }
    best = min(scored.values())
    expected = next(square for square in places if scored[square] == best)
    assert move.square == expected
    assert scored[move.square] == best


def test_ml_tie_breaks_a1_to_h8_order() -> None:
    from reversi.agents import ml

    position = initial_position()
    places = legal_places(position)
    model = _linear_ml_model({})
    values = [
        ml.value_of(apply_place(position.board, square, Color.BLACK), model)
        for square in places
    ]
    assert values and len(set(values)) == 1
    move = ml.choose_move(position, Random(0), model=model)
    assert move == Place(places[0])
    assert move == Place(Square.parse("d3"))


def test_ml_does_not_move_when_no_legal_places() -> None:
    from reversi.agents import ml

    model = _linear_ml_model({"a1": 1.0})
    assert ml.choose_move(_almost_full_white_with_black_on_b1(), model=model) is None
    assert ml.choose_move(_both_sides_cannot_place(), model=model) is None


def test_ml_default_model_plays_only_legal_moves_to_the_end() -> None:
    from reversi.agents import ml

    assert ml.DEFAULT_MODEL_PATH.is_file()
    model = ml.load_model(ml.DEFAULT_MODEL_PATH)
    assert len(model.weights) == VECTOR_SIZE
    position = initial_position()
    while not is_over(position):
        if pass_is_legal(position):
            position = play(position, PassMove())
            continue
        move = ml.choose_move(position, model=model)
        assert move is not None
        assert move.square in legal_places(position)
        position = play(position, move)
    assert is_over(position)


def test_ml_source_does_not_import_nn_or_sklearn() -> None:
    source = _module_source("ml.py")
    roots = _imported_roots(source)
    assert roots.isdisjoint(_FORBIDDEN_IMPORT_ROOTS)
    assert "torch" not in roots
    assert "onnxruntime" not in roots
    assert "sklearn" not in roots
    assert "openrouter" not in roots
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            lowered = node.value.lower()
            assert "ffothello.org" not in lowered
            assert ".wtb" not in lowered
            assert "openrouter.ai" not in lowered


def test_ml_model_rejects_non_finite_values() -> None:
    from reversi.agents.ml import LinearModel

    with pytest.raises(ValueError, match="有限"):
        LinearModel(tuple(0.0 for _ in range(VECTOR_SIZE)), float("nan"))
    inf_weights = [0.0] * VECTOR_SIZE
    inf_weights[0] = float("inf")
    with pytest.raises(ValueError, match="有限"):
        LinearModel(tuple(inf_weights), 0.0)


def test_ml_training_fits_sklearn_on_wthor_and_persisted_games(tmp_path: Path) -> None:
    from reversi.agents import most_flips, positional
    from reversi.agents.ml import ALGORITHM, load_model
    from reversi.api.persist import MODE_AGENT_VS_AGENT, save_if_over
    from reversi.train.ml import train_and_write

    wthor_dir = tmp_path / "wthor"
    wthor_dir.mkdir()
    db_path = tmp_path / "games.sqlite"
    out = tmp_path / "ml.json"

    _write_wtb(wthor_dir / "sample.wtb", ((Square.parse("f5"),),))

    finished, moves, squares = _play_record(
        most_flips.choose_move,
        positional.choose_move,
    )
    assert squares
    written = save_if_over(
        finished,
        mode=MODE_AGENT_VS_AGENT,
        black={"kind": "specimen", "specimen_id": most_flips.SPECIMEN_ID},
        white={"kind": "specimen", "specimen_id": positional.SPECIMEN_ID},
        moves=moves,
        db_path=db_path,
    )
    assert written is True
    _write_wtb(wthor_dir / "played.wtb", (squares[:60],))

    model = train_and_write(out, wthor=wthor_dir, games=db_path)
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["algorithm"] == ALGORITHM == "sklearn_ridge"
    assert len(loaded["weights"]) == VECTOR_SIZE
    assert len(model.weights) == VECTOR_SIZE
    assert load_model(out).weights == model.weights


def test_ml_training_requires_wthor_or_persisted_games(tmp_path: Path) -> None:
    from reversi.train.ml import train

    with pytest.raises(ValueError, match="学習例"):
        train(wthor=tmp_path / "missing-wthor", games=tmp_path / "missing.sqlite")


def test_ml_training_skips_unfinished_wthor(tmp_path: Path) -> None:
    from reversi.train.ml import train

    wthor_dir = tmp_path / "wthor"
    wthor_dir.mkdir()
    _write_wtb(wthor_dir / "cut.wtb", ((Square.parse("f5"),),))
    with pytest.raises(ValueError, match="学習例"):
        train(wthor=wthor_dir, games=tmp_path / "missing.sqlite")


class _LinearValueStub:
    """黒平面の指定マスの占有に比例する価値。LightGBM の predict 形に合わせる。"""

    def __init__(
        self,
        black_squares: dict[str, float],
        bias: float = 0.0,
        weights: tuple[float, ...] | None = None,
    ) -> None:
        if weights is None:
            values = [0.0] * VECTOR_SIZE
            for algebraic, value in black_squares.items():
                square = Square.parse(algebraic)
                values[_black_feature_index(square)] = value
            self._weights = tuple(values)
        else:
            self._weights = weights
        self._bias = bias

    def predict(self, data: list[list[float]]) -> list[float]:
        row = data[0]
        total = self._bias
        for weight, feature in zip(self._weights, row, strict=True):
            total += weight * feature
        return [total]


def test_catalog_lists_ml_lightgbm() -> None:
    from reversi.agents import lgbm

    item = _item_by_display_name("機械学習 (LightGBM)")
    ridge = _item_by_display_name("機械学習 (棋譜)")
    assert item.specimen_id == lgbm.SPECIMEN_ID == "lgbm"
    assert item.category == lgbm.CATEGORY == "machine_learning"
    assert item.display_name == lgbm.DISPLAY_NAME
    assert item.description == lgbm.DESCRIPTION
    assert item.description.strip()
    assert "WTHOR" in item.description
    assert "永続化" in item.description
    assert "LightGBM" in item.description
    assert "ニューラルネットワーク" in item.description
    assert _JAPANESE.search(item.description)
    assert item.display_name != ridge.display_name
    assert item.specimen_id != ridge.specimen_id
    assert item.category == ridge.category
    names = [entry.display_name for entry in items()]
    assert len(names) == len(set(names))
    assert get(lgbm.SPECIMEN_ID) == item
    with pytest.raises(KeyError):
        get("machine_learning")


def test_lgbm_greedy_maximizes_black_value() -> None:
    from reversi.agents import lgbm

    position = initial_position()
    model = _LinearValueStub({"c4": 4.0, "d3": 1.0})
    move = lgbm.choose_move(position, model=model)
    assert move == Place(Square.parse("c4"))
    assert move.square in legal_places(position)
    via_catalog = catalog_choose(lgbm.SPECIMEN_ID, position)
    assert via_catalog is not None
    assert via_catalog.square in legal_places(position)


def test_lgbm_white_minimizes_black_value() -> None:
    from reversi.agents import lgbm

    after_black = play(initial_position(), Place(Square.parse("d3")))
    assert after_black.side_to_move is Color.WHITE
    places = legal_places(after_black)
    assert len(places) >= 2
    model = _LinearValueStub(
        {},
        weights=tuple(float(index) for index in range(VECTOR_SIZE)),
    )
    move = lgbm.choose_move(after_black, model=model)
    assert move is not None
    scored = {
        square: lgbm.value_of(
            apply_place(after_black.board, square, Color.WHITE),
            model,
        )
        for square in places
    }
    best = min(scored.values())
    expected = next(square for square in places if scored[square] == best)
    assert move.square == expected
    assert scored[move.square] == best


def test_lgbm_tie_breaks_a1_to_h8_order() -> None:
    from reversi.agents import lgbm

    position = initial_position()
    places = legal_places(position)
    model = _LinearValueStub({})
    values = [
        lgbm.value_of(apply_place(position.board, square, Color.BLACK), model)
        for square in places
    ]
    assert values and len(set(values)) == 1
    move = lgbm.choose_move(position, Random(0), model=model)
    assert move == Place(places[0])
    assert move == Place(Square.parse("d3"))


def test_lgbm_does_not_move_when_no_legal_places() -> None:
    from reversi.agents import lgbm

    model = _LinearValueStub({"a1": 1.0})
    assert lgbm.choose_move(_almost_full_white_with_black_on_b1(), model=model) is None
    assert lgbm.choose_move(_both_sides_cannot_place(), model=model) is None


def test_lgbm_default_model_plays_only_legal_moves_to_the_end() -> None:
    from reversi.agents import lgbm

    assert lgbm.DEFAULT_MODEL_PATH.is_file()
    model = lgbm.load_model(lgbm.DEFAULT_MODEL_PATH)
    position = initial_position()
    while not is_over(position):
        if pass_is_legal(position):
            position = play(position, PassMove())
            continue
        move = lgbm.choose_move(position, model=model)
        assert move is not None
        assert move.square in legal_places(position)
        position = play(position, move)
    assert is_over(position)


def test_lgbm_default_model_values_vary_across_positions() -> None:
    from reversi.agents import lgbm

    model = lgbm.load_model(lgbm.DEFAULT_MODEL_PATH)
    start = initial_position()
    after = play(start, Place(Square.parse("d3")))
    later = play(after, Place(legal_places(after)[0]))
    scores = {
        round(lgbm.value_of(start.board, model), 8),
        round(lgbm.value_of(after.board, model), 8),
        round(lgbm.value_of(later.board, model), 8),
    }
    assert len(scores) >= 2


def test_lgbm_source_does_not_import_nn_sklearn_joblib_or_pickle() -> None:
    source = _module_source("lgbm.py")
    roots = _imported_roots(source)
    assert roots.isdisjoint(_FORBIDDEN_IMPORT_ROOTS)
    assert "lightgbm" in roots
    assert "torch" not in roots
    assert "onnxruntime" not in roots
    assert "sklearn" not in roots
    assert "joblib" not in roots
    assert "pickle" not in roots
    assert "openrouter" not in roots
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            lowered = node.value.lower()
            assert "ffothello.org" not in lowered
            assert ".wtb" not in lowered
            assert "openrouter.ai" not in lowered


def test_lgbm_load_model_rejects_non_native_text(tmp_path: Path) -> None:
    from reversi.agents import lgbm

    fake = tmp_path / "lgbm.txt"
    fake.write_bytes(b"\x80\x04joblib")
    with pytest.raises(ValueError, match="テキスト形式"):
        lgbm.load_model(fake)
    fake.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="テキスト形式"):
        lgbm.load_model(fake)


def test_lgbm_training_fits_lightgbm_on_wthor_and_persisted_games(
    tmp_path: Path,
) -> None:
    from reversi.agents import lgbm, most_flips, positional
    from reversi.api.persist import MODE_AGENT_VS_AGENT, save_if_over
    from reversi.train.lgbm import train_and_write

    wthor_dir = tmp_path / "wthor"
    wthor_dir.mkdir()
    db_path = tmp_path / "games.sqlite"
    out = tmp_path / "lgbm.txt"

    finished, moves, squares = _play_record(
        most_flips.choose_move,
        positional.choose_move,
    )
    assert squares
    written = save_if_over(
        finished,
        mode=MODE_AGENT_VS_AGENT,
        black={"kind": "specimen", "specimen_id": most_flips.SPECIMEN_ID},
        white={"kind": "specimen", "specimen_id": positional.SPECIMEN_ID},
        moves=moves,
        db_path=db_path,
    )
    assert written is True
    _write_wtb(wthor_dir / "played.wtb", (squares[:60],))

    booster = train_and_write(out, wthor=wthor_dir, games=db_path)
    raw = out.read_bytes()
    assert not raw.startswith(b"\x80")
    text = out.read_text(encoding="utf-8")
    assert text.lstrip("\ufeff").startswith("tree")
    loaded = lgbm.load_model(out)
    opening = initial_position()
    move = lgbm.choose_move(opening, model=loaded)
    assert move is not None
    assert move.square in legal_places(opening)
    assert lgbm.value_of(opening.board, loaded) == pytest.approx(
        lgbm.value_of(opening.board, booster),
    )


def test_lgbm_training_requires_wthor_or_persisted_games(tmp_path: Path) -> None:
    from reversi.train.lgbm import train

    with pytest.raises(ValueError, match="学習例"):
        train(wthor=tmp_path / "missing-wthor", games=tmp_path / "missing.sqlite")


def _spec_leaf_score(board: Board, root: Color) -> int:
    """SRS-FUN-026 の葉評価。位置評価の点数表の差。"""
    return positional.own_stone_score(board, root) - positional.own_stone_score(
        board, root.opponent
    )


def _plain_minimax_value(position: Position, depth: int, root: Color) -> int:
    """アルファベータ無しのミニマックス。パスも 1 深さ。"""
    if depth >= 4 or is_over(position):
        return _spec_leaf_score(position.board, root)
    moves = legal_moves(position)
    if not moves:
        return _spec_leaf_score(position.board, root)
    values = tuple(
        _plain_minimax_value(play(position, move), depth + 1, root) for move in moves
    )
    if position.side_to_move is root:
        return max(values)
    return min(values)


def _plain_minimax_choose(position: Position) -> Place | None:
    root = position.side_to_move
    best_square = None
    best_value: int | None = None
    for square in legal_places(position):
        value = _plain_minimax_value(play(position, Place(square)), 1, root)
        if best_value is None or value > best_value:
            best_value = value
            best_square = square
    if best_square is None:
        return None
    return Place(best_square)


def test_catalog_lists_minimax() -> None:
    item = _item_by_display_name("ルールベース (ミニマックス)")
    assert item.specimen_id == minimax.SPECIMEN_ID == "minimax"
    assert item.category == minimax.CATEGORY == "rule_based"
    assert item.display_name == minimax.DISPLAY_NAME
    assert item.description == minimax.DESCRIPTION
    assert item.description.strip()
    assert _JAPANESE.search(item.description)
    assert "ミニマックス" in item.description
    assert "深さ 4" in item.description
    assert "点数表" in item.description
    assert len(item.description) <= 100
    assert get(minimax.SPECIMEN_ID) == item
    with pytest.raises(KeyError):
        get("rule_based")


def test_minimax_leaf_score_is_root_minus_opponent_table() -> None:
    board = empty_board().replacing(
        {
            Square.parse("a1"): Stone.BLACK,
            Square.parse("b1"): Stone.WHITE,
            Square.parse("c3"): Stone.BLACK,
        }
    )
    assert score_at(Square.parse("a1")) == 100
    assert score_at(Square.parse("b1")) == -20
    assert score_at(Square.parse("c3")) == 1
    assert minimax.leaf_score(board, Color.BLACK) == 100 + 1 - (-20)
    assert minimax.leaf_score(board, Color.WHITE) == -20 - (100 + 1)
    assert minimax.leaf_score(board, Color.BLACK) == _spec_leaf_score(
        board, Color.BLACK
    )
    assert minimax.leaf_score(board, Color.BLACK) != positional.own_stone_score(
        board, Color.BLACK
    )


def test_minimax_picks_depth_4_value_with_a1_h8_ties() -> None:
    position = initial_position()
    places = legal_places(position)
    assert tuple(square.algebraic for square in places) == ("d3", "c4", "f5", "e6")
    values = {
        square.algebraic: _plain_minimax_value(
            play(position, Place(square)), 1, Color.BLACK
        )
        for square in places
    }
    best = max(values.values())
    first_best = next(square for square in places if values[square.algebraic] == best)
    move = minimax.choose_move(position)
    assert move == Place(first_best)
    assert move == _plain_minimax_choose(position)
    via_catalog = catalog_choose(minimax.SPECIMEN_ID, position)
    assert via_catalog == move
    assert minimax.choose_move(position, Random(0)) == move


def test_minimax_looks_ahead_past_immediate_positional() -> None:
    """初手 d3 のあと、位置評価は c3、深さ 4 は e3 を選ぶ。"""
    after_d3 = play(initial_position(), Place(Square.parse("d3")))
    places = legal_places(after_d3)
    assert tuple(square.algebraic for square in places) == ("c3", "e3", "c5")
    assert positional.choose_move(after_d3) == Place(Square.parse("c3"))
    move = minimax.choose_move(after_d3)
    assert move == Place(Square.parse("e3"))
    assert move == _plain_minimax_choose(after_d3)
    assert move != positional.choose_move(after_d3)


def test_minimax_matches_plain_search_on_corner_and_pass_lines() -> None:
    corner = _position_from_rank8_rows(_CORNER_VS_TWO_FLIPS, Color.BLACK)
    assert minimax.choose_move(corner) == _plain_minimax_choose(corner)
    assert minimax.choose_move(corner) is not None

    # 白番なら a1 のみ。探索中に黒はパスし、白の着手で終局する。
    almost_full = _almost_full_white_with_black_on_b1()
    white_to_move = Position(almost_full.board, Color.WHITE)
    assert legal_places(white_to_move) == (Square.parse("a1"),)
    assert pass_is_legal(Position(almost_full.board, Color.BLACK))
    assert minimax.choose_move(white_to_move) == Place(Square.parse("a1"))
    assert minimax.choose_move(white_to_move) == _plain_minimax_choose(white_to_move)

    # 黒が 2 手持ち、一方の後は白がパスする局面でも素朴探索と一致する。
    two_empties = empty_board().replacing(
        {
            Square.parse("b1"): Stone.BLACK,
            Square.parse("g8"): Stone.BLACK,
            **{
                Square(file=file, rank=rank): Stone.WHITE
                for rank in range(8)
                for file in range(8)
                if (file, rank) not in {(0, 0), (1, 0), (6, 7), (7, 7)}
            },
        }
    )
    branched = Position(two_empties, Color.WHITE)
    places = legal_places(branched)
    assert Square.parse("a1") in places
    assert Square.parse("h8") in places
    assert minimax.choose_move(branched) == _plain_minimax_choose(branched)


def test_minimax_does_not_move_when_no_legal_places() -> None:
    assert minimax.choose_move(_almost_full_white_with_black_on_b1()) is None
    assert minimax.choose_move(_both_sides_cannot_place()) is None


def test_minimax_depth_stays_four_during_play() -> None:
    assert minimax.SEARCH_DEPTH == 4
    snapshot = minimax.SEARCH_DEPTH
    position = initial_position()
    first = minimax.choose_move(position)
    assert first is not None
    after = play(position, first)
    minimax.choose_move(after)
    minimax.choose_move(_position_from_rank8_rows(_CORNER_VS_TWO_FLIPS, Color.BLACK))
    assert minimax.SEARCH_DEPTH == snapshot == 4


def test_minimax_source_does_not_call_models() -> None:
    for filename in (
        "minimax.py",
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
    minimax_source = _module_source("minimax.py")
    assert "endgame" not in minimax_source.lower()
    assert "完全読み" not in minimax_source


_PHASE4_CORNERS = frozenset(Square.parse(name) for name in ("a1", "a8", "h1", "h8"))
_PHASE4_X = {
    Square.parse("b2"): Square.parse("a1"),
    Square.parse("b7"): Square.parse("a8"),
    Square.parse("g2"): Square.parse("h1"),
    Square.parse("g7"): Square.parse("h8"),
}
_PHASE4_C = {
    Square.parse("a2"): Square.parse("a1"),
    Square.parse("b1"): Square.parse("a1"),
    Square.parse("a7"): Square.parse("a8"),
    Square.parse("b8"): Square.parse("a8"),
    Square.parse("g1"): Square.parse("h1"),
    Square.parse("h2"): Square.parse("h1"),
    Square.parse("g8"): Square.parse("h8"),
    Square.parse("h7"): Square.parse("h8"),
}
_PHASE4_NEIGHBOR_DELTAS = (
    (-1, -1),
    (-1, 0),
    (-1, 1),
    (0, -1),
    (0, 1),
    (1, -1),
    (1, 0),
    (1, 1),
)


def _phase4_danger_diff(
    board: Board,
    color: Color,
    related: dict[Square, Square],
) -> int:
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


def _phase4_is_frontier(board: Board, square: Square) -> bool:
    for delta_file, delta_rank in _PHASE4_NEIGHBOR_DELTAS:
        file = square.file + delta_file
        rank = square.rank + delta_rank
        if 0 <= file < BOARD_SIZE and 0 <= rank < BOARD_SIZE:
            neighbor = Square(file=file, rank=rank)
            if board.stone_at(neighbor) is Stone.EMPTY:
                return True
    return False


def _phase4_disc_weight(empty: int) -> int:
    if empty >= 40:
        return 1
    if empty >= 20:
        return 5
    if empty >= 10:
        return 20
    return 100


def _phase4_parts(
    board: Board, color: Color
) -> tuple[int, int, int, int, int, int, int]:
    """(Mobility, Corner, 石数, X, C, Frontier, 空きマス)。差は自分 − 相手。"""
    own_places = len(legal_places(Position(board, color)))
    opp_places = len(legal_places(Position(board, color.opponent)))
    own = color.stone
    corners = 0
    discs = 0
    frontier = 0
    empty = 0
    for square in all_squares():
        stone = board.stone_at(square)
        if stone is Stone.EMPTY:
            empty += 1
            continue
        sign = 1 if stone is own else -1
        discs += sign
        if square in _PHASE4_CORNERS:
            corners += sign
        if _phase4_is_frontier(board, square):
            frontier += sign
    x_squares = _phase4_danger_diff(board, color, _PHASE4_X)
    c_squares = _phase4_danger_diff(board, color, _PHASE4_C)
    return (
        own_places - opp_places,
        corners,
        discs,
        x_squares,
        c_squares,
        frontier,
        empty,
    )


def _phase4_leaf_score(board: Board, color: Color) -> int:
    """Phase 4 の葉。W は空きマス数（Game Phase）。"""
    mobility, corner, disc, x_squares, c_squares, frontier, empty = _phase4_parts(
        board, color
    )
    weight = _phase4_disc_weight(empty)
    return (
        50 * mobility
        + 1000 * corner
        - 150 * x_squares
        - 80 * c_squares
        - 10 * frontier
        + weight * disc
    )


def _board_with_empty_black_lead(empty: int) -> Board:
    occupied = BOARD_SIZE * BOARD_SIZE - empty
    whites = max((occupied - 1) // 2, 0)
    blacks = occupied - whites
    updates: dict[Square, Stone] = {}
    for index, square in enumerate(all_squares()):
        if index < blacks:
            updates[square] = Stone.BLACK
        elif index < blacks + whites:
            updates[square] = Stone.WHITE
        else:
            break
    return empty_board().replacing(updates)


def test_catalog_lists_alphabeta() -> None:
    item = _item_by_display_name("ルールベース (αβ)")
    minimax_item = _item_by_display_name("ルールベース (ミニマックス)")
    assert item.specimen_id == alphabeta.SPECIMEN_ID == "alphabeta"
    assert item.category == alphabeta.CATEGORY == "rule_based"
    assert item.display_name == alphabeta.DISPLAY_NAME
    assert item.description == alphabeta.DESCRIPTION
    assert item.description.strip()
    assert _JAPANESE.search(item.description)
    assert "アルファベータ" in item.description
    assert "深さ 4" in item.description
    assert "Move Ordering" not in item.description
    assert "Transposition Table" not in item.description
    assert "Zobrist" not in item.description
    assert "Mobility" not in item.description
    assert "Corner" not in item.description
    assert "Frontier" not in item.description
    assert "Game Phase" not in item.description
    assert "完全読み" not in item.description
    assert "点数表" not in item.description
    assert len(item.description) <= 100
    assert item.specimen_id != minimax_item.specimen_id
    assert item.display_name != minimax_item.display_name
    assert alphabeta.SEARCH_DEPTH == 4
    assert not hasattr(alphabeta, "ENDGAME_EMPTY")
    assert minimax.SEARCH_DEPTH == 4
    assert get(alphabeta.SPECIMEN_ID) == item
    assert get(minimax.SPECIMEN_ID) == minimax_item
    assert sum(1 for listed in items() if listed.specimen_id == alphabeta.SPECIMEN_ID) == 1
    with pytest.raises(KeyError):
        get("rule_based")


def test_alphabeta_leaf_prefers_own_corner_lead() -> None:
    extra = empty_board().replacing(
        {
            Square.parse("a1"): Stone.BLACK,
            Square.parse("e5"): Stone.WHITE,
        }
    )
    even = empty_board().replacing(
        {
            Square.parse("a1"): Stone.BLACK,
            Square.parse("h8"): Stone.WHITE,
        }
    )
    extra_mob, extra_corner, extra_disc, extra_x, extra_c, extra_f, _empty = (
        _phase4_parts(extra, Color.BLACK)
    )
    even_mob, even_corner, even_disc, even_x, even_c, even_f, _even_empty = (
        _phase4_parts(even, Color.BLACK)
    )
    assert extra_mob == even_mob == 0
    assert extra_disc == even_disc == 0
    assert extra_x == extra_c == extra_f == 0
    assert even_x == even_c == even_f == 0
    assert extra_corner == 1
    assert even_corner == 0
    extra_score = alphabeta.leaf_score(extra, Color.BLACK)
    even_score = alphabeta.leaf_score(even, Color.BLACK)
    assert extra_score == _phase4_leaf_score(extra, Color.BLACK) == 1000
    assert even_score == _phase4_leaf_score(even, Color.BLACK) == 0
    assert extra_score > even_score
    assert alphabeta.leaf_score(extra, Color.WHITE) == -1000


def test_alphabeta_leaf_prefers_own_mobility_lead() -> None:
    more = empty_board().replacing(
        {
            Square.parse("c5"): Stone.BLACK,
            Square.parse("d5"): Stone.BLACK,
            Square.parse("e5"): Stone.BLACK,
            Square.parse("e4"): Stone.BLACK,
            Square.parse("d4"): Stone.WHITE,
            Square.parse("c4"): Stone.WHITE,
            Square.parse("f4"): Stone.WHITE,
            Square.parse("f5"): Stone.WHITE,
        }
    )
    even = empty_board().replacing(
        {
            Square.parse("c4"): Stone.BLACK,
            Square.parse("d5"): Stone.BLACK,
            Square.parse("e4"): Stone.BLACK,
            Square.parse("f5"): Stone.BLACK,
            Square.parse("d4"): Stone.WHITE,
            Square.parse("e5"): Stone.WHITE,
            Square.parse("c5"): Stone.WHITE,
            Square.parse("f4"): Stone.WHITE,
        }
    )
    more_mob, more_corner, more_disc, more_x, more_c, more_f, _more_empty = (
        _phase4_parts(more, Color.BLACK)
    )
    even_mob, even_corner, even_disc, even_x, even_c, even_f, _even_empty = (
        _phase4_parts(even, Color.BLACK)
    )
    assert more_corner == even_corner == 0
    assert more_disc == even_disc == 0
    assert more_x == more_c == more_f == 0
    assert even_x == even_c == even_f == 0
    assert more_mob > even_mob
    more_score = alphabeta.leaf_score(more, Color.BLACK)
    even_score = alphabeta.leaf_score(even, Color.BLACK)
    assert more_score == _phase4_leaf_score(more, Color.BLACK) == 50 * more_mob
    assert even_score == _phase4_leaf_score(even, Color.BLACK) == 50 * even_mob
    assert more_score > even_score


def test_alphabeta_leaf_does_not_use_position_table() -> None:
    board = empty_board().replacing(
        {
            Square.parse("a1"): Stone.BLACK,
            Square.parse("b1"): Stone.WHITE,
            Square.parse("c3"): Stone.BLACK,
        }
    )
    table = minimax.leaf_score(board, Color.BLACK)
    phase4 = alphabeta.leaf_score(board, Color.BLACK)
    assert phase4 == _phase4_leaf_score(board, Color.BLACK)
    assert phase4 != table
    assert table == _spec_leaf_score(board, Color.BLACK)
    source = _module_source("alphabeta.py")
    assert "score_at" not in source
    assert "position_table" not in source


def test_alphabeta_game_path_keeps_depth_four() -> None:
    assert alphabeta.SEARCH_DEPTH == 4
    assert not hasattr(alphabeta, "ENDGAME_EMPTY")
    assert minimax.SEARCH_DEPTH == 4
    snapshot = alphabeta.SEARCH_DEPTH
    position = initial_position()
    first = alphabeta.choose_move(position)
    via_catalog = catalog_choose(alphabeta.SPECIMEN_ID, position)
    assert first is not None
    assert via_catalog == first
    assert first.square in legal_places(position)
    assert first == Place(Square.parse("d3"))
    after = play(position, first)
    second = alphabeta.choose_move(after)
    assert second is not None
    assert second.square in legal_places(after)
    corner = alphabeta.choose_move(
        _position_from_rank8_rows(_CORNER_VS_TWO_FLIPS, Color.BLACK)
    )
    assert corner is not None
    assert corner.square in legal_places(
        _position_from_rank8_rows(_CORNER_VS_TWO_FLIPS, Color.BLACK)
    )
    assert alphabeta.SEARCH_DEPTH == snapshot == 4
    assert not hasattr(alphabeta, "ENDGAME_EMPTY")
    assert alphabeta.choose_move is not minimax.choose_move
    assert alphabeta.choose_move(position) == alphabeta.choose_at_depth(position, 4)
    after_d3 = play(position, Place(Square.parse("d3")))
    depth_four = alphabeta.choose_move(after_d3)
    assert depth_four is not None
    assert depth_four.square in legal_places(after_d3)
    assert depth_four == alphabeta.choose_at_depth(after_d3, 4)


def test_alphabeta_does_not_move_when_no_legal_places() -> None:
    assert alphabeta.choose_move(_almost_full_white_with_black_on_b1()) is None
    assert alphabeta.choose_move(_both_sides_cannot_place()) is None
    assert alphabeta.choose_at_depth(_almost_full_white_with_black_on_b1(), 4) is None


def test_alphabeta_source_is_negamax_and_does_not_call_models() -> None:
    source = _module_source("alphabeta.py")
    assert "SEARCH_DEPTH = 4" in source
    assert "ENDGAME_EMPTY" not in source
    assert "完全読み" not in source
    assert "def _negamax(" in source
    assert "-beta" in source and "-alpha" in source
    assert "score_at" not in source
    assert "position_table" not in source
    assert "Mobility" in source
    assert "Corner" in source
    assert "Frontier" in source
    assert "Game Phase" in source
    assert "def ordered_places(" in source
    assert "_X_SQUARES" in source
    assert "_C_SQUARES" in source
    assert "Zobrist" in source
    assert "transposition" in source.lower()
    assert "_TT_EXACT" in source
    roots = _imported_roots(source)
    assert roots.isdisjoint(_FORBIDDEN_IMPORT_ROOTS)
    assert "minimax" not in roots
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "minimax" not in alias.name.split(".")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert "minimax" not in module.split(".")
            for alias in node.names:
                assert alias.name != "minimax"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            lowered = node.value.lower()
            assert "ffothello.org" not in lowered
            assert ".wtb" not in lowered
            assert "openrouter.ai" not in lowered


# a1（角）と a2（C）と b2（空き角に対する X）がともに合法。
_CORNER_AND_X = (
    "........",
    "........",
    "........",
    "B...BB..",
    "W...WW..",
    "W.......",
    "..WB....",
    ".WB.....",
)


def test_alphabeta_orders_corner_before_x() -> None:
    position = _position_from_rank8_rows(_CORNER_AND_X, Color.BLACK)
    names = [square.algebraic for square in alphabeta.ordered_places(position)]
    assert "a1" in names
    assert "a2" in names
    assert "b2" in names
    assert names[0] == "a1"
    assert names.index("a1") < names.index("a2") < names.index("b2")
    assert names[-1] == "b2"
    unordered = [square.algebraic for square in legal_places(position)]
    assert unordered.index("a1") < unordered.index("b2")
    assert names != unordered


def test_alphabeta_ordering_keeps_root_and_cuts_nodes() -> None:
    position = _position_from_rank8_rows(_CORNER_AND_X, Color.BLACK)
    places = {square.algebraic for square in legal_places(position)}
    assert "a1" in places and "b2" in places
    ordered_place, ordered_value, ordered_nodes = alphabeta.search_stats(
        position, alphabeta.SEARCH_DEPTH, order=True
    )
    unordered_place, unordered_value, unordered_nodes = alphabeta.search_stats(
        position, alphabeta.SEARCH_DEPTH, order=False
    )
    assert ordered_place is not None
    assert ordered_place == unordered_place
    assert ordered_value == unordered_value
    assert ordered_place.square in legal_places(position)
    assert ordered_nodes <= unordered_nodes
    assert ordered_nodes < unordered_nodes


def test_alphabeta_root_tiebreak_is_coordinate_not_ordering() -> None:
    position = initial_position()
    ordered_place, ordered_value, _nodes = alphabeta.search_stats(
        position, alphabeta.SEARCH_DEPTH, order=True
    )
    unordered_place, unordered_value, _unordered_nodes = alphabeta.search_stats(
        position, alphabeta.SEARCH_DEPTH, order=False
    )
    assert ordered_place == unordered_place == Place(Square.parse("d3"))
    assert ordered_value == unordered_value
    assert alphabeta.choose_move(position) == ordered_place


def test_alphabeta_transposition_keeps_root_and_does_not_increase_nodes() -> None:
    position = _position_from_rank8_rows(_CORNER_AND_X, Color.BLACK)
    places = {square.algebraic for square in legal_places(position)}
    assert "a1" in places and "b2" in places
    with_place, with_value, with_nodes = alphabeta.search_stats(
        position, alphabeta.SEARCH_DEPTH, order=True, table=True
    )
    without_place, without_value, without_nodes = alphabeta.search_stats(
        position, alphabeta.SEARCH_DEPTH, order=True, table=False
    )
    assert with_place is not None
    assert with_place == without_place
    assert with_value == without_value
    assert with_place.square in legal_places(position)
    assert with_nodes <= without_nodes
    assert with_nodes < without_nodes
    assert alphabeta.choose_move(position) == with_place
    assert alphabeta.choose_at_depth(position, 4, table=True) == with_place
    assert alphabeta.choose_at_depth(position, 4, table=False) == without_place


def test_alphabeta_transposition_keeps_initial_root() -> None:
    position = initial_position()
    with_place, with_value, with_nodes = alphabeta.search_stats(
        position, alphabeta.SEARCH_DEPTH, table=True
    )
    without_place, without_value, without_nodes = alphabeta.search_stats(
        position, alphabeta.SEARCH_DEPTH, table=False
    )
    assert with_place == without_place == Place(Square.parse("d3"))
    assert with_value == without_value
    assert with_nodes <= without_nodes
    assert alphabeta.choose_move(position) == with_place
    assert alphabeta.SEARCH_DEPTH == 4


def test_alphabeta_engine_is_not_bitboard() -> None:
    engine_dir = Path(__file__).resolve().parents[1] / "src" / "reversi" / "engine"
    files = list(engine_dir.glob("*.py"))
    assert files
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "bitboard" not in text.lower()
    source = _module_source("alphabeta.py")
    assert "Zobrist" in source
    assert "transposition" in source.lower()
    assert "ハッシュ" in source


def _empty_squares(board: Board) -> int:
    return sum(stone is Stone.EMPTY for row in board.cells for stone in row)


def _disc_diff(board: Board, color: Color) -> int:
    own = color.stone
    diff = 0
    for row in board.cells:
        for stone in row:
            if stone is Stone.EMPTY:
                continue
            diff += 1 if stone is own else -1
    return diff


def _two_empty_white_plays_a1() -> Position:
    # a1 と h8 が空。b1 が黒、他は白。白は a1 に打つと終局し、h8 は残る。
    board = empty_board().replacing(
        {
            Square.parse("b1"): Stone.BLACK,
            **{
                Square(file=file, rank=rank): Stone.WHITE
                for rank in range(8)
                for file in range(8)
                if (file, rank) not in {(0, 0), (1, 0), (7, 7)}
            },
        }
    )
    return Position(board, Color.WHITE)


# 空きマス 8。完全読みなら a1 が石数差 +44。深さ 4 の葉はヒューリスティック。
_ENDGAME_WIN_ON_A1 = (
    "..WWWWWB",
    "..WWWWWB",
    ".WWWWBBB",
    "BWWWBBBB",
    "BWWWWWBB",
    "BWBBWWWB",
    "BWWWBWBB",
    ".WW..BBB",
)

# 空きマス 11。深さ 4 の Phase 4 葉なら h7、終局石数差なら d7。
_MIDGAME_ELEVEN_EMPTY = (
    "....WBBW",
    "....BWB.",
    "..WBBBWB",
    "WBBBWWWW",
    "WBBBWBWW",
    "BBWBBWWW",
    "WWWWWWWW",
    "WWWWWWWW",
)

# 空きマスちょうど 10。深さ 4 の葉はヒューリスティック。
_ENDGAME_TEN_EMPTY = (
    "..BBBBBB",
    ".BBBBBBB",
    "B.BBBBB.",
    "BBBWWBBB",
    "BBWWWBB.",
    "BBBBWWW.",
    "W.BBBWWW",
    ".BBB.BBB",
)


def test_alphabeta_short_endgame_uses_heuristic_leaf() -> None:
    position = _two_empty_white_plays_a1()
    assert _empty_squares(position.board) == 2
    places = legal_places(position)
    assert places == (Square.parse("a1"),)
    move, value, nodes = alphabeta.search_stats(position, alphabeta.SEARCH_DEPTH)
    assert move == Place(Square.parse("a1"))
    assert nodes >= 1
    after = play(position, move)
    assert is_over(after)
    counts = stone_counts(after.board)
    assert counts.empty == 1
    disc = _disc_diff(after.board, Color.WHITE)
    official = official_score(after.board)
    child_heuristic = alphabeta.leaf_score(after.board, after.side_to_move)
    assert disc == 63
    assert official.white - official.black == 64
    assert child_heuristic == _phase4_leaf_score(after.board, after.side_to_move)
    assert value == -child_heuristic
    assert value != disc
    assert value != official.white - official.black
    assert alphabeta.choose_move(position) == move
    assert alphabeta.choose_move(position) == alphabeta.choose_at_depth(position, 4)


def test_alphabeta_eight_empty_keeps_depth_four() -> None:
    position = _position_from_rank8_rows(_ENDGAME_WIN_ON_A1, Color.BLACK)
    assert _empty_squares(position.board) == 8
    places = {square.algebraic for square in legal_places(position)}
    assert "a1" in places
    assert "e1" in places
    assert "b7" in places
    move, value, _nodes = alphabeta.search_stats(position, alphabeta.SEARCH_DEPTH)
    assert move == Place(Square.parse("a1"))
    assert value == 4140
    assert abs(value) > BOARD_SIZE * BOARD_SIZE
    heuristic_now = alphabeta.leaf_score(position.board, Color.BLACK)
    assert heuristic_now == _phase4_leaf_score(position.board, Color.BLACK)
    assert alphabeta.choose_move(position) == move
    assert catalog_choose(alphabeta.SPECIMEN_ID, position) == move
    assert alphabeta.choose_move(position) == alphabeta.choose_at_depth(position, 4)
    assert minimax.choose_move(position) == Place(Square.parse("b8"))
    assert minimax.choose_move(position) != move


def test_alphabeta_above_endgame_keeps_depth_four_leaf() -> None:
    position = _position_from_rank8_rows(_MIDGAME_ELEVEN_EMPTY, Color.WHITE)
    assert _empty_squares(position.board) == 11
    places = {square.algebraic for square in legal_places(position)}
    assert "h7" in places
    assert "d7" in places
    move, value, _nodes = alphabeta.search_stats(position, alphabeta.SEARCH_DEPTH)
    assert move == Place(Square.parse("h7"))
    assert value == 5410
    assert abs(value) > BOARD_SIZE * BOARD_SIZE
    assert alphabeta.choose_move(position) == move
    assert alphabeta.choose_move(position) == alphabeta.choose_at_depth(position, 4)
    assert alphabeta.SEARCH_DEPTH == 4


def test_alphabeta_ten_empty_keeps_depth_four() -> None:
    position = _position_from_rank8_rows(_ENDGAME_TEN_EMPTY, Color.BLACK)
    assert _empty_squares(position.board) == 10
    places = {square.algebraic for square in legal_places(position)}
    assert places == {"a1", "h3"}
    move, value, _nodes = alphabeta.search_stats(position, alphabeta.SEARCH_DEPTH)
    assert move == Place(Square.parse("a1"))
    assert value == 4660
    assert abs(value) > BOARD_SIZE * BOARD_SIZE
    heuristic_now = alphabeta.leaf_score(position.board, Color.BLACK)
    assert heuristic_now == _phase4_leaf_score(position.board, Color.BLACK)
    assert alphabeta.choose_move(position) == move
    assert alphabeta.choose_at_depth(position, 4) == move


def test_alphabeta_does_not_extend_search_in_endgame() -> None:
    assert not hasattr(alphabeta, "ENDGAME_EMPTY")
    snapshot = alphabeta.SEARCH_DEPTH
    alphabeta.choose_move(initial_position())
    eight = _position_from_rank8_rows(_ENDGAME_WIN_ON_A1, Color.BLACK)
    eleven = _position_from_rank8_rows(_MIDGAME_ELEVEN_EMPTY, Color.WHITE)
    two = _two_empty_white_plays_a1()
    assert alphabeta.choose_move(eight) == alphabeta.choose_at_depth(eight, 4)
    assert alphabeta.choose_move(eleven) == alphabeta.choose_at_depth(eleven, 4)
    assert alphabeta.choose_move(two) == alphabeta.choose_at_depth(two, 4)
    assert alphabeta.SEARCH_DEPTH == snapshot == 4
    source = _module_source("alphabeta.py")
    assert "ENDGAME_EMPTY" not in source
    assert "完全読み" not in source
    assert "endgame" not in _module_source("minimax.py").lower()
    assert "完全読み" not in _module_source("minimax.py")


def test_alphabeta_eval_record_has_paired_acceptance() -> None:
    root = Path(__file__).resolve().parents[2] / "docs" / "benchmarks"
    records = sorted(root.glob("alphabeta-eval*.json"))
    assert records, "αβ 対ミニマックスの評価 JSON が無い"
    data = json.loads(records[-1].read_text(encoding="utf-8"))
    for key in (
        "games",
        "win_rate",
        "mean_stone_diff",
        "mean_nodes",
        "mean_think_seconds",
        "max_think_seconds",
        "paired",
        "accepted",
    ):
        assert key in data, key
    assert data["paired"] is True
    assert data.get("complete") is False
    assert data.get("stopped_early") is True
    assert data["games"] >= 20
    assert data["games"] == len(data["game_records"])
    assert data["games"] < 2 * len(data["starts"])
    assert isinstance(data["accepted"], bool)
    assert data["accepted"] is False
    assert data.get("looks_strong") is True
    assert data["win_rate"] >= 0.70
    assert alphabeta.SEARCH_DEPTH == 4
    assert minimax.SEARCH_DEPTH == 4
    assert data["candidate"]["specimen_id"] == alphabeta.SPECIMEN_ID
    assert data["candidate"]["search_depth"] == 6
    assert data["candidate"]["search_depth"] != alphabeta.SEARCH_DEPTH
    assert data["candidate"]["endgame_empty"] == 10
    assert not hasattr(alphabeta, "ENDGAME_EMPTY")
    assert data["opponent"]["specimen_id"] == minimax.SPECIMEN_ID
    assert data["opponent"]["search_depth"] == minimax.SEARCH_DEPTH
    games = data["game_records"]
    wins = sum(1 for row in games if row["result"] == "win")
    draws = sum(1 for row in games if row["result"] == "draw")
    losses = sum(1 for row in games if row["result"] == "loss")
    n = len(games)
    assert data["wins"] == wins
    assert data["draws"] == draws
    assert data["losses"] == losses
    assert data["win_rate"] == (wins + 0.5 * draws) / n
    assert data["mean_stone_diff"] == sum(int(row["stone_diff"]) for row in games) / n
    by_key = {(int(row["start_index"]), row["alphabeta_color"]): row for row in games}
    pairs = data["paired_results"]
    assert len(pairs) >= 10
    assert len(pairs) < len(data["starts"])
    for pair in pairs:
        black = by_key[(int(pair["start_index"]), "black")]
        white = by_key[(int(pair["start_index"]), "white")]
        assert pair["black"]["alphabeta_color"] == "black"
        assert pair["white"]["alphabeta_color"] == "white"
        assert pair["black"]["result"] == black["result"]
        assert pair["white"]["result"] == white["result"]
        assert pair["black"]["stone_diff"] == black["stone_diff"]
        assert pair["white"]["stone_diff"] == white["stone_diff"]
        assert pair["pair_stone_diff"] == (
            int(black["stone_diff"]) + int(white["stone_diff"])
        ) / 2
    assert data.get("stop_reason") == "code_owner_instruction"
    assert data["catalog_policy"] == "keep_phase6"
    script = (root / "alphabeta_eval.py").read_text(encoding="utf-8")
    assert "keep_phase6" not in script
    assert "keep_depth4_no_exact" in script
    assert "keep_depth4_no_exact_until_retry" in script
    assert [item.display_name for item in items()].count("ルールベース (αβ)") == 1
    assert [item.display_name for item in items()].count("ルールベース (ミニマックス)") == 1
    report = root / "alphabeta-eval.md"
    assert report.is_file(), "αβ 評価のレポートが無い"
    text = report.read_text(encoding="utf-8")
    assert "コードオーナー" in text
    assert "強そう" in text


def test_alphabeta_eval_script_keeps_stopped_record(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    source = root / "docs" / "benchmarks" / "alphabeta-eval.json"
    dest = tmp_path / "alphabeta-eval.json"
    dest.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    before = dest.read_bytes()
    script = root / "docs" / "benchmarks" / "alphabeta_eval.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--output", str(dest)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "打ち切り済み" in completed.stderr
    assert dest.read_bytes() == before


def test_alphabeta_eval_resume_requires_endgame_empty() -> None:
    import importlib.util

    root = Path(__file__).resolve().parents[2]
    path = root / "docs" / "benchmarks" / "alphabeta_eval.py"
    spec = importlib.util.spec_from_file_location("alphabeta_eval_resume", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = json.loads(
        (root / "docs" / "benchmarks" / "alphabeta-eval.json").read_text(encoding="utf-8")
    )
    seed = int(data["protocol"]["seed"])
    n_starts = int(data["protocol"]["starts"])
    assert data["candidate"]["search_depth"] == 6
    assert data["candidate"]["endgame_empty"] == 10
    assert alphabeta.SEARCH_DEPTH == 4
    assert not hasattr(alphabeta, "ENDGAME_EMPTY")
    assert not module._progress_matches(data, seed, n_starts)
    data["candidate"]["search_depth"] = alphabeta.SEARCH_DEPTH
    assert not module._progress_matches(data, seed, n_starts)
    data["candidate"]["endgame_empty"] = 0
    assert module._progress_matches(data, seed, n_starts)
    data["candidate"]["endgame_empty"] = 10
    assert not module._progress_matches(data, seed, n_starts)


def test_alphabeta_leaf_penalizes_x_on_empty_corner() -> None:
    danger = empty_board().replacing(
        {
            Square.parse("b2"): Stone.BLACK,
            Square.parse("e5"): Stone.WHITE,
        }
    )
    inner = empty_board().replacing(
        {
            Square.parse("c3"): Stone.BLACK,
            Square.parse("e5"): Stone.WHITE,
        }
    )
    danger_parts = _phase4_parts(danger, Color.BLACK)
    inner_parts = _phase4_parts(inner, Color.BLACK)
    assert danger_parts[0] == inner_parts[0] == 0
    assert danger_parts[1] == inner_parts[1] == 0
    assert danger_parts[2] == inner_parts[2] == 0
    assert danger_parts[4] == inner_parts[4] == 0
    assert danger_parts[5] == inner_parts[5] == 0
    assert danger_parts[3] == 1
    assert inner_parts[3] == 0
    danger_score = alphabeta.leaf_score(danger, Color.BLACK)
    inner_score = alphabeta.leaf_score(inner, Color.BLACK)
    assert danger_score == _phase4_leaf_score(danger, Color.BLACK) == -150
    assert inner_score == _phase4_leaf_score(inner, Color.BLACK) == 0
    assert danger_score < inner_score


def test_alphabeta_leaf_penalizes_c_on_empty_corner() -> None:
    danger = empty_board().replacing(
        {
            Square.parse("a2"): Stone.BLACK,
            Square.parse("e5"): Stone.WHITE,
        }
    )
    inner = empty_board().replacing(
        {
            Square.parse("c3"): Stone.BLACK,
            Square.parse("e5"): Stone.WHITE,
        }
    )
    danger_parts = _phase4_parts(danger, Color.BLACK)
    inner_parts = _phase4_parts(inner, Color.BLACK)
    assert danger_parts[0] == inner_parts[0] == 0
    assert danger_parts[1] == inner_parts[1] == 0
    assert danger_parts[2] == inner_parts[2] == 0
    assert danger_parts[3] == inner_parts[3] == 0
    assert danger_parts[5] == inner_parts[5] == 0
    assert danger_parts[4] == 1
    assert inner_parts[4] == 0
    danger_score = alphabeta.leaf_score(danger, Color.BLACK)
    inner_score = alphabeta.leaf_score(inner, Color.BLACK)
    assert danger_score == _phase4_leaf_score(danger, Color.BLACK) == -80
    assert inner_score == _phase4_leaf_score(inner, Color.BLACK) == 0
    assert danger_score < inner_score


def test_alphabeta_leaf_releases_xc_after_owning_corner() -> None:
    x_danger = empty_board().replacing(
        {
            Square.parse("b2"): Stone.BLACK,
            Square.parse("e5"): Stone.WHITE,
        }
    )
    x_held = empty_board().replacing(
        {
            Square.parse("a1"): Stone.BLACK,
            Square.parse("b2"): Stone.BLACK,
            Square.parse("e5"): Stone.WHITE,
        }
    )
    c_danger = empty_board().replacing(
        {
            Square.parse("a2"): Stone.BLACK,
            Square.parse("e5"): Stone.WHITE,
        }
    )
    c_held = empty_board().replacing(
        {
            Square.parse("a1"): Stone.BLACK,
            Square.parse("a2"): Stone.BLACK,
            Square.parse("e5"): Stone.WHITE,
        }
    )
    assert _phase4_parts(x_danger, Color.BLACK)[3] == 1
    assert _phase4_parts(x_held, Color.BLACK)[3] == 0
    assert _phase4_parts(c_danger, Color.BLACK)[4] == 1
    assert _phase4_parts(c_held, Color.BLACK)[4] == 0
    assert alphabeta.leaf_score(x_danger, Color.BLACK) == _phase4_leaf_score(
        x_danger, Color.BLACK
    )
    assert alphabeta.leaf_score(x_held, Color.BLACK) == _phase4_leaf_score(
        x_held, Color.BLACK
    )
    assert alphabeta.leaf_score(c_danger, Color.BLACK) == _phase4_leaf_score(
        c_danger, Color.BLACK
    )
    assert alphabeta.leaf_score(c_held, Color.BLACK) == _phase4_leaf_score(
        c_held, Color.BLACK
    )
    assert alphabeta.leaf_score(x_danger, Color.BLACK) < alphabeta.leaf_score(
        x_held, Color.BLACK
    )
    assert alphabeta.leaf_score(c_danger, Color.BLACK) < alphabeta.leaf_score(
        c_held, Color.BLACK
    )


def test_alphabeta_leaf_prefers_fewer_own_frontier() -> None:
    few = empty_board().replacing(
        {
            Square.parse("c3"): Stone.BLACK,
            Square.parse("d3"): Stone.BLACK,
            Square.parse("e3"): Stone.BLACK,
            Square.parse("c4"): Stone.BLACK,
            Square.parse("d4"): Stone.BLACK,
            Square.parse("e4"): Stone.BLACK,
            Square.parse("c5"): Stone.BLACK,
            Square.parse("d5"): Stone.BLACK,
            Square.parse("e5"): Stone.BLACK,
            Square.parse("f3"): Stone.WHITE,
            Square.parse("g3"): Stone.WHITE,
            Square.parse("h3"): Stone.WHITE,
            Square.parse("f4"): Stone.WHITE,
            Square.parse("g4"): Stone.WHITE,
            Square.parse("h4"): Stone.WHITE,
            Square.parse("f5"): Stone.WHITE,
            Square.parse("g5"): Stone.WHITE,
            Square.parse("h5"): Stone.WHITE,
        }
    )
    many = empty_board().replacing(
        {
            Square.parse("c3"): Stone.BLACK,
            Square.parse("d3"): Stone.BLACK,
            Square.parse("e3"): Stone.BLACK,
            Square.parse("c4"): Stone.BLACK,
            Square.parse("e4"): Stone.BLACK,
            Square.parse("c5"): Stone.BLACK,
            Square.parse("d5"): Stone.BLACK,
            Square.parse("e5"): Stone.BLACK,
            Square.parse("b4"): Stone.BLACK,
            Square.parse("f3"): Stone.WHITE,
            Square.parse("g3"): Stone.WHITE,
            Square.parse("h3"): Stone.WHITE,
            Square.parse("f4"): Stone.WHITE,
            Square.parse("g4"): Stone.WHITE,
            Square.parse("h4"): Stone.WHITE,
            Square.parse("f5"): Stone.WHITE,
            Square.parse("g5"): Stone.WHITE,
            Square.parse("h5"): Stone.WHITE,
        }
    )
    few_parts = _phase4_parts(few, Color.BLACK)
    many_parts = _phase4_parts(many, Color.BLACK)
    assert few_parts[1] == many_parts[1]
    assert few_parts[2] == many_parts[2]
    assert few_parts[3] == many_parts[3]
    assert few_parts[4] == many_parts[4]
    assert few_parts[0] == many_parts[0]
    assert few_parts[5] < many_parts[5]
    few_score = alphabeta.leaf_score(few, Color.BLACK)
    many_score = alphabeta.leaf_score(many, Color.BLACK)
    assert few_score == _phase4_leaf_score(few, Color.BLACK)
    assert many_score == _phase4_leaf_score(many, Color.BLACK)
    assert few_score > many_score


def test_alphabeta_leaf_disc_weight_follows_empty_count() -> None:
    assert _phase4_disc_weight(40) == 1
    assert _phase4_disc_weight(39) == 5
    assert _phase4_disc_weight(20) == 5
    assert _phase4_disc_weight(19) == 20
    assert _phase4_disc_weight(10) == 20
    assert _phase4_disc_weight(9) == 100
    assert _phase4_disc_weight(9) > _phase4_disc_weight(40)
    samples = (40, 39, 20, 19, 10, 9)
    for empty in samples:
        board = _board_with_empty_black_lead(empty)
        parts = _phase4_parts(board, Color.BLACK)
        assert parts[6] == empty
        assert parts[2] != 0
        score = alphabeta.leaf_score(board, Color.BLACK)
        assert score == _phase4_leaf_score(board, Color.BLACK)
    early = _board_with_empty_black_lead(40)
    late = _board_with_empty_black_lead(9)
    early_mob, early_corner, early_disc, early_x, early_c, early_f, _ = _phase4_parts(
        early, Color.BLACK
    )
    late_mob, late_corner, late_disc, late_x, late_c, late_f, _ = _phase4_parts(
        late, Color.BLACK
    )
    assert early_disc != 0 and late_disc != 0
    early_other = (
        50 * early_mob
        + 1000 * early_corner
        - 150 * early_x
        - 80 * early_c
        - 10 * early_f
    )
    late_other = (
        50 * late_mob + 1000 * late_corner - 150 * late_x - 80 * late_c - 10 * late_f
    )
    early_weight = (alphabeta.leaf_score(early, Color.BLACK) - early_other) / early_disc
    late_weight = (alphabeta.leaf_score(late, Color.BLACK) - late_other) / late_disc
    assert early_weight == 1
    assert late_weight == 100
    assert late_weight > early_weight


def _play_algebraic(*names: str) -> Position:
    position = initial_position()
    for name in names:
        position = play(position, Place(Square.parse(name)))
    return position


def test_catalog_lists_opening_specimen() -> None:
    item = _item_by_display_name("ルールベース (定石)")
    assert item.specimen_id == opening.SPECIMEN_ID == "opening"
    assert item.category == opening.CATEGORY == "rule_based"
    assert item.display_name == opening.DISPLAY_NAME
    assert item.description == opening.DESCRIPTION
    assert item.description.strip()
    assert _JAPANESE.search(item.description)
    assert "定石" in item.description
    assert "位置評価" in item.description
    assert get(opening.SPECIMEN_ID) == item
    with pytest.raises(KeyError):
        get("rule_based")


def test_opening_book_lines_are_tiger_cow_mouse_and_fixed() -> None:
    expected = (
        ("f5", "d6", "c3", "d3", "c4"),
        ("f5", "f6", "e6", "d6", "c5"),
        ("f5", "f4", "e3", "f6", "d3"),
    )
    snapshot = tuple(
        tuple(square.algebraic for square in line) for line in opening.BOOK_LINES
    )
    assert snapshot == expected
    assert isinstance(opening.BOOK_LINES, tuple)
    assert all(isinstance(line, tuple) for line in opening.BOOK_LINES)
    opening.choose_move(initial_position())
    opening.choose_move(_play_algebraic("f5"))
    opening.choose_move(_play_algebraic("f5", "d6", "c4"))
    after = tuple(
        tuple(square.algebraic for square in line) for line in opening.BOOK_LINES
    )
    assert after == snapshot == expected
    assert len(opening.BOOK_LINES) == 3


def test_opening_initial_picks_d3_among_four_symmetric_first_moves() -> None:
    position = initial_position()
    places = legal_places(position)
    assert [square.algebraic for square in places] == ["d3", "c4", "f5", "e6"]
    move = opening.choose_move(position)
    assert move == Place(Square.parse("d3"))
    assert opening.choose_move(position, Random(0)) == move
    via_catalog = catalog_choose(opening.SPECIMEN_ID, position)
    assert via_catalog == move


def test_opening_after_f5_picks_f4_by_a1_to_h8_order() -> None:
    # 虎 d6・牛 f6・鼠 f4。FUN-014 は a1, b1, …, h1, a2, …, h8 なので f4。
    position = _play_algebraic("f5")
    places = legal_places(position)
    assert [square.algebraic for square in places] == ["f4", "d6", "f6"]
    move = opening.choose_move(position)
    assert move == Place(Square.parse("f4"))
    assert positional.choose_move(position) == Place(Square.parse("f6"))
    assert move != positional.choose_move(position)
    assert catalog_choose(opening.SPECIMEN_ID, position) == move


def test_opening_follows_each_canonical_line() -> None:
    assert opening.choose_move(_play_algebraic("f5", "d6")) == Place(Square.parse("c3"))
    assert opening.choose_move(_play_algebraic("f5", "f6")) == Place(Square.parse("e6"))
    assert opening.choose_move(_play_algebraic("f5", "f4")) == Place(Square.parse("e3"))
    assert opening.choose_move(_play_algebraic("f5", "d6", "c3")) == Place(
        Square.parse("d3")
    )
    assert opening.choose_move(_play_algebraic("f5", "f6", "e6")) == Place(
        Square.parse("d6")
    )
    assert opening.choose_move(_play_algebraic("f5", "f4", "e3")) == Place(
        Square.parse("f6")
    )


def test_opening_symmetric_c4_first_move_stays_on_book() -> None:
    position = _play_algebraic("c4")
    places = legal_places(position)
    assert Square.parse("c3") in places
    move = opening.choose_move(position)
    assert move == Place(Square.parse("c3"))
    assert move.square in places


def test_opening_off_book_matches_positional() -> None:
    position = _play_algebraic("f5", "d6", "c4")
    move = opening.choose_move(position)
    assert move == positional.choose_move(position)
    assert move == positional.choose_move(position, Random(1))
    assert catalog_choose(opening.SPECIMEN_ID, position) == move


def test_opening_after_complete_line_matches_positional() -> None:
    tiger = _play_algebraic("f5", "d6", "c3", "d3", "c4")
    cow = _play_algebraic("f5", "f6", "e6", "d6", "c5")
    mouse = _play_algebraic("f5", "f4", "e3", "f6", "d3")
    assert opening.choose_move(tiger) == positional.choose_move(tiger)
    assert opening.choose_move(cow) == positional.choose_move(cow)
    assert opening.choose_move(mouse) == positional.choose_move(mouse)


def test_opening_after_pass_matches_positional() -> None:
    passed = play(_almost_full_white_with_black_on_b1(), PassMove())
    assert legal_places(passed)
    assert opening.choose_move(passed) == positional.choose_move(passed)


def test_opening_stays_off_book_after_pass_then_place() -> None:
    passed = play(_almost_full_white_with_black_on_b1(), PassMove())
    assert passed.passed is True
    after_place = play(passed, Place(Square.parse("a1")))
    assert after_place.passed is True
    assert after_place.placed == (Square.parse("a1"),)
    assert opening.choose_move(after_place) == positional.choose_move(after_place)


def test_opening_does_not_move_when_no_legal_places() -> None:
    assert opening.choose_move(_almost_full_white_with_black_on_b1()) is None
    assert opening.choose_move(_both_sides_cannot_place()) is None


def test_opening_source_does_not_call_models_or_wthor() -> None:
    for filename in ("opening.py", "catalog.py"):
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
                assert "openrouter.ai" not in lowered
                assert "wthor" not in lowered


def _nn_item():
    from reversi.agents import nn

    return nn, _item_by_display_name("ニューラルネットワーク (棋譜)")


def test_nn_catalog_lists_kifu_specimen() -> None:
    nn, item = _nn_item()
    assert item.specimen_id == nn.SPECIMEN_ID == "nn"
    assert item.category == nn.CATEGORY == "neural_network"
    assert item.display_name == nn.DISPLAY_NAME
    assert item.description == nn.DESCRIPTION
    assert item.description.strip()
    assert "WTHOR" in item.description
    assert "永続化" in item.description
    assert "ニューラルネットワーク" in item.description
    assert _JAPANESE.search(item.description)
    assert get(nn.SPECIMEN_ID) == item
    with pytest.raises(KeyError):
        get("neural_network")


def test_nn_choose_move_matches_masked_onnx_logits() -> None:
    from reversi.agents import nn

    assert nn.DEFAULT_MODEL_PATH.is_file()
    position = initial_position()
    logits = nn.infer_logits(position.board)
    assert len(logits) == 64
    move = nn.choose_move(position)
    expected = nn.masked_place(position, logits)
    assert move == expected
    assert move is not None
    assert move.square in legal_places(position)
    via_catalog = catalog_choose(nn.SPECIMEN_ID, position)
    assert via_catalog == move
    assert nn.choose_move(position, Random(0)) == move


def test_nn_masks_illegal_squares_with_highest_logit() -> None:
    from reversi.agents import nn

    position = initial_position()
    places = legal_places(position)
    assert Square.parse("a1") not in places
    assert Square.parse("c4") in places
    logits = [0.0] * 64
    logits[nn.square_index(Square.parse("a1"))] = 100.0
    logits[nn.square_index(Square.parse("c4"))] = 50.0
    logits[nn.square_index(Square.parse("d3"))] = 1.0
    move = nn.choose_move(position, logits=tuple(logits))
    assert move == Place(Square.parse("c4"))


def test_nn_tie_breaks_a1_to_h8_order() -> None:
    from reversi.agents import nn

    position = initial_position()
    places = legal_places(position)
    logits = tuple(0.0 for _ in range(64))
    move = nn.choose_move(position, logits=logits)
    assert move == Place(places[0])
    assert move == Place(Square.parse("d3"))


def test_nn_does_not_move_when_no_legal_places() -> None:
    from reversi.agents import nn

    logits = tuple(1.0 for _ in range(64))
    assert nn.choose_move(_almost_full_white_with_black_on_b1(), logits=logits) is None
    assert nn.choose_move(_both_sides_cannot_place(), logits=logits) is None


def test_nn_default_onnx_plays_only_legal_moves_to_the_end() -> None:
    from reversi.agents import nn

    position = initial_position()
    while not is_over(position):
        if pass_is_legal(position):
            position = play(position, PassMove())
            continue
        move = nn.choose_move(position)
        assert move is not None
        assert move.square in legal_places(position)
        position = play(position, move)
    assert is_over(position)


def test_nn_source_uses_onnxruntime_cpu_not_torch() -> None:
    source = _module_source("nn.py")
    roots = _imported_roots(source)
    assert "onnxruntime" in roots
    assert "torch" not in roots
    assert "sklearn" not in roots
    assert "openrouter" not in roots
    modules = set()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value != "CUDAExecutionProvider"
    assert "reversi.train" not in modules
    assert all(not name.startswith("reversi.train") for name in modules)
    assert "CPUExecutionProvider" in source


def _write_nn_wtb(path: Path, squares: tuple[Square, ...]) -> Path:
    from reversi.train.wthor import RECORD_SIZE_8X8, encode_8x8_move

    header = bytearray(16)
    header[0:4] = bytes((20, 26, 9, 19))
    header[4:8] = (1).to_bytes(4, "little")
    header[10:12] = (2026).to_bytes(2, "little")
    header[12] = 8
    record = bytearray(RECORD_SIZE_8X8)
    for index, square in enumerate(squares):
        record[8 + index] = encode_8x8_move(square)
    path.write_bytes(bytes(header) + bytes(record))
    return path


def test_nn_training_reads_wthor_and_persisted_games(tmp_path: Path) -> None:
    from reversi.api.persist import MODE_AGENT_VS_AGENT, save_if_over
    from reversi.train.nn import collect_examples

    wthor = tmp_path / "wthor"
    wthor.mkdir()
    _write_nn_wtb(wthor / "tiny.wtb", (Square.parse("f5"),))
    db = tmp_path / "games.sqlite"
    save_if_over(
        _both_sides_cannot_place(),
        mode=MODE_AGENT_VS_AGENT,
        black={"kind": "specimen", "specimen_id": "nn"},
        white={"kind": "specimen", "specimen_id": "rl"},
        moves=({"type": "place", "square": "d3"},),
        db_path=db,
    )
    examples = collect_examples(wthor, db)
    labels = {example.square.algebraic for example in examples}
    assert "f5" in labels
    assert "d3" in labels
    assert all(example.board == initial_position().board for example in examples)


def test_nn_training_skips_corrupt_persisted_games(tmp_path: Path) -> None:
    import sqlite3

    from reversi.train.nn import collect_examples

    db = tmp_path / "games.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, moves TEXT NOT NULL)")
        conn.execute("INSERT INTO games (moves) VALUES (?)", ("not-json",))
        conn.execute("INSERT INTO games (moves) VALUES (?)", ("[1, 2]",))
        conn.execute(
            "INSERT INTO games (moves) VALUES (?)",
            ('[{"type": "place", "square": "f5"}]',),
        )
    examples = collect_examples(tmp_path / "missing-wthor", db)
    assert [example.square.algebraic for example in examples] == ["f5"]


def test_nn_training_writes_onnx_when_torch_is_installed(tmp_path: Path) -> None:
    pytest.importorskip("torch")
    pytest.importorskip("onnx")
    from reversi.agents.nn import infer_logits
    from reversi.train.nn import train_and_write

    out = tmp_path / "nn.onnx"
    n_examples = train_and_write(
        out,
        wthor=tmp_path / "missing-wthor",
        games=tmp_path / "missing.sqlite",
        hidden=8,
        epochs=1,
        seed=0,
    )
    assert n_examples == 0
    assert out.is_file()
    logits = infer_logits(initial_position().board, out)
    assert len(logits) == 64


def _toml_literal(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, int | float):
        return str(value)
    raise TypeError(type(value))


def _write_extra_genai(path: Path, entries: list[dict[str, object]]) -> Path:
    chunks: list[str] = []
    for entry in entries:
        chunks.append("[[generative_ai]]")
        for key, value in entry.items():
            chunks.append(f"{key} = {_toml_literal(value)}")
        chunks.append("")
    path.write_text("\n".join(chunks), encoding="utf-8")
    return path


def test_extra_genai_missing_config_does_not_add_specimens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(extra_genai, "CONFIG_PATH", tmp_path / "missing.toml")
    listed = items()
    names = [item.display_name for item in listed]
    assert names.count("生成 AI (Jev)") == 1
    generative = [item for item in listed if item.category == "generative_ai"]
    assert [item.display_name for item in generative] == ["生成 AI (Jev)"]
    assert all(not item.specimen_id.startswith("genai:") for item in listed)
    assert extra_genai.load() == ()


def test_extra_genai_does_not_preplace_opus_or_astra(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(extra_genai, "CONFIG_PATH", tmp_path / "missing.toml")
    names = [item.display_name for item in items()]
    lowered = " ".join(names).lower()
    assert "opus" not in lowered
    assert "astra" not in lowered
    assert "生成 AI (Opus)" not in names
    assert "生成 AI (Astra)" not in names


def test_extra_genai_config_adds_display_name_and_calls_model_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_id = "openai/gpt-test-not-a-catalog-default"
    config = _write_extra_genai(
        tmp_path / "config.toml",
        [{"model": model_id, "name": "GPT"}],
    )
    monkeypatch.setattr(extra_genai, "CONFIG_PATH", config)
    item = _item_by_display_name("生成 AI (GPT)")
    assert item.specimen_id == "genai:GPT"
    assert item.category == extra_genai.CATEGORY == "generative_ai"
    assert item.display_name == "生成 AI (GPT)"
    assert item.description.strip()
    assert _JAPANESE.search(item.description)
    assert model_id not in item.description
    assert "Chat Completions" in item.description
    assert "WTHOR" in item.description
    assert len(item.description) <= 100
    assert get(item.specimen_id) == item

    seen: dict[str, str] = {}

    def pick(_position, places, called_model_id: str, **_kwargs):
        seen["model_id"] = called_model_id
        return places[0]

    monkeypatch.setattr(chat_completions, "_call_openrouter", pick)
    position = initial_position()
    move = catalog_choose(item.specimen_id, position)
    assert seen["model_id"] == model_id
    assert move is not None
    assert move.square in legal_places(position)


def test_extra_genai_display_names_are_unique_in_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_extra_genai(
        tmp_path / "config.toml",
        [
            {"model": "vendor/one", "name": "One"},
            {"model": "vendor/two", "name": "Two"},
        ],
    )
    monkeypatch.setattr(extra_genai, "CONFIG_PATH", config)
    names = [item.display_name for item in items()]
    assert len(names) == len(set(names))
    assert names.count("生成 AI (One)") == 1
    assert names.count("生成 AI (Two)") == 1
    assert names.count("生成 AI (Jev)") == 1
    one = get("genai:One")
    two = get("genai:Two")
    assert one.display_name != two.display_name
    assert extra_genai.load()[0].model_id == "vendor/one"
    assert extra_genai.load()[1].model_id == "vendor/two"


def test_extra_genai_rejects_duplicate_display_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_extra_genai(
        tmp_path / "config.toml",
        [{"model": "vendor/other", "name": "Jev"}],
    )
    monkeypatch.setattr(extra_genai, "CONFIG_PATH", config)
    listed = items()
    names = [item.display_name for item in listed]
    assert "生成 AI (Jev)" in names
    assert all(not item.specimen_id.startswith("genai:") for item in listed)
    assert get(jev.SPECIMEN_ID).display_name == "生成 AI (Jev)"

    dup = _write_extra_genai(
        tmp_path / "dup.toml",
        [
            {"model": "vendor/a", "name": "Same"},
            {"model": "vendor/b", "name": "Same"},
        ],
    )
    monkeypatch.setattr(extra_genai, "CONFIG_PATH", dup)
    with pytest.raises(extra_genai.ConfigError, match="一意"):
        extra_genai.load()
    listed = items()
    assert get(jev.SPECIMEN_ID).display_name == "生成 AI (Jev)"
    assert all(not item.specimen_id.startswith("genai:") for item in listed)


def test_extra_genai_invalid_config_keeps_builtin_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = tmp_path / "config.toml"
    broken.write_text("{", encoding="utf-8")
    monkeypatch.setattr(extra_genai, "CONFIG_PATH", broken)
    with pytest.raises(extra_genai.ConfigError):
        extra_genai.load()
    listed = items()
    assert get(jev.SPECIMEN_ID) in listed
    assert all(not item.specimen_id.startswith("genai:") for item in listed)
    catalog_choose(SPECIMEN_ID, initial_position(), Random(0))


def test_extra_genai_picks_legal_place_from_chat_double(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_extra_genai(
        tmp_path / "config.toml",
        [{"model": "vendor/chat", "name": "Chat"}],
    )
    monkeypatch.setattr(extra_genai, "CONFIG_PATH", config)
    position = initial_position()
    places = legal_places(position)

    def pick_second(_position, legal, _model_id: str, **_kwargs):
        return legal[1]

    monkeypatch.setattr(chat_completions, "_call_openrouter", pick_second)
    move = catalog_choose("genai:Chat", position)
    assert move == Place(places[1])
    assert extra_genai.load()[0].choose_move(position) == move


def test_extra_genai_does_not_adopt_place_outside_legal_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_extra_genai(
        tmp_path / "config.toml",
        [{"model": "vendor/chat", "name": "Chat"}],
    )
    monkeypatch.setattr(extra_genai, "CONFIG_PATH", config)
    position = initial_position()
    illegal = Square.parse("a1")
    assert illegal not in legal_places(position)

    def pick_illegal(_position, _legal, _model_id: str, **_kwargs):
        return illegal

    monkeypatch.setattr(chat_completions, "_call_openrouter", pick_illegal)
    with pytest.raises(jev.ExternalModelError, match="合法手"):
        catalog_choose("genai:Chat", position)


def test_extra_genai_does_not_move_when_no_legal_places(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = {"n": 0}

    def should_not_run(_position, _legal, _model_id: str, **_kwargs):
        called["n"] += 1
        raise AssertionError("合法手が無い局面で OpenRouter を呼んではいけない")

    monkeypatch.setattr(chat_completions, "_call_openrouter", should_not_run)
    extra = extra_genai.ExtraSpecimen(
        specimen_id="genai:Chat",
        model_id="vendor/chat",
        display_name="生成 AI (Chat)",
        description="試験",
    )
    assert extra.choose_move(_almost_full_white_with_black_on_b1()) is None
    assert extra.choose_move(_both_sides_cannot_place()) is None
    assert called["n"] == 0


def test_extra_genai_config_passes_parameters_and_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_extra_genai(
        tmp_path / "config.toml",
        [
            {
                "model": "vendor/chat",
                "name": "Chat",
                "temperature": 0.2,
                "max_tokens": 32,
                "prompt": "chat-completions.md",
            }
        ],
    )
    monkeypatch.setattr(extra_genai, "CONFIG_PATH", config)
    extra = extra_genai.load()[0]
    assert extra.parameters == {"temperature": 0.2, "max_tokens": 32}
    assert extra.prompt_path == chat_completions.PROMPT_PATH
    seen: dict[str, object] = {}

    def pick(_position, places, called_model_id: str, **kwargs):
        seen["model_id"] = called_model_id
        seen["kwargs"] = kwargs
        return places[0]

    monkeypatch.setattr(chat_completions, "_call_openrouter", pick)
    position = initial_position()
    move = extra.choose_move(position)
    assert move is not None
    assert seen["model_id"] == "vendor/chat"
    kwargs = seen["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["parameters"] == {"temperature": 0.2, "max_tokens": 32}
    assert kwargs["prompt_path"] == chat_completions.PROMPT_PATH


def test_extra_genai_empty_toml_does_not_add_specimens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = tmp_path / "config.toml"
    empty.write_text("# 追加個体なし\n", encoding="utf-8")
    monkeypatch.setattr(extra_genai, "CONFIG_PATH", empty)
    assert extra_genai.load() == ()
    assert all(not item.specimen_id.startswith("genai:") for item in items())


def test_extra_genai_legacy_json_without_toml_is_config_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leftover = tmp_path / "genai.json"
    leftover.write_text(
        '[{"model_id": "vendor/old", "name": "Old"}]',
        encoding="utf-8",
    )
    monkeypatch.setattr(extra_genai, "CONFIG_PATH", tmp_path / "config.toml")
    with pytest.raises(extra_genai.ConfigError, match="config.toml に移して"):
        extra_genai.load()
    listed = items()
    assert get(jev.SPECIMEN_ID) in listed
    assert all(not item.specimen_id.startswith("genai:") for item in listed)


def test_extra_genai_rejects_out_of_range_parameters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = (
        (
            {"model": "vendor/chat", "name": "Chat", "temperature": float("nan")},
            "temperature",
        ),
        ({"model": "vendor/chat", "name": "Chat", "top_p": -0.1}, "top_p"),
        ({"model": "vendor/chat", "name": "Chat", "max_tokens": 0}, "max_tokens"),
    )
    for entry, key in cases:
        config = _write_extra_genai(tmp_path / f"{key}.toml", [entry])
        monkeypatch.setattr(extra_genai, "CONFIG_PATH", config)
        with pytest.raises(extra_genai.ConfigError, match=key):
            extra_genai.load()
        assert all(not item.specimen_id.startswith("genai:") for item in items())


def test_extra_genai_source_has_no_player_wizard() -> None:
    extra_source = _module_source("extra_genai.py")
    chat_source = _module_source("chat_completions.py")
    catalog_source = _module_source("catalog.py")
    assert "config.toml" in extra_source
    assert "ウィザード" in extra_source
    combined = extra_source + chat_source + catalog_source
    assert "wizard" not in combined.lower()
    roots = _imported_roots(extra_source)
    assert roots.isdisjoint(_FORBIDDEN_IMPORT_ROOTS)
    chat_roots = _imported_roots(chat_source)
    assert "openrouter" in chat_roots
    assert "wthor" not in chat_roots
    assert "https://openrouter.ai" in chat_source
    assert "chat.send" in chat_source or "chat" in chat_source
    assert "typesafe/jev-1.13" not in chat_source
    assert "Choose exactly one legal Reversi" not in chat_source
    assert "model_validate_json" in chat_source
    assert "response_format" in chat_source
    assert "json_schema" in chat_source
    assert "split()[0]" not in chat_source
    tree = ast.parse(chat_source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"getenv", "putenv"}
        ):
            raise AssertionError(
                "chat_completions.py は環境変数から鍵を読んではいけない"
            )
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            lowered = node.value.lower()
            assert "ffothello.org" not in lowered
            assert ".wtb" not in lowered
            assert "openrouter_api_key" not in lowered
