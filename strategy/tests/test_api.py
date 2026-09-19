"""戦略 API: カタログ・1 局の開始・着手・違法拒否。"""

from __future__ import annotations

import ast
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reversi.agents.catalog import items as catalog_items
from reversi.agents.jev import SPECIMEN_ID as JEV_ID
from reversi.agents.jev import ExternalModelError
from reversi.agents.random_uniform import SPECIMEN_ID
from reversi.api import create_app
from reversi.api.schemas import (
    Catalog,
    GameState,
    GameUnplayable,
    IllegalMoveNotApplied,
    MoveApplied,
)
from reversi.api.session import GameStore
from reversi.engine.rules import initial_position, legal_places

_API_DIR = Path(__file__).resolve().parents[1] / "src" / "reversi" / "api"
_HUMAN = {"kind": "human"}
_SPECIMEN = {"kind": "specimen", "specimen_id": SPECIMEN_ID}
_GAME_KEYS = {
    "id",
    "board",
    "side_to_move",
    "legal_moves",
    "pass_is_legal",
    "last_move",
    "is_over",
    "official_score",
    "result",
    "status",
    "continuation_possible",
    "unplayable_reason",
    "black",
    "white",
}


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(GameStore(db_path=tmp_path / "games.sqlite")))


def _problem(response, status: int, code: str) -> dict:
    assert response.status_code == status
    assert "application/problem+json" in response.headers["content-type"]
    body = response.json()
    assert set(body) == {"type", "title", "status", "detail", "code"}
    assert body["status"] == status
    assert body["code"] == code
    assert body["type"] == f"urn:reversi-ai:error:{code}"
    assert body["detail"]
    assert body["title"]
    return body


def _game_state(payload: dict) -> GameState:
    assert set(payload) == _GAME_KEYS
    return GameState.model_validate(payload)


def _create(client: TestClient, black: dict, white: dict) -> GameState:
    response = client.post("/api/games", json={"black": black, "white": white})
    assert response.status_code == 201, response.text
    game = _game_state(response.json())
    assert response.headers["location"] == f"/api/games/{game.id}"
    return game


def test_catalog_get_lists_specimens(client: TestClient) -> None:
    response = client.get("/api/catalog")
    assert response.status_code == 200
    body = Catalog.model_validate(response.json())
    listed = catalog_items()
    assert [item.specimen_id for item in body.items] == [
        item.specimen_id for item in listed
    ]
    match = next(item for item in body.items if item.specimen_id == SPECIMEN_ID)
    assert match.category == "random"
    assert match.display_name == "ランダム (一様)"
    assert match.description


def test_cannot_start_game_without_catalog_selection(client: TestClient) -> None:
    _problem(client.post("/api/games", json={}), 400, "validation_error")
    _problem(
        client.post("/api/games", json={"black": _HUMAN}),
        400,
        "validation_error",
    )
    _problem(
        client.post(
            "/api/games",
            json={
                "black": {"kind": "specimen"},
                "white": _HUMAN,
            },
        ),
        400,
        "validation_error",
    )
    _problem(
        client.post(
            "/api/games",
            json={
                "black": {"kind": "specimen", "specimen_id": "random"},
                "white": _HUMAN,
            },
        ),
        404,
        "specimen_not_found",
    )
    _problem(
        client.post(
            "/api/games",
            json={
                "black": {"kind": "specimen", "specimen_id": "missing"},
                "white": _HUMAN,
            },
        ),
        404,
        "specimen_not_found",
    )
    assert client.get("/api/catalog").status_code == 200


def test_human_vs_agent_human_can_be_black_or_white(client: TestClient) -> None:
    as_black = _create(client, _HUMAN, _SPECIMEN)
    assert as_black.black.kind == "human"
    assert as_black.white.kind == "specimen"
    assert as_black.side_to_move == "black"
    assert as_black.last_move is None
    assert as_black.status == "in_progress"
    assert as_black.official_score.black == 2
    assert as_black.official_score.white == 2
    opening = {square.algebraic for square in legal_places(initial_position())}
    assert set(as_black.legal_moves) == opening

    as_white = _create(client, _SPECIMEN, _HUMAN)
    assert as_white.black.kind == "specimen"
    assert as_white.white.kind == "human"
    assert as_white.last_move is not None
    assert as_white.last_move.type == "place"
    assert as_white.side_to_move == "white"
    assert as_white.is_over is False
    stones = sum(cell != "empty" for row in as_white.board for cell in row)
    assert stones == 5


def test_illegal_move_does_not_change_board_and_can_be_retried(
    client: TestClient,
) -> None:
    game = _create(client, _HUMAN, _SPECIMEN)
    before = client.get(f"/api/games/{game.id}").json()
    rejected = client.post(
        f"/api/games/{game.id}/moves",
        json={"type": "place", "square": "a1"},
    )
    assert rejected.status_code == 409
    body = IllegalMoveNotApplied.model_validate(rejected.json())
    assert body.applied is False
    assert body.code == "illegal_move"
    assert body.game.board == GameState.model_validate(before).board
    assert body.game.side_to_move == "black"
    after = client.get(f"/api/games/{game.id}").json()
    assert after == before

    legal = game.legal_moves[0]
    applied = client.post(
        f"/api/games/{game.id}/moves",
        json={"type": "place", "square": legal},
    )
    assert applied.status_code == 200
    payload = MoveApplied.model_validate(applied.json())
    assert payload.applied is True
    file_i = ord(legal[0]) - ord("a")
    rank_i = int(legal[1]) - 1
    assert payload.game.board[rank_i][file_i] == "black"


def test_legal_move_updates_board_and_side_to_move(client: TestClient) -> None:
    game = _create(client, _HUMAN, _HUMAN)
    square = game.legal_moves[0]
    applied = client.post(
        f"/api/games/{game.id}/moves",
        json={"type": "place", "square": square},
    )
    payload = MoveApplied.model_validate(applied.json())
    assert payload.applied is True
    assert payload.game.last_move is not None
    assert payload.game.last_move.type == "place"
    assert payload.game.last_move.square == square
    assert payload.game.side_to_move == "white"
    assert payload.game.status == "in_progress"
    file_i = ord(square[0]) - ord("a")
    rank_i = int(square[1]) - 1
    assert payload.game.board[rank_i][file_i] == "black"
    assert payload.game.official_score.black == 4
    assert payload.game.official_score.white == 1


def _wait_until_over(client: TestClient, game_id: str) -> GameState:
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        response = client.get(f"/api/games/{game_id}")
        assert response.status_code == 200, response.text
        game = _game_state(response.json())
        if game.is_over or game.status != "in_progress":
            return game
        time.sleep(0.01)
    raise AssertionError("人手の着手なしに終局まで進まなかった")


def test_agent_vs_agent_completes_without_waiting_for_human(
    client: TestClient,
) -> None:
    game = _create(client, _SPECIMEN, _SPECIMEN)
    assert game.black.kind == "specimen"
    assert game.white.kind == "specimen"
    assert game.last_move is None
    assert game.is_over is False
    finished = _wait_until_over(client, game.id)
    assert finished.is_over is True
    assert finished.status == "completed"
    assert finished.continuation_possible is False
    assert finished.result is not None
    assert finished.result.winner in {"black", "white", "draw"}
    assert finished.official_score.black + finished.official_score.white == 64
    assert finished.last_move is not None
    rejected = client.post(
        f"/api/games/{game.id}/moves",
        json={"type": "place", "square": "d3"},
    )
    assert rejected.status_code == 409


def test_new_game_can_start_during_or_after(client: TestClient) -> None:
    first = _create(client, _HUMAN, _SPECIMEN)
    client.post(
        f"/api/games/{first.id}/moves",
        json={"type": "place", "square": first.legal_moves[0]},
    )
    second = _create(client, _HUMAN, _SPECIMEN)
    assert second.id != first.id
    assert second.last_move is None
    assert second.side_to_move == "black"
    assert second.official_score.black == 2
    assert second.official_score.white == 2
    _problem(client.get(f"/api/games/{first.id}"), 404, "game_not_found")
    got = _game_state(client.get(f"/api/games/{second.id}").json())
    assert got.id == second.id

    finished = _create(client, _SPECIMEN, _SPECIMEN)
    done = _wait_until_over(client, finished.id)
    assert done.is_over is True
    again = _create(client, _HUMAN, _SPECIMEN)
    assert again.is_over is False
    assert again.last_move is None
    _problem(client.get(f"/api/games/{finished.id}"), 404, "game_not_found")


def test_module_entrypoint_is_python_m_reversi_api() -> None:
    from reversi.api.__main__ import HOST, PORT, main

    assert HOST == "0.0.0.0"
    assert PORT == 8000
    assert callable(main)


def test_api_package_does_not_import_train() -> None:
    for path in sorted(_API_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("reversi.train")
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("reversi.train")
    for name in list(sys.modules):
        if name == "reversi.train" or name.startswith("reversi.train."):
            del sys.modules[name]
    import reversi.api as api_pkg

    assert api_pkg.app is not None
    loaded = [name for name in sys.modules if name.startswith("reversi.train")]
    assert loaded == []


_JEV = {"kind": "specimen", "specimen_id": JEV_ID}


def test_catalog_includes_jev(client: TestClient) -> None:
    response = client.get("/api/catalog")
    body = Catalog.model_validate(response.json())
    match = next(item for item in body.items if item.specimen_id == JEV_ID)
    assert match.category == "generative_ai"
    assert match.display_name == "生成 AI (Jev)"
    assert "Jev" in match.description
    assert "OpenRouter" in match.description


def test_jev_failure_on_start_does_not_leave_partial_game(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def boom(_position, _legal):
        raise ExternalModelError("試験用の失敗")

    monkeypatch.setattr("reversi.agents.jev._call_openrouter", boom)
    client = TestClient(create_app(GameStore(db_path=tmp_path / "games.sqlite")))
    response = client.post(
        "/api/games",
        json={"black": _JEV, "white": _HUMAN},
    )
    _problem(response, 422, "external_model_failed")
    assert "sk-" not in response.text
    listed = client.get("/api/catalog")
    assert listed.status_code == 200


def test_jev_failure_after_human_move_marks_unplayable_without_adopting_model_move(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from reversi.engine.board import Square

    def illegal(_position, _legal):
        return Square.parse("a1")

    monkeypatch.setattr("reversi.agents.jev._call_openrouter", illegal)
    client = TestClient(create_app(GameStore(db_path=tmp_path / "games.sqlite")))
    game = _create(client, _HUMAN, _JEV)
    before_board = game.board
    legal = game.legal_moves[0]
    applied = client.post(
        f"/api/games/{game.id}/moves",
        json={"type": "place", "square": legal},
    )
    assert applied.status_code == 200
    payload = MoveApplied.model_validate(applied.json())
    assert payload.applied is True
    assert payload.game.status == "unplayable"
    assert payload.game.continuation_possible is False
    assert payload.game.unplayable_reason == "external_model_failed"
    assert payload.game.result is None
    file_i = ord(legal[0]) - ord("a")
    rank_i = int(legal[1]) - 1
    assert payload.game.board[rank_i][file_i] == "black"
    assert payload.game.board != before_board
    assert payload.game.board[0][0] == "empty"

    rejected = client.post(
        f"/api/games/{game.id}/moves",
        json={"type": "place", "square": "d3"},
    )
    assert rejected.status_code == 409
    body = GameUnplayable.model_validate(rejected.json())
    assert body.applied is False
    assert body.code == "external_model_failed"
    assert body.continuation_possible is False
    assert body.game.status == "unplayable"
    assert body.game.board == payload.game.board
