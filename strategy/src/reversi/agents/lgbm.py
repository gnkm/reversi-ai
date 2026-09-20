"""LightGBM で得た木の集合で合法手を選ぶ個体。NN ランタイムは使わない。"""

from __future__ import annotations

from pathlib import Path
from random import Random
from typing import Protocol

import lightgbm as lgb

from reversi.encode import encode
from reversi.engine.board import Board, Color, Square
from reversi.engine.rules import Place, Position, apply_place, legal_places

SPECIMEN_ID = "lgbm"
CATEGORY = "machine_learning"
DISPLAY_NAME = "機械学習 (LightGBM)"
DESCRIPTION = (
    "WTHOR と永続化対局から対局前に LightGBM で学習したモデルで着手する。"
    "対局時にニューラルネットワークの推論は使わない。"
)
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[4] / "models" / "lgbm.txt"
NATIVE_HEADER = "tree"

__all__ = [
    "CATEGORY",
    "DEFAULT_MODEL_PATH",
    "DESCRIPTION",
    "DISPLAY_NAME",
    "NATIVE_HEADER",
    "SPECIMEN_ID",
    "ValueModel",
    "choose_move",
    "greedy_place",
    "load_model",
    "value_of",
]


class ValueModel(Protocol):
    """1 行の特徴量からスカラーを返す。LightGBM の Booster と試験用スタブが満たす。"""

    def predict(self, data: list[list[float]]) -> object: ...


_CACHED: lgb.Booster | None = None
_CACHED_PATH: Path | None = None


def value_of(board: Board, model: ValueModel) -> float:
    """黒有利为正の予測値。"""
    vector = [float(feature) for feature in encode(board).as_vector()]
    predicted = model.predict([vector])
    return float(predicted[0])


def load_model(path: Path | None = None) -> lgb.Booster:
    """対局用の LightGBM ネイティブテキストを読む。pickle / joblib は使わない。"""
    model_path = DEFAULT_MODEL_PATH if path is None else path
    text = model_path.read_text(encoding="utf-8")
    first = text.lstrip("\ufeff").splitlines()[0].strip() if text.strip() else ""
    if first != NATIVE_HEADER:
        raise ValueError("lgbm.txt は LightGBM のテキスト形式でなければなりません")
    return lgb.Booster(model_file=str(model_path))


def default_model() -> lgb.Booster:
    """リポジトリの `models/lgbm.txt` を一度だけ読む。"""
    global _CACHED, _CACHED_PATH
    path = DEFAULT_MODEL_PATH
    if _CACHED is None or _CACHED_PATH != path:
        _CACHED = load_model(path)
        _CACHED_PATH = path
    return _CACHED


def _afterstate_score(position: Position, square: Square, model: ValueModel) -> float:
    after = apply_place(position.board, square, position.side_to_move)
    value = value_of(after, model)
    if position.side_to_move is Color.BLACK:
        return value
    return -value


def greedy_place(position: Position, model: ValueModel) -> Place | None:
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
    model: ValueModel | None = None,
) -> Place | None:
    """学習済み LightGBM の greedy。合法手が無ければ着手しない。"""
    del rng
    return greedy_place(position, model if model is not None else default_model())
