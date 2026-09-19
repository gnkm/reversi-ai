"""戦略 FastAPI。カタログと 1 局の開始・着手。"""

from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, Path, Response, status
from fastapi.exceptions import RequestValidationError

from reversi.agents.catalog import CatalogItem as AgentItem
from reversi.api.errors import (
    ApiProblem,
    MoveRejected,
    UnplayableGame,
    api_problem_handler,
    move_rejected_handler,
    unplayable_handler,
    validation_handler,
)
from reversi.api.schemas import (
    GAME_ID_PATTERN,
    Catalog,
    CatalogItem,
    CreateGameRequest,
    GameState,
    Move,
    MoveApplied,
)
from reversi.api.session import GameStore


def _catalog_item(item: AgentItem) -> CatalogItem:
    return CatalogItem(
        specimen_id=item.specimen_id,
        category=item.category,  # type: ignore[arg-type]
        display_name=item.display_name,
        description=item.description,
    )


def create_app(store: GameStore | None = None) -> FastAPI:
    app = FastAPI(
        title="Reversi AI 戦略 API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.store = store if store is not None else GameStore()
    app.add_exception_handler(ApiProblem, api_problem_handler)
    app.add_exception_handler(RequestValidationError, validation_handler)
    app.add_exception_handler(MoveRejected, move_rejected_handler)
    app.add_exception_handler(UnplayableGame, unplayable_handler)

    @app.get("/api/catalog", response_model=Catalog)
    def list_catalog() -> Catalog:
        items = [_catalog_item(item) for item in app.state.store.catalog()]
        return Catalog(items=items)

    @app.post(
        "/api/games",
        response_model=GameState,
        status_code=status.HTTP_201_CREATED,
    )
    def create_game(request: CreateGameRequest, response: Response) -> GameState:
        game = app.state.store.start(request)
        response.headers["Location"] = f"/api/games/{game.id}"
        return game

    @app.get("/api/games/{game_id}", response_model=GameState)
    def get_game(
        game_id: Annotated[str, Path(pattern=GAME_ID_PATTERN)],
    ) -> GameState:
        return app.state.store.snapshot(game_id)

    @app.post("/api/games/{game_id}/moves", response_model=MoveApplied)
    def play_move(
        game_id: Annotated[str, Path(pattern=GAME_ID_PATTERN)],
        move: Move,
    ) -> MoveApplied:
        game = app.state.store.play_move(game_id, move)
        return MoveApplied(applied=True, game=game)

    return app


app = create_app()
