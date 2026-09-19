"""戦略個体のカタログ。選ぶ対象はカテゴリではなく個体である。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from random import Random

from reversi.agents import (
    extra_genai,
    jev,
    minimax,
    most_flips,
    opening,
    positional,
    random_uniform,
    rl,
)
from reversi.engine.rules import Place, Position

Chooser = Callable[[Position, Random | None], Place | None]


__all__ = [
    "JEV",
    "MINIMAX",
    "MOST_FLIPS",
    "OPENING",
    "POSITIONAL",
    "RANDOM_UNIFORM",
    "RL",
    "CatalogItem",
    "choose_move",
    "get",
    "items",
]


@dataclass(frozen=True, slots=True)
class CatalogItem:
    """カタログの 1 個体。"""

    specimen_id: str
    category: str
    display_name: str
    description: str


RANDOM_UNIFORM = CatalogItem(
    specimen_id=random_uniform.SPECIMEN_ID,
    category=random_uniform.CATEGORY,
    display_name=random_uniform.DISPLAY_NAME,
    description=random_uniform.DESCRIPTION,
)
MOST_FLIPS = CatalogItem(
    specimen_id=most_flips.SPECIMEN_ID,
    category=most_flips.CATEGORY,
    display_name=most_flips.DISPLAY_NAME,
    description=most_flips.DESCRIPTION,
)
POSITIONAL = CatalogItem(
    specimen_id=positional.SPECIMEN_ID,
    category=positional.CATEGORY,
    display_name=positional.DISPLAY_NAME,
    description=positional.DESCRIPTION,
)
MINIMAX = CatalogItem(
    specimen_id=minimax.SPECIMEN_ID,
    category=minimax.CATEGORY,
    display_name=minimax.DISPLAY_NAME,
    description=minimax.DESCRIPTION,
)
OPENING = CatalogItem(
    specimen_id=opening.SPECIMEN_ID,
    category=opening.CATEGORY,
    display_name=opening.DISPLAY_NAME,
    description=opening.DESCRIPTION,
)
RL = CatalogItem(
    specimen_id=rl.SPECIMEN_ID,
    category=rl.CATEGORY,
    display_name=rl.DISPLAY_NAME,
    description=rl.DESCRIPTION,
)
JEV = CatalogItem(
    specimen_id=jev.SPECIMEN_ID,
    category=jev.CATEGORY,
    display_name=jev.DISPLAY_NAME,
    description=jev.DESCRIPTION,
)

# 一覧と着手関数は同じ登録から作る。追加の生成 AI は data/genai.json から足す。
_BUILTIN: tuple[tuple[CatalogItem, Chooser], ...] = (
    (RANDOM_UNIFORM, random_uniform.choose_move),
    (MOST_FLIPS, most_flips.choose_move),
    (POSITIONAL, positional.choose_move),
    (MINIMAX, minimax.choose_move),
    (OPENING, opening.choose_move),
    (RL, rl.choose_move),
    (JEV, jev.choose_move),
)


def _extra_entries() -> tuple[tuple[CatalogItem, Chooser], ...]:
    extras: list[tuple[CatalogItem, Chooser]] = []
    names = {item.display_name for item, _ in _BUILTIN}
    ids = {item.specimen_id for item, _ in _BUILTIN}
    for extra in extra_genai.load():
        if extra.display_name in names:
            raise extra_genai.ConfigError(
                "表示名はカタログ内で一意でなければなりません"
            )
        if extra.specimen_id in ids:
            raise extra_genai.ConfigError(
                "個体 ID はカタログ内で一意でなければなりません"
            )
        names.add(extra.display_name)
        ids.add(extra.specimen_id)
        extras.append(
            (
                CatalogItem(
                    specimen_id=extra.specimen_id,
                    category=extra_genai.CATEGORY,
                    display_name=extra.display_name,
                    description=extra.description,
                ),
                extra.choose_move,
            )
        )
    return tuple(extras)


def _registry() -> tuple[tuple[CatalogItem, Chooser], ...]:
    """追加設定の失敗は組込み個体から切り離す。"""
    try:
        extras = _extra_entries()
    except extra_genai.ConfigError:
        return _BUILTIN
    return _BUILTIN + extras


def _by_id() -> dict[str, tuple[CatalogItem, Chooser]]:
    return {item.specimen_id: (item, chooser) for item, chooser in _registry()}


def items() -> tuple[CatalogItem, ...]:
    """登録されている個体。"""
    return tuple(item for item, _ in _registry())


def get(specimen_id: str) -> CatalogItem:
    """個体 ID でカタログ項目を返す。"""
    try:
        item, _ = _by_id()[specimen_id]
    except KeyError:
        raise KeyError(specimen_id) from None
    return item


def choose_move(
    specimen_id: str,
    position: Position,
    rng: Random | None = None,
) -> Place | None:
    """指定した個体に着手を選ばせる。未知の個体は KeyError。"""
    try:
        _, chooser = _by_id()[specimen_id]
    except KeyError:
        raise KeyError(specimen_id) from None
    return chooser(position, rng)
