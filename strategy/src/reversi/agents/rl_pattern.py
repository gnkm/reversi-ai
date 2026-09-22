"""パターン特徴の評価を葉にする深さ 4 の αβ。NN も OpenRouter も使わない。"""

from __future__ import annotations

from pathlib import Path
from random import Random

from reversi.agents.alphabeta import choose_at_depth as alphabeta_choose_at_depth
from reversi.agents.pattern_eval import PatternPolicy, load_policy, perspective_value
from reversi.agents.rl_search import SEARCH_DEPTH
from reversi.engine.board import Board, Color
from reversi.engine.rules import Place, Position

SPECIMEN_ID = "rl_pattern"
CATEGORY = "reinforcement_learning"
DISPLAY_NAME = "強化学習 (パターンの読み)"
DESCRIPTION = (
    "自己対局で学んだパターン評価を使い、数手先を読んで着手する。"
    "対局時にニューラルネットワークも OpenRouter も使わない。"
)
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[4] / "models" / "rl-pattern.json"

__all__ = [
    "CATEGORY",
    "DEFAULT_MODEL_PATH",
    "DESCRIPTION",
    "DISPLAY_NAME",
    "SEARCH_DEPTH",
    "SPECIMEN_ID",
    "choose_at_depth",
    "choose_move",
    "default_policy",
    "leaf_score",
]


_CACHED: PatternPolicy | None = None
_CACHED_PATH: Path | None = None


def default_policy() -> PatternPolicy:
    """`models/rl-pattern.json` を一度だけ読む。"""
    global _CACHED, _CACHED_PATH
    path = DEFAULT_MODEL_PATH
    if _CACHED is None or _CACHED_PATH != path:
        _CACHED = load_policy(path)
        _CACHED_PATH = path
    return _CACHED


def leaf_score(
    board: Board,
    color: Color,
    policy: PatternPolicy | None = None,
) -> float:
    """color 視点のパターン評価。白番は符号反転。葉の外へ定数は足さない。"""
    loaded = default_policy() if policy is None else policy
    return perspective_value(board, color, loaded)


def choose_at_depth(
    position: Position,
    depth: int,
    *,
    policy: PatternPolicy | None = None,
) -> Place | None:
    """指定深さの αβ。葉はパターン特徴。同点は a1…h8。終盤の完全読みはしない。"""
    loaded = default_policy() if policy is None else policy

    def evaluate(board: Board, color: Color) -> float:
        return perspective_value(board, color, loaded)

    return alphabeta_choose_at_depth(position, depth, evaluate=evaluate)


def choose_move(position: Position, rng: Random | None = None) -> Place | None:
    """深さ 4 の αβ。葉は自己対局のパターン特徴。"""
    del rng
    return choose_at_depth(position, SEARCH_DEPTH)
