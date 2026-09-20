"""OpenRouter の Jev で合法手を選ぶ個体。言葉の事実の Choice と着手後評価を合成する。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from random import Random
from string import Formatter
from typing import Any

from openrouter import OpenRouter
from openrouter.utils.retries import BackoffStrategy, RetryConfig

from reversi.agents.position_table import score_at
from reversi.agents.prompt import PROMPTS_DIR, PromptFileError, load_json
from reversi.engine.board import Board, Color, Square, Stone, all_squares
from reversi.engine.rules import Place, Position, apply_place, flips_for, legal_places

MODEL_ID = "typesafe/jev-1.13"
SPECIMEN_ID = "jev"
CATEGORY = "generative_ai"
DISPLAY_NAME = "生成 AI (Jev)"
DESCRIPTION = (
    "OpenRouter 上の Jev を Decisions API で呼び、コードが言葉にした合法手を"
    "Choice で比べさせ、着手後の盤の点数と合成する。"
    "対局中に WTHOR は参照しない。"
)
DECISIONS_SERVER = "https://openrouter.ai"
SECRET_PATH = Path("/run/secrets/openrouter-api-key")
PROMPT_PATH = PROMPTS_DIR / "jev.json"
# Hono の戦略中継は 60 秒。それより先に失敗させ、ロックを返す。
DECISIONS_TIMEOUT_MS = 55_000
_NO_RETRY = RetryConfig("none", BackoffStrategy(0, 0, 1.0, 0), False)
_METRIC_KEYS = ("position", "mobility", "material", "corners")
_STAGE_KEYS = ("opening", "midgame", "endgame")
_KIND_KEYS = ("corner", "x", "c", "edge", "interior")
_AMOUNT_KEYS = ("few", "some", "many")
_YES_NO_KEYS = ("true", "false")
_SIDE_KEYS = ("black", "white")
_PLACE_FIELDS = ("kind", "takes_corner", "gives_corner", "opponent_places", "flips")
_BOARD_CORNERS = frozenset({"a1", "h1", "a8", "h8"})

__all__ = [
    "CATEGORY",
    "DECISIONS_SERVER",
    "DECISIONS_TIMEOUT_MS",
    "DESCRIPTION",
    "DISPLAY_NAME",
    "MODEL_ID",
    "PROMPT_PATH",
    "SECRET_PATH",
    "SPECIMEN_ID",
    "ExternalModelError",
    "choose_move",
    "read_secret",
]


class ExternalModelError(RuntimeError):
    """外部モデルの呼出し失敗。着手は採用しない。"""


@dataclass(frozen=True, slots=True)
class _Spec:
    objective: str
    question_id: str
    instructions: str
    place_line: str
    kinds: dict[str, frozenset[str]]
    kind_words: dict[str, str]
    yes_no: dict[str, str]
    amounts: dict[str, str]
    stages: dict[str, str]
    sides: dict[str, str]
    empty_buckets: dict[str, tuple[int, int]]
    opponent_buckets: dict[str, tuple[int, int]]
    flip_buckets: dict[str, tuple[int, int]]
    w_jev: float
    w_code: float
    w_confidence: float
    metric_weights: dict[str, float]
    scales: dict[str, float]
    stage_weights: dict[str, dict[str, float]]


@dataclass(frozen=True, slots=True)
class _Parsed:
    probabilities: dict[str, float]
    confidence: float


@dataclass(frozen=True, slots=True)
class _Metrics:
    position: float
    mobility: float
    material: float
    corners: float


def read_secret(path: Path | None = None) -> str:
    """`/run/secrets/openrouter-api-key` だけを読む。環境変数は見ない。"""
    target = SECRET_PATH if path is None else path
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise ExternalModelError("OpenRouter の資格情報を読めません") from exc
    key = raw.strip()
    if not key:
        raise ExternalModelError("OpenRouter の資格情報が空です")
    return key


def _fail_spec(exc: Exception | None = None) -> ExternalModelError:
    err = ExternalModelError("着手指示が不正です")
    if exc is not None:
        err.__cause__ = exc
    return err


def _text_field(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _fail_spec()
    return value.strip()


def _mapping_field(raw: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict) or not value:
        raise _fail_spec()
    return value


def _finite_float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _fail_spec()
    number = float(value)
    if not isfinite(number):
        raise _fail_spec()
    return number


def _float_map(raw: Mapping[str, Any], keys: Sequence[str]) -> dict[str, float]:
    if set(raw) != set(keys):
        raise _fail_spec()
    return {key: _finite_float(raw[key]) for key in keys}


def _word_map(raw: Mapping[str, Any], keys: Sequence[str]) -> dict[str, str]:
    if set(raw) != set(keys):
        raise _fail_spec()
    return {key: _text_field(raw, key) for key in keys}


def _int_pair(raw: object) -> tuple[int, int]:
    if not isinstance(raw, list) or len(raw) != 2:
        raise _fail_spec()
    lo, hi = raw
    if isinstance(lo, bool) or isinstance(hi, bool):
        raise _fail_spec()
    if not isinstance(lo, int) or not isinstance(hi, int):
        raise _fail_spec()
    if lo > hi:
        raise _fail_spec()
    return lo, hi


def _bucket_map(raw: Mapping[str, Any], keys: Sequence[str]) -> dict[str, tuple[int, int]]:
    if set(raw) != set(keys):
        raise _fail_spec()
    return {key: _int_pair(raw[key]) for key in keys}


def _require_cover(buckets: Mapping[str, tuple[int, int]], low: int, high: int) -> None:
    for value in range(low, high + 1):
        hits = [name for name, (lo, hi) in buckets.items() if lo <= value <= hi]
        if len(hits) != 1:
            raise _fail_spec()


def _algebraic_set(raw: object) -> frozenset[str]:
    if not isinstance(raw, list) or not raw:
        raise _fail_spec()
    names: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise _fail_spec()
        try:
            parsed = Square.parse(item)
        except ValueError as exc:
            raise _fail_spec(exc) from exc
        names.append(parsed.algebraic)
    if len(names) != len(set(names)):
        raise _fail_spec()
    return frozenset(names)


def _load_kinds(raw: Mapping[str, Any]) -> dict[str, frozenset[str]]:
    if set(raw) != set(_KIND_KEYS):
        raise _fail_spec()
    kinds = {name: _algebraic_set(raw[name]) for name in _KIND_KEYS}
    seen: set[str] = set()
    for group in kinds.values():
        if seen & group:
            raise _fail_spec()
        seen.update(group)
    expected = {square.algebraic for square in all_squares()}
    if seen != expected:
        raise _fail_spec()
    if kinds["corner"] != _BOARD_CORNERS:
        raise _fail_spec()
    return kinds


def _load_question(raw: Mapping[str, Any]) -> tuple[str, str]:
    if len(raw) != 1:
        raise _fail_spec()
    question_id, payload = next(iter(raw.items()))
    if not isinstance(question_id, str) or not question_id.strip():
        raise _fail_spec()
    if not isinstance(payload, dict):
        raise _fail_spec()
    if payload.get("type") != "choice":
        raise _fail_spec()
    return question_id.strip(), _text_field(payload, "instructions")


def _load_weights(raw: Mapping[str, Any]) -> tuple[
    float,
    float,
    float,
    dict[str, float],
    dict[str, float],
    dict[str, dict[str, float]],
]:
    w_jev = _finite_float(raw.get("jev"))
    w_code = _finite_float(raw.get("code"))
    w_confidence = _finite_float(raw.get("confidence"))
    if w_jev < 0.0 or w_code < 0.0 or w_confidence < 0.0:
        raise _fail_spec()
    metrics = _float_map(_mapping_field(raw, "metrics"), _METRIC_KEYS)
    scales = _float_map(_mapping_field(raw, "scales"), _METRIC_KEYS)
    if any(scales[key] <= 0.0 for key in _METRIC_KEYS):
        raise _fail_spec()
    stage_raw = _mapping_field(raw, "stage")
    if set(stage_raw) != set(_STAGE_KEYS):
        raise _fail_spec()
    stage = {
        name: _float_map(_mapping_field(stage_raw, name), _METRIC_KEYS)
        for name in _STAGE_KEYS
    }
    return w_jev, w_code, w_confidence, metrics, scales, stage


def _place_line_fields(template: str) -> set[str]:
    names: set[str] = set()
    for _, name, _, _ in Formatter().parse(template):
        if name is None:
            continue
        if not name or name.isdigit() or "." in name or "[" in name:
            raise _fail_spec()
        names.add(name)
    return names


def _require_place_line(template: str) -> str:
    if _place_line_fields(template) != set(_PLACE_FIELDS):
        raise _fail_spec()
    return template


def _load_spec(path: Path | None = None) -> _Spec:
    target = PROMPT_PATH if path is None else path
    try:
        loaded = load_json(target)
    except PromptFileError as exc:
        raise ExternalModelError(str(exc)) from exc
    if not isinstance(loaded, dict):
        raise _fail_spec()
    question_id, instructions = _load_question(_mapping_field(loaded, "questions"))
    vocab = _mapping_field(loaded, "vocabulary")
    buckets = _mapping_field(loaded, "buckets")
    empty_buckets = _bucket_map(_mapping_field(buckets, "empty"), _STAGE_KEYS)
    opponent_buckets = _bucket_map(
        _mapping_field(buckets, "opponent_places"), _AMOUNT_KEYS
    )
    flip_buckets = _bucket_map(_mapping_field(buckets, "flips"), _AMOUNT_KEYS)
    _require_cover(empty_buckets, 0, 64)
    _require_cover(opponent_buckets, 0, 32)
    _require_cover(flip_buckets, 1, 20)
    weights = _mapping_field(loaded, "weights")
    w_jev, w_code, w_confidence, metrics, scales, stage = _load_weights(weights)
    return _Spec(
        objective=_text_field(loaded, "objective"),
        question_id=question_id,
        instructions=instructions,
        place_line=_require_place_line(_text_field(loaded, "place_line")),
        kinds=_load_kinds(_mapping_field(loaded, "kinds")),
        kind_words=_word_map(_mapping_field(vocab, "kind"), _KIND_KEYS),
        yes_no=_word_map(_mapping_field(vocab, "yes_no"), _YES_NO_KEYS),
        amounts=_word_map(_mapping_field(vocab, "amount"), _AMOUNT_KEYS),
        stages=_word_map(_mapping_field(vocab, "stage"), _STAGE_KEYS),
        sides=_word_map(_mapping_field(vocab, "side"), _SIDE_KEYS),
        empty_buckets=empty_buckets,
        opponent_buckets=opponent_buckets,
        flip_buckets=flip_buckets,
        w_jev=w_jev,
        w_code=w_code,
        w_confidence=w_confidence,
        metric_weights=metrics,
        scales=scales,
        stage_weights=stage,
    )


def _empty_count(board: Board) -> int:
    return sum(1 for square in all_squares() if board.stone_at(square) is Stone.EMPTY)


def _bucket_label(value: int, buckets: Mapping[str, tuple[int, int]]) -> str:
    for name, (lo, hi) in buckets.items():
        if lo <= value <= hi:
            return name
    raise ExternalModelError("合成できません")


def _stage_of(board: Board, spec: _Spec) -> str:
    return _bucket_label(_empty_count(board), spec.empty_buckets)


def _kind_of(square: Square, spec: _Spec) -> str:
    name = square.algebraic
    for kind in _KIND_KEYS:
        if name in spec.kinds[kind]:
            return kind
    raise ExternalModelError("合成できません")


def _yes_no(flag: bool, spec: _Spec) -> str:
    return spec.yes_no["true"] if flag else spec.yes_no["false"]


def _amount_word(value: int, buckets: Mapping[str, tuple[int, int]], spec: _Spec) -> str:
    return spec.amounts[_bucket_label(value, buckets)]


def _gives_corner(position: Position, square: Square, spec: _Spec) -> bool:
    after = apply_place(position.board, square, position.side_to_move)
    replies = legal_places(Position(after, position.side_to_move.opponent))
    return any(place.algebraic in spec.kinds["corner"] for place in replies)


def _place_line(position: Position, square: Square, spec: _Spec) -> str:
    kind = _kind_of(square, spec)
    flipped = flips_for(position.board, square, position.side_to_move)
    mapping = {
        "kind": spec.kind_words[kind],
        "takes_corner": _yes_no(kind == "corner", spec),
        "gives_corner": _yes_no(_gives_corner(position, square, spec), spec),
        "opponent_places": _amount_word(
            len(legal_places(Position(
                apply_place(position.board, square, position.side_to_move),
                position.side_to_move.opponent,
            ))),
            spec.opponent_buckets,
            spec,
        ),
        "flips": _amount_word(len(flipped), spec.flip_buckets, spec),
    }
    if set(mapping) != set(_PLACE_FIELDS):
        raise _fail_spec()
    try:
        return spec.place_line.format(**mapping)
    except (KeyError, IndexError, ValueError) as exc:
        raise _fail_spec(exc) from exc


def _place_lines(
    position: Position, places: Sequence[Square], spec: _Spec
) -> dict[str, str]:
    return {square.algebraic: _place_line(position, square, spec) for square in places}


def _decision_state(
    position: Position, spec: _Spec, lines: Mapping[str, str]
) -> dict[str, Any]:
    stage = _stage_of(position.board, spec)
    return {
        "objective": spec.objective,
        "side_to_move": spec.sides[position.side_to_move.value],
        "stage": spec.stages[stage],
        "places": dict(lines),
    }


def _decision_questions(spec: _Spec, lines: Mapping[str, str]) -> dict[str, Any]:
    return {
        spec.question_id: {
            "type": "choice",
            "instructions": spec.instructions,
            "criteria": dict(lines),
        }
    }


def _attr(obj: object, name: str) -> object:
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _finite_answer(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ExternalModelError("合成できません")
    number = float(value)
    if not isfinite(number):
        raise ExternalModelError("合成できません")
    return number


def _unit_answer(value: object) -> float:
    number = _finite_answer(value)
    if number < 0.0 or number > 1.0:
        raise ExternalModelError("合成できません")
    return number


def _parse_probabilities(
    raw: object, places: Sequence[Square]
) -> dict[str, float] | None:
    if not isinstance(raw, Mapping):
        return None
    parsed: dict[str, float] = {}
    for square in places:
        key = square.algebraic
        if key not in raw:
            raise ExternalModelError("合成できません")
        parsed[key] = _unit_answer(raw[key])
    if not any(value > 0.0 for value in parsed.values()):
        raise ExternalModelError("合成できません")
    return parsed


def _parse_choice(
    answers: Mapping[str, Any], spec: _Spec, places: Sequence[Square]
) -> _Parsed:
    answer = answers.get(spec.question_id)
    if answer is None:
        raise ExternalModelError("合成できません")
    keys = {square.algebraic for square in places}
    choice = _attr(answer, "choice")
    if isinstance(choice, str) and choice not in keys:
        raise ExternalModelError("合法手の外です")
    probabilities = _parse_probabilities(_attr(answer, "probabilities"), places)
    if probabilities is None:
        if not isinstance(choice, str):
            raise ExternalModelError("合成できません")
        probabilities = {key: 1.0 if key == choice else 0.0 for key in keys}
    confidence_raw = _attr(answer, "confidence")
    confidence = 1.0 if confidence_raw is None else _unit_answer(confidence_raw)
    return _Parsed(probabilities=probabilities, confidence=confidence)


def _answers_from_response(
    response: object, spec: _Spec, places: Sequence[Square]
) -> _Parsed:
    answers = _attr(response, "answers")
    if not isinstance(answers, Mapping):
        raise ExternalModelError("OpenRouter の応答に着手がありません")
    return _parse_choice(answers, spec, places)


def _board_totals(board: Board, color: Color, spec: _Spec) -> tuple[float, float, float]:
    own = color.stone
    opponent = color.opponent.stone
    corners = spec.kinds["corner"]
    position = 0.0
    material = 0.0
    corner_score = 0.0
    for square in all_squares():
        stone = board.stone_at(square)
        if stone is own:
            sign = 1.0
        elif stone is opponent:
            sign = -1.0
        else:
            continue
        position += sign * float(score_at(square))
        material += sign
        if square.algebraic in corners:
            corner_score += sign
    return position, material, corner_score


def _after_metrics(
    position: Position, places: Sequence[Square], spec: _Spec
) -> dict[Square, _Metrics]:
    color = position.side_to_move
    scored: dict[Square, _Metrics] = {}
    for square in places:
        after = apply_place(position.board, square, color)
        own_places = legal_places(Position(after, color))
        opp_places = legal_places(Position(after, color.opponent))
        pos, material, corners = _board_totals(after, color, spec)
        scored[square] = _Metrics(
            position=pos,
            mobility=float(len(own_places) - len(opp_places)),
            material=material,
            corners=corners,
        )
    return scored


def _code_score(metrics: _Metrics, spec: _Spec, stage: str) -> float:
    mix = spec.stage_weights[stage]
    total = 0.0
    for key in _METRIC_KEYS:
        total += (
            spec.metric_weights[key]
            * mix[key]
            * (getattr(metrics, key) / spec.scales[key])
        )
    return total


def _combined_score(
    square: Square,
    metrics: _Metrics,
    parsed: _Parsed,
    spec: _Spec,
    stage: str,
) -> float:
    code = _code_score(metrics, spec, stage)
    jev = parsed.probabilities.get(square.algebraic, 0.0) * parsed.confidence
    return spec.w_code * code + spec.w_jev * spec.w_confidence * jev


def _select_square(
    position: Position,
    places: Sequence[Square],
    parsed: _Parsed,
    spec: _Spec,
) -> Square:
    stage = _stage_of(position.board, spec)
    metrics = _after_metrics(position, places, spec)
    best_square = places[0]
    best_score = _combined_score(best_square, metrics[best_square], parsed, spec, stage)
    for square in places[1:]:
        score = _combined_score(square, metrics[square], parsed, spec, stage)
        if score > best_score:
            best_score = score
            best_square = square
    return best_square


def _legal_square(square: Square, places: Sequence[Square]) -> Square:
    if square not in places:
        raise ExternalModelError("合法手の外です")
    return square


def _call_openrouter(position: Position, places: Sequence[Square]) -> Square:
    spec = _load_spec()
    key = read_secret()
    lines = _place_lines(position, places, spec)
    state = _decision_state(position, spec, lines)
    questions = _decision_questions(spec, lines)
    try:
        with OpenRouter(
            api_key=key,
            server_url=DECISIONS_SERVER,
            timeout_ms=DECISIONS_TIMEOUT_MS,
        ) as client:
            response = client.alpha.decisions.create(
                model=MODEL_ID,
                questions=questions,
                state=state,
                retries=_NO_RETRY,
                timeout_ms=DECISIONS_TIMEOUT_MS,
            )
    except ExternalModelError:
        raise
    except Exception:  # noqa: BLE001 - SDK の 4xx/5xx/timeout を継続不能に畳む
        raise ExternalModelError("OpenRouter の呼出しに失敗しました") from None
    parsed = _answers_from_response(response, spec, places)
    return _legal_square(_select_square(position, places, parsed, spec), places)


def choose_move(position: Position, rng: Random | None = None) -> Place | None:
    """Jev が選んだ合法手。失敗時は着手を採用せず継続不能を表す。"""
    del rng
    places = legal_places(position)
    if not places:
        return None
    if len(places) == 1:
        return Place(places[0])
    square = _call_openrouter(position, places)
    if square not in places:
        raise ExternalModelError("合法手の外です")
    return Place(square)
