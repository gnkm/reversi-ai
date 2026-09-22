"""自己対局で学んだ線形 v を葉にする深さ 4 の αβ。NN も OpenRouter も使わない。"""

from __future__ import annotations

from random import Random

from reversi.agents.alphabeta import choose_at_depth as alphabeta_choose_at_depth
from reversi.agents.rl import DEFAULT_MODEL_PATH as RL_MODEL_PATH
from reversi.agents.rl import LinearPolicy, default_policy, perspective_value
from reversi.engine.board import Board, Color
from reversi.engine.rules import Place, Position

SPECIMEN_ID = "rl_search"
CATEGORY = "reinforcement_learning"
DISPLAY_NAME = "強化学習 (自己対局＋読み)"
DESCRIPTION = (
    "自己対局で学んだ線形の評価を使い、数手先を読んで着手する。"
    "対局時にニューラルネットワークも OpenRouter も使わない。"
)
SEARCH_DEPTH = 4
# 評価はいまの RL の v。新しい重みファイルは学習しない。
DEFAULT_MODEL_PATH = RL_MODEL_PATH

__all__ = [
    "CATEGORY",
    "DEFAULT_MODEL_PATH",
    "DESCRIPTION",
    "DISPLAY_NAME",
    "SEARCH_DEPTH",
    "SPECIMEN_ID",
    "choose_at_depth",
    "choose_move",
    "leaf_score",
]


def leaf_score(
    board: Board,
    color: Color,
    policy: LinearPolicy | None = None,
) -> float:
    """color 視点の線形 v。白番は符号反転。葉の外へ定数は足さない。"""
    loaded = default_policy() if policy is None else policy
    return perspective_value(board, color, loaded)


def choose_at_depth(
    position: Position,
    depth: int,
    *,
    policy: LinearPolicy | None = None,
) -> Place | None:
    """指定深さの αβ。葉は学習済み線形 v。同点は a1…h8。"""
    loaded = default_policy() if policy is None else policy

    def evaluate(board: Board, color: Color) -> float:
        return perspective_value(board, color, loaded)

    return alphabeta_choose_at_depth(position, depth, evaluate=evaluate)


def choose_move(position: Position, rng: Random | None = None) -> Place | None:
    """深さ 4 の αβ で合法手を選ぶ。評価は自己対局の線形 v。"""
    del rng
    return choose_at_depth(position, SEARCH_DEPTH)
