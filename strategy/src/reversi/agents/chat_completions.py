"""運用者が追加した生成 AI 個体。Chat Completions の構造化出力で合法手を選ぶ。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from random import Random
from typing import Any

from openrouter import OpenRouter
from openrouter.utils.retries import BackoffStrategy, RetryConfig
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from reversi.agents.jev import SECRET_PATH, ExternalModelError, read_secret
from reversi.agents.prompt import PROMPTS_DIR, PromptFileError, load_sections
from reversi.engine.board import BOARD_SIZE, Square
from reversi.engine.rules import Place, Position, legal_places

CHAT_SERVER = "https://openrouter.ai"
PROMPT_PATH = PROMPTS_DIR / "chat-completions.md"
# Hono の戦略中継は 60 秒。それより先に失敗させ、ロックを返す。
CHAT_TIMEOUT_MS = 55_000
_NO_RETRY = RetryConfig("none", BackoffStrategy(0, 0, 1.0, 0), False)
_SEND_PARAMETERS = ("temperature", "max_tokens", "top_p", "seed")

__all__ = [
    "CHAT_SERVER",
    "CHAT_TIMEOUT_MS",
    "PROMPT_PATH",
    "SECRET_PATH",
    "ChosenMove",
    "choose_move",
    "response_format",
]


class ChosenMove(BaseModel):
    """Chat Completions の構造化着手。自由文の先頭トークンは使わない。"""

    model_config = ConfigDict(extra="forbid")
    square: str = Field(min_length=2, max_length=2, pattern=r"^[a-h][1-8]$")

    @field_validator("square", mode="before")
    @classmethod
    def _normalize_algebraic(cls, value: object) -> object:
        if isinstance(value, str) and len(value.strip()) == 2:
            text = value.strip()
            return text[0].lower() + text[1]
        return value


def response_format() -> dict[str, object]:
    """OpenRouter に渡す JSON Schema。Pydantic モデルと同一の形。"""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "chosen_move",
            "strict": True,
            "schema": ChosenMove.model_json_schema(),
        },
    }


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


def _system_instructions(path: Path | None = None) -> str:
    target = PROMPT_PATH if path is None else path
    try:
        return load_sections(target, "system")["system"]
    except PromptFileError as exc:
        raise ExternalModelError(str(exc)) from exc


def _messages(
    position: Position,
    places: Sequence[Square],
    prompt_path: Path | None,
) -> list[dict[str, str]]:
    legal = ", ".join(square.algebraic for square in places)
    return [
        {"role": "system", "content": _system_instructions(prompt_path)},
        {
            "role": "user",
            "content": (
                f"legal_places: {legal}\n"
                f"state: {_board_state(position, places)}"
            ),
        },
    ]


def _parse_chosen_move(content: object) -> ChosenMove:
    try:
        if isinstance(content, str):
            return ChosenMove.model_validate_json(content)
        if isinstance(content, Mapping):
            return ChosenMove.model_validate(content)
    except (ValidationError, ValueError):
        raise ExternalModelError("OpenRouter の応答を検証できません") from None
    raise ExternalModelError("OpenRouter の応答に着手がありません")


def _choice_from_response(response: object) -> str:
    choices = _attr(response, "choices")
    if not isinstance(choices, Sequence) or not choices:
        raise ExternalModelError("OpenRouter の応答に着手がありません")
    message = _attr(choices[0], "message")
    content = _attr(message, "content")
    return _parse_chosen_move(content).square


def _legal_square(algebraic: str, places: Sequence[Square]) -> Square:
    by_name = {square.algebraic: square for square in places}
    square = by_name.get(algebraic)
    if square is None:
        raise ExternalModelError("合法手の外です")
    return square


def _send_kwargs(
    model_id: str,
    messages: list[dict[str, str]],
    parameters: Mapping[str, object] | None,
) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "model": model_id,
        "messages": messages,
        "retries": _NO_RETRY,
        "timeout_ms": CHAT_TIMEOUT_MS,
        "response_format": response_format(),
    }
    if not parameters:
        return kwargs
    for key in _SEND_PARAMETERS:
        if key in parameters:
            kwargs[key] = parameters[key]
    return kwargs


def _call_openrouter(
    position: Position,
    places: Sequence[Square],
    model_id: str,
    *,
    parameters: Mapping[str, object] | None = None,
    prompt_path: Path | None = None,
) -> Square:
    key = read_secret(SECRET_PATH)
    messages = _messages(position, places, prompt_path)
    try:
        with OpenRouter(
            api_key=key,
            server_url=CHAT_SERVER,
            timeout_ms=CHAT_TIMEOUT_MS,
        ) as client:
            response = client.chat.send(**_send_kwargs(model_id, messages, parameters))
    except ExternalModelError:
        raise
    except Exception:  # noqa: BLE001 - SDK の 4xx/5xx/timeout を継続不能に畳む
        raise ExternalModelError("OpenRouter の呼出しに失敗しました") from None
    return _legal_square(_choice_from_response(response), places)


def choose_move(
    position: Position,
    model_id: str,
    rng: Random | None = None,
    *,
    parameters: Mapping[str, object] | None = None,
    prompt_path: Path | None = None,
) -> Place | None:
    """与えたモデル ID が選んだ合法手。失敗時は着手を採用しない。"""
    del rng
    places = legal_places(position)
    if not places:
        return None
    square = _call_openrouter(
        position,
        places,
        model_id,
        parameters=parameters,
        prompt_path=prompt_path,
    )
    if square not in places:
        raise ExternalModelError("合法手の外です")
    return Place(square)
