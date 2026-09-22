#!/usr/bin/env python3
"""RL 改善の段階 2。減衰・対称・探索手除外の線形 v を、段階 1 の RL と比べる。

対局の再実行は CI に載せない。ホストで明示的に走らせる。
評価経路は WTHOR を読まない。対局時に NN 推論も OpenRouter も使わない。
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
STRATEGY_SRC = ROOT / "strategy" / "src"
if str(STRATEGY_SRC) not in sys.path:
    sys.path.insert(0, str(STRATEGY_SRC))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import rl_eval

from reversi.agents import alphabeta, rl, rl_search, rl_tied
from reversi.agents.rl import LinearPolicy
from reversi.engine.board import Board, Color
from reversi.engine.rules import (
    PassMove,
    Place,
    Position,
    is_over,
    legal_places,
    play,
)
from reversi.engine.score import official_score, stone_counts

STAGE2_OUT = HERE / "rl-stage2.json"
DEPTHS = (1, 2, 4)
CURVE_DEPTH = rl_tied.SEARCH_DEPTH

__all__ = [
    "CURVE_DEPTH",
    "DEPTHS",
    "evaluate_depths",
    "verdict_of",
]


def _result_of(candidate_is_black: bool, position: Position) -> dict[str, Any]:
    counts = stone_counts(position.board)
    score = official_score(position.board)
    own_official = score.black if candidate_is_black else score.white
    opp_official = score.white if candidate_is_black else score.black
    own_stones = counts.black if candidate_is_black else counts.white
    opp_stones = counts.white if candidate_is_black else counts.black
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


def play_paired(
    start: Position,
    depth: int,
    candidate: LinearPolicy,
    baseline: LinearPolicy,
    candidate_is_black: bool,
) -> dict[str, Any]:
    """同じ深さで、段階 2 の葉と段階 1 の葉を先後固定で 1 局進める。"""

    def candidate_leaf(board: Board, color: Color) -> float:
        return rl.perspective_value(board, color, candidate)

    def baseline_leaf(board: Board, color: Color) -> float:
        return rl.perspective_value(board, color, baseline)

    position = start
    while not is_over(position):
        places = legal_places(position)
        if not places:
            position = play(position, PassMove())
            continue
        is_candidate = (position.side_to_move is Color.BLACK) == candidate_is_black
        leaf = candidate_leaf if is_candidate else baseline_leaf
        move = alphabeta.choose_at_depth(position, depth, evaluate=leaf)
        if not isinstance(move, Place) or move.square not in places:
            raise RuntimeError("合法手の外を選んだ")
        position = play(position, move)
    return _result_of(candidate_is_black, position)


def play_job(
    start: Mapping[str, Any],
    depth: int,
    candidate_is_black: bool,
    candidate_weights: Sequence[float],
    candidate_bias: float,
    baseline_weights: Sequence[float],
    baseline_bias: float,
) -> dict[str, Any]:
    """プロセスプール用。二つの重みの写しと深さと先後だけを受け取る。"""
    candidate = LinearPolicy(
        weights=tuple(float(value) for value in candidate_weights),
        bias=float(candidate_bias),
    )
    baseline = LinearPolicy(
        weights=tuple(float(value) for value in baseline_weights),
        bias=float(baseline_bias),
    )
    position = rl_eval._position_from_rows(start["board"], str(start["side_to_move"]))
    raw = play_paired(position, depth, candidate, baseline, candidate_is_black)
    return {
        "start_index": int(start["index"]),
        "depth": depth,
        "candidate_color": "black" if candidate_is_black else "white",
        **raw,
    }


def verdict_of(win_ci: Mapping[str, Any]) -> dict[str, str]:
    """改善は、段階 2 側の勝率の 95% 区間が 0.5 を上回るとき。"""
    if win_ci.get("crosses_even"):
        return {"code": "indistinguishable", "note": rl_eval.EVEN_NOTE}
    low = float(win_ci["low"])
    high = float(win_ci["high"])
    if low > 0.5:
        return {
            "code": "stage2",
            "note": "段階 2 の勝率の 95% 区間が 0.5 を上回る",
        }
    if high < 0.5:
        return {
            "code": "stage1",
            "note": "段階 2 の勝率の 95% 区間が 0.5 を下回る",
        }
    return {"code": "indistinguishable", "note": rl_eval.EVEN_NOTE}


def _summarize(games: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    scores = [float(game["score"]) for game in games]
    diffs = [float(game["stone_diff"]) for game in games]
    win = rl_eval.mean_and_ci95(scores)
    stone = rl_eval.mean_and_ci95(diffs)
    stone.pop("crosses_even", None)
    stone.pop("note", None)
    wins = sum(1 for game in games if game["result"] == "win")
    draws = sum(1 for game in games if game["result"] == "draw")
    losses = sum(1 for game in games if game["result"] == "loss")
    return {
        "n_games": len(games),
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "win_rate": win["mean"] if games else 0.0,
        "mean_stone_diff": stone["mean"] if games else 0.0,
        "ci95": {"win_rate": win, "mean_stone_diff": stone},
        "verdict": verdict_of(win),
    }


def evaluate_depths(
    candidate: LinearPolicy,
    baseline: LinearPolicy,
    openings: Sequence[Mapping[str, Any]],
    depths: Sequence[int],
    *,
    workers: int,
    progress: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """深さごとに、同じ開始局面と先後入れ替えで対局する。"""
    from concurrent.futures import ProcessPoolExecutor, as_completed

    jobs: list[tuple[Mapping[str, Any], int, bool]] = []
    for depth in depths:
        for start in openings:
            jobs.append((start, depth, True))
            jobs.append((start, depth, False))
    candidate_weights = list(candidate.weights)
    candidate_bias = float(candidate.bias)
    baseline_weights = list(baseline.weights)
    baseline_bias = float(baseline.bias)
    games: list[dict[str, Any]] = []
    total = len(jobs)

    def _note(record: Mapping[str, Any], done: int) -> None:
        if not progress:
            return
        print(
            f"depth {record['depth']} start {record['start_index']} "
            f"stage2={record['candidate_color']} {record['result']} "
            f"diff={record['stone_diff']} done={done}/{total}",
            flush=True,
        )

    if workers <= 1 or len(jobs) <= 1:
        for start, depth, candidate_is_black in jobs:
            record = play_job(
                start,
                depth,
                candidate_is_black,
                candidate_weights,
                candidate_bias,
                baseline_weights,
                baseline_bias,
            )
            games.append(record)
            _note(record, len(games))
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(
                    play_job,
                    start,
                    depth,
                    candidate_is_black,
                    candidate_weights,
                    candidate_bias,
                    baseline_weights,
                    baseline_bias,
                )
                for start, depth, candidate_is_black in jobs
            ]
            for future in as_completed(futures):
                record = future.result()
                games.append(record)
                _note(record, len(games))
    games.sort(
        key=lambda row: (
            int(row["depth"]),
            int(row["start_index"]),
            str(row["candidate_color"]),
        )
    )
    by_depth: list[dict[str, Any]] = []
    for depth in depths:
        rows = [game for game in games if int(game["depth"]) == depth]
        summary = _summarize(rows)
        by_depth.append({"depth": depth, **summary})
    return by_depth, games


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _payload(
    *,
    candidate_path: Path,
    baseline_path: Path,
    openings: Sequence[Mapping[str, Any]],
    by_depth: Sequence[Mapping[str, Any]],
    games: Sequence[Mapping[str, Any]],
    seed: int,
    workers: int,
    learning_curve: Sequence[Mapping[str, Any]],
    primary_depth: int,
) -> dict[str, Any]:
    primary = next(row for row in by_depth if int(row["depth"]) == primary_depth)
    return {
        "recorded_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
        "stage": 2,
        "candidate": {
            "specimen_id": rl_tied.SPECIMEN_ID,
            "display_name": rl_tied.DISPLAY_NAME,
            "category": rl_tied.CATEGORY,
            "model": _rel(candidate_path),
            "catalog_depth": rl_tied.SEARCH_DEPTH,
        },
        "baseline": {
            "specimen_id": rl_search.SPECIMEN_ID,
            "display_name": rl_search.DISPLAY_NAME,
            "model": _rel(baseline_path),
            "leaf": "stage1_linear_v",
            "search": "alphabeta",
        },
        "protocol": {
            "starts": len(openings),
            "games_per_start": 2,
            "opening_plies": list(rl_eval.OPENING_PLIES),
            "seed": seed,
            "openings": "docs/benchmarks/rl-openings.json",
            "paired": True,
            "workers": workers,
            "depths": [int(row["depth"]) for row in by_depth],
            "primary_depth": primary_depth,
            "notes": [
                "比較は同じ深さの αβ。一方の葉は models/rl-tied.json、もう一方は段階 1 の models/rl.json。",
                "開始局面は段階 0 と同じ集合。各局面で先後を入れ替える。勝率は段階 2 側から見る。",
                "白番の v は符号反転する。葉の外に閾値や定数ボーナスは足さない。",
                "勝率は（勝 + 0.5×分）/ 局数。石差は盤上の石数（段階 2 − 段階 1）。",
                "95% 区間は標本平均の正規近似。勝率の区間が 0.5 をまたぐときは「この局数では区別できない」と書く。差がない、とは書かない。",
                "改善と判定するのは、段階 2 側の勝率の 95% 区間が 0.5 を上回ったとき。",
                "学習曲線は同じ相手（段階 1 の葉）・同じ開始局面で、学習局数ごとの重みを深さ 4 で測る。",
                "既存の「強化学習 (自己対局)」と models/rl.json は残す。",
                "評価経路は WTHOR を読まない。対局時に NN 推論も OpenRouter も使わない。",
                "対局の再実行は CI に載せない。本スクリプトはホストで明示実行する。",
            ],
        },
        "depths": [int(row["depth"]) for row in by_depth],
        "win_rate": primary["win_rate"],
        "mean_stone_diff": primary["mean_stone_diff"],
        "ci95": primary["ci95"],
        "by_depth": [dict(row) for row in by_depth],
        "learning_curve": list(learning_curve),
        "game_records": list(games),
    }


def _curve_point(
    games_trained: int | str,
    model: Path,
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "games": games_trained,
        "model": _rel(model),
        "depth": CURVE_DEPTH,
        "n_games": summary["n_games"],
        "win_rate": summary["win_rate"],
        "mean_stone_diff": summary["mean_stone_diff"],
        "ci95": summary["ci95"],
        "verdict": summary["verdict"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="段階 2 の線形 v を、同じ深さの αβ で段階 1 の RL と比べる"
    )
    parser.add_argument("--openings", type=Path, default=rl_eval.OPENINGS_OUT)
    parser.add_argument("--output", type=Path, default=STAGE2_OUT)
    parser.add_argument("--starts", type=int, default=rl_eval.N_STARTS)
    parser.add_argument("--seed", type=int, default=rl_eval.SEED)
    parser.add_argument("--candidate", type=Path, default=rl_tied.DEFAULT_MODEL_PATH)
    parser.add_argument("--baseline", type=Path, default=rl.DEFAULT_MODEL_PATH)
    parser.add_argument("--depths", type=int, nargs="+", default=list(DEPTHS))
    parser.add_argument("--snapshots-dir", type=Path, default=None)
    parser.add_argument("--curve-depth", type=int, default=CURVE_DEPTH)
    parser.add_argument("--workers", type=int, default=0, help="並列数。0 なら CPU 数")
    args = parser.parse_args(argv)
    if args.starts < 1:
        raise SystemExit("開始局面数は 1 以上")
    if any(depth < 1 for depth in args.depths):
        raise SystemExit("深さは 1 以上")
    cpu = os.cpu_count() or 1
    workers = args.workers if args.workers > 0 else cpu
    openings = rl_eval.resolve_openings(args.openings, args.seed, args.starts)
    print(
        f"openings n={len(openings)} depths={args.depths} workers={workers}",
        flush=True,
    )
    candidate = rl.load_policy(args.candidate)
    baseline = rl.load_policy(args.baseline)
    by_depth: list[dict[str, Any]] = []
    games: list[dict[str, Any]] = []
    curve: list[dict[str, Any]] = []
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def _checkpoint() -> None:
        if not by_depth:
            return
        primary_depth = (
            rl_tied.SEARCH_DEPTH
            if any(int(row["depth"]) == rl_tied.SEARCH_DEPTH for row in by_depth)
            else int(by_depth[-1]["depth"])
        )
        payload = _payload(
            candidate_path=args.candidate,
            baseline_path=args.baseline,
            openings=openings,
            by_depth=by_depth,
            games=games,
            seed=args.seed,
            workers=workers,
            learning_curve=curve,
            primary_depth=primary_depth,
        )
        rl_eval._atomic_write(args.output, payload)

    if args.snapshots_dir is not None:
        for games_trained, path, snap in rl_eval.load_snapshot_policies(args.snapshots_dir):
            snap_rows, _snap_games = evaluate_depths(
                snap,
                baseline,
                openings,
                (args.curve_depth,),
                workers=workers,
                progress=True,
            )
            summary = snap_rows[0]
            curve.append(_curve_point(games_trained, path, summary))
            print(
                f"snapshot games={games_trained} "
                f"win_rate={summary['win_rate']:.4f} "
                f"mean_stone_diff={summary['mean_stone_diff']:.4f}",
                flush=True,
            )
    for depth in args.depths:
        depth_rows, depth_games = evaluate_depths(
            candidate,
            baseline,
            openings,
            (depth,),
            workers=workers,
            progress=True,
        )
        by_depth.extend(depth_rows)
        games.extend(depth_games)
        if int(depth) == args.curve_depth:
            curve.append(_curve_point("final", args.candidate, depth_rows[0]))
        _checkpoint()
        print(f"checkpoint depth={depth}", flush=True)
    for row in by_depth:
        ci = row["ci95"]["win_rate"]
        print(
            f"depth {row['depth']} n={row['n_games']} "
            f"win_rate={row['win_rate']:.4f} "
            f"ci=({ci['low']:.4f},{ci['high']:.4f}) "
            f"mean_stone_diff={row['mean_stone_diff']:.4f} "
            f"verdict={row['verdict']['note']}",
            flush=True,
        )
    print(f"wrote {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
