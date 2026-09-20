#!/usr/bin/env python3
"""Jev 段階 4 の絞り込みパラメータをオフラインで振る。

`margin = 0` をコードだけの基準線とし、平均損失がそれを下回る格子点があるかを探す。
プロンプト文言は変えない。資格情報と課金が要る Jev 呼出しは CI に載せない。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
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
from reversi.engine.rules import Position, legal_places  # noqa: E402

OUTPUT = HERE / "jev-stage4.json"
STAGE2_RECORD = HERE / "jev-stage2.json"
ASK_ATTEMPTS = 3
BLUNDER_LOSS = stage2.BLUNDER_LOSS
SHORTLIST_SIZES = (2, 3, 4, 5)
MARGINS = (0.0, 0.25, 0.5, 1.0, 2.0)
THRESHOLDS = (0.0, 0.3, 0.5, 0.8, 1.0)
_STONE = {".": Stone.EMPTY, "B": Stone.BLACK, "W": Stone.WHITE}


@dataclass(frozen=True, slots=True)
class _Prepared:
    index: int
    position: Position
    stage: str
    empties: int
    places: tuple
    scores: dict
    values: dict[str, int]
    best_value: int
    code_best: str
    board: list[str]


def _position_from_rows(rows: Sequence[str], side: str) -> Position:
    cells = tuple(tuple(_STONE[ch] for ch in row) for row in reversed(rows))
    return Position(Board(cells), Color(side))


def _load_stage2_positions(path: Path) -> list[Position]:
    data = json.loads(path.read_text(encoding="utf-8"))
    found: list[Position] = []
    for row in data["positions"]:
        found.append(_position_from_rows(row["board"], row["side_to_move"]))
    return found


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


def _prepare(index: int, position: Position, spec: jev._Spec) -> _Prepared:
    places = tuple(legal_places(position))
    stage = jev._stage_of(position.board, spec)
    metrics = jev._after_metrics(position, places, spec)
    scores = jev._code_scores(places, metrics, spec, stage)
    code_best = jev._best_square(places, scores)
    values = stage2._move_values(position)
    return _Prepared(
        index=index,
        position=position,
        stage=stage,
        empties=jev._empty_count(position.board),
        places=places,
        scores=scores,
        values=values,
        best_value=max(values.values()),
        code_best=code_best.algebraic,
        board=stage2._board_rows(position),
    )


def _needed_asks(
    prepared: Sequence[_Prepared],
    spec: jev._Spec,
    sizes: Sequence[int],
    margins: Sequence[float],
) -> list[tuple[_Prepared, tuple]]:
    needed: list[tuple[_Prepared, tuple]] = []
    seen: set[tuple[int, tuple[str, ...]]] = set()
    for item in prepared:
        for size in sizes:
            for margin in margins:
                if margin == 0.0:
                    continue
                probe = replace(spec, shortlist_size=size, margin=margin)
                _best, shortlist = jev._shortlist(item.places, item.scores, probe)
                if len(shortlist) < 2:
                    continue
                key = (item.index, tuple(square.algebraic for square in shortlist))
                if key in seen:
                    continue
                seen.add(key)
                needed.append((item, tuple(shortlist)))
    return needed


def _ask_record(parsed: jev._Parsed, shortlist: Sequence) -> dict[str, Any]:
    keys = [square.algebraic for square in shortlist]
    return {
        "shortlist": keys,
        "probabilities": {key: parsed.probabilities[key] for key in keys},
        "confidence": parsed.confidence,
        "choice": parsed.choice,
    }


def _parsed_from_record(row: Mapping[str, Any]) -> jev._Parsed:
    choice = row.get("choice")
    return jev._Parsed(
        probabilities={key: float(value) for key, value in row["probabilities"].items()},
        confidence=float(row["confidence"]),
        choice=choice if isinstance(choice, str) else None,
    )


def _select_prepared(
    item: _Prepared,
    spec: jev._Spec,
    asks: Mapping[tuple[int, tuple[str, ...]], Mapping[str, Any]],
) -> tuple[str, bool]:
    best, shortlist = jev._shortlist(item.places, item.scores, spec)
    if spec.margin == 0.0:
        return best.algebraic, False
    if len(shortlist) == 1:
        return shortlist[0].algebraic, False
    key = (item.index, tuple(square.algebraic for square in shortlist))
    parsed = _parsed_from_record(asks[key])
    chosen = jev._select_square(item.position, item.places, parsed, spec)
    return chosen.algebraic, True


def _cell_row(
    size: int,
    margin: float,
    threshold: float,
    prepared: Sequence[_Prepared],
    spec: jev._Spec,
    asks: Mapping[tuple[int, tuple[str, ...]], Mapping[str, Any]],
) -> dict[str, Any]:
    probe = replace(
        spec,
        shortlist_size=size,
        margin=margin,
        confidence_threshold=threshold,
    )
    losses: list[int] = []
    asked = 0
    matches = 0
    blunders = 0
    for item in prepared:
        algebraic, did_ask = _select_prepared(item, probe, asks)
        loss = item.best_value - item.values[algebraic]
        losses.append(loss)
        asked += int(did_ask)
        matches += int(loss == 0)
        blunders += int(loss >= BLUNDER_LOSS)
    n = len(prepared)
    return {
        "shortlist_size": size,
        "margin": margin,
        "confidence_threshold": threshold,
        "n": n,
        "asked": asked,
        "match_rate": matches / n if n else 0.0,
        "mean_loss": sum(losses) / n if n else 0.0,
        "blunder_rate": blunders / n if n else 0.0,
    }


def _conclude(
    grid: Sequence[Mapping[str, Any]],
    baseline: float,
) -> dict[str, Any]:
    beating = [row for row in grid if row["mean_loss"] < baseline]
    if not beating:
        return {
            "beats_baseline": False,
            "return_to_stage3": True,
            "chosen": None,
        }
    chosen = min(
        beating,
        key=lambda row: (
            row["mean_loss"],
            row["margin"],
            row["shortlist_size"],
            -row["confidence_threshold"],
        ),
    )
    return {
        "beats_baseline": True,
        "return_to_stage3": False,
        "chosen": {
            "shortlist_size": chosen["shortlist_size"],
            "margin": chosen["margin"],
            "confidence_threshold": chosen["confidence_threshold"],
            "mean_loss": chosen["mean_loss"],
        },
    }


def _payload(
    prepared: Sequence[_Prepared],
    grid: Sequence[Mapping[str, Any]],
    asks: Sequence[Mapping[str, Any]],
    spec: jev._Spec,
    conclusion: Mapping[str, Any],
    baseline: float,
) -> dict[str, Any]:
    zeros = [row for row in grid if row["margin"] == 0.0]
    zero_loss = zeros[0]["mean_loss"] if zeros else baseline
    return {
        "recorded_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
        "protocol": {
            "positions": len(prepared),
            "search_depth": stage2.SEARCH_DEPTH,
            "exact_empty": stage2.EXACT_EMPTY,
            "blunder_loss": BLUNDER_LOSS,
            "label": "alphabeta",
            "wthor": False,
            "source": "jev-stage2.json",
            "grid": {
                "shortlist_size": list(SHORTLIST_SIZES),
                "margin": list(MARGINS),
                "confidence_threshold": list(THRESHOLDS),
            },
            "notes": [
                "局面集合は段階 2 の 18 局面。正解は手元の αβ（深さ 4。空きマスが 8 以下なら終局まで）。",
                "margin = 0 はコード最善と同じ手を選ぶ基準線。ここから shortlist_size / margin / confidence_threshold を振る。",
                "平均損失が基準線より小さい格子点があれば 1 組を指名する。無ければ段階 3 へ戻る。",
                "オフラインの差は探索損失であり、対局の勝率の有意差ではない。",
                "プロンプト文言は変えていない。資格情報と課金が要る呼出しは CI に載せない。",
            ],
        },
        "baseline_mean_loss": baseline,
        "margin_zero_mean_loss": zero_loss,
        "grid": list(grid),
        "asks": list(asks),
        "beats_baseline": conclusion["beats_baseline"],
        "return_to_stage3": conclusion["return_to_stage3"],
        "chosen": conclusion["chosen"],
        "positions": [
            {
                "index": item.index,
                "stage": item.stage,
                "empties": item.empties,
                "side_to_move": item.position.side_to_move.value,
                "board": item.board,
                "best_value": item.best_value,
                "code_best": item.code_best,
                "code_best_loss": item.best_value - item.values[item.code_best],
                "values": dict(item.values),
            }
            for item in prepared
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Jev 段階 4 のパラメータ格子を書く")
    parser.add_argument("--output", type=Path, default=OUTPUT, help="書き出す JSON")
    parser.add_argument(
        "--from-stage2",
        type=Path,
        default=STAGE2_RECORD,
        help="同じ局面集合の正本（段階 2 の記録）",
    )
    args = parser.parse_args()
    output = args.output
    stage2._ensure_output(output)
    jev._log_candidates = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    secret = stage2._bind_secret_if_needed()
    if not jev.SECRET_PATH.is_file():
        raise SystemExit("OpenRouter の資格情報が無く、Jev のオフライン評価を計測できない")
    spec = jev._load_spec()
    try:
        if not args.from_stage2.is_file():
            raise SystemExit(f"段階 2 の記録が無い: {args.from_stage2}")
        positions = _load_stage2_positions(args.from_stage2)
        print(f"positions={len(positions)} from {args.from_stage2}", flush=True)
        prepared: list[_Prepared] = []
        for index, position in enumerate(positions):
            print(
                f"prepare {index + 1}/{len(positions)} "
                f"{jev._stage_of(position.board, spec)} "
                f"empty={jev._empty_count(position.board)}",
                flush=True,
            )
            prepared.append(_prepare(index, position, spec))
        losses = [
            item.best_value - item.values[item.code_best] for item in prepared
        ]
        baseline = sum(losses) / len(losses)
        needed = _needed_asks(prepared, spec, SHORTLIST_SIZES, MARGINS)
        print(f"unique asks={len(needed)} baseline_mean_loss={baseline}", flush=True)
        ask_map: dict[tuple[int, tuple[str, ...]], dict[str, Any]] = {}
        ask_rows: list[dict[str, Any]] = []
        for index, (item, shortlist) in enumerate(needed, start=1):
            keys = tuple(square.algebraic for square in shortlist)
            print(
                f"ask {index}/{len(needed)} pos={item.index} "
                f"shortlist={list(keys)}",
                flush=True,
            )
            parsed = _ask_with_retry(item.position, shortlist, spec)
            record = {"position": item.index, **_ask_record(parsed, shortlist)}
            ask_map[(item.index, keys)] = record
            ask_rows.append(record)
        grid: list[dict[str, Any]] = []
        total = len(SHORTLIST_SIZES) * len(MARGINS) * len(THRESHOLDS)
        done = 0
        for size in SHORTLIST_SIZES:
            for margin in MARGINS:
                for threshold in THRESHOLDS:
                    done += 1
                    row = _cell_row(
                        size, margin, threshold, prepared, spec, ask_map
                    )
                    grid.append(row)
                    print(
                        f"grid {done}/{total} k={size} m={margin} t={threshold} "
                        f"mean_loss={row['mean_loss']:.4f} asked={row['asked']}",
                        flush=True,
                    )
        conclusion = _conclude(grid, baseline)
        stage2._atomic_write(
            output,
            _payload(prepared, grid, ask_rows, spec, conclusion, baseline),
        )
    finally:
        if secret is not None:
            secret.unlink(missing_ok=True)
    payload = json.loads(output.read_text(encoding="utf-8"))
    print(
        f"wrote {output} beats_baseline={payload['beats_baseline']} "
        f"chosen={payload.get('chosen')} "
        f"return_to_stage3={payload.get('return_to_stage3')}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
