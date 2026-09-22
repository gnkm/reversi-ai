#!/usr/bin/env python3
"""RL 改善の段階 4。同じパターン評価で終盤完全読みの有無だけを比べる。

対局の再実行は CI に載せない。ホストで明示的に走らせる。
評価経路は WTHOR を読まない。対局時に NN 推論も OpenRouter も使わない。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
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

from reversi.agents import alphabeta, rl_pattern
from reversi.agents.pattern_eval import PatternPolicy, load_policy, perspective_value
from reversi.engine.board import Board, Color
from reversi.engine.rules import PassMove, Place, Position, is_over, legal_places, play
from reversi.engine.score import official_score, stone_counts

STAGE4_OUT = HERE / "rl-stage4.json"
THRESHOLD_CANDIDATES = (10, 12, 14)
THINK_LIMIT_SECONDS = 2.0
_WORKER: dict[str, Any] = {}

__all__ = ["evaluate_match", "measure_threshold", "verdict_of"]


def _init_worker(candidate_path: str) -> None:
    _WORKER["pattern"] = load_policy(Path(candidate_path))


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


def _choose(
    position: Position,
    depth: int,
    policy: PatternPolicy,
    exact_empty: int,
) -> Place | None:
    return rl_pattern.choose_at_depth(
        position, depth, policy=policy, exact_empty=exact_empty
    )


def play_paired(
    start: Position,
    depth: int,
    policy: PatternPolicy,
    exact_empty: int,
    candidate_is_black: bool,
) -> dict[str, Any]:
    """同じ評価関数で、完全読みありとなしを先後固定で 1 局進める。"""
    position = start
    while not is_over(position):
        places = legal_places(position)
        if not places:
            position = play(position, PassMove())
            continue
        is_candidate = (position.side_to_move is Color.BLACK) == candidate_is_black
        if is_candidate:
            move = _choose(position, depth, policy, exact_empty)
        else:
            move = _choose(position, depth, policy, 0)
        if not isinstance(move, Place) or move.square not in places:
            raise RuntimeError("合法手の外を選んだ")
        position = play(position, move)
    return _result_of(candidate_is_black, position)


def play_job(
    start: Mapping[str, Any],
    depth: int,
    exact_empty: int,
    candidate_is_black: bool,
) -> dict[str, Any]:
    position = rl_eval._position_from_rows(start["board"], str(start["side_to_move"]))
    raw = play_paired(
        position,
        depth,
        _WORKER["pattern"],
        exact_empty,
        candidate_is_black,
    )
    return {
        "start_index": int(start["index"]),
        "depth": depth,
        "candidate_color": "black" if candidate_is_black else "white",
        **raw,
    }


def verdict_of(win_ci: Mapping[str, Any]) -> dict[str, str]:
    """改善は、完全読みあり側の勝率の 95% 区間が 0.5 を上回るとき。"""
    if win_ci.get("crosses_even"):
        return {"code": "indistinguishable", "note": rl_eval.EVEN_NOTE}
    low = float(win_ci["low"])
    high = float(win_ci["high"])
    if low > 0.5:
        return {
            "code": "exact",
            "note": "完全読みありの勝率の 95% 区間が 0.5 を上回る",
        }
    if high < 0.5:
        return {
            "code": "no_exact",
            "note": "完全読みありの勝率の 95% 区間が 0.5 を下回る",
        }
    return {"code": "indistinguishable", "note": rl_eval.EVEN_NOTE}


def _summarize(games: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
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
        "verdict": verdict_of(win),
    }


def evaluate_match(
    openings: Sequence[Mapping[str, Any]],
    depth: int,
    exact_empty: int,
    *,
    candidate_path: Path,
    workers: int,
    progress: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """同じ開始局面と先後入れ替えで、完全読みあり／なしを対局する。"""
    jobs: list[tuple[Mapping[str, Any], bool]] = []
    for start in openings:
        jobs.append((start, True))
        jobs.append((start, False))
    games: list[dict[str, Any]] = []
    total = len(jobs)
    with ProcessPoolExecutor(
        max_workers=max(1, workers),
        initializer=_init_worker,
        initargs=(str(candidate_path),),
    ) as pool:
        futures = [
            pool.submit(play_job, start, depth, exact_empty, candidate_is_black)
            for start, candidate_is_black in jobs
        ]
        for future in as_completed(futures):
            record = future.result()
            games.append(record)
            if progress:
                print(
                    f"start {record['start_index']} {record['candidate_color']} "
                    f"{record['result']} done={len(games)}/{total}",
                    flush=True,
                )
    games.sort(
        key=lambda row: (int(row["start_index"]), str(row["candidate_color"]))
    )
    return _summarize(games), games


def _collect_endgames(
    openings: Sequence[Mapping[str, Any]],
    policy: PatternPolicy,
    targets: Sequence[int],
    per_target: int,
) -> dict[int, list[Position]]:
    """深さ 4・完全読みなしで進め、指定の空きマス数の局面を集める。"""
    wanted = {int(value) for value in targets}
    found: dict[int, list[Position]] = {value: [] for value in wanted}
    leaf = _pattern_leaf(policy)
    for start in openings:
        if all(len(found[value]) >= per_target for value in wanted):
            break
        position = rl_eval._position_from_rows(
            start["board"], str(start["side_to_move"])
        )
        while not is_over(position):
            empty = stone_counts(position.board).empty
            if empty in wanted and len(found[empty]) < per_target:
                if legal_places(position):
                    found[empty].append(position)
            places = legal_places(position)
            if not places:
                position = play(position, PassMove())
                continue
            move = alphabeta.choose_at_depth(position, 4, evaluate=leaf)
            if not isinstance(move, Place):
                break
            position = play(position, move)
    return found


def measure_threshold(
    openings: Sequence[Mapping[str, Any]],
    policy: PatternPolicy,
    candidates: Sequence[int],
    *,
    samples: int,
    think_limit: float,
) -> dict[str, Any]:
    """各空きマス数で完全読み 1 手の所要時間を測り、上限以内の最大を採る。"""
    positions = _collect_endgames(openings, policy, candidates, samples)
    by_empty: list[dict[str, Any]] = []
    adopted = min(candidates)
    for empty in candidates:
        seconds: list[float] = []
        nodes: list[int] = []
        for position in positions.get(int(empty), ())[:samples]:
            started = time.perf_counter()
            _move, _value, node_count = rl_pattern.search_stats(
                position, rl_pattern.SEARCH_DEPTH, policy=policy, exact_empty=empty
            )
            elapsed = time.perf_counter() - started
            seconds.append(elapsed)
            nodes.append(int(node_count))
        mean_s = sum(seconds) / len(seconds) if seconds else 0.0
        max_s = max(seconds) if seconds else 0.0
        ok = bool(seconds) and max_s <= think_limit
        if ok:
            adopted = int(empty)
        by_empty.append(
            {
                "empty": int(empty),
                "n": len(seconds),
                "mean_seconds": mean_s,
                "max_seconds": max_s,
                "mean_nodes": (sum(nodes) / len(nodes)) if nodes else 0.0,
                "within_limit": ok,
            }
        )
    return {
        "think_limit_seconds": think_limit,
        "samples_per_empty": samples,
        "by_empty": by_empty,
        "adopted": adopted,
        "code_constant": rl_pattern.EXACT_EMPTY,
        "notes": [
            "上限以内で完全読みし切れる最大の空きマス数を採る。",
            "コードの EXACT_EMPTY と一致させる。shall ではない。",
        ],
    }


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="段階 4 の終盤完全読みを同じ評価関数で比べる"
    )
    parser.add_argument("--openings", type=Path, default=rl_eval.OPENINGS_OUT)
    parser.add_argument("--output", type=Path, default=STAGE4_OUT)
    parser.add_argument("--starts", type=int, default=rl_eval.N_STARTS)
    parser.add_argument("--seed", type=int, default=rl_eval.SEED)
    parser.add_argument("--candidate", type=Path, default=rl_pattern.DEFAULT_MODEL_PATH)
    parser.add_argument("--depth", type=int, default=rl_pattern.SEARCH_DEPTH)
    parser.add_argument("--exact-empty", type=int, default=rl_pattern.EXACT_EMPTY)
    parser.add_argument("--threshold-samples", type=int, default=8)
    parser.add_argument("--think-limit", type=float, default=THINK_LIMIT_SECONDS)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--skip-records", action="store_true")
    parser.add_argument("--threshold-only", action="store_true")
    args = parser.parse_args(argv)
    workers = args.workers if args.workers > 0 else (os.cpu_count() or 1)
    openings = rl_eval.resolve_openings(args.openings, args.seed, args.starts)
    policy = load_policy(args.candidate)
    print(
        f"openings n={len(openings)} depth={args.depth} "
        f"exact_empty={args.exact_empty} workers={workers}",
        flush=True,
    )
    threshold = measure_threshold(
        openings,
        policy,
        THRESHOLD_CANDIDATES,
        samples=args.threshold_samples,
        think_limit=args.think_limit,
    )
    print(
        f"threshold adopted={threshold['adopted']} "
        f"code={threshold['code_constant']}",
        flush=True,
    )
    for row in threshold["by_empty"]:
        print(
            f"empty {row['empty']} n={row['n']} "
            f"mean={row['mean_seconds']:.3f}s max={row['max_seconds']:.3f}s "
            f"within={row['within_limit']}",
            flush=True,
        )
    if args.threshold_only:
        return 0
    if int(args.exact_empty) != int(threshold["adopted"]):
        print(
            "warning: --exact-empty と計測で採った値が違います。"
            " JSON には引数の閾値を書きます。",
            flush=True,
        )
    summary, games = evaluate_match(
        openings,
        args.depth,
        args.exact_empty,
        candidate_path=args.candidate,
        workers=workers,
        progress=True,
    )
    payload: dict[str, Any] = {
        "recorded_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
        "stage": 4,
        "exact_empty_threshold": int(args.exact_empty),
        "win_rate": summary["win_rate"],
        "mean_stone_diff": summary["mean_stone_diff"],
        "ci95": summary["ci95"],
        "candidate": {
            "specimen_id": rl_pattern.SPECIMEN_ID,
            "display_name": rl_pattern.DISPLAY_NAME,
            "category": rl_pattern.CATEGORY,
            "model": _rel(args.candidate),
            "catalog_depth": rl_pattern.SEARCH_DEPTH,
            "exact_empty": int(args.exact_empty),
            "leaf": "pattern_features_or_terminal_disc",
        },
        "baseline": {
            "specimen_id": rl_pattern.SPECIMEN_ID,
            "display_name": rl_pattern.DISPLAY_NAME,
            "model": _rel(args.candidate),
            "catalog_depth": args.depth,
            "exact_empty": 0,
            "leaf": "pattern_features",
        },
        "threshold": threshold,
        "protocol": {
            "starts": len(openings),
            "games_per_start": 2,
            "seed": args.seed,
            "openings": "docs/benchmarks/rl-openings.json",
            "depth": args.depth,
            "workers": workers,
            "notes": [
                "比較は同じ評価関数（段階 3 のパターン特徴）。完全読みの有無だけを変える。",
                "候補は空きマスが閾値以下なら終局まで読む。相手は同じ葉で終盤延長しない。",
                "開始局面は段階 0 と同じ集合。各局面で先後を入れ替える。",
                "勝率は完全読みあり側の（勝 + 0.5×分）/ 局数。石差は盤上の石数。",
                "白番の評価は符号反転する。葉の外に定数ボーナスは足さない。",
                "既存の線形 RL は置き換えない。WTHOR も対局時の NN も OpenRouter も使わない。",
            ],
        },
        "summary": summary,
        "game_records": [] if args.skip_records else games,
    }
    rl_eval._atomic_write(args.output, payload)
    ci = summary["ci95"]["win_rate"]
    print(
        f"exact vs none depth {args.depth} "
        f"win_rate={summary['win_rate']:.4f} "
        f"ci=({ci['low']:.4f},{ci['high']:.4f}) "
        f"diff={summary['mean_stone_diff']:.3f} {summary['verdict']['note']}",
        flush=True,
    )
    print(f"wrote {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
