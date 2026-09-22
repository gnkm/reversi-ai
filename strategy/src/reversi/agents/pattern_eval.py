"""パターン特徴（N-tuple）の評価。対局時に NN も OpenRouter も使わない。

盤の決まったマス組ごとに、黒・白・空の組み合わせを 1 つの重みにする。
8 回対称で一致する組は同じ表を共有する。段階は石数で 10 個。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from reversi.engine.board import BOARD_SIZE, Board, Color, Stone
from reversi.engine.rules import count_places

N_STAGES = 10
STAGE_WIDTH = 6
NEIGHBOR_SMOOTH = 0.5
SCALAR_NAMES = ("mobility", "frontier", "parity")
SCALAR_SCALE = 8.0
ALGORITHM = "pattern_td_lambda"
# 保存時にこれ未満は 0 とみなす。JSON を疎にする。
WEIGHT_EPSILON = 5e-7

__all__ = [
    "ALGORITHM",
    "NEIGHBOR_SMOOTH",
    "N_STAGES",
    "PATTERN_SPECS",
    "SCALAR_NAMES",
    "STAGE_WIDTH",
    "PatternPolicy",
    "PatternSpec",
    "active_count",
    "analyze",
    "black_value",
    "dump_policy",
    "load_policy",
    "perspective_value",
    "stage_disc_span",
    "stage_of",
    "xc_table",
    "zero_policy",
]


def _transform(file: int, rank: int, rotations: int, mirrored: bool) -> tuple[int, int]:
    """回転のあと、必要なら左右を反転する。段階 2 の対称と同じ向き。"""
    last = BOARD_SIZE - 1
    next_file, next_rank = file, rank
    for _ in range(rotations):
        next_file, next_rank = next_rank, last - next_file
    if mirrored:
        next_file = last - next_file
    return next_file, next_rank


def _label(file: int, rank: int) -> str:
    return f"{'abcdefgh'[file]}{'12345678'[rank]}"


def _instances(squares: tuple[tuple[int, int], ...]) -> tuple[tuple[int, ...], ...]:
    """同じマス集合は 1 回だけ。順序は変換後の並びで、重み表の添字になる。"""
    found: list[tuple[int, ...]] = []
    seen: set[frozenset[int]] = set()
    for rotations in range(4):
        for mirrored in (False, True):
            mapped: list[int] = []
            for file, rank in squares:
                next_file, next_rank = _transform(file, rank, rotations, mirrored)
                mapped.append(next_rank * BOARD_SIZE + next_file)
            key = frozenset(mapped)
            if key in seen:
                continue
            seen.add(key)
            found.append(tuple(mapped))
    return tuple(found)


def _line(
    start_file: int,
    start_rank: int,
    file_step: int,
    rank_step: int,
    length: int,
) -> tuple[tuple[int, int], ...]:
    return tuple(
        (start_file + file_step * offset, start_rank + rank_step * offset)
        for offset in range(length)
    )


def _canonical_patterns() -> tuple[tuple[str, tuple[tuple[int, int], ...]], ...]:
    """代表の向き。辺＋2X、角 3×3、角 2×5、斜め、辺から 2〜4 列目。"""
    edge = tuple((file, 0) for file in range(BOARD_SIZE)) + ((1, 1), (6, 1))
    corner_3x3 = tuple((file, rank) for rank in range(3) for file in range(3))
    corner_2x5 = tuple((file, rank) for rank in range(2) for file in range(5))
    patterns: list[tuple[str, tuple[tuple[int, int], ...]]] = [
        ("edge_2x", edge),
        ("corner_3x3", corner_3x3),
        ("corner_2x5", corner_2x5),
    ]
    diagonals = (
        (8, "diag_8"),
        (7, "diag_7"),
        (6, "diag_6"),
        (5, "diag_5"),
        (4, "diag_4"),
    )
    for length, name in diagonals:
        patterns.append((name, _line(BOARD_SIZE - length, 0, 1, 1, length)))
    for distance, name in ((1, "line_2"), (2, "line_3"), (3, "line_4")):
        patterns.append((name, _line(0, distance, 1, 0, BOARD_SIZE)))
    return tuple(patterns)


@dataclass(frozen=True, slots=True)
class PatternSpec:
    """1 種類のマス組。instances は共有する重み表を引く盤上の位置。"""

    name: str
    labels: tuple[str, ...]
    coords: np.ndarray
    powers: np.ndarray
    size: int

    @property
    def n_instances(self) -> int:
        return int(self.coords.shape[0])


def _build_specs() -> tuple[PatternSpec, ...]:
    specs: list[PatternSpec] = []
    for name, squares in _canonical_patterns():
        instances = _instances(squares)
        length = len(squares)
        specs.append(
            PatternSpec(
                name=name,
                labels=tuple(_label(file, rank) for file, rank in squares),
                coords=np.asarray(instances, dtype=np.int16),
                powers=np.asarray(
                    [3**index for index in range(length)], dtype=np.int32
                ),
                size=3**length,
            )
        )
    return tuple(specs)


PATTERN_SPECS = _build_specs()
_SPEC_BY_NAME = {spec.name: spec for spec in PATTERN_SPECS}


def active_count() -> int:
    """1 局面で立つ項目。組の出現回数と、スカラー 3 つと切片。"""
    return sum(spec.n_instances for spec in PATTERN_SPECS) + len(SCALAR_NAMES) + 1


def stage_of(discs: int) -> int:
    """石数 4 から 6 個ずつ。最後の段階は 58〜64 をまとめる。"""
    if discs < 4:
        return 0
    index = (discs - 4) // STAGE_WIDTH
    if index >= N_STAGES:
        return N_STAGES - 1
    return index


def stage_disc_span(stage: int) -> tuple[int, int]:
    if not 0 <= stage < N_STAGES:
        raise ValueError("段階は 0 から 9 までです")
    start = 4 + stage * STAGE_WIDTH
    if stage == N_STAGES - 1:
        return start, 64
    return start, start + STAGE_WIDTH - 1


def _index_of(states: tuple[int, ...]) -> int:
    index = 0
    power = 1
    for state in states:
        index += state * power
        power *= 3
    return index


# 辺＋2X の並び: a1 b1 c1 d1 e1 f1 g1 h1 b2 g2。b2 が a1 の X。
EDGE_X_BLACK_CORNER_EMPTY = _index_of((0, 0, 0, 0, 0, 0, 0, 0, 1, 0))
EDGE_X_BLACK_CORNER_BLACK = _index_of((1, 0, 0, 0, 0, 0, 0, 0, 1, 0))
EDGE_X_WHITE_CORNER_EMPTY = _index_of((0, 0, 0, 0, 0, 0, 0, 0, 2, 0))
EDGE_X_WHITE_CORNER_WHITE = _index_of((2, 0, 0, 0, 0, 0, 0, 0, 2, 0))
# 角 3×3 は a1 から行優先。b1 が C、b2 が X。
CORNER_C_BLACK_CORNER_EMPTY = _index_of((0, 1, 0, 0, 0, 0, 0, 0, 0))
CORNER_C_BLACK_CORNER_BLACK = _index_of((1, 1, 0, 0, 0, 0, 0, 0, 0))
CORNER_C_WHITE_CORNER_EMPTY = _index_of((0, 2, 0, 0, 0, 0, 0, 0, 0))
CORNER_C_WHITE_CORNER_WHITE = _index_of((2, 2, 0, 0, 0, 0, 0, 0, 0))


@dataclass(slots=True)
class PatternPolicy:
    """段階ごとの参照表。価値は黒有利が正。"""

    weights: dict[str, np.ndarray]
    scalars: np.ndarray
    bias: np.ndarray
    reward: str = "win_loss"
    lam: float = 0.7
    games: int = 0

    def __post_init__(self) -> None:
        _check_policy(self)


def _check_policy(policy: PatternPolicy) -> None:
    if policy.reward not in {"win_loss", "stone_diff"}:
        raise ValueError("reward は win_loss か stone_diff です")
    if not math.isfinite(policy.lam) or not 0.0 <= policy.lam <= 1.0:
        raise ValueError("λ は 0 以上 1 以下の有限値です")
    if policy.scalars.shape != (N_STAGES, len(SCALAR_NAMES)):
        raise ValueError("スカラー重みの形が段階数と合いません")
    if policy.bias.shape != (N_STAGES,):
        raise ValueError("切片の長さが段階数と合いません")
    if not np.isfinite(policy.scalars).all() or not np.isfinite(policy.bias).all():
        raise ValueError("スカラー重みと切片は有限値でなければなりません")
    for spec in PATTERN_SPECS:
        table = policy.weights.get(spec.name)
        if table is None or table.shape != (N_STAGES, spec.size):
            raise ValueError(f"{spec.name} の重み表の形が合いません")
        if not np.isfinite(table).all():
            raise ValueError(f"{spec.name} の重みは有限値でなければなりません")


def zero_policy() -> PatternPolicy:
    weights = {
        spec.name: np.zeros((N_STAGES, spec.size), dtype=np.float64)
        for spec in PATTERN_SPECS
    }
    return PatternPolicy(
        weights=weights,
        scalars=np.zeros((N_STAGES, len(SCALAR_NAMES)), dtype=np.float64),
        bias=np.zeros(N_STAGES, dtype=np.float64),
    )


_PACK = np.empty(BOARD_SIZE * BOARD_SIZE, dtype=np.int16)
_DELTAS = (
    (1, 0),
    (-1, 0),
    (0, 1),
    (0, -1),
    (1, 1),
    (1, -1),
    (-1, 1),
    (-1, -1),
)


def _pack(board: Board) -> np.ndarray:
    """空 0、黒 1、白 2。呼び出しのあいだだけ有効なバッファを返す。"""
    pack = _PACK
    index = 0
    for row in board.cells:
        for stone in row:
            if stone is Stone.EMPTY:
                pack[index] = 0
            elif stone is Stone.BLACK:
                pack[index] = 1
            else:
                pack[index] = 2
            index += 1
    return pack


def _adjacent_empty(pack: np.ndarray, file: int, rank: int) -> bool:
    for file_step, rank_step in _DELTAS:
        next_file = file + file_step
        next_rank = rank + rank_step
        if (
            0 <= next_file < BOARD_SIZE
            and 0 <= next_rank < BOARD_SIZE
            and pack[next_rank * BOARD_SIZE + next_file] == 0
        ):
            return True
    return False


def _frontier_feature(pack: np.ndarray) -> float:
    black = 0
    white = 0
    for index, state in enumerate(pack.tolist()):
        if state == 0:
            continue
        if not _adjacent_empty(pack, index % BOARD_SIZE, index // BOARD_SIZE):
            continue
        if state == 1:
            black += 1
        else:
            white += 1
    return (black - white) / SCALAR_SCALE


def _mobility_feature(board: Board) -> float:
    black = count_places(board, Color.BLACK)
    white = count_places(board, Color.WHITE)
    return (black - white) / SCALAR_SCALE


def _parity_feature(empty: int, side: Color) -> float:
    black_takes_last = (empty % 2 == 1) == (side is Color.BLACK)
    if black_takes_last:
        return 1.0
    return -1.0


def _pattern_total(
    pack: np.ndarray,
    stage: int,
    policy: PatternPolicy,
    hits: dict[tuple[str, int], float] | None,
) -> float:
    total = 0.0
    for spec in PATTERN_SPECS:
        states = pack[spec.coords]
        indices = (states * spec.powers).sum(axis=1)
        picked = policy.weights[spec.name][stage, indices]
        total += float(picked.sum())
        if hits is None:
            continue
        for index in indices.tolist():
            key = (spec.name, int(index))
            hits[key] = hits.get(key, 0.0) + 1.0
    return total


def _scalar_values(
    board: Board, pack: np.ndarray, side: Color
) -> tuple[float, float, float]:
    empty = int(np.count_nonzero(pack == 0))
    return (
        _mobility_feature(board),
        _frontier_feature(pack),
        _parity_feature(empty, side),
    )


def analyze(
    board: Board,
    side: Color,
    policy: PatternPolicy,
) -> tuple[int, tuple[tuple[str, int, float], ...], float]:
    """段階、活性な項目（名前、添字、勾配）、黒有利の価値。"""
    pack = _pack(board)
    stage = stage_of(int(np.count_nonzero(pack)))
    grouped: dict[tuple[str, int], float] = {}
    total = float(policy.bias[stage]) + _pattern_total(pack, stage, policy, grouped)
    scalars = _scalar_values(board, pack, side)
    hits = [("bias", 0, 1.0)]
    hits.extend((name, index, gradient) for (name, index), gradient in grouped.items())
    for index, feature in enumerate(scalars):
        total += float(policy.scalars[stage, index]) * feature
        hits.append(("scalar", index, feature))
    return stage, tuple(hits), total


def black_value(board: Board, side: Color, policy: PatternPolicy) -> float:
    """黒有利が正。パターンの参照表とスカラーを足す。192 次元の配置特徴ではない。"""
    pack = _pack(board)
    stage = stage_of(int(np.count_nonzero(pack)))
    total = float(policy.bias[stage]) + _pattern_total(pack, stage, policy, None)
    scalars = np.asarray(_scalar_values(board, pack, side), dtype=np.float64)
    return total + float(policy.scalars[stage] @ scalars)


def perspective_value(board: Board, color: Color, policy: PatternPolicy) -> float:
    """手番 color から見た価値。白番は黒有利の v を符号反転する。"""
    value = black_value(board, color, policy)
    if color is Color.BLACK:
        return value
    return -value


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _changed(left: float, right: float) -> bool:
    return _sign(left) * _sign(right) < 0


def _xc_row(policy: PatternPolicy, stage: int) -> dict[str, Any]:
    start, end = stage_disc_span(stage)
    edge = policy.weights["edge_2x"]
    corner = policy.weights["corner_3x3"]
    x_empty = float(edge[stage, EDGE_X_BLACK_CORNER_EMPTY])
    x_owned = float(edge[stage, EDGE_X_BLACK_CORNER_BLACK])
    c_empty = float(corner[stage, CORNER_C_BLACK_CORNER_EMPTY])
    c_owned = float(corner[stage, CORNER_C_BLACK_CORNER_BLACK])
    return {
        "stage": stage,
        "discs_from": start,
        "discs_to": end,
        "x_black_corner_empty": x_empty,
        "x_black_corner_black": x_owned,
        "x_white_corner_empty": float(edge[stage, EDGE_X_WHITE_CORNER_EMPTY]),
        "x_white_corner_white": float(edge[stage, EDGE_X_WHITE_CORNER_WHITE]),
        "x_sign_changes": _changed(x_empty, x_owned),
        "c_black_corner_empty": c_empty,
        "c_black_corner_black": c_owned,
        "c_white_corner_empty": float(corner[stage, CORNER_C_WHITE_CORNER_EMPTY]),
        "c_white_corner_white": float(corner[stage, CORNER_C_WHITE_CORNER_WHITE]),
        "c_sign_changes": _changed(c_empty, c_owned),
    }


def xc_table(policy: PatternPolicy) -> dict[str, Any]:
    """X と C の重みが、角の空きと自石で符号を変えるかを表から読む。"""
    rows = [_xc_row(policy, stage) for stage in range(N_STAGES)]
    return {
        "encoding": "empty=0, black=1, white=2, index=sum state_i * 3^i",
        "edge_2x_squares": list(_SPEC_BY_NAME["edge_2x"].labels),
        "corner_3x3_squares": list(_SPEC_BY_NAME["corner_3x3"].labels),
        "x_note": "辺＋2X の b2 を黒にし、a1 が空のときと黒のときを比べる。他のマスは空。",
        "c_note": "角 3×3 の b1 を黒にし、a1 が空のときと黒のときを比べる。他のマスは空。",
        "stages": rows,
        "x_sign_changes": any(row["x_sign_changes"] for row in rows),
        "c_sign_changes": any(row["c_sign_changes"] for row in rows),
    }


def _triples(table: np.ndarray) -> list[list[float]]:
    rows: list[list[float]] = []
    stages, indices = np.nonzero(np.abs(table) >= WEIGHT_EPSILON)
    for stage, index in zip(stages.tolist(), indices.tolist(), strict=True):
        rows.append([int(stage), int(index), round(float(table[stage, index]), 6)])
    return rows


def _payload(policy: PatternPolicy, extra: dict[str, Any] | None) -> dict[str, Any]:
    patterns = {
        spec.name: {
            "length": len(spec.labels),
            "size": spec.size,
            "squares": list(spec.labels),
            "nonzero": _triples(policy.weights[spec.name]),
        }
        for spec in PATTERN_SPECS
    }
    body: dict[str, Any] = {
        "algorithm": ALGORITHM,
        "reward": policy.reward,
        "lambda": policy.lam,
        "stages": N_STAGES,
        "stage_width": STAGE_WIDTH,
        "neighbor_smooth": NEIGHBOR_SMOOTH,
        "scalar_names": list(SCALAR_NAMES),
        "scalar_scale": SCALAR_SCALE,
        "games": policy.games,
        "scalars": [
            [round(float(value), 6) for value in row] for row in policy.scalars.tolist()
        ],
        "bias": [round(float(value), 6) for value in policy.bias.tolist()],
        "patterns": patterns,
    }
    if extra:
        body.update(extra)
    return body


def dump_policy(
    path: Path,
    policy: PatternPolicy,
    *,
    extra: dict[str, Any] | None = None,
) -> None:
    """疎な JSON を書く。0 に近い重みは落とす。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(
        _payload(policy, extra), ensure_ascii=False, separators=(",", ":")
    )
    path.write_text(text + "\n", encoding="utf-8")


def _scatter(spec: PatternSpec, rows: object) -> np.ndarray:
    table = np.zeros((N_STAGES, spec.size), dtype=np.float64)
    if not isinstance(rows, list):
        raise TypeError(f"{spec.name} の nonzero は配列でなければなりません")
    for row in rows:
        if not isinstance(row, list) or len(row) != 3:
            raise TypeError(f"{spec.name} の非零は [段階, 添字, 重み] です")
        stage, index, weight = int(row[0]), int(row[1]), float(row[2])
        if not 0 <= stage < N_STAGES or not 0 <= index < spec.size:
            raise ValueError(f"{spec.name} の非零が範囲外です")
        if not math.isfinite(weight):
            raise ValueError(f"{spec.name} の重みは有限値でなければなりません")
        table[stage, index] = weight
    return table


def _pattern_rows(patterns: dict[str, Any], spec: PatternSpec) -> object:
    block = patterns.get(spec.name)
    if not isinstance(block, dict):
        raise TypeError(f"{spec.name} の定義がありません")
    return block.get("nonzero")


def load_policy(path: Path) -> PatternPolicy:
    """対局用のパターン重みを JSON から読む。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("パターン重みの根はオブジェクトでなければなりません")
    if raw.get("algorithm") != ALGORITHM:
        raise ValueError("algorithm は pattern_td_lambda でなければなりません")
    patterns = raw.get("patterns")
    scalars = raw.get("scalars")
    bias = raw.get("bias")
    if not isinstance(patterns, dict):
        raise TypeError("patterns が必要です")
    if not isinstance(scalars, list) or not isinstance(bias, list):
        raise TypeError("scalars と bias が必要です")
    weights = {
        spec.name: _scatter(spec, _pattern_rows(patterns, spec))
        for spec in PATTERN_SPECS
    }
    return PatternPolicy(
        weights=weights,
        scalars=np.asarray(scalars, dtype=np.float64),
        bias=np.asarray(bias, dtype=np.float64),
        reward=str(raw.get("reward", "win_loss")),
        lam=float(raw.get("lambda", 0.7)),
        games=int(raw.get("games", 0)),
    )
