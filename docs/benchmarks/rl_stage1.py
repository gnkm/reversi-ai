#!/usr/bin/env python3
"""RL 改善の段階 1。同じ深さの αβ で、位置評価の葉と線形 v の葉を比べる。

対局の再実行は CI に載せない。ホストで明示的に走らせる。
評価経路は WTHOR を読まない。対局時に NN 推論も OpenRouter も使わない。
"""

from __future__ import annotations

import argparse
import json
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

from reversi.agents import alphabeta, minimax, rl, rl_search
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

STAGE1_OUT = HERE / "rl-stage1.json"
DEPTHS = (1, 2, 4)
CATALOG_DEPTH = rl_search.SEARCH_DEPTH

__all__ = [
    "CATALOG_DEPTH",
    "DEPTHS",
    "evaluate_depths",
    "position_leaf",
    "verdict_of",
]


def position_leaf(board: Board, color: Color) -> int:
    """手番 color から見た POSITION_SCORES の差。ミニマックスの葉と同じ。"""
    return minimax.leaf_score(board, color)


def _result_of(rl_is_black: bool, position: Position) -> dict[str, Any]:
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


def play_paired(
    start: Position,
    depth: int,
    policy: LinearPolicy,
    rl_is_black: bool,
) -> dict[str, Any]:
    """同じ深さで、線形 v の葉と位置評価表の葉を先後固定で 1 局進める。"""

    def rl_leaf(board: Board, color: Color) -> float:
        return rl.perspective_value(board, color, policy)

    position = start
    while not is_over(position):
        places = legal_places(position)
        if not places:
            position = play(position, PassMove())
            continue
        is_rl = (position.side_to_move is Color.BLACK) == rl_is_black
        if is_rl:
            move = alphabeta.choose_at_depth(position, depth, evaluate=rl_leaf)
        else:
            move = alphabeta.choose_at_depth(position, depth, evaluate=position_leaf)
        if not isinstance(move, Place) or move.square not in places:
            raise RuntimeError("合法手の外を選んだ")
        position = play(position, move)
    return _result_of(rl_is_black, position)


def play_job(
    start: Mapping[str, Any],
    depth: int,
    rl_is_black: bool,
    weights: Sequence[float],
    bias: float,
) -> dict[str, Any]:
    """プロセスプール用。重みの写しと深さと先後だけを受け取る。"""
    policy = LinearPolicy(weights=tuple(float(value) for value in weights), bias=float(bias))
    position = rl_eval._position_from_rows(start["board"], str(start["side_to_move"]))
    raw = play_paired(position, depth, policy, rl_is_black)
    return {
        "start_index": int(start["index"]),
        "depth": depth,
        "rl_color": "black" if rl_is_black else "white",
        **raw,
    }


def verdict_of(win_ci: Mapping[str, Any]) -> dict[str, str]:
    """改善は、線形 v 側の勝率の 95% 区間が 0.5 を上回るとき。"""
    if win_ci.get("crosses_even"):
        return {"code": "indistinguishable", "note": rl_eval.EVEN_NOTE}
    low = float(win_ci["low"])
    high = float(win_ci["high"])
    if low > 0.5:
        return {
            "code": "rl_leaf",
            "note": "αβ＋線形 v の勝率の 95% 区間が 0.5 を上回る",
        }
    if high < 0.5:
        return {
            "code": "position_leaf",
            "note": "αβ＋線形 v の勝率の 95% 区間が 0.5 を下回る",
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
    policy: LinearPolicy,
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
    weights = list(policy.weights)
    bias = float(policy.bias)
    games: list[dict[str, Any]] = []
    total = len(jobs)

    def _note(record: Mapping[str, Any], done: int) -> None:
        if not progress:
            return
        print(
            f"depth {record['depth']} start {record['start_index']} "
            f"rl={record['rl_color']} {record['result']} "
            f"diff={record['stone_diff']} done={done}/{total}",
            flush=True,
        )

    if workers <= 1 or len(jobs) <= 1:
        for start, depth, rl_is_black in jobs:
            record = play_job(start, depth, rl_is_black, weights, bias)
            games.append(record)
            _note(record, len(games))
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(play_job, start, depth, rl_is_black, weights, bias)
                for start, depth, rl_is_black in jobs
            ]
            for future in as_completed(futures):
                record = future.result()
                games.append(record)
                _note(record, len(games))
    games.sort(
        key=lambda row: (int(row["depth"]), int(row["start_index"]), str(row["rl_color"]))
    )
    by_depth: list[dict[str, Any]] = []
    for depth in depths:
        rows = [game for game in games if int(game["depth"]) == depth]
        summary = _summarize(rows)
        by_depth.append({"depth": depth, **summary})
    return by_depth, games


def _payload(
    *,
    model_path: Path,
    openings: Sequence[Mapping[str, Any]],
    by_depth: Sequence[Mapping[str, Any]],
    games: Sequence[Mapping[str, Any]],
    seed: int,
    workers: int,
) -> dict[str, Any]:
    try:
        rel: Path | str = model_path.resolve().relative_to(ROOT)
    except ValueError:
        rel = model_path
    win_rate = {str(row["depth"]): row["win_rate"] for row in by_depth}
    mean_stone_diff = {str(row["depth"]): row["mean_stone_diff"] for row in by_depth}
    ci95 = {str(row["depth"]): row["ci95"] for row in by_depth}
    return {
        "recorded_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
        "stage": 1,
        "candidate": {
            "specimen_id": rl_search.SPECIMEN_ID,
            "display_name": rl_search.DISPLAY_NAME,
            "category": rl_search.CATEGORY,
            "model": str(rel),
            "catalog_depth": CATALOG_DEPTH,
        },
        "baseline": {
            "leaf": "POSITION_SCORES",
            "leaf_function": "minimax.leaf_score",
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
            "depths": list(DEPTHS) if not by_depth else [int(row["depth"]) for row in by_depth],
            "catalog_depth": CATALOG_DEPTH,
            "notes": [
                "比較は同じ深さの αβ。一方の葉は POSITION_SCORES の差（ミニマックスの葉）、もう一方は models/rl.json の線形 v。",
                "開始局面は段階 0 と同じ集合。各局面で先後を入れ替える。勝率は線形 v 側から見る。",
                "白番の v は符号反転する。葉の外に閾値や定数ボーナスは足さない。尺度の違いは枝刈りに使わない。",
                "勝率は（勝 + 0.5×分）/ 局数。石差は盤上の石数（線形 v − 位置評価）。",
                "95% 区間は標本平均の正規近似。勝率の区間が 0.5 をまたぐときは「この局数では区別できない」と書く。差がない、とは書かない。",
                "改善と判定するのは、線形 v 側の勝率の 95% 区間が 0.5 を上回ったとき。下回る、またはまたぐときも比較の枠として残す。",
                "カタログ既定の深さは 4。既存の「強化学習 (自己対局)」は 1 手読みのまま残す。",
                "評価経路は WTHOR を読まない。対局時に NN 推論も OpenRouter も使わない。",
                "対局の再実行は CI に載せない。本スクリプトはホストで明示実行する。",
            ],
        },
        "depths": [int(row["depth"]) for row in by_depth],
        "win_rate": win_rate,
        "mean_stone_diff": mean_stone_diff,
        "ci95": ci95,
        "by_depth": [dict(row) for row in by_depth],
        "game_records": list(games),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="同じ深さの αβ で位置評価の葉と線形 v の葉を比べる"
    )
    parser.add_argument("--openings", type=Path, default=rl_eval.OPENINGS_OUT)
    parser.add_argument("--output", type=Path, default=STAGE1_OUT)
    parser.add_argument("--starts", type=int, default=rl_eval.N_STARTS)
    parser.add_argument("--seed", type=int, default=rl_eval.SEED)
    parser.add_argument("--policy", type=Path, default=rl.DEFAULT_MODEL_PATH)
    parser.add_argument("--depths", type=int, nargs="+", default=list(DEPTHS))
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="並列数。0 なら CPU 数",
    )
    args = parser.parse_args(argv)
    if args.starts < 1:
        raise SystemExit("開始局面数は 1 以上")
    if any(depth < 1 for depth in args.depths):
        raise SystemExit("深さは 1 以上")
    cpu = os.cpu_count() or 1
    workers = args.workers if args.workers > 0 else cpu
    openings = rl_eval.resolve_openings(args.openings, args.seed, args.starts)
    print(f"openings n={len(openings)} depths={args.depths} workers={workers}", flush=True)
    policy = rl.load_policy(args.policy)
    by_depth: list[dict[str, Any]] = []
    games: list[dict[str, Any]] = []
    for depth in args.depths:
        depth_rows, depth_games = evaluate_depths(
            policy,
            openings,
            (depth,),
            workers=workers,
            progress=True,
        )
        by_depth.extend(depth_rows)
        games.extend(depth_games)
        partial = _payload(
            model_path=args.policy,
            openings=openings,
            by_depth=by_depth,
            games=games,
            seed=args.seed,
            workers=workers,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        rl_eval._atomic_write(args.output, partial)
        print(f"checkpoint depths={partial['depths']}", flush=True)
    payload = _payload(
        model_path=args.policy,
        openings=openings,
        by_depth=by_depth,
        games=games,
        seed=args.seed,
        workers=workers,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rl_eval._atomic_write(args.output, payload)
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
