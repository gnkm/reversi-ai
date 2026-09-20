"""sklearn で線形モデルを学習し、対局用の係数 JSON を書く。

データ源は WTHOR と永続化対局。成果物は models/ml.json。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import Ridge

from reversi.agents.ml import ALGORITHM, LinearModel, load_model
from reversi.encode import VECTOR_SIZE
from reversi.train.examples import DEFAULT_GAMES_DB, collect_examples
from reversi.train.wthor import DEFAULT_WTHOR_DIR

DEFAULT_OUT = Path(__file__).resolve().parents[4] / "models" / "ml.json"
DEFAULT_ALPHA = 1.0

__all__ = [
    "DEFAULT_GAMES_DB",
    "DEFAULT_OUT",
    "dump_model",
    "train",
    "train_and_write",
]


def _fit_ridge(features: np.ndarray, labels: np.ndarray, alpha: float) -> LinearModel:
    estimator = Ridge(alpha=alpha)
    estimator.fit(features, labels)
    weights = tuple(float(value) for value in np.asarray(estimator.coef_).ravel())
    intercept = np.asarray(estimator.intercept_).reshape(-1)
    return LinearModel(weights=weights, bias=float(intercept[0]))


def train(
    *,
    wthor: Path | None = None,
    games: Path | None = None,
    alpha: float = DEFAULT_ALPHA,
) -> LinearModel:
    """WTHOR と永続化対局から Ridge を学習し、対局用の係数を返す。"""
    features, labels = collect_examples(wthor=wthor, games=games)
    if features.shape[1] != VECTOR_SIZE:
        raise ValueError(f"特徴量の長さは {VECTOR_SIZE} でなければなりません")
    return _fit_ridge(features, labels, alpha)


def dump_model(path: Path, model: LinearModel) -> None:
    """対局経路が読む JSON を書く。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "algorithm": ALGORITHM,
        "weights": [float(value) for value in model.weights],
        "bias": float(model.bias),
    }
    path.write_text(
        json.dumps(payload, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def train_and_write(
    path: Path,
    *,
    wthor: Path | None = None,
    games: Path | None = None,
    alpha: float = DEFAULT_ALPHA,
) -> LinearModel:
    """学習して `path` に書き、読めることを確認する。"""
    model = train(wthor=wthor, games=games, alpha=alpha)
    dump_model(path, model)
    load_model(path)
    return model


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="WTHOR と永続化対局から sklearn の線形モデルを学習し、対局用係数を書く。",
    )
    parser.add_argument("--wthor", type=Path, default=DEFAULT_WTHOR_DIR)
    parser.add_argument("--games", type=Path, default=DEFAULT_GAMES_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--alpha", type=float, default=DEFAULT_ALPHA)
    args = parser.parse_args(argv)
    train_and_write(args.out, wthor=args.wthor, games=args.games, alpha=args.alpha)


if __name__ == "__main__":
    main()
