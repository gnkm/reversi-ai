"""LightGBM で勾配ブースティングを学習し、対局用のネイティブテキストを書く。

データ源は WTHOR と永続化対局。成果物は models/lgbm.txt。
対局時は pickle / joblib / ONNX を使わない。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import lightgbm as lgb
import numpy as np

from reversi.agents.lgbm import DEFAULT_MODEL_PATH, NATIVE_HEADER, load_model
from reversi.encode import VECTOR_SIZE
from reversi.train.examples import DEFAULT_GAMES_DB, collect_examples
from reversi.train.wthor import DEFAULT_WTHOR_DIR

DEFAULT_OUT = DEFAULT_MODEL_PATH
DEFAULT_NUM_BOOST_ROUND = 32
DEFAULT_NUM_LEAVES = 8
DEFAULT_MAX_DEPTH = 4
DEFAULT_LEARNING_RATE = 0.08
DEFAULT_MIN_DATA_IN_LEAF = 1
DEFAULT_SEED = 0

__all__ = [
    "DEFAULT_GAMES_DB",
    "DEFAULT_OUT",
    "dump_model",
    "train",
    "train_and_write",
]


def _min_data_in_leaf(n_examples: int, requested: int) -> int:
    if n_examples < 1:
        raise ValueError("学習例がありません。WTHOR または永続化対局が必要です")
    return max(1, min(requested, n_examples))


def _fit_booster(
    features: np.ndarray,
    labels: np.ndarray,
    *,
    num_boost_round: int,
    num_leaves: int,
    max_depth: int,
    learning_rate: float,
    min_data_in_leaf: int,
    seed: int,
) -> lgb.Booster:
    params = {
        "objective": "regression",
        "metric": "l2",
        "verbosity": -1,
        "num_leaves": num_leaves,
        "max_depth": max_depth,
        "learning_rate": learning_rate,
        "min_data_in_leaf": _min_data_in_leaf(features.shape[0], min_data_in_leaf),
        "min_data_in_bin": 1,
        "feature_pre_filter": False,
        "seed": seed,
        "num_threads": 1,
        "force_col_wise": True,
        "deterministic": True,
    }
    names = [f"f{index}" for index in range(VECTOR_SIZE)]
    dataset = lgb.Dataset(
        features,
        label=labels,
        feature_name=names,
        params={"verbose": -1},
    )
    return lgb.train(params, dataset, num_boost_round=num_boost_round)


def train(
    *,
    wthor: Path | None = None,
    games: Path | None = None,
    num_boost_round: int = DEFAULT_NUM_BOOST_ROUND,
    num_leaves: int = DEFAULT_NUM_LEAVES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    learning_rate: float = DEFAULT_LEARNING_RATE,
    min_data_in_leaf: int = DEFAULT_MIN_DATA_IN_LEAF,
    seed: int = DEFAULT_SEED,
) -> lgb.Booster:
    """WTHOR と永続化対局から LightGBM を学習し、対局用の Booster を返す。"""
    features, labels = collect_examples(wthor=wthor, games=games)
    return _fit_booster(
        features,
        labels,
        num_boost_round=num_boost_round,
        num_leaves=num_leaves,
        max_depth=max_depth,
        learning_rate=learning_rate,
        min_data_in_leaf=min_data_in_leaf,
        seed=seed,
    )


def dump_model(path: Path, booster: lgb.Booster) -> None:
    """対局経路が読む LightGBM ネイティブテキストを書く。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(path))
    header = path.read_text(encoding="utf-8").lstrip("\ufeff").splitlines()[0].strip()
    if header != NATIVE_HEADER:
        raise ValueError("書き出した成果物が LightGBM のテキスト形式ではありません")


def train_and_write(
    path: Path,
    *,
    wthor: Path | None = None,
    games: Path | None = None,
    num_boost_round: int = DEFAULT_NUM_BOOST_ROUND,
    num_leaves: int = DEFAULT_NUM_LEAVES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    learning_rate: float = DEFAULT_LEARNING_RATE,
    min_data_in_leaf: int = DEFAULT_MIN_DATA_IN_LEAF,
    seed: int = DEFAULT_SEED,
) -> lgb.Booster:
    """学習して `path` に書き、読めることを確認する。"""
    booster = train(
        wthor=wthor,
        games=games,
        num_boost_round=num_boost_round,
        num_leaves=num_leaves,
        max_depth=max_depth,
        learning_rate=learning_rate,
        min_data_in_leaf=min_data_in_leaf,
        seed=seed,
    )
    dump_model(path, booster)
    load_model(path)
    return booster


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="WTHOR と永続化対局から LightGBM を学習し、対局用テキストを書く。",
    )
    parser.add_argument("--wthor", type=Path, default=DEFAULT_WTHOR_DIR)
    parser.add_argument("--games", type=Path, default=DEFAULT_GAMES_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--num-boost-round", type=int, default=DEFAULT_NUM_BOOST_ROUND)
    parser.add_argument("--num-leaves", type=int, default=DEFAULT_NUM_LEAVES)
    parser.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH)
    parser.add_argument("--learning-rate", type=float, default=DEFAULT_LEARNING_RATE)
    parser.add_argument("--min-data-in-leaf", type=int, default=DEFAULT_MIN_DATA_IN_LEAF)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args(argv)
    train_and_write(
        args.out,
        wthor=args.wthor,
        games=args.games,
        num_boost_round=args.num_boost_round,
        num_leaves=args.num_leaves,
        max_depth=args.max_depth,
        learning_rate=args.learning_rate,
        min_data_in_leaf=args.min_data_in_leaf,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
