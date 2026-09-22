"""パターン特徴の評価を葉にする深さ 4 の αβ。終盤は完全読み。NN も OpenRouter も使わない。"""

from __future__ import annotations

from pathlib import Path
from random import Random

from reversi.agents.alphabeta import search_stats as alphabeta_search_stats
from reversi.agents.pattern_eval import PatternPolicy, load_policy, perspective_value
from reversi.agents.rl_search import SEARCH_DEPTH
from reversi.engine.board import BOARD_SIZE, Board, Color
from reversi.engine.rules import Place, Position
from reversi.engine.score import stone_counts

SPECIMEN_ID = "rl_pattern"
CATEGORY = "reinforcement_learning"
DISPLAY_NAME = "強化学習 (パターンの読み)"
DESCRIPTION = (
    "自己対局で学んだパターン評価を使い、数手先を読んで着手する。"
    "空きマスが少なければ終局まで読む。対局時に NN も OpenRouter も使わない。"
)
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[4] / "models" / "rl-pattern.json"
# 1 手の思考時間の上限から決める。shall ではない。目安 10〜14。
EXACT_EMPTY = 10
_EXACT_LIMIT = BOARD_SIZE * BOARD_SIZE

__all__ = [
    "CATEGORY",
    "DEFAULT_MODEL_PATH",
    "DESCRIPTION",
    "DISPLAY_NAME",
    "EXACT_EMPTY",
    "SEARCH_DEPTH",
    "SPECIMEN_ID",
    "choose_at_depth",
    "choose_move",
    "default_policy",
    "exact_leaf_score",
    "leaf_score",
    "search_stats",
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


def exact_leaf_score(board: Board, color: Color) -> int:
    """終局の石数差（自分 − 相手）。公式スコアの空マス加算はしない。"""
    counts = stone_counts(board)
    if color is Color.BLACK:
        return counts.black - counts.white
    return counts.white - counts.black


def _empty_count(board: Board) -> int:
    return stone_counts(board).empty


def _uses_exact(position: Position, exact_empty: int) -> bool:
    return exact_empty > 0 and _empty_count(position.board) <= exact_empty


def _resolve_threshold(exact_empty: int | None) -> int:
    if exact_empty is None:
        return EXACT_EMPTY
    return exact_empty


def _pattern_evaluate(policy: PatternPolicy):
    def evaluate(board: Board, color: Color) -> float:
        return perspective_value(board, color, policy)

    return evaluate


def choose_at_depth(
    position: Position,
    depth: int,
    *,
    policy: PatternPolicy | None = None,
    exact_empty: int | None = None,
) -> Place | None:
    """指定深さの αβ。葉はパターン特徴。空きマスが閾値以下なら終局まで読む。同点は a1…h8。"""
    place, _value, _nodes = search_stats(
        position, depth, policy=policy, exact_empty=exact_empty
    )
    return place


def search_stats(
    position: Position,
    depth: int,
    *,
    policy: PatternPolicy | None = None,
    exact_empty: int | None = None,
) -> tuple[Place | None, float | None, int]:
    """(手, その Negamax 値, 探索ノード数)。閾値以下なら終局石数差。"""
    loaded = default_policy() if policy is None else policy
    threshold = _resolve_threshold(exact_empty)
    if _uses_exact(position, threshold):
        return alphabeta_search_stats(
            position, _EXACT_LIMIT, evaluate=exact_leaf_score
        )
    return alphabeta_search_stats(
        position, depth, evaluate=_pattern_evaluate(loaded)
    )


def choose_move(position: Position, rng: Random | None = None) -> Place | None:
    """深さ 4 の αβ。空きマスが少なければ終局まで読む。葉は自己対局のパターン特徴。"""
    del rng
    return choose_at_depth(position, SEARCH_DEPTH)
