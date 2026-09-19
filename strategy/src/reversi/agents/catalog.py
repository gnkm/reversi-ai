"""戦略個体のカタログ。選ぶ対象はカテゴリではなく個体である。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from random import Random

from reversi.agents import jev, most_flips, positional, random_uniform
from reversi.engine.rules import Place, Position

Chooser = Callable[[Position, Random | None], Place | None]


__all__ = [
    "JEV",
    "MOST_FLIPS",
    "POSITIONAL",
    "RANDOM_UNIFORM",
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
JEV = CatalogItem(
    specimen_id=jev.SPECIMEN_ID,
    category=jev.CATEGORY,
    display_name=jev.DISPLAY_NAME,
    description=jev.DESCRIPTION,
)

# 一覧と着手関数は同じ登録から作る。
_REGISTRY: tuple[tuple[CatalogItem, Chooser], ...] = (
    (RANDOM_UNIFORM, random_uniform.choose_move),
    (MOST_FLIPS, most_flips.choose_move),
    (POSITIONAL, positional.choose_move),
    (JEV, jev.choose_move),
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
