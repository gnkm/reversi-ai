"""docs/openapi.yml の components と同じ形の Pydantic モデル。"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

GAME_ID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
SQUARE_PATTERN = r"^[a-h][1-8]$"

Color = Literal["black", "white"]
Cell = Literal["empty", "black", "white"]
Category = Literal[
    "random",
    "rule_based",
    "machine_learning",
    "reinforcement_learning",
    "neural_network",
]
ErrorCode = Literal[
    "validation_error",
    "game_not_found",
    "specimen_not_found",
    "illegal_move",
    "game_already_over",
    "external_model_failed",
    "internal_error",
]
Outcome = Literal["win", "loss", "draw"]
GameStatus = Literal["in_progress", "completed", "unplayable"]
Winner = Literal["black", "white", "draw"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Problem(_Strict):
    type: str
    title: str
    status: int
    detail: str
    code: ErrorCode


class CatalogItem(_Strict):
    specimen_id: str = Field(min_length=1)
    category: Category
    display_name: str = Field(min_length=1)
    description: str


class Catalog(_Strict):
    items: list[CatalogItem]


class HumanPlayer(_Strict):
    kind: Literal["human"]


class SpecimenPlayer(_Strict):
    kind: Literal["specimen"]
    specimen_id: str = Field(min_length=1)


PlayerSpec = Annotated[
    HumanPlayer | SpecimenPlayer,
    Field(discriminator="kind"),
]


class CreateGameRequest(_Strict):
    black: PlayerSpec
    white: PlayerSpec


class PlaceMove(_Strict):
    type: Literal["place"]
    square: str = Field(pattern=SQUARE_PATTERN)


class PassMove(_Strict):
    type: Literal["pass"]


Move = Annotated[PlaceMove | PassMove, Field(discriminator="type")]


class OfficialScore(_Strict):
    black: int = Field(ge=0, le=64)
    white: int = Field(ge=0, le=64)


class GameResult(_Strict):
    winner: Winner
    black: Outcome
    white: Outcome


class GameState(_Strict):
    id: str = Field(pattern=GAME_ID_PATTERN)
    board: list[list[Cell]] = Field(min_length=8, max_length=8)
    side_to_move: Color
    legal_moves: list[str]
    pass_is_legal: bool
    last_move: Move | None
    is_over: bool
    official_score: OfficialScore
    result: GameResult | None
    status: GameStatus
    continuation_possible: bool
    unplayable_reason: Literal["external_model_failed"] | None
    black: PlayerSpec
    white: PlayerSpec


class MoveApplied(_Strict):
    applied: Literal[True]
    game: GameState


class IllegalMoveNotApplied(_Strict):
    applied: Literal[False]
    code: Literal["illegal_move"]
    detail: str
    game: GameState
