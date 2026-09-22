#!/usr/bin/env python3
"""RL 改善の段階 3。パターン特徴の TD(λ) を、段階 2 と位置評価付き αβ と比べる。

対局の再実行は CI に載せない。ホストで明示的に走らせる。
評価経路は WTHOR を読まない。対局時に NN 推論も OpenRouter も使わない。
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
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

from reversi.agents import alphabeta, minimax, rl, rl_pattern, rl_tied
from reversi.agents.pattern_eval import (
    PatternPolicy,
    load_policy,
    perspective_value,
    xc_table,
)
from reversi.engine.board import Board, Color
from reversi.engine.rules import PassMove, Place, Position, is_over, legal_places, play
from reversi.engine.score import official_score, stone_counts

STAGE3_OUT = HERE / "rl-stage3.json"
DEPTHS = (1, 2, 4)
OPPONENTS = ("stage2", "positional")
_WORKER: dict[str, Any] = {}

__all__ = ["evaluate_match", "verdict_of"]


def _init_worker(candidate_path: str, stage2_path: str) -> None:
    _WORKER["pattern"] = load_policy(Path(candidate_path))
    _WORKER["stage2"] = rl.load_policy(Path(stage2_path))


def _result_of(candidate_is_black: bool, position: Position) -> dict[str, Any]:
    counts = stone_counts(position.board)
    score = official_score(position.board)
    own_official = score.black if candidate_is_black else score.white
    opp_official = score.white if candidate_is_black else score.black
    own_stones = counts.black if candidate_is_black else counts.white
    opp_stones = counts.white if candidate_is_black else counts.black
    if own_official > opp_official:
        result, score_value = "win", 1.0
    elif own_official < opp_official:
        result, score_value = "loss", 0.0
    else:
        result, score_value = "draw", 0.5
    return {
        "result": result,
        "score": score_value,
        "stone_diff": own_stones - opp_stones,
        "official_black": score.black,
        "official_white": score.white,
        "stones_black": counts.black,
        "stones_white": counts.white,
    }


def _pattern_leaf(policy: PatternPolicy):
    def evaluate(board: Board, color: Color) -> float:
        return perspective_value(board, color, policy)

    return evaluate


def _stage2_leaf(policy: rl.LinearPolicy):
    def evaluate(board: Board, color: Color) -> float:
        return rl.perspective_value(board, color, policy)

    return evaluate


def _positional_leaf(board: Board, color: Color) -> float:
    return float(minimax.leaf_score(board, color))


def play_paired(
    start: Position,
    depth: int,
    pattern: PatternPolicy,
    opponent: str,
    stage2: rl.LinearPolicy,
    candidate_is_black: bool,
) -> dict[str, Any]:
    """同じ深さで、パターン葉と相手の葉を先後固定で 1 局進める。"""
    candidate_leaf = _pattern_leaf(pattern)
    if opponent == "stage2":
        other_leaf = _stage2_leaf(stage2)
    elif opponent == "positional":
        other_leaf = _positional_leaf
    else:
        raise ValueError(f"未知の相手です: {opponent}")
    position = start
    while not is_over(position):
        places = legal_places(position)
        if not places:
            position = play(position, PassMove())
            continue
        is_candidate = (position.side_to_move is Color.BLACK) == candidate_is_black
        leaf = candidate_leaf if is_candidate else other_leaf
        move = alphabeta.choose_at_depth(position, depth, evaluate=leaf)
        if not isinstance(move, Place) or move.square not in places:
            raise RuntimeError("合法手の外を選んだ")
        position = play(position, move)
    return _result_of(candidate_is_black, position)


def play_job(
    start: Mapping[str, Any],
    depth: int,
    opponent: str,
    candidate_is_black: bool,
) -> dict[str, Any]:
    position = rl_eval._position_from_rows(start["board"], str(start["side_to_move"]))
    raw = play_paired(
        position,
        depth,
        _WORKER["pattern"],
        opponent,
        _WORKER["stage2"],
        candidate_is_black,
    )
    return {
        "start_index": int(start["index"]),
        "depth": depth,
        "opponent": opponent,
        "candidate_color": "black" if candidate_is_black else "white",
        **raw,
    }


def verdict_of(win_ci: Mapping[str, Any], baseline: str) -> dict[str, str]:
    """改善は、段階 3 側の勝率の 95% 区間が 0.5 を上回るとき。"""
    if win_ci.get("crosses_even"):
        return {"code": "indistinguishable", "note": rl_eval.EVEN_NOTE}
    low = float(win_ci["low"])
    high = float(win_ci["high"])
    if low > 0.5:
        return {
            "code": "stage3",
            "note": "段階 3 の勝率の 95% 区間が 0.5 を上回る",
        }
    if high < 0.5:
        return {
            "code": baseline,
            "note": f"段階 3 の勝率の 95% 区間が 0.5 を下回る（{baseline}）",
        }
    return {"code": "indistinguishable", "note": rl_eval.EVEN_NOTE}


def _summarize(games: Sequence[Mapping[str, Any]], baseline: str) -> dict[str, Any]:
    scores = [float(game["score"]) for game in games]
    diffs = [float(game["stone_diff"]) for game in games]
    win = rl_eval.mean_and_ci95(scores)
    stone = rl_eval.mean_and_ci95(diffs)
    stone.pop("crosses_even", None)
    stone.pop("note", None)
    return {
        "n_games": len(games),
        "wins": sum(1 for game in games if game["result"] == "win"),
        "draws": sum(1 for game in games if game["result"] == "draw"),
        "losses": sum(1 for game in games if game["result"] == "loss"),
        "win_rate": win["mean"] if games else 0.0,
        "mean_stone_diff": stone["mean"] if games else 0.0,
        "ci95": {"win_rate": win, "mean_stone_diff": stone},
        "verdict": verdict_of(win, baseline),
    }


def evaluate_match(
    openings: Sequence[Mapping[str, Any]],
    depths: Sequence[int],
    opponents: Sequence[str],
    *,
    candidate_path: Path,
    stage2_path: Path,
    workers: int,
    progress: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """深さと相手ごとに、同じ開始局面と先後入れ替えで対局する。"""
    jobs: list[tuple[Mapping[str, Any], int, str, bool]] = []
    for opponent in opponents:
        for depth in depths:
            for start in openings:
                jobs.append((start, depth, opponent, True))
                jobs.append((start, depth, opponent, False))
    games: list[dict[str, Any]] = []
    total = len(jobs)
    with ProcessPoolExecutor(
        max_workers=max(1, workers),
        initializer=_init_worker,
        initargs=(str(candidate_path), str(stage2_path)),
    ) as pool:
        futures = [
            pool.submit(play_job, start, depth, opponent, candidate_is_black)
            for start, depth, opponent, candidate_is_black in jobs
        ]
        for future in as_completed(futures):
            record = future.result()
            games.append(record)
            if progress:
                print(
                    f"{record['opponent']} depth {record['depth']} "
                    f"start {record['start_index']} {record['candidate_color']} "
                    f"{record['result']} done={len(games)}/{total}",
                    flush=True,
                )
    games.sort(
        key=lambda row: (
            str(row["opponent"]),
            int(row["depth"]),
            int(row["start_index"]),
            str(row["candidate_color"]),
        )
    )
    blocks: list[dict[str, Any]] = []
    for opponent in opponents:
        for depth in depths:
            rows = [
                game
                for game in games
                if game["opponent"] == opponent and int(game["depth"]) == depth
            ]
            summary = _summarize(rows, opponent)
            blocks.append({"opponent": opponent, "depth": depth, **summary})
    return blocks, games


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _headline(blocks: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    for block in blocks:
        if block["opponent"] == "stage2" and int(block["depth"]) == rl_pattern.SEARCH_DEPTH:
            return block
    return blocks[-1]


def _curve_jobs(directory: Path) -> list[tuple[int, Path]]:
    found: list[tuple[int, Path]] = []
    for path in sorted(directory.glob("games-*.json")):
        digits = "".join(ch for ch in path.stem if ch.isdigit())
        found.append((int(digits or "0"), path))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="段階 3 のパターン評価を同じ深さの αβ で比べる")
    parser.add_argument("--openings", type=Path, default=rl_eval.OPENINGS_OUT)
    parser.add_argument("--output", type=Path, default=STAGE3_OUT)
    parser.add_argument("--starts", type=int, default=rl_eval.N_STARTS)
    parser.add_argument("--seed", type=int, default=rl_eval.SEED)
    parser.add_argument("--candidate", type=Path, default=rl_pattern.DEFAULT_MODEL_PATH)
    parser.add_argument("--stage2", type=Path, default=rl_tied.DEFAULT_MODEL_PATH)
    parser.add_argument("--depths", type=int, nargs="+", default=list(DEPTHS))
    parser.add_argument("--opponents", nargs="+", default=list(OPPONENTS))
    parser.add_argument("--snapshots-dir", type=Path, default=None)
    parser.add_argument("--curve-depth", type=int, default=2)
    parser.add_argument("--curve-opponent", default="stage2")
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--skip-records", action="store_true")
    args = parser.parse_args(argv)
    workers = args.workers if args.workers > 0 else (os.cpu_count() or 1)
    openings = rl_eval.resolve_openings(args.openings, args.seed, args.starts)
    policy = load_policy(args.candidate)
    print(
        f"openings n={len(openings)} depths={args.depths} "
        f"opponents={args.opponents} workers={workers} games={policy.games}",
        flush=True,
    )
    curve: list[dict[str, Any]] = []
    if args.snapshots_dir is not None:
        for games_trained, path in _curve_jobs(args.snapshots_dir):
            blocks, _games = evaluate_match(
                openings,
                (args.curve_depth,),
                (args.curve_opponent,),
                candidate_path=path,
                stage2_path=args.stage2,
                workers=workers,
                progress=True,
            )
            summary = blocks[0]
            curve.append(
                {
                    "games": games_trained,
                    "model": _rel(path),
                    "opponent": args.curve_opponent,
                    "depth": args.curve_depth,
                    "win_rate": summary["win_rate"],
                    "mean_stone_diff": summary["mean_stone_diff"],
                    "ci95": summary["ci95"],
                    "verdict": summary["verdict"],
                }
            )
            print(
                f"snapshot games={games_trained} win_rate={summary['win_rate']:.4f}",
                flush=True,
            )
    blocks, games = evaluate_match(
        openings,
        args.depths,
        args.opponents,
        candidate_path=args.candidate,
        stage2_path=args.stage2,
        workers=workers,
        progress=True,
    )
    primary = _headline(blocks)
    payload: dict[str, Any] = {
        "recorded_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
        "stage": 3,
        "reward": policy.reward,
        "train_games": policy.games,
        "lambda": policy.lam,
        "win_rate": primary["win_rate"],
        "mean_stone_diff": primary["mean_stone_diff"],
        "ci95": primary["ci95"],
        "candidate": {
            "specimen_id": rl_pattern.SPECIMEN_ID,
            "display_name": rl_pattern.DISPLAY_NAME,
            "category": rl_pattern.CATEGORY,
            "model": _rel(args.candidate),
            "catalog_depth": rl_pattern.SEARCH_DEPTH,
        },
        "opponents": {
            "stage2": {
                "specimen_id": rl_tied.SPECIMEN_ID,
                "model": _rel(args.stage2),
                "leaf": "stage2_linear_v",
            },
            "positional": {
                "specimen_id": minimax.SPECIMEN_ID,
                "leaf": "POSITION_SCORES",
                "leaf_function": "minimax.leaf_score",
            },
        },
        "protocol": {
            "starts": len(openings),
            "games_per_start": 2,
            "seed": args.seed,
            "openings": "docs/benchmarks/rl-openings.json",
            "depths": list(args.depths),
            "workers": workers,
            "notes": [
                "比較は同じ深さの αβ。段階 3 の葉はパターン特徴。",
                "相手は段階 2 の線形 v と、POSITION_SCORES の差（ミニマックスの葉）。",
                "開始局面は段階 0 と同じ集合。各局面で先後を入れ替える。",
                "勝率は段階 3 側の（勝 + 0.5×分）/ 局数。石差は盤上の石数。",
                "白番の評価は符号反転する。葉の外に閾値や定数ボーナスは足さない。",
                "終盤完全読みはしない。WTHOR も対局時の NN も OpenRouter も使わない。",
            ],
        },
        "by_opponent": blocks,
        "learning_curve": curve,
        "xc": xc_table(policy),
        "game_records": [] if args.skip_records else games,
    }
    rl_eval._atomic_write(args.output, payload)
    for block in blocks:
        ci = block["ci95"]["win_rate"]
        print(
            f"{block['opponent']} depth {block['depth']} "
            f"win_rate={block['win_rate']:.4f} "
            f"ci=({ci['low']:.4f},{ci['high']:.4f}) "
            f"diff={block['mean_stone_diff']:.3f} {block['verdict']['note']}",
            flush=True,
        )
    print(f"wrote {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
