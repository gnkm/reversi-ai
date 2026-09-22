"""パターン特徴の自己対局 TD(λ)。WTHOR を使わない。成果物は models/rl-pattern.json。"""

from __future__ import annotations

import argparse
from pathlib import Path
from random import Random

from reversi.agents.pattern_eval import (
    N_STAGES,
    NEIGHBOR_SMOOTH,
    PatternPolicy,
    active_count,
    analyze,
    black_value,
    dump_policy,
    load_policy,
    perspective_value,
    zero_policy,
)
from reversi.engine.board import Board, Color
from reversi.engine.rules import (
    PassMove,
    Place,
    Position,
    initial_position,
    is_over,
    legal_places,
    pass_is_legal,
    play,
)
from reversi.engine.score import official_score, stone_counts
from reversi.train.rl import scheduled_rate

DEFAULT_OUT = Path(__file__).resolve().parents[4] / "models" / "rl-pattern.json"
DEFAULT_GAMES = 400
DEFAULT_ALPHA = 0.05
DEFAULT_EPSILON = 0.1
DEFAULT_LAMBDA = 0.7
# α は全対局を通して初期値の 20% まで下げる。0 にはしない。
ALPHA_FLOOR_RATIO = 0.2
ALPHA_DECAY_FRACTION = 1.0
# ε は対局数の 70% で 0 にする。後半は貪欲手だけを学ぶ。
EPSILON_FLOOR_RATIO = 0.0
EPSILON_DECAY_FRACTION = 0.7
TRACE_FLOOR = 1e-8

__all__ = [
    "DEFAULT_LAMBDA",
    "DEFAULT_OUT",
    "terminal_reward",
    "train",
    "train_and_write",
]


def terminal_reward(board: Board, reward: str) -> float:
    """勝敗は +1/0/−1。石差は盤上の（黒−白）/64。"""
    if reward == "win_loss":
        score = official_score(board)
        if score.black > score.white:
            return 1.0
        if score.white > score.black:
            return -1.0
        return 0.0
    counts = stone_counts(board)
    return (counts.black - counts.white) / 64.0


def _greedy_place(position: Position, policy: PatternPolicy) -> Place | None:
    """深さ 1 の αβ と同じ符号。同点は a1…h8。"""
    best_square = None
    best_score: float | None = None
    for square in legal_places(position):
        after = play(position, Place(square))
        score = -perspective_value(after.board, after.side_to_move, policy)
        if best_score is None or score > best_score:
            best_score = score
            best_square = square
    if best_square is None:
        return None
    return Place(best_square)


def _self_play(
    rng: Random,
    policy: PatternPolicy,
    epsilon: float,
    reward_name: str,
) -> tuple[tuple[tuple[Board, Color], ...], tuple[bool, ...], float]:
    position = initial_position()
    afterstates: list[tuple[Board, Color]] = []
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
            move = _greedy_place(position, policy)
            if move is None:
                break
            position = play(position, move)
            exploratory.append(False)
        afterstates.append((position.board, position.side_to_move))
    reward = terminal_reward(position.board, reward_name)
    return tuple(afterstates), tuple(exploratory), reward


def _decay_trace(trace: dict[tuple[int, str, int], float], lam: float) -> None:
    if lam == 0.0:
        trace.clear()
        return
    dead: list[tuple[int, str, int]] = []
    for key, value in trace.items():
        nxt = value * lam
        if abs(nxt) < TRACE_FLOOR:
            dead.append(key)
        else:
            trace[key] = nxt
    for key in dead:
        del trace[key]


def _activate(
    trace: dict[tuple[int, str, int], float],
    stage: int,
    hits: tuple[tuple[str, int, float], ...],
) -> None:
    for name, index, gradient in hits:
        trace[(stage, name, index)] = gradient


def _add(
    policy: PatternPolicy, stage: int, name: str, index: int, amount: float
) -> None:
    if name == "bias":
        policy.bias[stage] += amount
        return
    if name == "scalar":
        policy.scalars[stage, index] += amount
        return
    policy.weights[name][stage, index] += amount


def _apply_trace(
    policy: PatternPolicy,
    trace: dict[tuple[int, str, int], float],
    step: float,
    delta: float,
) -> None:
    for (stage, name, index), eligibility in trace.items():
        amount = step * delta * eligibility
        _add(policy, stage, name, index, amount)
        if stage > 0:
            _add(policy, stage - 1, name, index, NEIGHBOR_SMOOTH * amount)
        if stage + 1 < N_STAGES:
            _add(policy, stage + 1, name, index, NEIGHBOR_SMOOTH * amount)


def _segment_end(
    states: tuple[tuple[Board, Color], ...],
    flags: tuple[bool, ...],
    start: int,
) -> int:
    """start から続く貪欲 afterstate の終端（含まない）。"""
    index = start
    while index < len(states) and not flags[index]:
        index += 1
    return index


def _delta_of(
    states: tuple[tuple[Board, Color], ...],
    index: int,
    stop: int,
    value: float,
    bootstrap: tuple[Board, Color] | None,
    reward: float | None,
    policy: PatternPolicy,
) -> float | None:
    if index + 1 < stop:
        nxt_board, nxt_side = states[index + 1]
        return black_value(nxt_board, nxt_side, policy) - value
    if reward is not None:
        return reward - value
    if bootstrap is None:
        return None
    return black_value(bootstrap[0], bootstrap[1], policy) - value


def _td_segment(
    policy: PatternPolicy,
    states: tuple[tuple[Board, Color], ...],
    start: int,
    stop: int,
    bootstrap: tuple[Board, Color] | None,
    reward: float | None,
    alpha: float,
    lam: float,
) -> None:
    """[start, stop) を更新する。終局なら reward、探索手の直前なら bootstrap。"""
    if stop <= start:
        return
    trace: dict[tuple[int, str, int], float] = {}
    step = alpha / active_count()
    for index in range(start, stop):
        board, side = states[index]
        stage, hits, value = analyze(board, side, policy)
        _decay_trace(trace, lam)
        _activate(trace, stage, hits)
        delta = _delta_of(states, index, stop, value, bootstrap, reward, policy)
        if delta is None:
            return
        _apply_trace(policy, trace, step, delta)


def _td_game(
    policy: PatternPolicy,
    states: tuple[tuple[Board, Color], ...],
    flags: tuple[bool, ...],
    reward: float,
    alpha: float,
    lam: float,
) -> None:
    """探索手の直後は目標にしない。貪欲の連続だけを TD(λ) で遡る。"""
    if len(flags) != len(states):
        raise ValueError("探索手の印は afterstate と同じ長さでなければなりません")
    start = 0
    while start < len(states):
        if flags[start]:
            start += 1
            continue
        end = _segment_end(states, flags, start)
        if end == len(states):
            _td_segment(policy, states, start, end, None, reward, alpha, lam)
            return
        # 次が探索手なので、その直前の貪欲局面は更新しない。
        _td_segment(
            policy,
            states,
            start,
            end - 1,
            states[end - 1],
            None,
            alpha,
            lam,
        )
        start = end


def _snapshot_name(games: int) -> str:
    return f"games-{games:05d}.json"


def train(
    games: int = DEFAULT_GAMES,
    *,
    seed: int = 0,
    alpha: float = DEFAULT_ALPHA,
    epsilon: float = DEFAULT_EPSILON,
    lam: float = DEFAULT_LAMBDA,
    reward: str = "win_loss",
    snapshot_every: int | None = None,
    snapshot_dir: Path | None = None,
) -> PatternPolicy:
    """自己対局の TD(λ)。活性な項目数で α を割る。"""
    if games < 1:
        raise ValueError("対局数は 1 以上でなければなりません")
    if reward not in {"win_loss", "stone_diff"}:
        raise ValueError("reward は win_loss か stone_diff です")
    if not 0.0 <= lam <= 1.0:
        raise ValueError("λ は 0 以上 1 以下です")
    if snapshot_every is not None and snapshot_every < 1:
        raise ValueError("スナップショット間隔は 1 以上でなければなりません")
    if snapshot_every and snapshot_dir is None:
        raise ValueError("スナップショット間隔を使うときは出力先が必要です")
    rng = Random(seed)
    policy = zero_policy()
    policy.reward = reward
    policy.lam = lam
    for game_index in range(1, games + 1):
        alpha_t = scheduled_rate(
            alpha, game_index, games, ALPHA_FLOOR_RATIO, ALPHA_DECAY_FRACTION
        )
        epsilon_t = scheduled_rate(
            epsilon,
            game_index,
            games,
            EPSILON_FLOOR_RATIO,
            EPSILON_DECAY_FRACTION,
        )
        states, flags, score = _self_play(rng, policy, epsilon_t, reward)
        _td_game(policy, states, flags, score, alpha_t, lam)
        if game_index == 1 or game_index % 200 == 0 or game_index == games:
            print(
                f"games={game_index}/{games} alpha={alpha_t:.5f} epsilon={epsilon_t:.4f}",
                flush=True,
            )
        if (
            snapshot_dir is not None
            and snapshot_every
            and (game_index == games or game_index % snapshot_every == 0)
        ):
            policy.games = game_index
            dump_policy(snapshot_dir / _snapshot_name(game_index), policy)
    policy.games = games
    return policy


def train_and_write(
    path: Path,
    games: int = DEFAULT_GAMES,
    *,
    seed: int = 0,
    alpha: float = DEFAULT_ALPHA,
    epsilon: float = DEFAULT_EPSILON,
    lam: float = DEFAULT_LAMBDA,
    reward: str = "win_loss",
    snapshot_every: int | None = None,
    snapshot_dir: Path | None = None,
) -> PatternPolicy:
    """自己対局して path に書き、読めることを確認する。"""
    policy = train(
        games,
        seed=seed,
        alpha=alpha,
        epsilon=epsilon,
        lam=lam,
        reward=reward,
        snapshot_every=snapshot_every,
        snapshot_dir=snapshot_dir,
    )
    dump_policy(
        path,
        policy,
        extra={"seed": seed, "alpha": alpha, "epsilon": epsilon},
    )
    load_policy(path)
    return policy


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="自己対局のパターン TD(λ) で対局用重みを書く。WTHOR は使わない。",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--games", type=int, default=DEFAULT_GAMES)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--alpha", type=float, default=DEFAULT_ALPHA)
    parser.add_argument("--epsilon", type=float, default=DEFAULT_EPSILON)
    parser.add_argument("--lambda", dest="lam", type=float, default=DEFAULT_LAMBDA)
    parser.add_argument(
        "--reward",
        choices=("win_loss", "stone_diff"),
        default="win_loss",
    )
    parser.add_argument("--snapshot-every", type=int, default=0)
    parser.add_argument("--snapshot-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    snapshot_every = args.snapshot_every if args.snapshot_every > 0 else None
    train_and_write(
        args.out,
        args.games,
        seed=args.seed,
        alpha=args.alpha,
        epsilon=args.epsilon,
        lam=args.lam,
        reward=args.reward,
        snapshot_every=snapshot_every,
        snapshot_dir=args.snapshot_dir,
    )


if __name__ == "__main__":
    main()
