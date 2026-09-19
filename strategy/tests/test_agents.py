"""カタログと戦略個体（ランダム・最多取り・位置評価・ミニマックス・定石・強化学習・ニューラルネットワーク・生成 AI）。"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from random import Random

import pytest

from reversi.agents import jev, minimax, most_flips, opening, positional
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
from reversi.engine.board import Board, Color, Square, Stone, empty_board
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
        if specimen_id == jev.SPECIMEN_ID:
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
        positional.own_stone_score(apply_place(position.board, square, Color.BLACK), Color.BLACK)
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


def test_jev_source_uses_jev_model_and_skips_wthor() -> None:
    source = _module_source("jev.py")
    assert "typesafe/jev-1.13" in source
    assert "https://openrouter.ai" in source
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


def test_rl_training_does_not_read_wthor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert minimax.leaf_score(board, Color.BLACK) == _spec_leaf_score(board, Color.BLACK)
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
    snapshot = tuple(tuple(square.algebraic for square in line) for line in opening.BOOK_LINES)
    assert snapshot == expected
    assert isinstance(opening.BOOK_LINES, tuple)
    assert all(isinstance(line, tuple) for line in opening.BOOK_LINES)
    opening.choose_move(initial_position())
    opening.choose_move(_play_algebraic("f5"))
    opening.choose_move(_play_algebraic("f5", "d6", "c4"))
    after = tuple(tuple(square.algebraic for square in line) for line in opening.BOOK_LINES)
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
    assert opening.choose_move(_play_algebraic("f5", "d6", "c3")) == Place(Square.parse("d3"))
    assert opening.choose_move(_play_algebraic("f5", "f6", "e6")) == Place(Square.parse("d6"))
    assert opening.choose_move(_play_algebraic("f5", "f4", "e3")) == Place(Square.parse("f6"))


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

