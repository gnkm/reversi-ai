"""自己対局の線形 TD。WTHOR を使わない。成果物は models/rl.json。"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from random import Random
from typing import Any

import numpy as np

from reversi.agents.rl import LinearPolicy, greedy_place, load_policy
from reversi.encode import VECTOR_SIZE, encode
from reversi.engine.board import Board
from reversi.engine.rules import (
    PassMove,
    Place,
    initial_position,
    is_over,
    legal_places,
    pass_is_legal,
    play,
)
from reversi.engine.score import Score, official_score

DEFAULT_OUT = Path(__file__).resolve().parents[4] / "models" / "rl.json"
DEFAULT_GAMES = 400
DEFAULT_ALPHA = 0.001
DEFAULT_EPSILON = 0.1

__all__ = [
    "DEFAULT_OUT",
    "dump_policy",
    "train",
    "train_and_write",
]


def _features(board: Board) -> np.ndarray:
    return np.asarray(encode(board).as_vector(), dtype=np.float64)


def _black_reward(score: Score) -> float:
    if score.black > score.white:
        return 1.0
    if score.white > score.black:
        return -1.0
    return 0.0


def _to_policy(weights: np.ndarray, bias: float) -> LinearPolicy:
    return LinearPolicy(weights=tuple(float(value) for value in weights), bias=float(bias))


def _self_play(
    rng: Random,
    policy: LinearPolicy,
    epsilon: float,
) -> tuple[tuple[Board, ...], float]:
    position = initial_position()
    afterstates: list[Board] = []
    while not is_over(position):
        if pass_is_legal(position):
            position = play(position, PassMove())
            continue
        places = legal_places(position)
        if rng.random() < epsilon:
            square = places[rng.randrange(len(places))]
            position = play(position, Place(square))
        else:
            move = greedy_place(position, policy)
            if move is None:
                break
            position = play(position, move)
        afterstates.append(position.board)
    reward = _black_reward(official_score(position.board))
    return tuple(afterstates), reward


def _td_update(
    weights: np.ndarray,
    bias: float,
    boards: tuple[Board, ...],
    reward: float,
    alpha: float,
) -> tuple[np.ndarray, float]:
    for index, board in enumerate(boards):
        phi = _features(board)
        current = float(weights @ phi + bias)
        if index + 1 == len(boards):
            target = reward
        else:
            target = float(weights @ _features(boards[index + 1]) + bias)
        delta = target - current
        weights = weights + alpha * delta * phi
        bias = bias + alpha * delta
    return weights, bias


def _snapshot_name(games: int) -> str:
    return f"games-{games:05d}.json"


def _should_snapshot(game_index: int, total: int, every: int | None) -> bool:
    if every is None or every < 1:
        return False
    return game_index == total or game_index % every == 0


def train(
    games: int = DEFAULT_GAMES,
    *,
    seed: int = 0,
    alpha: float = DEFAULT_ALPHA,
    epsilon: float = DEFAULT_EPSILON,
    snapshot_every: int | None = None,
    snapshot_dir: Path | None = None,
) -> LinearPolicy:
    """同じエンジンで自己対局し、線形 TD(0) で重みを更新する。"""
    if games < 1:
        raise ValueError("対局数は 1 以上でなければなりません")
    if snapshot_every is not None and snapshot_every < 1:
        raise ValueError("スナップショット間隔は 1 以上でなければなりません")
    if snapshot_every and snapshot_dir is None:
        raise ValueError("スナップショット間隔を使うときは出力先が必要です")
    rng = Random(seed)
    weights = np.zeros(VECTOR_SIZE, dtype=np.float64)
    bias = 0.0
    policy = _to_policy(weights, bias)
    for game_index in range(1, games + 1):
        boards, reward = _self_play(rng, policy, epsilon)
        weights, bias = _td_update(weights, bias, boards, reward, alpha)
        policy = _to_policy(weights, bias)
        if snapshot_dir is not None and _should_snapshot(
            game_index, games, snapshot_every
        ):
            dump_policy(
                snapshot_dir / _snapshot_name(game_index),
                policy,
                extra={"games": game_index},
            )
    return policy


def dump_policy(
    path: Path,
    policy: LinearPolicy,
    *,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """対局経路が読む JSON を書く。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "algorithm": "linear_td",
        "weights": [float(value) for value in policy.weights],
        "bias": float(policy.bias),
    }
    if extra:
        payload.update(dict(extra))
    path.write_text(
        json.dumps(payload, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def train_and_write(
    path: Path,
    games: int = DEFAULT_GAMES,
    *,
    seed: int = 0,
    alpha: float = DEFAULT_ALPHA,
    epsilon: float = DEFAULT_EPSILON,
    snapshot_every: int | None = None,
    snapshot_dir: Path | None = None,
) -> LinearPolicy:
    """自己対局して `path` に書き、読めることを確認する。"""
    policy = train(
        games,
        seed=seed,
        alpha=alpha,
        epsilon=epsilon,
        snapshot_every=snapshot_every,
        snapshot_dir=snapshot_dir,
    )
    dump_policy(path, policy)
    load_policy(path)
    return policy


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="自己対局の線形 TD で対局用重みを書く。WTHOR は使わない。",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--games", type=int, default=DEFAULT_GAMES)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--alpha", type=float, default=DEFAULT_ALPHA)
    parser.add_argument("--epsilon", type=float, default=DEFAULT_EPSILON)
    parser.add_argument(
        "--snapshot-every",
        type=int,
        default=0,
        help="N 局ごとに重み JSON を書く。0 なら書かない。",
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=None,
        help="学習曲線用スナップショットの出力先。",
    )
    args = parser.parse_args(argv)
    snapshot_every = args.snapshot_every if args.snapshot_every > 0 else None
    train_and_write(
        args.out,
        args.games,
        seed=args.seed,
        alpha=args.alpha,
        epsilon=args.epsilon,
        snapshot_every=snapshot_every,
        snapshot_dir=args.snapshot_dir,
    )


if __name__ == "__main__":
    main()
