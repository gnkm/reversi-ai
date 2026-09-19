"""OpenRouter の Jev で合法手を選ぶ個体。Decisions API。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from random import Random
from typing import Any

from openrouter import OpenRouter

from reversi.engine.board import BOARD_SIZE, Square
from reversi.engine.rules import Place, Position, legal_places

MODEL_ID = "typesafe/jev-1.13"
SPECIMEN_ID = "jev"
CATEGORY = "generative_ai"
DISPLAY_NAME = "生成 AI (Jev)"
DESCRIPTION = (
    "OpenRouter 上の Jev を Decisions API で呼び、自分の手番の合法手から着手を選ぶ。"
    "対局中に WTHOR は参照しない。"
)
DECISIONS_SERVER = "https://openrouter.ai"
SECRET_PATH = Path("/run/secrets/openrouter-api-key")
_QUESTION_ID = "move"

__all__ = [
    "CATEGORY",
    "DECISIONS_SERVER",
    "DESCRIPTION",
    "DISPLAY_NAME",
    "MODEL_ID",
    "SECRET_PATH",
    "SPECIMEN_ID",
    "ExternalModelError",
    "choose_move",
]


class ExternalModelError(RuntimeError):
    """外部モデルの呼出し失敗。着手は採用しない。"""


def _read_api_key() -> str:
    try:
        raw = SECRET_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise ExternalModelError("OpenRouter の資格情報を読めません") from exc
    key = raw.strip()
    if not key:
        raise ExternalModelError("OpenRouter の資格情報が空です")
    return key


def _board_state(position: Position, places: Sequence[Square]) -> dict[str, Any]:
    board = [
        [position.board.cells[rank][file].value for file in range(BOARD_SIZE)]
        for rank in range(BOARD_SIZE)
    ]
    return {
        "side_to_move": position.side_to_move.value,
        "board": board,
        "legal_places": [square.algebraic for square in places],
    }


def _questions(places: Sequence[Square]) -> dict[str, Any]:
    return {
        _QUESTION_ID: {
            "type": "choice",
            "instructions": (
                "Choose exactly one legal Reversi move for the side to move. "
                "Each option is an algebraic square. a1 is bottom-left for Black."
            ),
            "criteria": {
                square.algebraic: f"Place a stone on {square.algebraic}."
                for square in places
            },
        }
    }


def _attr(obj: object, name: str) -> object:
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _choice_from_response(response: object) -> str:
    answers = _attr(response, "answers")
    if not isinstance(answers, Mapping):
        raise ExternalModelError("OpenRouter の応答に着手がありません")
    answer = answers.get(_QUESTION_ID)
    if answer is None:
        raise ExternalModelError("OpenRouter の応答に着手がありません")
    choice = _attr(answer, "choice")
    if not isinstance(choice, str) or not choice:
        raise ExternalModelError("OpenRouter の応答が choice ではありません")
    return choice


def _legal_square(algebraic: str, places: Sequence[Square]) -> Square:
    by_name = {square.algebraic: square for square in places}
    square = by_name.get(algebraic)
    if square is None:
        raise ExternalModelError("合法手の外です")
    return square


def _call_openrouter(position: Position, places: Sequence[Square]) -> Square:
    key = _read_api_key()
    try:
        with OpenRouter(api_key=key, server_url=DECISIONS_SERVER) as client:
            response = client.alpha.decisions.create(
                model=MODEL_ID,
                questions=_questions(places),
                state=_board_state(position, places),
            )
    except ExternalModelError:
        raise
    except Exception:  # noqa: BLE001 - SDK の 4xx/5xx/timeout を継続不能に畳む
        raise ExternalModelError("OpenRouter の呼出しに失敗しました") from None
    return _legal_square(_choice_from_response(response), places)


def choose_move(position: Position, rng: Random | None = None) -> Place | None:
    """Jev が選んだ合法手。失敗時は着手を採用せず継続不能を表す。"""
    del rng
    places = legal_places(position)
    if not places:
        return None
    square = _call_openrouter(position, places)
    if square not in places:
        raise ExternalModelError("合法手の外です")
    return Place(square)
