#!/usr/bin/env python3
"""RL 改善の段階 0。開始局面集合と先後入れ替え評価を JSON に書く。

対局の再実行は CI に載せない。ホストで明示的に走らせる。
評価経路は WTHOR を読まない。対局時に NN 推論も OpenRouter も使わない。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from random import Random
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STRATEGY_SRC = ROOT / "strategy" / "src"
if str(STRATEGY_SRC) not in sys.path:
    sys.path.insert(0, str(STRATEGY_SRC))

from reversi.agents import minimax, positional, random_uniform, rl  # noqa: E402
from reversi.agents.rl import LinearPolicy  # noqa: E402
from reversi.engine.board import Board, Color, Square, Stone  # noqa: E402
from reversi.engine.rules import (  # noqa: E402
    PassMove,
    Place,
    Position,
    initial_position,
    is_over,
    legal_places,
    play,
)
from reversi.engine.score import official_score, stone_counts  # noqa: E402

OPENINGS_OUT = Path(__file__).resolve().parent / "rl-openings.json"
STAGE0_OUT = Path(__file__).resolve().parent / "rl-stage0.json"
SEED = 20260922
N_STARTS = 200
OPENING_PLIES = (4, 5, 6, 7, 8)
Z95 = 1.959963984540054
EVEN_NOTE = "この局数では区別できない"
OPPONENTS: tuple[dict[str, str], ...] = (
    {
        "specimen_id": random_uniform.SPECIMEN_ID,
        "display_name": random_uniform.DISPLAY_NAME,
    },
    {
        "specimen_id": positional.SPECIMEN_ID,
        "display_name": positional.DISPLAY_NAME,
    },
    {
        "specimen_id": minimax.SPECIMEN_ID,
        "display_name": minimax.DISPLAY_NAME,
    },
)
_STONE = {".": Stone.EMPTY, "B": Stone.BLACK, "W": Stone.WHITE}
_CHAR = {Stone.EMPTY: ".", Stone.BLACK: "B", Stone.WHITE: "W"}
_ROUND_ROBIN = Path(__file__).resolve().parent / "round-robin.md"

__all__ = [
    "EVEN_NOTE",
    "N_STARTS",
    "OPENING_PLIES",
    "OPPONENTS",
    "SEED",
    "evaluate_policy",
    "make_openings",
    "mean_and_ci95",
    "openings_payload",
    "summarize_games",
]


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - replace で原子的に置く
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    )
    tmp = Path(handle.name)
    try:
        handle.write(serialized.encode("utf-8"))
        handle.close()
        tmp.replace(path)
    except Exception:
        handle.close()
        tmp.unlink(missing_ok=True)
        raise


def _board_rows(position: Position) -> list[str]:
    rows: list[str] = []
    for rank in range(7, -1, -1):
        rows.append(
            "".join(
                _CHAR[position.board.stone_at(Square(file=file, rank=rank))]
                for file in range(8)
            )
        )
    return rows


def _position_from_rows(rows: Sequence[str], side: str) -> Position:
    cells = tuple(tuple(_STONE[ch] for ch in row) for row in reversed(rows))
    color = Color.BLACK if side in {"B", "black"} else Color.WHITE
    return Position(Board(cells), color)


def _random_opening(rng: Random, plies: int) -> Position:
    position = initial_position()
    for _ in range(plies):
        if is_over(position):
            break
        places = legal_places(position)
        if not places:
            position = play(position, PassMove())
            continue
        position = play(position, Place(rng.choice(list(places))))
    return position


def make_openings(rng: Random, count: int) -> list[dict[str, Any]]:
    """seed 付き乱数から、初形 4〜8 手の開始局面を固定する。"""
    if count < 1:
        raise ValueError("開始局面数は 1 以上でなければなりません")
    found: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    attempts = 0
    while len(found) < count:
        attempts += 1
        if attempts > count * 50:
            raise RuntimeError("開始局面を十分な数だけ作れない")
        plies = OPENING_PLIES[len(found) % len(OPENING_PLIES)]
        position = _random_opening(rng, plies)
        if is_over(position) or not legal_places(position):
            continue
        rows = _board_rows(position)
        key = (*rows, position.side_to_move.value)
        if key in seen:
            continue
        seen.add(key)
        found.append(
            {
                "index": len(found),
                "opening_plies": plies,
                "side_to_move": position.side_to_move.value,
                "board": rows,
            }
        )
    return found


def openings_payload(
    positions: Sequence[Mapping[str, Any]],
    seed: int,
) -> dict[str, Any]:
    return {
        "seed": seed,
        "count": len(positions),
        "opening_plies": list(OPENING_PLIES),
        "notes": [
            "初形からランダムな合法手を 4〜8 手進めた開始局面。比較するどの個体にも同じ集合を使う。",
            "乱数種を固定すると同じ集合が再現する。対局の再実行は CI に載せない。",
        ],
        "positions": [dict(row) for row in positions],
    }


def mean_and_ci95(values: Sequence[float]) -> dict[str, Any]:
    """標本平均と正規近似の 95% 区間。勝率の区間が 0.5 をまたぐときは区別できない。"""
    n = len(values)
    if n == 0:
        return {
            "n": 0,
            "mean": 0.0,
            "low": 0.0,
            "high": 0.0,
            "crosses_even": True,
            "note": EVEN_NOTE,
        }
    mean = sum(values) / n
    if n == 1:
        return {
            "n": 1,
            "mean": mean,
            "low": mean,
            "high": mean,
            "crosses_even": mean == 0.5,
            "note": EVEN_NOTE if mean == 0.5 else None,
        }
    centered = [(value - mean) ** 2 for value in values]
    stdev = math.sqrt(sum(centered) / (n - 1))
    half = Z95 * stdev / math.sqrt(n)
    low = mean - half
    high = mean + half
    crosses = low <= 0.5 <= high
    return {
        "n": n,
        "mean": mean,
        "low": low,
        "high": high,
        "crosses_even": crosses,
        "note": EVEN_NOTE if crosses else None,
    }


def _policy_from_mapping(raw: Mapping[str, Any]) -> LinearPolicy:
    return LinearPolicy(
        weights=tuple(float(value) for value in raw["weights"]),
        bias=float(raw["bias"]),
    )


def _choose_opponent(position: Position, opponent_id: str, rng: Random) -> Place | None:
    if opponent_id == random_uniform.SPECIMEN_ID:
        return random_uniform.choose_move(position, rng)
    if opponent_id == positional.SPECIMEN_ID:
        return positional.choose_move(position)
    if opponent_id == minimax.SPECIMEN_ID:
        return minimax.choose_move(position)
    raise KeyError(opponent_id)


def play_game(
    start: Position,
    policy: LinearPolicy,
    opponent_id: str,
    rl_is_black: bool,
    rng: Random,
) -> dict[str, Any]:
    """1 局を最後まで進め、RL から見た勝敗と石差を返す。"""
    position = start
    while not is_over(position):
        places = legal_places(position)
        if not places:
            position = play(position, PassMove())
            continue
        is_rl = (position.side_to_move is Color.BLACK) == rl_is_black
        if is_rl:
            move = rl.greedy_place(position, policy)
        else:
            move = _choose_opponent(position, opponent_id, rng)
        if not isinstance(move, Place) or move.square not in places:
            raise RuntimeError("合法手の外を選んだ")
        position = play(position, move)
    counts = stone_counts(position.board)
    score = official_score(position.board)
    own_official = score.black if rl_is_black else score.white
    opp_official = score.white if rl_is_black else score.black
    own_stones = counts.black if rl_is_black else counts.white
    opp_stones = counts.white if rl_is_black else counts.black
    if own_official > opp_official:
        result = "win"
        score_value = 1.0
    elif own_official < opp_official:
        result = "loss"
        score_value = 0.0
    else:
        result = "draw"
        score_value = 0.5
    return {
        "result": result,
        "score": score_value,
        "stone_diff": own_stones - opp_stones,
        "official_black": score.black,
        "official_white": score.white,
        "stones_black": counts.black,
        "stones_white": counts.white,
    }


def _job_rng(base_seed: int, start_index: int, opponent_id: str, rl_is_black: bool) -> Random:
    material = f"{base_seed}:{start_index}:{opponent_id}:{'B' if rl_is_black else 'W'}"
    return Random(int.from_bytes(material.encode("utf-8"), "little") % (2**32))


def play_job(
    start: Mapping[str, Any],
    opponent_id: str,
    rl_is_black: bool,
    weights: Sequence[float],
    bias: float,
    base_seed: int,
) -> dict[str, Any]:
    """プロセスプール用。重みの写しと先後だけを受け取る。"""
    policy = LinearPolicy(weights=tuple(float(value) for value in weights), bias=float(bias))
    position = _position_from_rows(start["board"], str(start["side_to_move"]))
    raw = play_game(
        position,
        policy,
        opponent_id,
        rl_is_black,
        _job_rng(base_seed, int(start["index"]), opponent_id, rl_is_black),
    )
    return {
        "start_index": int(start["index"]),
        "opponent": opponent_id,
        "rl_color": "black" if rl_is_black else "white",
        **raw,
    }


def _ci_block(scores: Sequence[float], diffs: Sequence[float]) -> dict[str, Any]:
    win = mean_and_ci95(scores)
    stone = mean_and_ci95(diffs)
    stone.pop("crosses_even", None)
    stone.pop("note", None)
    return {"win_rate": win, "mean_stone_diff": stone}


def summarize_games(games: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    n = len(games)
    wins = sum(1 for game in games if game["result"] == "win")
    draws = sum(1 for game in games if game["result"] == "draw")
    losses = sum(1 for game in games if game["result"] == "loss")
    scores = [float(game["score"]) for game in games]
    diffs = [float(game["stone_diff"]) for game in games]
    ci95 = _ci_block(scores, diffs)
    win_rate = ci95["win_rate"]["mean"] if n else 0.0
    mean_diff = ci95["mean_stone_diff"]["mean"] if n else 0.0
    by_opponent: list[dict[str, Any]] = []
    for meta in OPPONENTS:
        rows = [game for game in games if game["opponent"] == meta["specimen_id"]]
        opp_scores = [float(game["score"]) for game in rows]
        opp_diffs = [float(game["stone_diff"]) for game in rows]
        opp_ci = _ci_block(opp_scores, opp_diffs)
        by_opponent.append(
            {
                "specimen_id": meta["specimen_id"],
                "display_name": meta["display_name"],
                "n_games": len(rows),
                "wins": sum(1 for game in rows if game["result"] == "win"),
                "draws": sum(1 for game in rows if game["result"] == "draw"),
                "losses": sum(1 for game in rows if game["result"] == "loss"),
                "win_rate": opp_ci["win_rate"]["mean"] if rows else 0.0,
                "mean_stone_diff": opp_ci["mean_stone_diff"]["mean"] if rows else 0.0,
                "ci95": opp_ci,
            }
        )
    return {
        "n_games": n,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "win_rate": win_rate,
        "mean_stone_diff": mean_diff,
        "ci95": ci95,
        "opponents": by_opponent,
    }


def _round_robin_tendency() -> dict[str, Any]:
    text = _ROUND_ROBIN.read_text(encoding="utf-8") if _ROUND_ROBIN.is_file() else ""
    return {
        "source": "docs/benchmarks/round-robin.md",
        "recorded_at": "2026-09-21 19:09",
        "rl_points": 9.5,
        "rl_rank": 5,
        "notes": [
            "総当たりは組み合わせごとに初形から 2 局だけで、決定的な個体では同じ 2 局しか出ない。",
            "19:09 の記録では強化学習 (自己対局) は勝ち点 9.5・5 位。位置評価は 9 点・6 位、ミニマックスは 17.5 点・2 位、一様乱択は 5 点・11 位。",
            "本評価は同じ 3 相手を、固定した開始局面集合と先後入れ替えで測る。傾向が合うかは勝率の大小で見る。",
        ],
        "present_in_round_robin_md": "強化学習 (自己対局)" in text,
    }


def evaluate_policy(
    policy: LinearPolicy,
    openings: Sequence[Mapping[str, Any]],
    *,
    seed: int,
    workers: int,
    opponent_ids: Sequence[str] | None = None,
    progress: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """同じ開始局面・先後入れ替えで相手ごとに対局し、要約と棋譜を返す。"""
    wanted = tuple(opponent_ids) if opponent_ids is not None else tuple(
        item["specimen_id"] for item in OPPONENTS
    )
    jobs: list[tuple[Mapping[str, Any], str, bool]] = []
    for start in openings:
        for opponent_id in wanted:
            jobs.append((start, opponent_id, True))
            jobs.append((start, opponent_id, False))
    games: list[dict[str, Any]] = []
    weights = list(policy.weights)
    bias = float(policy.bias)
    total = len(jobs)

    def _note(record: Mapping[str, Any], done: int) -> None:
        if not progress:
            return
        print(
            f"start {record['start_index']} opp={record['opponent']} "
            f"rl={record['rl_color']} {record['result']} "
            f"diff={record['stone_diff']} done={done}/{total}",
            flush=True,
        )

    if workers <= 1 or len(jobs) <= 1:
        for start, opponent_id, rl_is_black in jobs:
            record = play_job(start, opponent_id, rl_is_black, weights, bias, seed)
            games.append(record)
            _note(record, len(games))
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(
                    play_job, start, opponent_id, rl_is_black, weights, bias, seed
                )
                for start, opponent_id, rl_is_black in jobs
            ]
            for future in as_completed(futures):
                record = future.result()
                games.append(record)
                _note(record, len(games))
    games.sort(
        key=lambda row: (
            int(row["start_index"]),
            str(row["opponent"]),
            str(row["rl_color"]),
        )
    )
    return summarize_games(games), games


def _snapshot_sort_key(path: Path) -> tuple[int, str]:
    stem = path.stem
    prefix = "games-"
    if stem.startswith(prefix):
        digits = stem[len(prefix) :]
        if digits.isdigit():
            return (int(digits), stem)
    payload = json.loads(path.read_text(encoding="utf-8"))
    games = payload.get("games")
    if isinstance(games, int):
        return (games, stem)
    return (10**9, stem)


def load_snapshot_policies(directory: Path) -> list[tuple[int, Path, LinearPolicy]]:
    files = sorted(directory.glob("*.json"), key=_snapshot_sort_key)
    loaded: list[tuple[int, Path, LinearPolicy]] = []
    for path in files:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or "weights" not in raw:
            continue
        games, _ = _snapshot_sort_key(path)
        loaded.append((games, path, _policy_from_mapping(raw)))
    if not loaded:
        raise FileNotFoundError(f"スナップショット JSON が無い: {directory}")
    return loaded


def _protocol(seed: int, n_starts: int, workers: int) -> dict[str, Any]:
    return {
        "starts": n_starts,
        "games_per_start": 2,
        "opening_plies": list(OPENING_PLIES),
        "seed": seed,
        "paired": True,
        "workers": workers,
        "minimax_depth": minimax.SEARCH_DEPTH,
        "notes": [
            "開始局面は初形から 4〜8 手を一様乱択で進めた組。各局面で先後を入れ替える。",
            "候補はカタログの「強化学習 (自己対局)」。表示名・個体 ID・カテゴリは変えない。",
            "対戦相手はランダム (一様)、ルールベース (位置評価)、カタログのミニマックス（深さ 4）。新しいカタログ個体は置かない。",
            "勝率は（勝 + 0.5×分）/ 局数。石差は盤上の石数（RL − 相手）。",
            "95% 区間は標本平均の正規近似。勝率の区間が 0.5 をまたぐときは「この局数では区別できない」と書く。差がない、とは書かない。",
            "学習 N 局ごとの重みスナップショットは train.rl の --snapshot-every で書き、同じ相手で測れる。",
            "評価経路は WTHOR を読まない。対局時に NN 推論も OpenRouter も使わない。",
            "対局の再実行は CI に載せない。本スクリプトはホストで明示実行する。",
        ],
    }


def _stage0_payload(
    *,
    model_path: Path,
    openings: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
    games: Sequence[Mapping[str, Any]],
    seed: int,
    workers: int,
    learning_curve: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    rel = model_path
    try:
        rel = model_path.resolve().relative_to(ROOT)
    except ValueError:
        rel = model_path
    return {
        "recorded_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
        "candidate": {
            "specimen_id": rl.SPECIMEN_ID,
            "display_name": rl.DISPLAY_NAME,
            "category": rl.CATEGORY,
            "model": str(rel),
        },
        "protocol": _protocol(seed, len(openings), workers),
        **summary,
        "learning_curve": list(learning_curve),
        "round_robin_tendency": _round_robin_tendency(),
        "starts": [dict(row) for row in openings],
        "game_records": list(games),
    }


def _load_openings(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return [dict(row) for row in raw]
    positions = raw.get("positions")
    if not isinstance(positions, list):
        raise ValueError("開始局面 JSON に positions が無い")
    return [dict(row) for row in positions]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="RL の開始局面集合と先後入れ替え評価を書く"
    )
    parser.add_argument("--openings-out", type=Path, default=OPENINGS_OUT)
    parser.add_argument("--output", type=Path, default=STAGE0_OUT)
    parser.add_argument("--starts", type=int, default=N_STARTS)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--policy", type=Path, default=rl.DEFAULT_MODEL_PATH)
    parser.add_argument("--snapshots-dir", type=Path, default=None)
    parser.add_argument("--write-openings-only", action="store_true")
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="並列数。0 なら CPU 数（最大 4）",
    )
    args = parser.parse_args(argv)
    if args.starts < 1:
        raise SystemExit("開始局面数は 1 以上")
    cpu = os.cpu_count() or 1
    workers = args.workers if args.workers > 0 else min(4, cpu)
    openings_path = args.openings_out
    openings_path.parent.mkdir(parents=True, exist_ok=True)
    if openings_path.is_file():
        openings = _load_openings(openings_path)
        print(f"loaded openings n={len(openings)} path={openings_path}", flush=True)
    else:
        openings = make_openings(Random(args.seed), args.starts)
        _atomic_write(openings_path, openings_payload(openings, args.seed))
        print(f"wrote openings n={len(openings)} path={openings_path}", flush=True)
    if args.write_openings_only:
        return 0
    if len(openings) != args.starts:
        openings = openings[: args.starts]
    policy = rl.load_policy(args.policy)
    summary, games = evaluate_policy(
        policy, openings, seed=args.seed, workers=workers, progress=True
    )
    curve: list[dict[str, Any]] = [
        {
            "games": "committed",
            "model": str(args.policy),
            "n_games": summary["n_games"],
            "win_rate": summary["win_rate"],
            "mean_stone_diff": summary["mean_stone_diff"],
            "ci95": summary["ci95"],
            "opponents": summary["opponents"],
        }
    ]
    if args.snapshots_dir is not None:
        for games_trained, path, snap_policy in load_snapshot_policies(args.snapshots_dir):
            snap_summary, _records = evaluate_policy(
                snap_policy,
                openings,
                seed=args.seed,
                workers=workers,
                progress=True,
            )
            curve.append(
                {
                    "games": games_trained,
                    "model": str(path),
                    "n_games": snap_summary["n_games"],
                    "win_rate": snap_summary["win_rate"],
                    "mean_stone_diff": snap_summary["mean_stone_diff"],
                    "ci95": snap_summary["ci95"],
                    "opponents": snap_summary["opponents"],
                }
            )
            print(
                f"snapshot games={games_trained} "
                f"win_rate={snap_summary['win_rate']:.4f} "
                f"mean_stone_diff={snap_summary['mean_stone_diff']:.4f}",
                flush=True,
            )
    payload = _stage0_payload(
        model_path=args.policy,
        openings=openings,
        summary=summary,
        games=games,
        seed=args.seed,
        workers=workers,
        learning_curve=curve,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(args.output, payload)
    print(
        f"wrote {args.output} n_games={payload['n_games']} "
        f"win_rate={payload['win_rate']:.4f} "
        f"mean_stone_diff={payload['mean_stone_diff']:.4f}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
