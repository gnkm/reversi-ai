#!/usr/bin/env python3
"""Jev 段階 2 の局面単位オフライン評価を書き出す。

対局ログ（カタログ個体の対局。SQLite があればそれも）から合法手が 2 手以上の
局面を序盤・中盤・終盤から集め、αβ の評価値を正解とする。
資格情報と課金が要る Jev 呼出しは CI に載せない。ホストで明示的に走らせる。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from random import Random
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STRATEGY_SRC = ROOT / "strategy" / "src"
if str(STRATEGY_SRC) not in sys.path:
    sys.path.insert(0, str(STRATEGY_SRC))

from reversi.agents import catalog, jev, minimax  # noqa: E402
from reversi.api import persist  # noqa: E402
from reversi.engine.board import Color, Square, Stone  # noqa: E402
from reversi.engine.rules import (  # noqa: E402
    IllegalMoveError,
    PassMove,
    Place,
    Position,
    initial_position,
    is_over,
    legal_moves,
    legal_places,
    play,
)

Chooser = Callable[[Position], Place | None]

OUTPUT = Path(__file__).resolve().parent / "jev-stage2.json"
SEARCH_DEPTH = 4
EXACT_EMPTY = 8
BLUNDER_LOSS = 50
PER_STAGE = 6
CONFIDENCE_EDGES = (0.0, 0.2, 0.4, 0.6, 0.8, 1.01)
_NEG_INF = -10_000
_POS_INF = 10_000
GAME_PAIRS = (
    ("most_flips", "positional"),
    ("positional", "opening"),
    ("opening", "minimax"),
    ("most_flips", "minimax"),
    ("positional", "minimax"),
    ("most_flips", "opening"),
)


@dataclass(frozen=True, slots=True)
class _Sample:
    position: Position
    stage: str
    empties: int
    values: dict[str, int]
    best_value: int
    code_best: str
    jev_all: str
    shortlist: str
    jev_all_confidence: float
    shortlist_confidence: float | None
    shortlist_keys: tuple[str, ...]


def _bind_secret_if_needed() -> Path | None:
    if jev.SECRET_PATH.is_file() and jev.SECRET_PATH.read_text(encoding="utf-8").strip():
        return None
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        return None
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - 評価中は残す
        prefix="openrouter-api-key-",
        suffix=".txt",
        delete=False,
    )
    handle.write(key.encode("utf-8"))
    handle.close()
    path = Path(handle.name)
    jev.SECRET_PATH = path
    return path


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


def _chooser(specimen_id: str) -> Chooser:
    def choose(position: Position) -> Place | None:
        return catalog.choose_move(specimen_id, position)

    return choose


def _key_of(position: Position) -> tuple[str, tuple[tuple[str, ...], ...]]:
    cells = tuple(
        tuple(position.board.stone_at(square).value for square in row)
        for row in (
            tuple(Square(file=file, rank=rank) for file in range(8))
            for rank in range(8)
        )
    )
    return position.side_to_move.value, cells


def _collect_from_game(black: Chooser, white: Chooser) -> list[Position]:
    found: list[Position] = []
    position = initial_position()
    while not is_over(position):
        places = legal_places(position)
        if not places:
            position = play(position, PassMove())
            continue
        if len(places) >= 2:
            found.append(position)
        chooser = black if position.side_to_move is Color.BLACK else white
        move = chooser(position)
        if not isinstance(move, Place):
            raise RuntimeError("着手不能")
        position = play(position, move)
    return found


def _collect_from_sqlite() -> list[Position]:
    if not persist.DEFAULT_DB_PATH.is_file():
        return []
    found: list[Position] = []
    for game in persist.load():
        position = initial_position()
        for raw in game.moves:
            places = legal_places(position)
            if not places:
                if raw.get("type") != "pass":
                    break
                position = play(position, PassMove())
                continue
            if len(places) >= 2:
                found.append(position)
            if raw.get("type") != "place":
                break
            square_text = raw.get("square")
            if not isinstance(square_text, str):
                break
            try:
                position = play(position, Place(Square.parse(square_text)))
            except (ValueError, IllegalMoveError):
                break
    return found


def _collect_positions() -> list[Position]:
    found: list[Position] = _collect_from_sqlite()
    for black_id, white_id in GAME_PAIRS:
        found.extend(_collect_from_game(_chooser(black_id), _chooser(white_id)))
        found.extend(_collect_from_game(_chooser(white_id), _chooser(black_id)))
    unique: list[Position] = []
    seen: set[tuple[str, tuple[tuple[str, ...], ...]]] = set()
    for position in found:
        key = _key_of(position)
        if key in seen:
            continue
        seen.add(key)
        unique.append(position)
    return unique


def _search_limit(position: Position) -> int:
    if jev._empty_count(position.board) <= EXACT_EMPTY:
        return 64
    return SEARCH_DEPTH


def _is_leaf(position: Position, depth: int, limit: int) -> bool:
    return depth >= limit or is_over(position)


def _max_value(
    position: Position,
    depth: int,
    root: Color,
    alpha: int,
    beta: int,
    limit: int,
) -> int:
    if _is_leaf(position, depth, limit):
        return minimax.leaf_score(position.board, root)
    value = _NEG_INF
    moves = legal_moves(position)
    if not moves:
        return minimax.leaf_score(position.board, root)
    for move in moves:
        child = _min_value(play(position, move), depth + 1, root, alpha, beta, limit)
        value = max(value, child)
        alpha = max(alpha, value)
        if alpha >= beta:
            break
    return value


def _min_value(
    position: Position,
    depth: int,
    root: Color,
    alpha: int,
    beta: int,
    limit: int,
) -> int:
    if _is_leaf(position, depth, limit):
        return minimax.leaf_score(position.board, root)
    value = _POS_INF
    moves = legal_moves(position)
    if not moves:
        return minimax.leaf_score(position.board, root)
    for move in moves:
        child = _max_value(play(position, move), depth + 1, root, alpha, beta, limit)
        value = min(value, child)
        beta = min(beta, value)
        if alpha >= beta:
            break
    return value


def _move_values(position: Position) -> dict[str, int]:
    root = position.side_to_move
    limit = _search_limit(position)
    values: dict[str, int] = {}
    for square in legal_places(position):
        child = play(position, Place(square))
        values[square.algebraic] = _min_value(
            child, 1, root, _NEG_INF, _POS_INF, limit
        )
    return values


def _board_rows(position: Position) -> list[str]:
    mapping = {Stone.EMPTY: ".", Stone.BLACK: "B", Stone.WHITE: "W"}
    rows: list[str] = []
    for rank in range(7, -1, -1):
        rows.append(
            "".join(
                mapping[position.board.stone_at(Square(file=file, rank=rank))]
                for file in range(8)
            )
        )
    return rows


def _sample_stage(
    pools: Mapping[str, Sequence[Position]],
    per_stage: int,
    rng: Random,
) -> list[Position]:
    picked: list[Position] = []
    for stage in jev._STAGE_KEYS:
        bucket = list(pools[stage])
        rng.shuffle(bucket)
        picked.extend(bucket[:per_stage])
    return picked


def _evaluate_position(position: Position, spec: jev._Spec) -> _Sample:
    places = legal_places(position)
    stage = jev._stage_of(position.board, spec)
    metrics = jev._after_metrics(position, places, spec)
    scores = jev._code_scores(places, metrics, spec, stage)
    code_best, shortlist = jev._shortlist(places, scores, spec)
    values = _move_values(position)
    best_value = max(values.values())
    parsed_all = jev._ask_jev(position, places, spec)
    jev_all = jev._pick_choice(parsed_all, places)
    if spec.margin == 0.0 or len(shortlist) == 1:
        short_move = code_best
        short_conf: float | None = None
    else:
        parsed_short = jev._ask_jev(position, shortlist, spec)
        short_move = jev._select_square(position, places, parsed_short, spec)
        short_conf = parsed_short.confidence
    return _Sample(
        position=position,
        stage=stage,
        empties=jev._empty_count(position.board),
        values=values,
        best_value=best_value,
        code_best=code_best.algebraic,
        jev_all=jev_all.algebraic,
        shortlist=short_move.algebraic,
        jev_all_confidence=parsed_all.confidence,
        shortlist_confidence=short_conf,
        shortlist_keys=tuple(square.algebraic for square in shortlist),
    )


def _loss(sample: _Sample, algebraic: str) -> int:
    return sample.best_value - sample.values[algebraic]


def _method_row(name: str, samples: Sequence[_Sample], pick: Callable[[_Sample], str]) -> dict[str, Any]:
    n = len(samples)
    losses = [_loss(sample, pick(sample)) for sample in samples]
    matches = sum(
        1
        for sample, loss in zip(samples, losses, strict=True)
        if loss == 0
    )
    blunders = sum(1 for loss in losses if loss >= BLUNDER_LOSS)
    return {
        "name": name,
        "n": n,
        "match_rate": matches / n if n else 0.0,
        "mean_loss": sum(losses) / n if n else 0.0,
        "blunder_rate": blunders / n if n else 0.0,
    }


def _confidence_bins(samples: Sequence[_Sample]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, lo in enumerate(CONFIDENCE_EDGES[:-1]):
        hi = CONFIDENCE_EDGES[index + 1]
        subset = [
            sample
            for sample in samples
            if lo <= sample.jev_all_confidence < hi
        ]
        n = len(subset)
        if n == 0:
            rows.append(
                {
                    "lo": lo,
                    "hi": min(hi, 1.0),
                    "n": 0,
                    "match_rate": 0.0,
                    "mean_loss": 0.0,
                }
            )
            continue
        losses = [_loss(sample, sample.jev_all) for sample in subset]
        matches = sum(1 for loss in losses if loss == 0)
        rows.append(
            {
                "lo": lo,
                "hi": min(hi, 1.0),
                "n": n,
                "match_rate": matches / n,
                "mean_loss": sum(losses) / n,
            }
        )
    return rows


def _payload(
    samples: Sequence[_Sample], spec: jev._Spec, per_stage: int
) -> dict[str, Any]:
    methods = [
        _method_row("code_best", samples, lambda sample: sample.code_best),
        _method_row("jev_all", samples, lambda sample: sample.jev_all),
        _method_row("shortlist", samples, lambda sample: sample.shortlist),
    ]
    return {
        "recorded_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
        "protocol": {
            "positions_per_stage": per_stage,
            "search_depth": SEARCH_DEPTH,
            "exact_empty": EXACT_EMPTY,
            "blunder_loss": BLUNDER_LOSS,
            "confidence_edges": list(CONFIDENCE_EDGES[:-1]) + [1.0],
            "label": "alphabeta",
            "wthor": False,
            "selection": {
                "shortlist_size": spec.shortlist_size,
                "margin": spec.margin,
                "confidence_threshold": spec.confidence_threshold,
            },
            "notes": [
                "対局ログはカタログ個体同士の対局と、あれば data/games.sqlite から集めた。",
                "合法手が 2 手以上の局面を序盤・中盤・終盤から偏りなくサンプリングした。",
                "正解は手元の αβ（深さ 4。空きマスが 8 以下なら終局まで）の評価値。",
                "WTHOR の手は正解に使っていない。",
                "code_best はコード評価の最善手。jev_all は全合法手 Choice。shortlist は絞り込み。",
                "confidence 区間は jev_all の答え。資格情報と課金が要る呼出しは CI に載せない。",
            ],
        },
        "methods": methods,
        "confidence_bins": _confidence_bins(samples),
        "positions": [
            {
                "stage": sample.stage,
                "empties": sample.empties,
                "side_to_move": sample.position.side_to_move.value,
                "board": _board_rows(sample.position),
                "best_value": sample.best_value,
                "code_best": sample.code_best,
                "jev_all": sample.jev_all,
                "shortlist": sample.shortlist,
                "shortlist_keys": list(sample.shortlist_keys),
                "jev_all_confidence": sample.jev_all_confidence,
                "shortlist_confidence": sample.shortlist_confidence,
                "code_best_loss": _loss(sample, sample.code_best),
                "jev_all_loss": _loss(sample, sample.jev_all),
                "shortlist_loss": _loss(sample, sample.shortlist),
            }
            for sample in samples
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Jev 段階 2 のオフライン評価を書く")
    parser.add_argument("--output", type=Path, default=OUTPUT, help="書き出す JSON")
    parser.add_argument(
        "--per-stage",
        type=int,
        default=PER_STAGE,
        help="序盤・中盤・終盤それぞれの局面数",
    )
    args = parser.parse_args()
    output = args.output
    _ensure_output(output)
    jev._log_candidates = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    secret = _bind_secret_if_needed()
    if not jev.SECRET_PATH.is_file():
        raise SystemExit("OpenRouter の資格情報が無く、Jev の 2 方式を計測できない")
    spec = jev._load_spec()
    rng = Random(0)
    try:
        collected = _collect_positions()
        pools: dict[str, list[Position]] = {name: [] for name in jev._STAGE_KEYS}
        for position in collected:
            if len(legal_places(position)) < 2:
                continue
            pools[jev._stage_of(position.board, spec)].append(position)
        for stage, bucket in pools.items():
            print(f"pool {stage}={len(bucket)}", flush=True)
            if len(bucket) < args.per_stage:
                raise SystemExit(
                    f"{stage} の局面が足りません: {len(bucket)} < {args.per_stage}"
                )
        selected = _sample_stage(pools, args.per_stage, rng)
        samples: list[_Sample] = []
        for index, position in enumerate(selected, start=1):
            print(
                f"eval {index}/{len(selected)} "
                f"{jev._stage_of(position.board, spec)} "
                f"empty={jev._empty_count(position.board)}",
                flush=True,
            )
            samples.append(_evaluate_position(position, spec))
        _atomic_write(output, _payload(samples, spec, args.per_stage))
    finally:
        if secret is not None:
            secret.unlink(missing_ok=True)
    payload = json.loads(output.read_text(encoding="utf-8"))
    names = [row["name"] for row in payload["methods"]]
    print(f"wrote {output} methods={names}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
