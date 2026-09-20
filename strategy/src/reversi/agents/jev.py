"""OpenRouter の Jev で合法手を選ぶ個体。優先の答えと着手後評価を合成する。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from random import Random
from typing import Any

from openrouter import OpenRouter
from openrouter.utils.retries import BackoffStrategy, RetryConfig

from reversi.agents.position_table import score_at
from reversi.agents.prompt import PROMPTS_DIR, PromptFileError, load_json
from reversi.engine.board import BOARD_SIZE, Board, Color, Square, all_squares
from reversi.engine.rules import Place, Position, apply_place, legal_places

MODEL_ID = "typesafe/jev-1.13"
SPECIMEN_ID = "jev"
CATEGORY = "generative_ai"
DISPLAY_NAME = "生成 AI (Jev)"
DESCRIPTION = (
    "OpenRouter 上の Jev を Decisions API で呼び、どの目標を優先するかを"
    "原子質問で答えさせ、着手後の盤の点数はコードが付けて合成する。"
    "対局中に WTHOR は参照しない。"
)
DECISIONS_SERVER = "https://openrouter.ai"
SECRET_PATH = Path("/run/secrets/openrouter-api-key")
PROMPT_PATH = PROMPTS_DIR / "jev.json"
# Hono の戦略中継は 60 秒。それより先に失敗させ、ロックを返す。
DECISIONS_TIMEOUT_MS = 55_000
_NO_RETRY = RetryConfig("none", BackoffStrategy(0, 0, 1.0, 0), False)
_NOUL_IDS = ("corner_priority", "mobility_priority", "position_priority")
_SCORE_ID = "material_importance"
_STAGE_ID = "stage"
_STAGE_KEYS = ("opening", "midgame", "endgame")
_METRIC_KEYS = ("position", "mobility", "material", "corners")
_METRIC_ANSWERS = {
    "position": "position_priority",
    "mobility": "mobility_priority",
    "material": _SCORE_ID,
    "corners": "corner_priority",
}
_CORNERS = frozenset(
    {Square.parse(name) for name in ("a1", "h1", "a8", "h8")}
)

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
    origin: str
    questions: dict[str, Any]
    answer_weights: dict[str, float]
    metric_weights: dict[str, float]
    stage_weights: dict[str, dict[str, float]]
    score_span: float


@dataclass(frozen=True, slots=True)
class _Parsed:
    noul: dict[str, float]
    material: float
    stage: dict[str, float]


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


def _question_payload(raw: object, expected: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise _fail_spec()
    if raw.get("type") != expected:
        raise _fail_spec()
    instructions = raw.get("instructions")
    if not isinstance(instructions, str) or not instructions.strip():
        raise _fail_spec()
    payload: dict[str, Any] = {
        "type": expected,
        "instructions": instructions.strip(),
    }
    criteria = raw.get("criteria")
    if expected == "noul":
        if criteria is not None:
            if not isinstance(criteria, dict) or set(criteria) != {"true", "false"}:
                raise _fail_spec()
            payload["criteria"] = criteria
        return payload
    if expected == "score":
        if not isinstance(criteria, list) or len(criteria) < 2:
            raise _fail_spec()
        if any(not isinstance(item, str) or not item.strip() for item in criteria):
            raise _fail_spec()
        payload["criteria"] = criteria
        return payload
    if not isinstance(criteria, dict) or set(criteria) != set(_STAGE_KEYS):
        raise _fail_spec()
    payload["criteria"] = criteria
    return payload


def _load_spec(path: Path | None = None) -> _Spec:
    target = PROMPT_PATH if path is None else path
    try:
        loaded = load_json(target)
    except PromptFileError as exc:
        raise ExternalModelError(str(exc)) from exc
    if not isinstance(loaded, dict):
        raise _fail_spec()
    questions_raw = _mapping_field(loaded, "questions")
    if len(questions_raw) < 2:
        raise _fail_spec()
    expected = {
        "corner_priority": "noul",
        "mobility_priority": "noul",
        "position_priority": "noul",
        _SCORE_ID: "score",
        _STAGE_ID: "choice",
    }
    if set(questions_raw) != set(expected):
        raise _fail_spec()
    questions = {
        qid: _question_payload(questions_raw[qid], qtype)
        for qid, qtype in expected.items()
    }
    weights = _mapping_field(loaded, "weights")
    answers = _float_map(_mapping_field(weights, "answers"), _NOUL_IDS + (_SCORE_ID,))
    metrics = _float_map(_mapping_field(weights, "metrics"), _METRIC_KEYS)
    stage_raw = _mapping_field(weights, "stage")
    if set(stage_raw) != set(_STAGE_KEYS):
        raise _fail_spec()
    stage = {
        name: _float_map(_mapping_field(stage_raw, name), _METRIC_KEYS)
        for name in _STAGE_KEYS
    }
    criteria = questions[_SCORE_ID]["criteria"]
    return _Spec(
        objective=_text_field(loaded, "objective"),
        origin=_text_field(loaded, "origin"),
        questions=questions,
        answer_weights=answers,
        metric_weights=metrics,
        stage_weights=stage,
        score_span=float(len(criteria) - 1),
    )


def _board_state(
    position: Position, places: Sequence[Square], spec: _Spec
) -> dict[str, Any]:
    board = [
        [position.board.cells[rank][file].value for file in range(BOARD_SIZE)]
        for rank in range(BOARD_SIZE)
    ]
    return {
        "objective": spec.objective,
        "origin": spec.origin,
        "side_to_move": position.side_to_move.value,
        "board": board,
        "legal_places": [square.algebraic for square in places],
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


def _clamp_unit(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _parse_noul(answers: Mapping[str, Any]) -> dict[str, float]:
    parsed: dict[str, float] = {}
    for qid in _NOUL_IDS:
        answer = answers.get(qid)
        if answer is None:
            raise ExternalModelError("合成できません")
        parsed[qid] = _clamp_unit(_finite_answer(_attr(answer, "noul")))
    return parsed


def _parse_material(answers: Mapping[str, Any], span: float) -> float:
    answer = answers.get(_SCORE_ID)
    if answer is None or span <= 0.0:
        raise ExternalModelError("合成できません")
    return _clamp_unit(_finite_answer(_attr(answer, "score")) / span)


def _normalized_stage_probs(probs: Mapping[object, object]) -> dict[str, float] | None:
    values = {key: _finite_answer(probs.get(key, 0.0)) for key in _STAGE_KEYS}
    if any(value < 0.0 or value > 1.0 for value in values.values()):
        raise ExternalModelError("合成できません")
    total = sum(values.values())
    if total <= 0.0:
        return None
    return {key: value / total for key, value in values.items()}


def _parse_stage(answers: Mapping[str, Any]) -> dict[str, float]:
    answer = answers.get(_STAGE_ID)
    if answer is None:
        raise ExternalModelError("合成できません")
    probs = _attr(answer, "probabilities")
    if isinstance(probs, Mapping):
        mixed = _normalized_stage_probs(probs)
        if mixed is not None:
            return mixed
    choice = _attr(answer, "choice")
    if not isinstance(choice, str) or choice not in _STAGE_KEYS:
        raise ExternalModelError("合成できません")
    return {key: 1.0 if key == choice else 0.0 for key in _STAGE_KEYS}


def _answers_from_response(response: object, spec: _Spec) -> _Parsed:
    answers = _attr(response, "answers")
    if not isinstance(answers, Mapping):
        raise ExternalModelError("OpenRouter の応答に着手がありません")
    return _Parsed(
        noul=_parse_noul(answers),
        material=_parse_material(answers, spec.score_span),
        stage=_parse_stage(answers),
    )


def _normalize(raw: Mapping[Square, float]) -> dict[Square, float]:
    values = tuple(raw.values())
    lo = min(values)
    span = max(values) - lo
    if span == 0.0:
        return dict.fromkeys(raw, 0.0)
    return {square: (value - lo) / span for square, value in raw.items()}


def _board_totals(board: Board, color: Color) -> tuple[float, float, float]:
    own = color.stone
    opponent = color.opponent.stone
    position = 0.0
    material = 0.0
    corners = 0.0
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
        if square in _CORNERS:
            corners += sign
    return position, material, corners


def _after_metrics(position: Position, places: Sequence[Square]) -> dict[Square, _Metrics]:
    color = position.side_to_move
    position_raw: dict[Square, float] = {}
    mobility_raw: dict[Square, float] = {}
    material_raw: dict[Square, float] = {}
    corners_raw: dict[Square, float] = {}
    for square in places:
        after = apply_place(position.board, square, color)
        own_places = legal_places(Position(after, color))
        opp_places = legal_places(Position(after, color.opponent))
        pos, material, corners = _board_totals(after, color)
        position_raw[square] = pos
        mobility_raw[square] = float(len(own_places) - len(opp_places))
        material_raw[square] = material
        corners_raw[square] = corners
    position_n = _normalize(position_raw)
    mobility_n = _normalize(mobility_raw)
    material_n = _normalize(material_raw)
    corners_n = _normalize(corners_raw)
    return {
        square: _Metrics(
            position=position_n[square],
            mobility=mobility_n[square],
            material=material_n[square],
            corners=corners_n[square],
        )
        for square in places
    }


def _stage_mix(parsed: _Parsed, spec: _Spec) -> dict[str, float]:
    mixed = dict.fromkeys(_METRIC_KEYS, 0.0)
    for name, share in parsed.stage.items():
        row = spec.stage_weights[name]
        for key in _METRIC_KEYS:
            mixed[key] += share * row[key]
    return mixed


def _answer_factor(parsed: _Parsed, spec: _Spec, metric: str) -> float:
    qid = _METRIC_ANSWERS[metric]
    if qid == _SCORE_ID:
        value = parsed.material
    else:
        value = parsed.noul[qid]
    return 1.0 + spec.answer_weights[qid] * value


def _score_metrics(
    metrics: _Metrics, parsed: _Parsed, spec: _Spec, stage: Mapping[str, float]
) -> float:
    total = 0.0
    for key in _METRIC_KEYS:
        total += (
            spec.metric_weights[key]
            * getattr(metrics, key)
            * stage[key]
            * _answer_factor(parsed, spec, key)
        )
    return total


def _select_square(
    position: Position,
    places: Sequence[Square],
    parsed: _Parsed,
    spec: _Spec,
) -> Square:
    metrics = _after_metrics(position, places)
    stage = _stage_mix(parsed, spec)
    best_square = places[0]
    best_score = _score_metrics(metrics[best_square], parsed, spec, stage)
    for square in places[1:]:
        score = _score_metrics(metrics[square], parsed, spec, stage)
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
    state = _board_state(position, places, spec)
    try:
        with OpenRouter(
            api_key=key,
            server_url=DECISIONS_SERVER,
            timeout_ms=DECISIONS_TIMEOUT_MS,
        ) as client:
            response = client.alpha.decisions.create(
                model=MODEL_ID,
                questions=spec.questions,
                state=state,
                retries=_NO_RETRY,
                timeout_ms=DECISIONS_TIMEOUT_MS,
            )
    except ExternalModelError:
        raise
    except Exception:  # noqa: BLE001 - SDK の 4xx/5xx/timeout を継続不能に畳む
        raise ExternalModelError("OpenRouter の呼出しに失敗しました") from None
    parsed = _answers_from_response(response, spec)
    return _legal_square(_select_square(position, places, parsed, spec), places)


def choose_move(position: Position, rng: Random | None = None) -> Place | None:
    """Jev が選んだ合法手。失敗時は着手を採用せず継続不能を表す。"""
    del rng
    places = legal_places(position)
    if not places:
        return None
    square = _call_openrouter(position, places)
    if square not in places:
        raise ExternalModelError("合法手の外です")
    return Place(square)
