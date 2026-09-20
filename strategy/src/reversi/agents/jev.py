"""OpenRouter の Jev で合法手を選ぶ個体。Decisions API の原子質問を合成する。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from random import Random
from typing import Any

from openrouter import OpenRouter
from openrouter.utils.retries import BackoffStrategy, RetryConfig

from reversi.agents.prompt import PROMPTS_DIR, PromptFileError, load_json
from reversi.engine.board import BOARD_SIZE, Board, Square, Stone
from reversi.engine.rules import Place, Position, apply_place, flips_for, legal_places

MODEL_ID = "typesafe/jev-1.13"
SPECIMEN_ID = "jev"
CATEGORY = "generative_ai"
DISPLAY_NAME = "生成 AI (Jev)"
DESCRIPTION = (
    "OpenRouter 上の Jev を Decisions API で呼び、原子質問と盤の特徴を合成して"
    "合法手から着手を選ぶ。対局中に WTHOR は参照しない。"
)
DECISIONS_SERVER = "https://openrouter.ai"
SECRET_PATH = Path("/run/secrets/openrouter-api-key")
PROMPT_PATH = PROMPTS_DIR / "jev.json"
# Hono の戦略中継は 60 秒。それより先に失敗させ、ロックを返す。
DECISIONS_TIMEOUT_MS = 55_000
_NO_RETRY = RetryConfig("none", BackoffStrategy(0, 0, 1.0, 0), False)
_NOUL_IDS = ("corner_priority", "mobility_priority", "corner_danger")
_SCORE_ID = "material_importance"
_STAGE_ID = "stage"
_STAGE_KEYS = ("opening", "midgame", "endgame")
_STAGE_FEATURES = ("corner", "flips", "mobility")
_FEATURE_KEYS = (
    "corner",
    "x_square",
    "c_square",
    "edge",
    "flips",
    "mobility",
    "gives_corner",
)
_CORNERS = frozenset(
    {Square.parse(name) for name in ("a1", "h1", "a8", "h8")}
)
_X_SQUARES = {
    Square.parse("b2"): Square.parse("a1"),
    Square.parse("g2"): Square.parse("h1"),
    Square.parse("b7"): Square.parse("a8"),
    Square.parse("g7"): Square.parse("h8"),
}
_C_SQUARES = {
    Square.parse("a2"): Square.parse("a1"),
    Square.parse("b1"): Square.parse("a1"),
    Square.parse("g1"): Square.parse("h1"),
    Square.parse("h2"): Square.parse("h1"),
    Square.parse("a7"): Square.parse("a8"),
    Square.parse("b8"): Square.parse("a8"),
    Square.parse("g8"): Square.parse("h8"),
    Square.parse("h7"): Square.parse("h8"),
}

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
    feature_weights: dict[str, float]
    stage_weights: dict[str, dict[str, float]]
    score_span: float


@dataclass(frozen=True, slots=True)
class _Parsed:
    noul: dict[str, float]
    material: float
    stage: dict[str, float]


@dataclass(frozen=True, slots=True)
class _Features:
    corner: float
    x_square: float
    c_square: float
    edge: float
    flips: float
    mobility: float
    gives_corner: float


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
        "corner_danger": "noul",
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
    features = _float_map(_mapping_field(weights, "features"), _FEATURE_KEYS)
    stage_raw = _mapping_field(weights, "stage")
    if set(stage_raw) != set(_STAGE_KEYS):
        raise _fail_spec()
    stage = {
        name: _float_map(_mapping_field(stage_raw, name), _STAGE_FEATURES)
        for name in _STAGE_KEYS
    }
    criteria = questions[_SCORE_ID]["criteria"]
    return _Spec(
        objective=_text_field(loaded, "objective"),
        origin=_text_field(loaded, "origin"),
        questions=questions,
        answer_weights=answers,
        feature_weights=features,
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


def _parse_stage(answers: Mapping[str, Any]) -> dict[str, float]:
    answer = answers.get(_STAGE_ID)
    if answer is None:
        raise ExternalModelError("合成できません")
    probs = _attr(answer, "probabilities")
    if isinstance(probs, Mapping):
        values = {key: _finite_answer(probs.get(key, 0.0)) for key in _STAGE_KEYS}
        total = sum(values.values())
        if total > 0.0:
            return {key: value / total for key, value in values.items()}
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


def _danger_flag(
    square: Square, table: Mapping[Square, Square], own: Stone, board: Board
) -> float:
    corner = table.get(square)
    if corner is None:
        return 0.0
    if board.stone_at(corner) is own:
        return 0.0
    return 1.0


def _place_features(position: Position, places: Sequence[Square]) -> dict[Square, _Features]:
    color = position.side_to_move
    own = color.stone
    flips: dict[Square, float] = {}
    mobility: dict[Square, float] = {}
    extras: dict[Square, tuple[float, float, float, float, float]] = {}
    for square in places:
        flipped = flips_for(position.board, square, color)
        flips[square] = float(len(flipped))
        after = apply_place(position.board, square, color)
        opp_places = legal_places(Position(after, color.opponent))
        mobility[square] = float(len(opp_places))
        gives = 1.0 if any(item in _CORNERS for item in opp_places) else 0.0
        is_corner = 1.0 if square in _CORNERS else 0.0
        is_edge = 1.0 if (square.file in (0, 7) or square.rank in (0, 7)) and not is_corner else 0.0
        extras[square] = (
            is_corner,
            _danger_flag(square, _X_SQUARES, own, position.board),
            _danger_flag(square, _C_SQUARES, own, position.board),
            is_edge,
            gives,
        )
    flips_n = _normalize(flips)
    mobility_n = _normalize(mobility)
    scored: dict[Square, _Features] = {}
    for square in places:
        corner, x_square, c_square, edge, gives = extras[square]
        scored[square] = _Features(
            corner=corner,
            x_square=x_square,
            c_square=c_square,
            edge=edge,
            flips=flips_n[square],
            mobility=1.0 - mobility_n[square],
            gives_corner=gives,
        )
    return scored


def _stage_mix(parsed: _Parsed, spec: _Spec) -> dict[str, float]:
    mixed = dict.fromkeys(_STAGE_FEATURES, 0.0)
    for name, share in parsed.stage.items():
        row = spec.stage_weights[name]
        for key in _STAGE_FEATURES:
            mixed[key] += share * row[key]
    return mixed


def _score_square(
    features: _Features, parsed: _Parsed, spec: _Spec, stage: Mapping[str, float]
) -> float:
    ans = spec.answer_weights
    feat = spec.feature_weights
    noul = parsed.noul
    return (
        feat["corner"]
        * features.corner
        * stage["corner"]
        * (1.0 + ans["corner_priority"] * noul["corner_priority"])
        + feat["x_square"] * features.x_square
        + feat["c_square"] * features.c_square
        + feat["edge"] * features.edge
        + feat["flips"]
        * features.flips
        * stage["flips"]
        * (1.0 + ans["material_importance"] * parsed.material)
        + feat["mobility"]
        * features.mobility
        * stage["mobility"]
        * (1.0 + ans["mobility_priority"] * noul["mobility_priority"])
        + feat["gives_corner"]
        * features.gives_corner
        * (1.0 + ans["corner_danger"] * noul["corner_danger"])
    )


def _select_square(
    position: Position,
    places: Sequence[Square],
    parsed: _Parsed,
    spec: _Spec,
) -> Square:
    features = _place_features(position, places)
    stage = _stage_mix(parsed, spec)
    best_square = places[0]
    best_score = _score_square(features[best_square], parsed, spec, stage)
    for square in places[1:]:
        score = _score_square(features[square], parsed, spec, stage)
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
