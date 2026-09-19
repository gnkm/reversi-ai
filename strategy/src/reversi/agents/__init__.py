"""戦略個体。選択単位は個体でありカテゴリではない。"""

from reversi.agents.catalog import CatalogItem, get, items
from reversi.agents.random_uniform import choose_move

__all__ = [
    "CatalogItem",
    "choose_move",
    "get",
    "items",
]
