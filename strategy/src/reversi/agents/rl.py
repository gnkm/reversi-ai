"""自己対局の線形方針で合法手を選ぶ個体。NN 推論も OpenRouter も使わない。"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from random import Random

from reversi.encode import VECTOR_SIZE, encode
from reversi.engine.board import Board, Color, Square
from reversi.engine.rules import Place, Position, apply_place, legal_places

SPECIMEN_ID = "rl"
CATEGORY = "reinforcement_learning"
DISPLAY_NAME = "強化学習 (自己対局)"
DESCRIPTION = (
    "自己対局による強化学習で得た線形の方針で合法手を選ぶ。"
    "対局時にニューラルネットワークの推論も OpenRouter も使わない。"
)
DEFAULT_MODEL_PATH = (
    Path(__file__).resolve().parents[4] / "models" / "rl.json"
)

__all__ = [
    "CATEGORY",
    "DEFAULT_MODEL_PATH",
    "DESCRIPTION",
    "DISPLAY_NAME",
    "SPECIMEN_ID",
    "LinearPolicy",
    "choose_move",
    "greedy_place",
    "load_policy",
    "value_of",
]


@dataclass(frozen=True, slots=True)
class LinearPolicy:
    """黒から見た盤の価値。重みは 3×8×8 の入力符号化に対応する。"""

    weights: tuple[float, ...]
    bias: float

    def __post_init__(self) -> None:
        if len(self.weights) != VECTOR_SIZE:
            raise ValueError(
                f"重みの長さは {VECTOR_SIZE} でなければなりません"
            )
        if not math.isfinite(self.bias):
            raise ValueError("bias は有限値でなければなりません")
        if any(not math.isfinite(weight) for weight in self.weights):
            raise ValueError("重みは有限値でなければなりません")


_CACHED: LinearPolicy | None = None
_CACHED_PATH: Path | None = None


def value_of(board: Board, policy: LinearPolicy) -> float:
    """黒有利为正の線形価値。"""
    total = policy.bias
    for weight, feature in zip(policy.weights, encode(board).as_vector(), strict=True):
        if feature:
            total += weight
    return total


def load_policy(path: Path | None = None) -> LinearPolicy:
    """対局用の線形重みを JSON から読む。"""
    model_path = DEFAULT_MODEL_PATH if path is None else path
    raw = json.loads(model_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("rl.json の根はオブジェクトでなければなりません")
    algorithm = raw.get("algorithm")
    if algorithm is not None and algorithm != "linear_td":
        raise ValueError("rl.json の algorithm は linear_td でなければなりません")
    weights = raw.get("weights")
    bias = raw.get("bias")
    if not isinstance(weights, list) or not isinstance(bias, (int, float)):
        raise TypeError("rl.json に weights と bias が必要です")
    return LinearPolicy(
        weights=tuple(float(value) for value in weights),
        bias=float(bias),
    )


def default_policy() -> LinearPolicy:
    """リポジトリの `models/rl.json` を一度だけ読む。"""
    global _CACHED, _CACHED_PATH
    path = DEFAULT_MODEL_PATH
    if _CACHED is None or _CACHED_PATH != path:
        _CACHED = load_policy(path)
        _CACHED_PATH = path
    return _CACHED


def _afterstate_score(position: Position, square: Square, policy: LinearPolicy) -> float:
    after = apply_place(position.board, square, position.side_to_move)
    value = value_of(after, policy)
    if position.side_to_move is Color.BLACK:
        return value
    return -value


def greedy_place(position: Position, policy: LinearPolicy) -> Place | None:
    """黒は価値を最大化、白は最小化する。同点は a1…h8。"""
    best_square = None
    best_score: float | None = None
    for square in legal_places(position):
        score = _afterstate_score(position, square, policy)
        if best_score is None or score > best_score:
            best_score = score
            best_square = square
    if best_square is None:
        return None
    return Place(best_square)


def choose_move(
    position: Position,
    rng: Random | None = None,
    *,
    policy: LinearPolicy | None = None,
) -> Place | None:
    """学習済み線形方針の greedy。合法手が無ければ着手しない。"""
    del rng
    return greedy_place(position, policy if policy is not None else default_policy())
