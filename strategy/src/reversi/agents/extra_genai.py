"""`data/config.toml` から追加の生成 AI 個体を読む。対局者向けウィザードは置かない。"""

from __future__ import annotations

import math
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from random import Random

from reversi.agents import chat_completions
from reversi.agents.prompt import PROMPTS_DIR
from reversi.engine.rules import Place, Position

CATEGORY = "generative_ai"
CONFIG_PATH = Path(__file__).resolve().parents[4] / "data" / "config.toml"
DEFAULT_PROMPT = "chat-completions.md"
_OPTIONAL_NUMBERS = {
    "temperature": (int, float),
    "top_p": (int, float),
    "max_tokens": (int,),
    "seed": (int,),
}
_KNOWN_KEYS = {"model", "name", "prompt", *_OPTIONAL_NUMBERS}

__all__ = [
    "CATEGORY",
    "CONFIG_PATH",
    "DEFAULT_PROMPT",
    "ConfigError",
    "ExtraSpecimen",
    "load",
]


class ConfigError(ValueError):
    """追加生成 AI の設定が読めない。"""


@dataclass(frozen=True, slots=True)
class ExtraSpecimen:
    """設定ファイルから足す生成 AI 個体。"""

    specimen_id: str
    model_id: str
    display_name: str
    description: str
    parameters: dict[str, float | int] = field(default_factory=dict)
    prompt_path: Path | None = None

    def choose_move(
        self, position: Position, rng: Random | None = None
    ) -> Place | None:
        return chat_completions.choose_move(
            position,
            self.model_id,
            rng,
            parameters=self.parameters,
            prompt_path=self.prompt_path,
        )


def _require_text(raw: Mapping[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key} は空でない文字列でなければなりません")
    return value.strip()


def _in_range(value: float, low: float, high: float | None) -> bool:
    if value < low:
        return False
    return True if high is None else value <= high


def _optional_number(raw: Mapping[str, object], key: str) -> float | int | None:
    if key not in raw:
        return None
    value = raw[key]
    allowed = _OPTIONAL_NUMBERS[key]
    if isinstance(value, bool) or not isinstance(value, allowed):
        raise ConfigError(f"{key} の型が不正です")
    if isinstance(value, float) and not math.isfinite(value):
        raise ConfigError(f"{key} は有限でなければなりません")
    if key == "temperature" and not _in_range(float(value), 0.0, 2.0):
        raise ConfigError("temperature は 0 以上 2 以下でなければなりません")
    if key == "top_p" and not _in_range(float(value), 0.0, 1.0):
        raise ConfigError("top_p は 0 以上 1 以下でなければなりません")
    if key == "max_tokens" and not _in_range(int(value), 1, None):
        raise ConfigError("max_tokens は 1 以上でなければなりません")
    return value


def _prompt_path(raw: Mapping[str, object]) -> Path:
    name = DEFAULT_PROMPT
    if "prompt" in raw:
        name = _require_text(raw, "prompt")
    if Path(name).name != name or name in {".", ".."}:
        raise ConfigError("prompt は prompts/ 直下のファイル名でなければなりません")
    candidate = PROMPTS_DIR / name
    try:
        candidate.resolve().relative_to(PROMPTS_DIR.resolve())
    except ValueError:
        raise ConfigError("prompt は prompts/ 直下のファイル名でなければなりません") from None
    return candidate


def _parse_entry(raw: object) -> ExtraSpecimen:
    if not isinstance(raw, dict):
        raise ConfigError("config.toml の各個体はテーブルでなければなりません")
    unknown = set(raw) - _KNOWN_KEYS
    if unknown:
        keys = ", ".join(sorted(unknown))
        raise ConfigError(f"config.toml の未知のキーです: {keys}")
    name = _require_text(raw, "name")
    model_id = _require_text(raw, "model")
    parameters: dict[str, float | int] = {}
    for key in _OPTIONAL_NUMBERS:
        number = _optional_number(raw, key)
        if number is not None:
            parameters[key] = number
    return ExtraSpecimen(
        specimen_id=f"genai:{name}",
        model_id=model_id,
        display_name=f"生成 AI ({name})",
        description=(
            "OpenRouter の Chat Completions を構造化出力で呼び、"
            "自分の手番の合法手から着手を選ぶ。対局中に WTHOR は参照しない。"
        ),
        parameters=parameters,
        prompt_path=_prompt_path(raw),
    )


def _ensure_unique(extras: tuple[ExtraSpecimen, ...]) -> None:
    names = [extra.display_name for extra in extras]
    if len(names) != len(set(names)):
        raise ConfigError("表示名はカタログ内で一意でなければなりません")
    ids = [extra.specimen_id for extra in extras]
    if len(ids) != len(set(ids)):
        raise ConfigError("個体 ID はカタログ内で一意でなければなりません")


def _reject_legacy_json(config_path: Path) -> None:
    legacy = config_path.with_name("genai.json")
    if legacy.is_file():
        raise ConfigError("genai.json は使えません。config.toml に移してください")


def load(path: Path | None = None) -> tuple[ExtraSpecimen, ...]:
    """設定が無ければ空。対局者向けの作成画面は持たない。"""
    target = CONFIG_PATH if path is None else path
    if not target.is_file():
        _reject_legacy_json(target)
        return ()
    try:
        with target.open("rb") as handle:
            raw = tomllib.load(handle)
    except OSError as exc:
        raise ConfigError("config.toml を読めません") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError("config.toml が TOML ではありません") from exc
    if "generative_ai" not in raw:
        return ()
    entries = raw["generative_ai"]
    if not isinstance(entries, list):
        raise ConfigError("generative_ai は配列でなければなりません")
    extras = tuple(_parse_entry(item) for item in entries)
    _ensure_unique(extras)
    return extras
