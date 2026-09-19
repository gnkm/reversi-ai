"""`data/genai.json` から追加の生成 AI 個体を読む。対局者向けウィザードは置かない。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from random import Random

from reversi.agents import chat_completions
from reversi.engine.rules import Place, Position

CATEGORY = "generative_ai"
CONFIG_PATH = Path(__file__).resolve().parents[4] / "data" / "genai.json"

__all__ = [
    "CATEGORY",
    "CONFIG_PATH",
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

    def choose_move(
        self, position: Position, rng: Random | None = None
    ) -> Place | None:
        return chat_completions.choose_move(position, self.model_id, rng)


def _parse_entry(raw: object) -> ExtraSpecimen:
    if not isinstance(raw, dict):
        raise ConfigError("genai.json の各要素はオブジェクトでなければなりません")
    model_id = raw.get("model_id")
    name = raw.get("name")
    if not isinstance(model_id, str) or not model_id.strip():
        raise ConfigError("model_id は空でない文字列でなければなりません")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError("呼称は空でない文字列でなければなりません")
    name = name.strip()
    model_id = model_id.strip()
    return ExtraSpecimen(
        specimen_id=f"genai:{name}",
        model_id=model_id,
        display_name=f"生成 AI ({name})",
        description=(
            f"OpenRouter 上の {model_id} を Chat Completions で呼び、"
            "自分の手番の合法手から着手を選ぶ。対局中に WTHOR は参照しない。"
        ),
    )


def _ensure_unique(extras: tuple[ExtraSpecimen, ...]) -> None:
    names = [extra.display_name for extra in extras]
    if len(names) != len(set(names)):
        raise ConfigError("表示名はカタログ内で一意でなければなりません")
    ids = [extra.specimen_id for extra in extras]
    if len(ids) != len(set(ids)):
        raise ConfigError("個体 ID はカタログ内で一意でなければなりません")


def load(path: Path | None = None) -> tuple[ExtraSpecimen, ...]:
    """設定が無ければ空。対局者向けの作成画面は持たない。"""
    target = CONFIG_PATH if path is None else path
    if not target.is_file():
        return ()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError("genai.json を読めません") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError("genai.json が JSON ではありません") from exc
    if not isinstance(raw, list):
        raise ConfigError("genai.json の根は配列でなければなりません")
    extras = tuple(_parse_entry(item) for item in raw)
    _ensure_unique(extras)
    return extras
