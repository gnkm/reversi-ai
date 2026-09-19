"""裏返す相手石が最大の合法手を選ぶ個体。置いた自分の石は数えない。"""

from __future__ import annotations

from random import Random

from reversi.engine.rules import Place, Position, flips_for, legal_places

SPECIMEN_ID = "most_flips"
CATEGORY = "rule_based"
DISPLAY_NAME = "ルールベース (最多取り)"
DESCRIPTION = (
    "裏返す相手石の個数が最大の合法手を選ぶ。置いた自分の石は数えない。"
    "同点は a1 から h8 の座標順。対局中に学習済みモデルも OpenRouter も呼ばない。"
)

__all__ = [
    "CATEGORY",
    "DESCRIPTION",
    "DISPLAY_NAME",
    "SPECIMEN_ID",
    "choose_move",
]


def choose_move(position: Position, rng: Random | None = None) -> Place | None:
    """相手石を最も多く裏返す合法手。同点は a1…h8 で先に最大となった手。"""
    del rng
    color = position.side_to_move
    best_square = None
    best_flips = -1
    for square in legal_places(position):
        n = len(flips_for(position.board, square, color))
        if n > best_flips:
            best_flips = n
            best_square = square
    if best_square is None:
        return None
    return Place(best_square)
