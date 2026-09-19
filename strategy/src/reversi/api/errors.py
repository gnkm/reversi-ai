"""RFC 9457 の Problem Details。内部パスやスタックは載せない。"""

from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from reversi.api.schemas import GameState, IllegalMoveNotApplied, Problem


class ApiProblem(Exception):
    """契約どおりの Problem を返す。"""

    def __init__(self, status: int, code: str, title: str, detail: str) -> None:
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail

    def body(self) -> dict[str, object]:
        problem = Problem(
            type=f"urn:reversi-ai:error:{self.code}",
            title=self.title,
            status=self.status,
            detail=self.detail,
            code=self.code,  # type: ignore[arg-type]
        )
        return problem.model_dump(mode="json")


class MoveRejected(Exception):
    """違法着手。盤は変えない。"""

    def __init__(self, game: GameState, detail: str) -> None:
        self.game = game
        self.detail = detail


def problem_response(exc: ApiProblem) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content=exc.body(),
        media_type="application/problem+json",
    )


async def api_problem_handler(_request: Request, exc: ApiProblem) -> JSONResponse:
    return problem_response(exc)


async def validation_handler(
    _request: Request,
    _exc: RequestValidationError,
) -> JSONResponse:
    return problem_response(
        ApiProblem(
            status=400,
            code="validation_error",
            title="Bad Request",
            detail="リクエストの形が契約と違う",
        )
    )


async def move_rejected_handler(_request: Request, exc: MoveRejected) -> JSONResponse:
    body = IllegalMoveNotApplied(
        applied=False,
        code="illegal_move",
        detail=exc.detail,
        game=exc.game,
    )
    return JSONResponse(status_code=409, content=body.model_dump(mode="json"))


def specimen_not_found() -> ApiProblem:
    return ApiProblem(
        status=404,
        code="specimen_not_found",
        title="Not Found",
        detail="個体が無い",
    )


def game_not_found() -> ApiProblem:
    return ApiProblem(
        status=404,
        code="game_not_found",
        title="Not Found",
        detail="対局が無い",
    )
