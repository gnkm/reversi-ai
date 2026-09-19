"""戦略 API: カタログ・1 局の開始・着手・違法拒否。"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reversi.agents.catalog import items as catalog_items
from reversi.agents.random_uniform import SPECIMEN_ID
from reversi.api import create_app
from reversi.api.schemas import (
    Catalog,
    GameState,
    IllegalMoveNotApplied,
    MoveApplied,
)
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
def client() -> TestClient:
    return TestClient(create_app())


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


def test_agent_vs_agent_completes_without_waiting_for_human(
    client: TestClient,
) -> None:
    game = _create(client, _SPECIMEN, _SPECIMEN)
    assert game.is_over is True
    assert game.status == "completed"
    assert game.continuation_possible is False
    assert game.result is not None
    assert game.result.winner in {"black", "white", "draw"}
    assert game.official_score.black + game.official_score.white == 64
    assert game.last_move is not None
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
    assert finished.is_over is True
    again = _create(client, _HUMAN, _SPECIMEN)
    assert again.is_over is False
    assert again.last_move is None
    _problem(client.get(f"/api/games/{finished.id}"), 404, "game_not_found")


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
