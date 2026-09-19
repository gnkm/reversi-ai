"""運用者が追加した生成 AI 個体。Chat Completions で合法手を選ぶ。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from random import Random
from typing import Any

from openrouter import OpenRouter
from openrouter.utils.retries import BackoffStrategy, RetryConfig

from reversi.agents.jev import SECRET_PATH, ExternalModelError, read_secret
from reversi.engine.board import BOARD_SIZE, Square
from reversi.engine.rules import Place, Position, legal_places

CHAT_SERVER = "https://openrouter.ai"
# Hono の戦略中継は 60 秒。それより先に失敗させ、ロックを返す。
CHAT_TIMEOUT_MS = 55_000
_NO_RETRY = RetryConfig("none", BackoffStrategy(0, 0, 1.0, 0), False)

__all__ = [
    "CHAT_SERVER",
    "CHAT_TIMEOUT_MS",
    "SECRET_PATH",
    "choose_move",
]


def _attr(obj: object, name: str) -> object:
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


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


def _messages(position: Position, places: Sequence[Square]) -> list[dict[str, str]]:
    legal = ", ".join(square.algebraic for square in places)
    return [
        {
            "role": "system",
            "content": (
                "Choose exactly one legal Reversi move for the side to move. "
                "Reply with only the algebraic square (for example d3). "
                "a1 is bottom-left for Black."
            ),
        },
        {
            "role": "user",
            "content": (
                f"legal_places: {legal}\n"
                f"state: {_board_state(position, places)}"
            ),
        },
    ]


def _choice_from_response(response: object) -> str:
    choices = _attr(response, "choices")
    if not isinstance(choices, Sequence) or not choices:
        raise ExternalModelError("OpenRouter の応答に着手がありません")
    message = _attr(choices[0], "message")
    content = _attr(message, "content")
    if not isinstance(content, str) or not content.strip():
        raise ExternalModelError("OpenRouter の応答に着手がありません")
    token = content.strip().split()[0].strip(".,:;\"'`()[]")
    if len(token) == 2:
        token = token[0].lower() + token[1]
    if not token:
        raise ExternalModelError("OpenRouter の応答に着手がありません")
    return token


def _legal_square(algebraic: str, places: Sequence[Square]) -> Square:
    by_name = {square.algebraic: square for square in places}
    square = by_name.get(algebraic)
    if square is None:
        raise ExternalModelError("合法手の外です")
    return square


def _call_openrouter(
    position: Position,
    places: Sequence[Square],
    model_id: str,
) -> Square:
    key = read_secret(SECRET_PATH)
    try:
        with OpenRouter(
            api_key=key,
            server_url=CHAT_SERVER,
            timeout_ms=CHAT_TIMEOUT_MS,
        ) as client:
            response = client.chat.send(
                model=model_id,
                messages=_messages(position, places),
                retries=_NO_RETRY,
                timeout_ms=CHAT_TIMEOUT_MS,
            )
    except ExternalModelError:
        raise
    except Exception:  # noqa: BLE001 - SDK の 4xx/5xx/timeout を継続不能に畳む
        raise ExternalModelError("OpenRouter の呼出しに失敗しました") from None
    return _legal_square(_choice_from_response(response), places)


def choose_move(
    position: Position,
    model_id: str,
    rng: Random | None = None,
) -> Place | None:
    """与えたモデル ID が選んだ合法手。失敗時は着手を採用しない。"""
    del rng
    places = legal_places(position)
    if not places:
        return None
    square = _call_openrouter(position, places, model_id)
    if square not in places:
        raise ExternalModelError("合法手の外です")
    return Place(square)
