"""合法手を等確率で選ぶ個体。棋譜も学習済みモデルも見ない。"""

from __future__ import annotations

from random import Random, SystemRandom

from reversi.engine.rules import Place, Position, legal_places

SPECIMEN_ID = "random_uniform"
CATEGORY = "random"
DISPLAY_NAME = "ランダム (一様)"
DESCRIPTION = (
    "自分の手番の合法手を等確率で 1 つ選ぶ。"
    "対局中に WTHOR などの棋譜も学習済みモデルも参照しない。"
)

__all__ = [
    "CATEGORY",
    "DESCRIPTION",
    "DISPLAY_NAME",
    "SPECIMEN_ID",
    "choose_move",
]

_RNG = SystemRandom()


def choose_move(position: Position, rng: Random | None = None) -> Place | None:
    """手番の合法手から一様に 1 つ選ぶ。合法手が無ければ着手しない。"""
    places = legal_places(position)
    if not places:
        return None
    square = (rng if rng is not None else _RNG).choice(places)
    return Place(square)
