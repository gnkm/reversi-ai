#!/usr/bin/env python3
"""Phase 6 の αβ 個体を深さ 4 ミニマックスと先後入れ替え対局し、成績 JSON を書く。

対局の再実行は CI に載せない。ホストで明示的に走らせる。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
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

from reversi.agents import alphabeta, minimax  # noqa: E402
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

OUTPUT = Path(__file__).resolve().parent / "alphabeta-eval.json"
SEED = 20260921
N_STARTS = 50
OPENING_PLIES = (4, 6, 8)
ACCEPT_WIN_RATE = 0.70
_STONE = {".": Stone.EMPTY, "B": Stone.BLACK, "W": Stone.WHITE}
_CHAR = {Stone.EMPTY: ".", Stone.BLACK: "B", Stone.WHITE: "W"}


def _ensure_output(path: Path) -> None:
    parent = path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        probe = parent / f".{path.name}.write-probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        raise SystemExit(f"出力先を書けません: {path}") from exc


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


def _make_starts(rng: Random, count: int) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    attempts = 0
    while len(found) < count:
        attempts += 1
        if attempts > count * 50:
            raise SystemExit("開始局面を十分な数だけ作れない")
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


def _play_recorded(start: Position, alphabeta_is_black: bool) -> dict[str, Any]:
    """1 局を最後まで進め、αβ の探索局面数と思考時間を残す。"""
    position = start
    nodes: list[int] = []
    thinks: list[float] = []
    while not is_over(position):
        places = legal_places(position)
        if not places:
            position = play(position, PassMove())
            continue
        is_ab = (position.side_to_move is Color.BLACK) == alphabeta_is_black
        started = time.perf_counter()
        if is_ab:
            move, _value, searched = alphabeta.search_stats(
                position, alphabeta.SEARCH_DEPTH
            )
            thinks.append(time.perf_counter() - started)
            nodes.append(searched)
        else:
            move = minimax.choose_move(position)
        if not isinstance(move, Place) or move.square not in places:
            raise RuntimeError("合法手の外を選んだ")
        position = play(position, move)
    counts = stone_counts(position.board)
    score = official_score(position.board)
    return {
        "official_black": score.black,
        "official_white": score.white,
        "stones_black": counts.black,
        "stones_white": counts.white,
        "ab_moves": len(nodes),
        "nodes": nodes,
        "think_seconds": thinks,
    }


def _stone_diff(game: Mapping[str, Any], alphabeta_is_black: bool) -> int:
    own = int(game["stones_black"] if alphabeta_is_black else game["stones_white"])
    opp = int(game["stones_white"] if alphabeta_is_black else game["stones_black"])
    return own - opp


def _result(game: Mapping[str, Any], alphabeta_is_black: bool) -> str:
    black = int(game["official_black"])
    white = int(game["official_white"])
    own = black if alphabeta_is_black else white
    opp = white if alphabeta_is_black else black
    if own > opp:
        return "win"
    if own < opp:
        return "loss"
    return "draw"


def play_job(start: Mapping[str, Any], alphabeta_is_black: bool) -> dict[str, Any]:
    """プロセスプール用。開始局面の写しと先後だけを受け取る。"""
    position = _position_from_rows(start["board"], str(start["side_to_move"]))
    raw = _play_recorded(position, alphabeta_is_black)
    color = "black" if alphabeta_is_black else "white"
    thinks = [float(value) for value in raw["think_seconds"]]
    nodes = [int(value) for value in raw["nodes"]]
    return {
        "start_index": int(start["index"]),
        "alphabeta_color": color,
        "result": _result(raw, alphabeta_is_black),
        "stone_diff": _stone_diff(raw, alphabeta_is_black),
        "official_black": int(raw["official_black"]),
        "official_white": int(raw["official_white"]),
        "stones_black": int(raw["stones_black"]),
        "stones_white": int(raw["stones_white"]),
        "ab_moves": int(raw["ab_moves"]),
        "mean_nodes": (sum(nodes) / len(nodes)) if nodes else 0.0,
        "mean_think_seconds": (sum(thinks) / len(thinks)) if thinks else 0.0,
        "max_think_seconds": max(thinks) if thinks else 0.0,
        "total_nodes": sum(nodes),
        "total_think_seconds": sum(thinks),
    }


def _pair_key(start_index: int, alphabeta_is_black: bool) -> tuple[int, str]:
    return (start_index, "black" if alphabeta_is_black else "white")


def _pairs_from_games(
    starts: Sequence[Mapping[str, Any]],
    games: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_key = {
        (int(row["start_index"]), row["alphabeta_color"]): row for row in games
    }
    pairs: list[dict[str, Any]] = []
    for start in starts:
        index = int(start["index"])
        black = by_key.get((index, "black"))
        white = by_key.get((index, "white"))
        if black is None or white is None:
            continue
        pair_diff = (int(black["stone_diff"]) + int(white["stone_diff"])) / 2
        pairs.append(
            {
                "start_index": index,
                "black": dict(black),
                "white": dict(white),
                "pair_stone_diff": pair_diff,
            }
        )
    return pairs


def _conclude(
    games: Sequence[Mapping[str, Any]],
    complete: bool,
) -> dict[str, Any]:
    n = len(games)
    wins = sum(1 for game in games if game["result"] == "win")
    draws = sum(1 for game in games if game["result"] == "draw")
    losses = sum(1 for game in games if game["result"] == "loss")
    win_rate = (wins + 0.5 * draws) / n if n else 0.0
    mean_stone_diff = (
        sum(int(game["stone_diff"]) for game in games) / n if n else 0.0
    )
    total_moves = sum(int(game["ab_moves"]) for game in games)
    mean_nodes = (
        sum(float(game["mean_nodes"]) * int(game["ab_moves"]) for game in games)
        / total_moves
        if total_moves
        else 0.0
    )
    mean_think = (
        sum(
            float(game["mean_think_seconds"]) * int(game["ab_moves"])
            for game in games
        )
        / total_moves
        if total_moves
        else 0.0
    )
    max_think = max(
        (float(game["max_think_seconds"]) for game in games),
        default=0.0,
    )
    accepted = complete and win_rate >= ACCEPT_WIN_RATE
    conclusion: dict[str, Any] = {
        "games": n,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "win_rate": win_rate,
        "mean_stone_diff": mean_stone_diff,
        "mean_nodes": mean_nodes,
        "mean_think_seconds": mean_think,
        "max_think_seconds": max_think,
        "paired": True,
        "accepted": accepted,
        "complete": complete,
        "catalog_policy": "keep_phase6",
    }
    if complete and not accepted:
        # 勝率不足は葉評価の寄与が足りない可能性が高い。TT（Phase 5）は速さ、
        # 終盤完全読み（Phase 6）はすでに入っている。
        conclusion["next_phase"] = 4
        conclusion["catalog_policy"] = "keep_phase6_until_retry"
    return conclusion


def _payload(
    starts: Sequence[Mapping[str, Any]],
    games: Sequence[Mapping[str, Any]],
    pairs: Sequence[Mapping[str, Any]],
    conclusion: Mapping[str, Any],
    seed: int,
    workers: int,
) -> dict[str, Any]:
    return {
        "recorded_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
        "candidate": {
            "specimen_id": alphabeta.SPECIMEN_ID,
            "display_name": alphabeta.DISPLAY_NAME,
            "search_depth": alphabeta.SEARCH_DEPTH,
            "endgame_empty": alphabeta.ENDGAME_EMPTY,
        },
        "opponent": {
            "specimen_id": minimax.SPECIMEN_ID,
            "display_name": minimax.DISPLAY_NAME,
            "search_depth": minimax.SEARCH_DEPTH,
        },
        "protocol": {
            "starts": len(starts),
            "games_per_start": 2,
            "opening_plies": list(OPENING_PLIES),
            "seed": seed,
            "paired": True,
            "workers": workers,
            "acceptance_win_rate": ACCEPT_WIN_RATE,
            "notes": [
                "開始局面は初形から 4/6/8 手を一様乱択で進めた組。各局面で先後を入れ替える。",
                "候補はカタログの「ルールベース (αβ)」（深さ 4、空きマス 10 以下は終盤完全読み）。",
                "比較対象は既存の「ルールベース (ミニマックス)」（深さ 4、位置評価表）。AI-B / AI-C は置かない。",
                "勝敗は公式スコア。石数差は盤上の石数（αβ − ミニマックス）。",
                "探索局面数と思考時間は αβ の各着手（search_stats）の平均と最大。",
                "勝率は（勝 + 0.5×分）/ 局数。0.70 以上なら accepted。shall にはしない。",
                "採用しても不採用でもカタログ個体は 1 体のまま。総当たりの取り直しはしない。",
                "不採用なら next_phase に戻る段階を残す。再開は seed と開始局面数が一致するときだけ。",
                "対局の再実行は CI に載せない。本スクリプトはホストで明示実行する。",
            ],
        },
        **conclusion,
        "paired_results": list(pairs),
        "starts": list(starts),
        "game_records": list(games),
    }


def _load_progress(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(loaded, dict):
        return None
    starts = loaded.get("starts")
    games = loaded.get("game_records")
    if not isinstance(starts, list) or not isinstance(games, list):
        return None
    return loaded


def _progress_matches(
    progress: Mapping[str, Any],
    seed: int,
    n_starts: int,
) -> bool:
    protocol = progress.get("protocol")
    if not isinstance(protocol, dict) or protocol.get("seed") != seed:
        return False
    starts = progress.get("starts")
    if not isinstance(starts, list) or len(starts) != n_starts:
        return False
    candidate = progress.get("candidate")
    opponent = progress.get("opponent")
    if not isinstance(candidate, dict) or not isinstance(opponent, dict):
        return False
    try:
        return (
            str(candidate["specimen_id"]) == alphabeta.SPECIMEN_ID
            and int(candidate["search_depth"]) == alphabeta.SEARCH_DEPTH
            and int(candidate["endgame_empty"]) == alphabeta.ENDGAME_EMPTY
            and str(opponent["specimen_id"]) == minimax.SPECIMEN_ID
            and int(opponent["search_depth"]) == minimax.SEARCH_DEPTH
        )
    except (KeyError, TypeError, ValueError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="αβ を深さ 4 ミニマックスと先後入れ替え対局して記録する"
    )
    parser.add_argument("--output", type=Path, default=OUTPUT, help="書き出す JSON")
    parser.add_argument("--starts", type=int, default=N_STARTS, help="開始局面数")
    parser.add_argument("--seed", type=int, default=SEED, help="開始局面の乱数種")
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="並列数。0 なら CPU 数（最大 4）",
    )
    args = parser.parse_args()
    if args.starts < 1:
        raise SystemExit("開始局面数は 1 以上")
    cpu = os.cpu_count() or 1
    workers = args.workers if args.workers > 0 else min(4, cpu)
    output = args.output
    _ensure_output(output)
    if alphabeta.SEARCH_DEPTH != 4:
        raise SystemExit("αβ の深さは 4 のままであること")
    if minimax.SEARCH_DEPTH != 4:
        raise SystemExit("ミニマックスの深さは 4 のままであること")
    progress = _load_progress(output)
    rng = Random(args.seed)
    if progress is not None:
        if progress.get("stopped_early") is True:
            raise SystemExit(
                "打ち切り済みの記録です。上書きしません。別の --output を指定してください。"
            )
        if not _progress_matches(progress, args.seed, args.starts):
            raise SystemExit(
                "既存の記録は別の設定です。別の --output を指定してください。"
            )
        starts = list(progress["starts"])
        games = [row for row in progress["game_records"] if isinstance(row, dict)]
        print(f"resume starts={len(starts)} games={len(games)}", flush=True)
    else:
        starts = _make_starts(rng, args.starts)
        games = []
        print(f"starts={len(starts)} seed={args.seed} workers={workers}", flush=True)
    done = {
        _pair_key(int(row["start_index"]), row["alphabeta_color"] == "black")
        for row in games
        if "start_index" in row and "alphabeta_color" in row
    }
    jobs: list[tuple[dict[str, Any], bool]] = []
    for start in starts:
        for alphabeta_is_black in (True, False):
            key = _pair_key(int(start["index"]), alphabeta_is_black)
            if key in done:
                continue
            jobs.append((dict(start), alphabeta_is_black))

    def _save() -> None:
        pairs = _pairs_from_games(starts, games)
        complete = len(games) == 2 * len(starts) and len(pairs) == len(starts)
        _atomic_write(
            output,
            _payload(
                starts,
                games,
                pairs,
                _conclude(games, complete),
                args.seed,
                workers,
            ),
        )

    _save()
    if jobs:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(play_job, start, alphabeta_is_black): (
                    int(start["index"]),
                    "black" if alphabeta_is_black else "white",
                )
                for start, alphabeta_is_black in jobs
            }
            for future in as_completed(futures):
                index, color = futures[future]
                record = future.result()
                games.append(record)
                done.add(_pair_key(index, color == "black"))
                _save()
                print(
                    f"start {index}/{len(starts) - 1} αβ={color} "
                    f"{record['result']} stones "
                    f"{record['stones_black']}-{record['stones_white']} "
                    f"diff={record['stone_diff']} "
                    f"done={len(games)}/{2 * len(starts)}",
                    flush=True,
                )
    _save()
    payload = json.loads(output.read_text(encoding="utf-8"))
    extra = ""
    if payload.get("accepted") is False:
        extra = f" next_phase={payload.get('next_phase')}"
    print(
        f"wrote {output} games={payload['games']} "
        f"win_rate={payload['win_rate']:.4f} "
        f"mean_stone_diff={payload['mean_stone_diff']:.4f} "
        f"mean_nodes={payload['mean_nodes']:.1f} "
        f"mean_think_seconds={payload['mean_think_seconds']:.4f} "
        f"max_think_seconds={payload['max_think_seconds']:.4f} "
        f"accepted={payload['accepted']} complete={payload.get('complete')}"
        f"{extra}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
