"""棋譜から得た線形モデルで合法手を選ぶ個体。NN ランタイムは使わない。"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from random import Random

from reversi.encode import VECTOR_SIZE, encode
from reversi.engine.board import Board, Color, Square
from reversi.engine.rules import Place, Position, apply_place, legal_places

SPECIMEN_ID = "ml"
CATEGORY = "machine_learning"
DISPLAY_NAME = "機械学習 (棋譜)"
DESCRIPTION = (
    "WTHOR と永続化対局から対局前に学習した線形モデルで着手する。"
    "対局時にニューラルネットワークの推論は使わない。"
)
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[4] / "models" / "ml.json"
ALGORITHM = "sklearn_ridge"

__all__ = [
    "ALGORITHM",
    "CATEGORY",
    "DEFAULT_MODEL_PATH",
    "DESCRIPTION",
    "DISPLAY_NAME",
    "SPECIMEN_ID",
    "LinearModel",
    "choose_move",
    "greedy_place",
    "load_model",
    "value_of",
]


@dataclass(frozen=True, slots=True)
class LinearModel:
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


_CACHED: LinearModel | None = None
_CACHED_PATH: Path | None = None


def value_of(board: Board, model: LinearModel) -> float:
    """黒有利为正の係数の積和。"""
    total = model.bias
    for weight, feature in zip(model.weights, encode(board).as_vector(), strict=True):
        total += weight * feature
    return total


def load_model(path: Path | None = None) -> LinearModel:
    """対局用の係数を JSON から読む。"""
    model_path = DEFAULT_MODEL_PATH if path is None else path
    raw = json.loads(model_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("ml.json の根はオブジェクトでなければなりません")
    algorithm = raw.get("algorithm")
    if algorithm is not None and algorithm != ALGORITHM:
        raise ValueError(f"ml.json の algorithm は {ALGORITHM} でなければなりません")
    weights = raw.get("weights")
    bias = raw.get("bias")
    if not isinstance(weights, list) or not isinstance(bias, (int, float)):
        raise TypeError("ml.json に weights と bias が必要です")
    return LinearModel(
        weights=tuple(float(value) for value in weights),
        bias=float(bias),
    )


def default_model() -> LinearModel:
    """リポジトリの `models/ml.json` を一度だけ読む。"""
    global _CACHED, _CACHED_PATH
    path = DEFAULT_MODEL_PATH
    if _CACHED is None or _CACHED_PATH != path:
        _CACHED = load_model(path)
        _CACHED_PATH = path
    return _CACHED


def _afterstate_score(position: Position, square: Square, model: LinearModel) -> float:
    after = apply_place(position.board, square, position.side_to_move)
    value = value_of(after, model)
    if position.side_to_move is Color.BLACK:
        return value
    return -value


def greedy_place(position: Position, model: LinearModel) -> Place | None:
    """黒は価値を最大化、白は最小化する。同点は a1…h8。"""
    best_square = None
    best_score: float | None = None
    for square in legal_places(position):
        score = _afterstate_score(position, square, model)
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
    model: LinearModel | None = None,
) -> Place | None:
    """学習済み線形モデルの greedy。合法手が無ければ着手しない。"""
    del rng
    return greedy_place(position, model if model is not None else default_model())
