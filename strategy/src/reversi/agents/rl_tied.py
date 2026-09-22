"""減衰・対称・探索手除外で学んだ線形 v を葉にする深さ 4 の αβ。

NN も OpenRouter も使わない。既存の「強化学習 (自己対局)」の重みは読まない。
"""

from __future__ import annotations

from pathlib import Path
from random import Random

from reversi.agents.rl import LinearPolicy, load_policy
from reversi.agents.rl_search import SEARCH_DEPTH, choose_at_depth
from reversi.engine.rules import Place, Position

SPECIMEN_ID = "rl_tied"
CATEGORY = "reinforcement_learning"
DISPLAY_NAME = "強化学習 (対称な読み)"
DESCRIPTION = (
    "自己対局で学んだ対称な線形評価を使い、数手先を読んで着手する。"
    "対局時にニューラルネットワークも OpenRouter も使わない。"
)
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[4] / "models" / "rl-tied.json"

__all__ = [
    "CATEGORY",
    "DEFAULT_MODEL_PATH",
    "DESCRIPTION",
    "DISPLAY_NAME",
    "SEARCH_DEPTH",
    "SPECIMEN_ID",
    "choose_move",
    "default_policy",
]


_CACHED: LinearPolicy | None = None
_CACHED_PATH: Path | None = None


def default_policy() -> LinearPolicy:
    """`models/rl-tied.json` を一度だけ読む。"""
    global _CACHED, _CACHED_PATH
    path = DEFAULT_MODEL_PATH
    if _CACHED is None or _CACHED_PATH != path:
        _CACHED = load_policy(path)
        _CACHED_PATH = path
    return _CACHED


def choose_move(position: Position, rng: Random | None = None) -> Place | None:
    """深さ 4 の αβ。葉は対称に共有した線形 v。終盤の完全読みはしない。"""
    del rng
    return choose_at_depth(position, SEARCH_DEPTH, policy=default_policy())
