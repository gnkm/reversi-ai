#!/usr/bin/env python3
"""Jev 段階 3 のプロンプト変更を 1 つずつオフライン評価する。

平均損失が改善し、改訂に使っていない局面でも改善した変更だけを採用する。
資格情報と課金が要る Jev 呼出しは CI に載せない。ホストで明示的に走らせる。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
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
from reversi.engine.board import Board, Color, Square, Stone, all_squares  # noqa: E402
from reversi.engine.rules import (  # noqa: E402
    Position,
    apply_place,
    flips_for,
    legal_places,
)

OUTPUT = HERE / "jev-stage3.json"
PER_STAGE = 6
ASK_ATTEMPTS = 3
NEW_INSTRUCTIONS = (
    "Given `stage`, which place is best for `side_to_move` to play?"
)
NEW_GIVES_LINE = (
    "{kind}. Occupies a corner: {takes_corner}. "
    "Newly lets the opponent take a corner next turn: {gives_corner}. "
    "Opponent replies: {opponent_places}. Discs turned: {flips}."
)

ChooserPatch = Callable[[], None]


@dataclass(frozen=True, slots=True)
class _Prepared:
    position: Position
    stage: str
    empties: int
    values: dict[str, int]
    best_value: int
    places: tuple[Square, ...]
    code_best: Square
    shortlist: tuple[Square, ...]
    flips: dict[str, int]


@dataclass(frozen=True, slots=True)
class _EvalRow:
    algebraic: str
    loss: int
    asked: bool
    flips: int
    code_best_flips: int
    confidence: float | None


@dataclass
class _Variant:
    change: str
    apply: Callable[[jev._Spec], jev._Spec]
    install: Callable[[], None]
    uninstall: Callable[[], None]


_orig_place_line = jev._place_line
_active_extras: tuple[str, ...] = ()


_AXES = ((1, 0), (0, 1), (1, 1), (1, -1))


def _on_edge(square: Square, spec: jev._Spec) -> bool:
    return jev._kind_of(square, spec) in {"edge", "c"}


def _line_filled(board: Board, file: int, rank: int, dfile: int, drank: int) -> bool:
    for sign in (1, -1):
        cur_file, cur_rank = file, rank
        while True:
            cur_file += sign * dfile
            cur_rank += sign * drank
            if not (0 <= cur_file < 8 and 0 <= cur_rank < 8):
                break
            if board.stone_at(Square(file=cur_file, rank=cur_rank)) is Stone.EMPTY:
                return False
    return True


def _axis_closed(
    file: int,
    rank: int,
    dfile: int,
    drank: int,
    board: Board,
    stable: set[tuple[int, int]],
) -> bool:
    if _line_filled(board, file, rank, dfile, drank):
        return True
    for sign in (1, -1):
        neighbor = (file + sign * dfile, rank + sign * drank)
        nfile, nrank = neighbor
        if not (0 <= nfile < 8 and 0 <= nrank < 8):
            continue
        if neighbor not in stable:
            return False
    return True


def _stable_count(board: Board, color: Color) -> int:
    """保守的な確定石。角を種にし、軸が埋まっているか安定石に挟まれていれば足す。"""
    own = color.stone
    stable: set[tuple[int, int]] = set()
    for file, rank in ((0, 0), (7, 0), (0, 7), (7, 7)):
        if board.stone_at(Square(file=file, rank=rank)) is own:
            stable.add((file, rank))
    changed = True
    while changed:
        changed = False
        for square in all_squares():
            if board.stone_at(square) is not own:
                continue
            coord = (square.file, square.rank)
            if coord in stable:
                continue
            if all(
                _axis_closed(square.file, square.rank, dfile, drank, board, stable)
                for dfile, drank in _AXES
            ):
                stable.add(coord)
                changed = True
    return len(stable)


def _stable_increases(position: Position, square: Square) -> bool:
    color = position.side_to_move
    before = _stable_count(position.board, color)
    after = _stable_count(apply_place(position.board, square, color), color)
    return after > before


def _reply_change_word(position: Position, square: Square) -> str:
    opponent = position.side_to_move.opponent
    before = len(legal_places(Position(position.board, opponent)))
    after_board = apply_place(position.board, square, position.side_to_move)
    after = len(legal_places(Position(after_board, opponent)))
    if after > before:
        return "increased"
    if after < before:
        return "decreased"
    return "same"


def _place_line_with_extras(
    position: Position, square: Square, spec: jev._Spec
) -> str:
    line = _orig_place_line(position, square, spec)
    bits: list[str] = []
    if "takes_edge" in _active_extras:
        bits.append(
            "Occupies an edge: " + jev._yes_no(_on_edge(square, spec), spec)
        )
    if "stable_increase" in _active_extras:
        bits.append(
            "Stable discs increase: "
            + jev._yes_no(_stable_increases(position, square), spec)
        )
    if "reply_change" in _active_extras:
        bits.append(
            "Opponent replies vs now: " + _reply_change_word(position, square)
        )
    if not bits:
        return line
    return line.rstrip() + " " + " ".join(bit if bit.endswith(".") else bit + "." for bit in bits)


def _set_extras(names: tuple[str, ...]) -> None:
    global _active_extras
    _active_extras = names


def _clear_extras() -> None:
    _set_extras(())


def _noop() -> None:
    return None


def _ask_with_retry(
    position: Position,
    places: Sequence[Square],
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
            time.sleep(2 ** attempt)
    assert last is not None
    raise last


def _prepare(position: Position, spec: jev._Spec) -> _Prepared:
    places = tuple(legal_places(position))
    stage = jev._stage_of(position.board, spec)
    metrics = jev._after_metrics(position, places, spec)
    scores = jev._code_scores(places, metrics, spec, stage)
    code_best, shortlist = jev._shortlist(places, scores, spec)
    values = stage2._move_values(position)
    flips = {
        square.algebraic: len(flips_for(position.board, square, position.side_to_move))
        for square in places
    }
    return _Prepared(
        position=position,
        stage=stage,
        empties=jev._empty_count(position.board),
        values=values,
        best_value=max(values.values()),
        places=places,
        code_best=code_best,
        shortlist=tuple(shortlist),
        flips=flips,
    )


def _evaluate_one(prepared: _Prepared, spec: jev._Spec) -> _EvalRow:
    if spec.margin == 0.0 or len(prepared.shortlist) == 1:
        chosen = prepared.code_best if spec.margin == 0.0 else prepared.shortlist[0]
        return _EvalRow(
            algebraic=chosen.algebraic,
            loss=prepared.best_value - prepared.values[chosen.algebraic],
            asked=False,
            flips=prepared.flips[chosen.algebraic],
            code_best_flips=prepared.flips[prepared.code_best.algebraic],
            confidence=None,
        )
    parsed = _ask_with_retry(prepared.position, prepared.shortlist, spec)
    chosen = jev._select_square(
        prepared.position, prepared.places, parsed, spec
    )
    return _EvalRow(
        algebraic=chosen.algebraic,
        loss=prepared.best_value - prepared.values[chosen.algebraic],
        asked=True,
        flips=prepared.flips[chosen.algebraic],
        code_best_flips=prepared.flips[prepared.code_best.algebraic],
        confidence=parsed.confidence,
    )


def _evaluate_set(
    prepared: Sequence[_Prepared],
    spec: jev._Spec,
    label: str,
) -> list[_EvalRow]:
    rows: list[_EvalRow] = []
    for index, item in enumerate(prepared, start=1):
        print(
            f"{label} {index}/{len(prepared)} {item.stage} empty={item.empties}",
            flush=True,
        )
        rows.append(_evaluate_one(item, spec))
    return rows


def _mean_loss(rows: Sequence[_EvalRow]) -> float:
    return sum(row.loss for row in rows) / len(rows) if rows else 0.0


def _mean_flips(rows: Sequence[_EvalRow], attr: str) -> float:
    return sum(getattr(row, attr) for row in rows) / len(rows) if rows else 0.0


def _split_positions(
    pools: Mapping[str, Sequence[Position]],
    per_stage: int,
) -> tuple[list[Position], list[Position]]:
    train: list[Position] = []
    holdout: list[Position] = []
    train_rng = Random(0)
    hold_rng = Random(1)
    for stage in jev._STAGE_KEYS:
        bucket = list(pools[stage])
        bucket.sort(key=lambda position: stage2._key_of(position))
        shuffled = list(bucket)
        train_rng.shuffle(shuffled)
        chosen_train = shuffled[:per_stage]
        train_keys = {stage2._key_of(position) for position in chosen_train}
        remain = [
            position
            for position in bucket
            if stage2._key_of(position) not in train_keys
        ]
        hold_rng.shuffle(remain)
        chosen_hold = remain[:per_stage]
        if len(chosen_train) < per_stage:
            raise SystemExit(
                f"{stage} の改訂用局面が足りません: {len(chosen_train)} < {per_stage}"
            )
        if len(chosen_hold) < per_stage:
            raise SystemExit(
                f"{stage} の別局面が足りません: {len(chosen_hold)} < {per_stage}"
            )
        train.extend(chosen_train)
        holdout.extend(chosen_hold)
    return train, holdout


def _variants() -> list[_Variant]:
    def apply_instructions(spec: jev._Spec) -> jev._Spec:
        return replace(
            spec,
            instructions=NEW_INSTRUCTIONS,
            places_in_state=False,
        )

    def apply_drop_objective(spec: jev._Spec) -> jev._Spec:
        return replace(spec, objective="")

    def apply_gives_newly(spec: jev._Spec) -> jev._Spec:
        return replace(
            spec,
            gives_corner_newly=True,
            place_line=NEW_GIVES_LINE,
        )

    def add_extra(name: str) -> Callable[[], None]:
        def install() -> None:
            if name not in _active_extras:
                _set_extras((*_active_extras, name))

        return install

    def drop_extra(name: str) -> Callable[[], None]:
        def uninstall() -> None:
            _set_extras(tuple(item for item in _active_extras if item != name))

        return uninstall

    return [
        _Variant(
            "instructions_reference_stage_and_side",
            apply_instructions,
            _noop,
            _noop,
        ),
        _Variant("drop_objective", apply_drop_objective, _noop, _noop),
        _Variant("gives_corner_newly", apply_gives_newly, _noop, _noop),
        _Variant(
            "add_takes_edge",
            lambda spec: spec,
            add_extra("takes_edge"),
            drop_extra("takes_edge"),
        ),
        _Variant(
            "add_stable_increase",
            lambda spec: spec,
            add_extra("stable_increase"),
            drop_extra("stable_increase"),
        ),
        _Variant(
            "add_reply_change",
            lambda spec: spec,
            add_extra("reply_change"),
            drop_extra("reply_change"),
        ),
    ]


def _trial_row(
    change: str,
    before: Sequence[_EvalRow],
    after: Sequence[_EvalRow],
    accepted: bool,
    holdout_before: Sequence[_EvalRow] | None,
    holdout_after: Sequence[_EvalRow] | None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "change": change,
        "mean_loss_before": _mean_loss(before),
        "mean_loss_after": _mean_loss(after),
        "accepted": accepted,
        "n": len(before),
        "asked_before": sum(1 for item in before if item.asked),
        "asked_after": sum(1 for item in after if item.asked),
        "mean_flips_jev_before": _mean_flips(before, "flips"),
        "mean_flips_jev_after": _mean_flips(after, "flips"),
        "mean_flips_code_best": _mean_flips(before, "code_best_flips"),
    }
    if holdout_before is not None and holdout_after is not None:
        row["holdout_mean_loss_before"] = _mean_loss(holdout_before)
        row["holdout_mean_loss_after"] = _mean_loss(holdout_after)
        row["holdout_n"] = len(holdout_before)
    return row


def _payload(
    trials: Sequence[Mapping[str, Any]],
    accepted: Sequence[str],
    holdout: Mapping[str, Any],
    per_stage: int,
    spec: jev._Spec,
) -> dict[str, Any]:
    return {
        "recorded_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
        "protocol": {
            "positions_per_stage": per_stage,
            "search_depth": stage2.SEARCH_DEPTH,
            "exact_empty": stage2.EXACT_EMPTY,
            "label": "alphabeta",
            "wthor": False,
            "selection": {
                "shortlist_size": spec.shortlist_size,
                "margin": spec.margin,
                "confidence_threshold": spec.confidence_threshold,
            },
            "notes": [
                "変更は 1 つずつ入れ、改訂用局面の平均損失が下がったときだけ別局面でも測る。",
                "別局面でも平均損失が下がった変更だけを採用する。",
                "指標は絞り込み方式の平均損失（対局時と同じ経路）。",
                "正解は手元の αβ（深さ 4。空きマスが 8 以下なら終局まで）の評価値。",
                "WTHOR の手は正解に使っていない。資格情報と課金が要る呼出しは CI に載せない。",
            ],
        },
        "trials": list(trials),
        "accepted_changes": list(accepted),
        "holdout": dict(holdout),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Jev 段階 3 のオフライン評価を書く")
    parser.add_argument("--output", type=Path, default=OUTPUT, help="書き出す JSON")
    parser.add_argument(
        "--per-stage",
        type=int,
        default=PER_STAGE,
        help="序盤・中盤・終盤それぞれの改訂用・別局面の数",
    )
    args = parser.parse_args()
    output = args.output
    stage2._ensure_output(output)
    jev._log_candidates = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    jev._place_line = _place_line_with_extras  # type: ignore[method-assign]
    secret = stage2._bind_secret_if_needed()
    if not jev.SECRET_PATH.is_file():
        raise SystemExit("OpenRouter の資格情報が無く、Jev のオフライン評価を計測できない")
    spec = jev._load_spec()
    try:
        collected = stage2._collect_positions()
        pools: dict[str, list[Position]] = {name: [] for name in jev._STAGE_KEYS}
        for position in collected:
            if len(legal_places(position)) < 2:
                continue
            pools[jev._stage_of(position.board, spec)].append(position)
        for stage, bucket in pools.items():
            print(f"pool {stage}={len(bucket)}", flush=True)
        train_pos, hold_pos = _split_positions(pools, args.per_stage)
        print("prepare train", flush=True)
        train = [_prepare(position, spec) for position in train_pos]
        print("prepare holdout", flush=True)
        holdout = [_prepare(position, spec) for position in hold_pos]
        print("eval baseline train", flush=True)
        current = spec
        train_before = _evaluate_set(train, current, "baseline-train")
        hold_cache: dict[tuple[str, ...], list[_EvalRow]] = {}
        trials: list[dict[str, Any]] = []
        accepted: list[str] = []
        holdout_checks: list[dict[str, Any]] = []

        def hold_key(active: Sequence[str]) -> tuple[str, ...]:
            return tuple(active)

        hold_cache[hold_key(accepted)] = _evaluate_set(holdout, current, "baseline-hold")

        for variant in _variants():
            print(f"trial {variant.change}", flush=True)
            candidate = variant.apply(current)
            variant.install()
            try:
                train_after = _evaluate_set(train, candidate, f"{variant.change}-train")
                improved_train = _mean_loss(train_after) < _mean_loss(train_before)
                hold_before_rows: list[_EvalRow] | None = None
                hold_after_rows: list[_EvalRow] | None = None
                accepted_now = False
                if improved_train:
                    hold_before_rows = hold_cache[hold_key(accepted)]
                    hold_after_rows = _evaluate_set(
                        holdout, candidate, f"{variant.change}-hold"
                    )
                    accepted_now = _mean_loss(hold_after_rows) < _mean_loss(
                        hold_before_rows
                    )
                    holdout_checks.append(
                        {
                            "change": variant.change,
                            "mean_loss_before": _mean_loss(hold_before_rows),
                            "mean_loss_after": _mean_loss(hold_after_rows),
                            "improved": accepted_now,
                        }
                    )
                trials.append(
                    _trial_row(
                        variant.change,
                        train_before,
                        train_after,
                        accepted_now,
                        hold_before_rows,
                        hold_after_rows,
                    )
                )
                if accepted_now:
                    accepted.append(variant.change)
                    current = candidate
                    train_before = train_after
                    hold_cache[hold_key(accepted)] = hold_after_rows or []
                else:
                    variant.uninstall()
            except Exception:
                variant.uninstall()
                raise
            stage2._atomic_write(
                output,
                _payload(trials, accepted, {"n": len(holdout), "trials": holdout_checks}, args.per_stage, spec),
            )

        final_hold = hold_cache[hold_key(accepted)]
        original_hold = hold_cache[hold_key(())]
        holdout_summary = {
            "n": len(holdout),
            "mean_loss_baseline": _mean_loss(original_hold),
            "mean_loss_accepted": _mean_loss(final_hold),
            "improved": _mean_loss(final_hold) < _mean_loss(original_hold),
            "trials": holdout_checks,
        }
        stage2._atomic_write(
            output,
            _payload(trials, accepted, holdout_summary, args.per_stage, spec),
        )
    finally:
        _clear_extras()
        jev._place_line = _orig_place_line  # type: ignore[method-assign]
        if secret is not None:
            secret.unlink(missing_ok=True)
    payload = json.loads(output.read_text(encoding="utf-8"))
    print(
        f"wrote {output} accepted={payload['accepted_changes']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
