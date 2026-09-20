#!/usr/bin/env python3
"""Jev 段階 5 の対局による最終確認を書き出す。

段階 4 で指名した絞り込み設定と、コードだけの基準線（margin = 0）を、
同じ開始局面の組で先後入れ替えて対局する。対の石差の符号検定で有意に良く、
勝率も下回らなければ採用する。資格情報と課金が要る対局は CI に載せない。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from random import Random
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STRATEGY_SRC = ROOT / "strategy" / "src"
HERE = Path(__file__).resolve().parent
if str(STRATEGY_SRC) not in sys.path:
    sys.path.insert(0, str(STRATEGY_SRC))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import jev_stage2 as stage2  # noqa: E402
from reversi.agents import jev  # noqa: E402
from reversi.engine.board import Board, Color, Stone  # noqa: E402
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

OUTPUT = HERE / "jev-stage5.json"
STAGE4_RECORD = HERE / "jev-stage4.json"
ASK_ATTEMPTS = 3
SEED = 20260920
N_STARTS = 24
OPENING_PLIES = (4, 6, 8)
ALPHA = 0.05
_STONE = {".": Stone.EMPTY, "B": Stone.BLACK, "W": Stone.WHITE}
Chooser = Callable[[Position], Place | None]


def _position_from_rows(rows: Sequence[str], side: str) -> Position:
    cells = tuple(tuple(_STONE[ch] for ch in row) for row in reversed(rows))
    color = Color.BLACK if side in {"B", "black"} else Color.WHITE
    return Position(Board(cells), color)


def _load_chosen(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("beats_baseline"):
        raise SystemExit("段階 4 が上回る設定を指名していないので段階 5 には着手しない")
    chosen = data["chosen"]
    for key in ("shortlist_size", "margin", "confidence_threshold"):
        if key not in chosen:
            raise SystemExit(f"段階 4 の指名に {key} が無い")
    return {
        "shortlist_size": int(chosen["shortlist_size"]),
        "margin": float(chosen["margin"]),
        "confidence_threshold": float(chosen["confidence_threshold"]),
        "mean_loss": float(chosen["mean_loss"]),
    }


def _ask_with_retry(
    position: Position,
    places: Sequence,
    spec: jev._Spec,
) -> jev._Parsed:
    last: jev.ExternalModelError | None = None
    for attempt in range(ASK_ATTEMPTS):
        try:
            return jev._ask_jev(position, places, spec)
        except jev.ExternalModelError as exc:
            last = exc
            if attempt + 1 >= ASK_ATTEMPTS:
                break
            time.sleep(2**attempt)
    assert last is not None
    raise last


def _choose_with_spec(
    position: Position,
    spec: jev._Spec,
    asks: dict[tuple[str, ...], dict[str, Any]],
) -> tuple[Place | None, bool]:
    places = legal_places(position)
    if not places:
        return None, False
    if len(places) == 1:
        return Place(places[0]), False
    if spec.margin == 0.0:
        square = jev._select_code_best(position, places, spec)
        return Place(square), False
    stage = jev._stage_of(position.board, spec)
    metrics = jev._after_metrics(position, places, spec)
    scores = jev._code_scores(places, metrics, spec, stage)
    _best, shortlist = jev._shortlist(places, scores, spec)
    if len(shortlist) < 2:
        parsed = jev._dummy_parsed(places)
        square = jev._legal_square(
            jev._select_square(position, places, parsed, spec), places
        )
        return Place(square), False
    key = (
        *stage2._board_rows(position),
        position.side_to_move.value,
        *(square.algebraic for square in shortlist),
    )
    cached = asks.get(key)
    if cached is None:
        parsed = _ask_with_retry(position, shortlist, spec)
        cached = {
            "shortlist": [square.algebraic for square in shortlist],
            "probabilities": {
                square.algebraic: parsed.probabilities[square.algebraic]
                for square in shortlist
            },
            "confidence": parsed.confidence,
            "choice": parsed.choice,
        }
        asks[key] = cached
    parsed = jev._Parsed(
        probabilities={k: float(v) for k, v in cached["probabilities"].items()},
        confidence=float(cached["confidence"]),
        choice=cached["choice"] if isinstance(cached.get("choice"), str) else None,
    )
    square = jev._legal_square(
        jev._select_square(position, places, parsed, spec), places
    )
    return Place(square), True


def _play(
    start: Position,
    black: Chooser,
    white: Chooser,
) -> dict[str, Any]:
    position = start
    while not is_over(position):
        if not legal_places(position):
            position = play(position, PassMove())
            continue
        chooser = black if position.side_to_move is Color.BLACK else white
        move = chooser(position)
        if not isinstance(move, Place):
            raise jev.ExternalModelError("着手不能")
        position = play(position, move)
    counts = stone_counts(position.board)
    score = official_score(position.board)
    return {
        "official_black": score.black,
        "official_white": score.white,
        "stones_black": counts.black,
        "stones_white": counts.white,
    }


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
        rows = stage2._board_rows(position)
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


def _stone_diff(game: Mapping[str, Any], candidate_is_black: bool) -> int:
    own = int(game["stones_black"] if candidate_is_black else game["stones_white"])
    opp = int(game["stones_white"] if candidate_is_black else game["stones_black"])
    return own - opp


def _result(game: Mapping[str, Any], candidate_is_black: bool) -> str:
    black = int(game["official_black"])
    white = int(game["official_white"])
    own = black if candidate_is_black else white
    opp = white if candidate_is_black else black
    if own > opp:
        return "win"
    if own < opp:
        return "loss"
    return "draw"


def _sign_test(diffs: Sequence[float]) -> dict[str, Any]:
    nonzero = [value for value in diffs if value != 0]
    n = len(nonzero)
    positive = sum(1 for value in nonzero if value > 0)
    if n == 0:
        p_value = 1.0
    else:
        tail = sum(math.comb(n, k) for k in range(positive, n + 1))
        p_value = tail / (2**n)
    return {
        "n": n,
        "positive": positive,
        "negative": n - positive,
        "ties": len(diffs) - n,
        "p_value": p_value,
        "alpha": ALPHA,
        "method": "sign_test_one_sided_pair_stone_diff",
    }


def _conclude(
    games: Sequence[Mapping[str, Any]],
    pairs: Sequence[Mapping[str, Any]],
    complete: bool,
) -> dict[str, Any]:
    n = len(games)
    wins = sum(1 for game in games if game["result"] == "win")
    draws = sum(1 for game in games if game["result"] == "draw")
    losses = sum(1 for game in games if game["result"] == "loss")
    win_rate = (wins + 0.5 * draws) / n if n else 0.0
    baseline_win_rate = (losses + 0.5 * draws) / n if n else 0.0
    mean_stone_diff = (
        sum(int(game["stone_diff"]) for game in games) / n if n else 0.0
    )
    pair_diffs = [float(row["pair_stone_diff"]) for row in pairs]
    sign = _sign_test(pair_diffs)
    accepted = (
        mean_stone_diff > 0
        and win_rate >= baseline_win_rate
        and sign["p_value"] < ALPHA
        and sign["positive"] > sign["n"] / 2
    )
    if not complete:
        accepted = False
        catalog_policy = "in_progress"
        return_to = False
    elif accepted:
        catalog_policy = "adopted_stage4_chosen"
        return_to = False
    else:
        catalog_policy = "code_only_v2_jev0"
        return_to = True
    return {
        "games": n,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "win_rate": win_rate,
        "baseline_win_rate": baseline_win_rate,
        "mean_stone_diff": mean_stone_diff,
        "paired": True,
        "sign_test": sign,
        "accepted": accepted,
        "complete": complete,
        "catalog_policy": catalog_policy,
        "return_to_stage3_and_4": return_to,
    }


def _payload(
    starts: Sequence[Mapping[str, Any]],
    games: Sequence[Mapping[str, Any]],
    pairs: Sequence[Mapping[str, Any]],
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    conclusion: Mapping[str, Any],
    seed: int,
) -> dict[str, Any]:
    return {
        "recorded_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
        "protocol": {
            "starts": len(starts),
            "games_per_start": 2,
            "opening_plies": list(OPENING_PLIES),
            "seed": seed,
            "paired": True,
            "alpha": ALPHA,
            "significance": "sign_test_one_sided_pair_stone_diff",
            "notes": [
                "開始局面は初形から 4/6/8 手を一様乱択で進めた組。各局面で先後を入れ替える。",
                "基準線はコード最善（margin = 0）。候補は段階 4 が指名した絞り込み設定。",
                "勝敗は公式スコア、最終石差は盤上の石数差（候補−基準線）。",
                "採用は、平均石差が正、勝率が基準線を下回らず、対の石差の片側符号検定が有意であること。",
                "満たさなければカタログはコードだけの v2_jev0 を維持し、段階 3 と 4 へ戻る。",
                "再開は seed・開始局面数・候補と基準線の selection が一致するときだけ。不一致なら別の --output を使う。",
                "全対局が終わるまで complete は false で、accepted は出さない。",
                "資格情報と課金が要る対局は CI に載せない。本スクリプトはホストで明示実行する。",
            ],
        },
        "baseline": dict(baseline),
        "candidate": dict(candidate),
        **conclusion,
        "paired_results": list(pairs),
        "starts": list(starts),
        "game_records": list(games),
    }


def _same_selection(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    try:
        return (
            int(left["shortlist_size"]) == int(right["shortlist_size"])
            and float(left["margin"]) == float(right["margin"])
            and float(left["confidence_threshold"]) == float(right["confidence_threshold"])
        )
    except (KeyError, TypeError, ValueError):
        return False


def _progress_matches(
    progress: Mapping[str, Any],
    seed: int,
    n_starts: int,
    candidate: Mapping[str, Any],
    baseline: Mapping[str, Any],
) -> bool:
    protocol = progress.get("protocol")
    if not isinstance(protocol, dict) or protocol.get("seed") != seed:
        return False
    starts = progress.get("starts")
    if not isinstance(starts, list) or len(starts) != n_starts:
        return False
    prev_c = progress.get("candidate")
    prev_b = progress.get("baseline")
    if not isinstance(prev_c, dict) or not isinstance(prev_b, dict):
        return False
    if not _same_selection(prev_c, candidate):
        return False
    try:
        return float(prev_b["margin"]) == float(baseline["margin"])
    except (KeyError, TypeError, ValueError):
        return False


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


def _pair_key(start_index: int, candidate_is_black: bool) -> tuple[int, str]:
    return (start_index, "black" if candidate_is_black else "white")


def main() -> int:
    parser = argparse.ArgumentParser(description="Jev 段階 5 の対の比較対局を書く")
    parser.add_argument("--output", type=Path, default=OUTPUT, help="書き出す JSON")
    parser.add_argument(
        "--from-stage4",
        type=Path,
        default=STAGE4_RECORD,
        help="段階 4 の指名が入った記録",
    )
    parser.add_argument("--starts", type=int, default=N_STARTS, help="開始局面数")
    parser.add_argument("--seed", type=int, default=SEED, help="開始局面の乱数種")
    args = parser.parse_args()
    if args.starts < 1:
        raise SystemExit("開始局面数は 1 以上")
    output = args.output
    stage2._ensure_output(output)
    jev._log_candidates = lambda *_a, **_k: None  # type: ignore[method-assign]
    secret = stage2._bind_secret_if_needed()
    try:
        if not jev.SECRET_PATH.is_file():
            raise SystemExit("OpenRouter の資格情報が無く、段階 5 の対局を計測できない")
        spec = jev._load_spec()
        chosen = _load_chosen(args.from_stage4)
        baseline_spec = replace(spec, margin=0.0)
        candidate_spec = replace(
            spec,
            shortlist_size=chosen["shortlist_size"],
            margin=chosen["margin"],
            confidence_threshold=chosen["confidence_threshold"],
        )
        baseline_meta = {
            "label": "code_only",
            "shortlist_size": baseline_spec.shortlist_size,
            "margin": baseline_spec.margin,
            "confidence_threshold": baseline_spec.confidence_threshold,
        }
        candidate_meta = {
            "label": "stage4_chosen",
            "source": args.from_stage4.name,
            **chosen,
        }
        progress = _load_progress(output)
        rng = Random(args.seed)
        if progress is not None:
            if not _progress_matches(
                progress, args.seed, args.starts, candidate_meta, baseline_meta
            ):
                raise SystemExit(
                    "既存の記録は別の設定です。別の --output を指定してください。"
                )
            starts = list(progress["starts"])
            games = [row for row in progress["game_records"] if isinstance(row, dict)]
            print(f"resume starts={len(starts)} games={len(games)}", flush=True)
        else:
            starts = _make_starts(rng, args.starts)
            games = []
            print(f"starts={len(starts)} seed={args.seed}", flush=True)
        done = {
            _pair_key(int(row["start_index"]), row["candidate_color"] == "black")
            for row in games
            if "start_index" in row and "candidate_color" in row
        }
        asks: dict[tuple[str, ...], dict[str, Any]] = {}

        def _candidate_chooser(position: Position) -> Place | None:
            move, _asked = _choose_with_spec(position, candidate_spec, asks)
            return move

        def _baseline_chooser(position: Position) -> Place | None:
            move, _asked = _choose_with_spec(position, baseline_spec, asks)
            return move

        def _save() -> None:
            pairs = _pairs_from_games(starts, games)
            complete = len(games) == 2 * len(starts) and len(pairs) == len(starts)
            conclusion = _conclude(games, pairs, complete)
            stage2._atomic_write(
                output,
                _payload(
                    starts,
                    games,
                    pairs,
                    baseline_meta,
                    candidate_meta,
                    conclusion,
                    args.seed,
                ),
            )

        for start in starts:
            position = _position_from_rows(start["board"], start["side_to_move"])
            for candidate_is_black in (True, False):
                key = _pair_key(int(start["index"]), candidate_is_black)
                color = "black" if candidate_is_black else "white"
                if key in done:
                    print(
                        f"start {start['index']} candidate={color} skip",
                        flush=True,
                    )
                    continue
                black, white = (
                    (_candidate_chooser, _baseline_chooser)
                    if candidate_is_black
                    else (_baseline_chooser, _candidate_chooser)
                )
                print(
                    f"start {start['index']}/{len(starts) - 1} "
                    f"candidate={color} plies={start['opening_plies']}",
                    flush=True,
                )
                raw = _play(position, black, white)
                record = {
                    "start_index": int(start["index"]),
                    "candidate_color": color,
                    "result": _result(raw, candidate_is_black),
                    "stone_diff": _stone_diff(raw, candidate_is_black),
                    **raw,
                }
                games.append(record)
                done.add(key)
                _save()
                print(
                    f"  {record['result']} stones "
                    f"{raw['stones_black']}-{raw['stones_white']} "
                    f"diff={record['stone_diff']}",
                    flush=True,
                )
        _save()
    finally:
        if secret is not None:
            secret.unlink(missing_ok=True)
    payload = json.loads(output.read_text(encoding="utf-8"))
    print(
        f"wrote {output} games={payload['games']} "
        f"win_rate={payload['win_rate']:.4f} "
        f"mean_stone_diff={payload['mean_stone_diff']:.4f} "
        f"accepted={payload['accepted']} complete={payload.get('complete')}",
        flush=True,
    )
    return 0


def _pairs_from_games(
    starts: Sequence[Mapping[str, Any]],
    games: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_key = {
        (int(row["start_index"]), row["candidate_color"]): row for row in games
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
                "candidate_better": pair_diff > 0,
            }
        )
    return pairs


if __name__ == "__main__":
    raise SystemExit(main())
