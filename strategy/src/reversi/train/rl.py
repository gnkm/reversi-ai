"""自己対局の線形 TD。WTHOR を使わない。

α と ε は局が進むほど下げる。探索手の直後は更新の目標にしない。
8 回対称で一致するマスは同じ重みを共有し、空平面は使わない。
既定の書き出しは models/rl.json。段階 2 のカタログ個体は models/rl-tied.json を読む。
"""

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
# 減衰が終わるときの割合。その後は下限のままにする。下限は 0 で、後半の重みを動かさない。
ALPHA_FLOOR_RATIO = 0.0
EPSILON_FLOOR_RATIO = 0.0
DECAY_FRACTION = 0.7
PLANE = 64
EMPTY_PLANE = 2 * PLANE

__all__ = [
    "ALPHA_FLOOR_RATIO",
    "DECAY_FRACTION",
    "DEFAULT_OUT",
    "EPSILON_FLOOR_RATIO",
    "SQUARE_ORBITS",
    "dump_policy",
    "scheduled_rate",
    "train",
    "train_and_write",
]


def _d4_images(file: int, rank: int) -> tuple[int, ...]:
    """回転と反転で重なるマス。添字は rank * 8 + file。"""
    last = 7
    found: set[int] = set()
    for rotations in range(4):
        for mirrored in (False, True):
            next_file, next_rank = file, rank
            for _ in range(rotations):
                next_file, next_rank = next_rank, last - next_file
            if mirrored:
                next_file = last - next_file
            found.add(next_rank * 8 + next_file)
    return tuple(sorted(found))


def _square_orbits() -> tuple[tuple[int, ...], ...]:
    seen: set[int] = set()
    orbits: list[tuple[int, ...]] = []
    for rank in range(8):
        for file in range(8):
            index = rank * 8 + file
            if index in seen:
                continue
            orbit = _d4_images(file, rank)
            seen.update(orbit)
            orbits.append(orbit)
    return tuple(orbits)


SQUARE_ORBITS = _square_orbits()


def scheduled_rate(
    initial: float,
    game_index: int,
    games: int,
    floor_ratio: float,
    decay_fraction: float = DECAY_FRACTION,
) -> float:
    """序盤から中盤にかけて線形に下げ、その後は下限のままにする。"""
    if games < 1:
        raise ValueError("対局数は 1 以上でなければなりません")
    if game_index < 1 or game_index > games:
        raise ValueError("局番号は 1 から対局数までです")
    if floor_ratio < 0 or floor_ratio > 1:
        raise ValueError("下限の割合は 0 以上 1 以下です")
    if decay_fraction <= 0 or decay_fraction > 1:
        raise ValueError("減衰の割合は 0 より大きく 1 以下です")
    if games == 1:
        return float(initial)
    decay_games = max(1, round(decay_fraction * (games - 1)))
    step = game_index - 1
    if step >= decay_games:
        return float(initial) * floor_ratio
    progress = step / decay_games
    return float(initial) * (1.0 - progress * (1.0 - floor_ratio))


def _features(board: Board) -> np.ndarray:
    """黒・白だけを使う。空平面は黒＋白＋空＝1 で切片と線形従属なので 0 にする。"""
    phi = np.asarray(encode(board).as_vector(), dtype=np.float64)
    phi[EMPTY_PLANE:] = 0.0
    return phi


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
) -> tuple[tuple[Board, ...], tuple[bool, ...], float]:
    """afterstate と、その手を ε で選んだかの列を返す。"""
    position = initial_position()
    afterstates: list[Board] = []
    exploratory: list[bool] = []
    while not is_over(position):
        if pass_is_legal(position):
            position = play(position, PassMove())
            continue
        places = legal_places(position)
        if rng.random() < epsilon:
            square = places[rng.randrange(len(places))]
            position = play(position, Place(square))
            exploratory.append(True)
        else:
            move = greedy_place(position, policy)
            if move is None:
                break
            position = play(position, move)
            exploratory.append(False)
        afterstates.append(position.board)
    reward = _black_reward(official_score(position.board))
    return tuple(afterstates), tuple(exploratory), reward


def _share_orbit(weights: np.ndarray, plane: int, orbit: tuple[int, ...], theta: float) -> None:
    base = plane * PLANE
    for index in orbit:
        weights[base + index] = theta


def _td_update(
    weights: np.ndarray,
    bias: float,
    boards: tuple[Board, ...],
    reward: float,
    alpha: float,
    exploratory: tuple[bool, ...] | None = None,
) -> tuple[np.ndarray, float]:
    """貪欲手の afterstate だけを更新する。探索手の直後は目標にしない。

    黒平面と白平面は、8 回対称で一致するマスが同じ重みを共有する。空平面は更新しない。
    """
    flags = exploratory if exploratory is not None else tuple(False for _ in boards)
    if len(flags) != len(boards):
        raise ValueError("探索手の印は afterstate と同じ長さでなければなりません")
    updated = weights.copy()
    updated[EMPTY_PLANE:] = 0.0
    for index, board in enumerate(boards):
        if flags[index]:
            continue
        phi = _features(board)
        current = float(updated @ phi + bias)
        if index + 1 == len(boards):
            target = reward
        elif flags[index + 1]:
            continue
        else:
            target = float(updated @ _features(boards[index + 1]) + bias)
        delta = target - current
        for plane in (0, 1):
            base = plane * PLANE
            for orbit in SQUARE_ORBITS:
                gradient = float(sum(phi[base + square] for square in orbit))
                theta = float(updated[base + orbit[0]]) + alpha * delta * gradient
                _share_orbit(updated, plane, orbit, theta)
        updated[EMPTY_PLANE:] = 0.0
        bias = bias + alpha * delta
    return updated, bias


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
        alpha_t = scheduled_rate(alpha, game_index, games, ALPHA_FLOOR_RATIO)
        epsilon_t = scheduled_rate(epsilon, game_index, games, EPSILON_FLOOR_RATIO)
        boards, exploratory, reward = _self_play(rng, policy, epsilon_t)
        weights, bias = _td_update(
            weights,
            bias,
            boards,
            reward,
            alpha_t,
            exploratory,
        )
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
    dump_policy(
        path,
        policy,
        extra={"games": games, "seed": seed, "alpha": alpha, "epsilon": epsilon},
    )
    load_policy(path)
    return policy


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="自己対局の線形 TD で対局用重みを書く。WTHOR は使わない。",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--games", type=int, default=DEFAULT_GAMES)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--alpha",
        type=float,
        default=DEFAULT_ALPHA,
        help="最初の局の学習率。対局数の 70% で 0 まで線形に下げ、その後は 0 のまま。",
    )
    parser.add_argument(
        "--epsilon",
        type=float,
        default=DEFAULT_EPSILON,
        help="最初の局の探索率。対局数の 70% で 0 まで線形に下げ、その後は 0 のまま。",
    )
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
