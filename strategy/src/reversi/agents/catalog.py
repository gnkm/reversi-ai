"""戦略個体のカタログ。選ぶ対象はカテゴリではなく個体である。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from random import Random

from reversi.agents.random_uniform import (
    CATEGORY,
    DESCRIPTION,
    DISPLAY_NAME,
    SPECIMEN_ID,
    choose_move as choose_random_uniform,
)
from reversi.engine.rules import Place, Position

Chooser = Callable[[Position, Random | None], Place | None]


__all__ = [
    "CatalogItem",
    "RANDOM_UNIFORM",
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
    specimen_id=SPECIMEN_ID,
    category=CATEGORY,
    display_name=DISPLAY_NAME,
    description=DESCRIPTION,
)

# 一覧と着手関数は同じ登録から作る。
_REGISTRY: tuple[tuple[CatalogItem, Chooser], ...] = (
    (RANDOM_UNIFORM, choose_random_uniform),
)
_BY_ID: dict[str, tuple[CatalogItem, Chooser]] = {
    item.specimen_id: (item, chooser) for item, chooser in _REGISTRY
}


def items() -> tuple[CatalogItem, ...]:
    """登録されている個体。"""
    return tuple(item for item, _ in _REGISTRY)


def get(specimen_id: str) -> CatalogItem:
    """個体 ID でカタログ項目を返す。"""
    try:
        item, _ = _BY_ID[specimen_id]
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
        _, chooser = _BY_ID[specimen_id]
    except KeyError:
        raise KeyError(specimen_id) from None
    return chooser(position, rng)
