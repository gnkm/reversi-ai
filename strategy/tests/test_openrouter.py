"""OpenRouter の鍵ファイルと Jev Decisions 呼出し境界。"""

from __future__ import annotations

import ast
import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest

from reversi.agents import chat_completions, extra_genai, jev
from reversi.agents.prompt import PromptFileError, load_json, markdown_sections
from reversi.api import openrouter_key
from reversi.engine.board import Board, Color, Square, Stone
from reversi.engine.rules import Position, apply_place, initial_position, legal_places

_API_KEY = "sk-test-not-a-real-key"
_ENV_KEY = "sk-env-must-not-be-used"


def _fake_openrouter(
    responder: Callable[[dict[str, object]], SimpleNamespace],
) -> type:
    class Fake:
        last_init: dict[str, object] | None = None
        last_create: dict[str, object] | None = None

        def __init__(self, **kwargs: object) -> None:
            type(self).last_init = kwargs
            self.alpha = self
            self.decisions = self

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def create(self, **kwargs: object) -> SimpleNamespace:
            type(self).last_create = kwargs
            return responder(kwargs)

    return Fake


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _choice_answers(
    places: Sequence[Square],
    *,
    focused: str | None = None,
    confidence: float = 1.0,
    probabilities: Mapping[str, float] | None = None,
) -> dict[str, SimpleNamespace]:
    spec = load_json(jev.PROMPT_PATH)
    assert isinstance(spec, dict)
    questions = spec["questions"]
    assert isinstance(questions, dict)
    question_id = next(iter(questions))
    keys = [square.algebraic for square in places]
    if probabilities is None:
        if focused is None:
            each = 1.0 / float(len(keys))
            probs = dict.fromkeys(keys, each)
            choice = keys[0]
        else:
            probs = {key: 1.0 if key == focused else 0.0 for key in keys}
            choice = focused
    else:
        probs = {key: float(probabilities.get(key, 0.0)) for key in keys}
        choice = max(keys, key=lambda key: probs[key])
    return {
        question_id: SimpleNamespace(
            type="choice",
            choice=choice,
            confidence=confidence,
            probabilities=probs,
        )
    }


def _respond_with(answers: Mapping[str, SimpleNamespace]):
    def respond(kwargs: dict[str, object]) -> SimpleNamespace:
        del kwargs
        return SimpleNamespace(answers=answers, api_key=_API_KEY)

    return respond


def _write_spec(path: Path, spec: dict[str, object]) -> Path:
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def _repo_spec() -> dict[str, object]:
    path = Path(__file__).resolve().parents[2] / "prompts" / "jev.json"
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_openrouter_key_reads_secret_file_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = tmp_path / "openrouter-api-key"
    secret.write_text(f"  {_API_KEY}\n", encoding="utf-8")
    monkeypatch.setattr(openrouter_key, "SECRET_PATH", secret)
    monkeypatch.setenv("OPENROUTER_API_KEY", _ENV_KEY)
    assert openrouter_key.read_api_key() == _API_KEY
    assert os.environ["OPENROUTER_API_KEY"] == _ENV_KEY


def test_openrouter_key_does_not_copy_into_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = tmp_path / "openrouter-api-key"
    secret.write_text(_API_KEY, encoding="utf-8")
    monkeypatch.setattr(openrouter_key, "SECRET_PATH", secret)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert openrouter_key.read_api_key() == _API_KEY
    assert "OPENROUTER_API_KEY" not in os.environ


def test_openrouter_key_missing_or_empty_file_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = tmp_path / "missing"
    monkeypatch.setattr(openrouter_key, "SECRET_PATH", missing)
    monkeypatch.setenv("OPENROUTER_API_KEY", _ENV_KEY)
    with pytest.raises(openrouter_key.OpenRouterKeyError) as missing_err:
        openrouter_key.read_api_key()
    assert _ENV_KEY not in str(missing_err.value)
    assert _ENV_KEY not in repr(missing_err.value)

    empty = tmp_path / "empty"
    empty.write_text(" \n", encoding="utf-8")
    monkeypatch.setattr(openrouter_key, "SECRET_PATH", empty)
    with pytest.raises(openrouter_key.OpenRouterKeyError) as empty_err:
        openrouter_key.read_api_key()
    assert _ENV_KEY not in str(empty_err.value)


def test_openrouter_key_default_path_is_podman_secret() -> None:
    assert openrouter_key.SECRET_PATH == Path("/run/secrets/openrouter-api-key")
    assert jev.SECRET_PATH is openrouter_key.SECRET_PATH
    assert jev.DECISIONS_SERVER.startswith("https://")
    assert jev.DECISIONS_SERVER == "https://openrouter.ai"
    assert jev.MODEL_ID == "typesafe/jev-1.13"


def test_openrouter_key_read_uses_jev_secret_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = tmp_path / "openrouter-api-key"
    secret.write_text(f"  {_API_KEY}\n", encoding="utf-8")
    monkeypatch.setattr(openrouter_key, "SECRET_PATH", secret)
    assert openrouter_key.read_api_key() == jev.read_secret(secret)


def test_openrouter_key_source_does_not_read_environment() -> None:
    path = Path(openrouter_key.__file__)
    source = _source(path)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {"getenv", "putenv", "environ"}
        if isinstance(node, ast.Attribute) and node.attr == "environ":
            raise AssertionError("openrouter_key.py は os.environ を使ってはいけない")


def test_jev_ignores_environment_key_when_secret_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(jev, "SECRET_PATH", tmp_path / "missing")
    monkeypatch.setenv("OPENROUTER_API_KEY", _ENV_KEY)
    with pytest.raises(jev.ExternalModelError) as err:
        jev.choose_move(initial_position())
    assert _ENV_KEY not in str(err.value)
    assert _API_KEY not in str(err.value)


def test_jev_decisions_call_uses_https_and_model_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = tmp_path / "openrouter-api-key"
    secret.write_text(_API_KEY, encoding="utf-8")
    monkeypatch.setattr(jev, "SECRET_PATH", secret)
    monkeypatch.setenv("OPENROUTER_API_KEY", _ENV_KEY)
    position = initial_position()
    places = legal_places(position)

    fake = _fake_openrouter(_respond_with(_choice_answers(places)))
    monkeypatch.setattr(jev, "OpenRouter", fake)
    move = jev.choose_move(position)
    assert move is not None
    assert move.square in places
    init = fake.last_init
    assert isinstance(init, dict)
    assert init["api_key"] == _API_KEY
    assert init["server_url"] == "https://openrouter.ai"
    assert init["timeout_ms"] == jev.DECISIONS_TIMEOUT_MS == 55_000
    assert jev.DECISIONS_TIMEOUT_MS < 60_000
    create = fake.last_create
    assert isinstance(create, dict)
    assert create["model"] == "typesafe/jev-1.13"
    assert create["timeout_ms"] == jev.DECISIONS_TIMEOUT_MS
    retries = create["retries"]
    assert getattr(retries, "strategy", None) == "none"
    questions = create["questions"]
    assert isinstance(questions, dict)
    assert len(questions) == 1
    spec = load_json(jev.PROMPT_PATH)
    assert isinstance(spec, dict)
    question_id = next(iter(spec["questions"]))
    assert set(questions) == {question_id}
    assert question_id not in {square.algebraic for square in places}
    spec_text = jev.PROMPT_PATH.read_text(encoding="utf-8")
    payload = questions[question_id]
    assert payload["type"] == "choice"
    assert payload["instructions"]
    assert payload["instructions"] in spec_text
    lowered = payload["instructions"].lower()
    assert "how many" not in lowered
    assert "count the" not in lowered
    assert "legal_places" not in lowered
    assert set(payload["criteria"]) == {square.algebraic for square in places}
    state = create["state"]
    assert isinstance(state, dict)
    assert "board" not in state
    assert "origin" not in state
    assert isinstance(state["places"], dict)
    assert set(state["places"]) == {square.algebraic for square in places}
    assert state["places"] == payload["criteria"]
    assert "more discs" in str(state["objective"]).lower()
    for text in state["places"].values():
        assert not re.search(r"\d", text)
    assert "Place a stone on" not in spec_text


def _corner_vs_two_flips() -> Position:
    rows = (
        "........",
        "........",
        "........",
        "...B....",
        "...W....",
        "...W....",
        "........",
        ".WB.....",
    )
    stone = {".": Stone.EMPTY, "B": Stone.BLACK, "W": Stone.WHITE}
    cells = tuple(tuple(stone[ch] for ch in row) for row in reversed(rows))
    return Position(Board(cells), Color.BLACK)


def test_jev_fake_choice_probability_on_corner_picks_that_square(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = tmp_path / "openrouter-api-key"
    secret.write_text(_API_KEY, encoding="utf-8")
    monkeypatch.setattr(jev, "SECRET_PATH", secret)
    position = _corner_vs_two_flips()
    places = legal_places(position)
    assert Square.parse("a1") in places
    assert Square.parse("d2") in places
    after_a1 = apply_place(position.board, Square.parse("a1"), Color.BLACK)
    after_d2 = apply_place(position.board, Square.parse("d2"), Color.BLACK)
    assert after_a1.stone_at(Square.parse("a1")) is Stone.BLACK
    assert after_d2.stone_at(Square.parse("a1")) is Stone.EMPTY

    fake = _fake_openrouter(_respond_with(_choice_answers(places, focused="a1")))
    monkeypatch.setattr(jev, "OpenRouter", fake)
    corner_move = jev.choose_move(position)
    assert corner_move is not None
    assert corner_move.square == Square.parse("a1")
    assert corner_move.square in places
    create = fake.last_create
    assert isinstance(create, dict)
    questions = create["questions"]
    assert isinstance(questions, dict)
    payload = next(iter(questions.values()))
    assert payload["type"] == "choice"
    assert set(payload["criteria"]) == {square.algebraic for square in places}

    fake_other = _fake_openrouter(_respond_with(_choice_answers(places, focused="d2")))
    monkeypatch.setattr(jev, "OpenRouter", fake_other)
    other_move = jev.choose_move(position)
    assert other_move is not None
    assert other_move.square == Square.parse("d2")
    assert other_move.square in places
    assert other_move.square != corner_move.square


def test_jev_http_error_from_sdk_is_unplayable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = tmp_path / "openrouter-api-key"
    secret.write_text(_API_KEY, encoding="utf-8")
    monkeypatch.setattr(jev, "SECRET_PATH", secret)

    def boom(kwargs: dict[str, object]) -> SimpleNamespace:
        del kwargs
        raise RuntimeError(f"401 unauthorized {_API_KEY}")

    monkeypatch.setattr(jev, "OpenRouter", _fake_openrouter(boom))
    with pytest.raises(jev.ExternalModelError) as err:
        jev.choose_move(initial_position())
    assert _API_KEY not in str(err.value)
    assert err.value.args
    assert all(_API_KEY not in str(arg) for arg in err.value.args)


def test_jev_incomplete_answers_are_unplayable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = tmp_path / "openrouter-api-key"
    secret.write_text(_API_KEY, encoding="utf-8")
    monkeypatch.setattr(jev, "SECRET_PATH", secret)
    position = initial_position()
    assert Square.parse("a1") not in legal_places(position)
    monkeypatch.setattr(
        jev,
        "OpenRouter",
        _fake_openrouter(_respond_with({"move": SimpleNamespace(choice="a1")})),
    )
    with pytest.raises(jev.ExternalModelError, match="合成できません"):
        jev.choose_move(position)


def test_jev_prompt_path_is_repo_json() -> None:
    root = Path(__file__).resolve().parents[2]
    assert jev.PROMPT_PATH == root / "prompts" / "jev.json"
    assert jev.PROMPT_PATH.is_file()
    assert chat_completions.PROMPT_PATH == root / "prompts" / "chat-completions.md"
    assert chat_completions.PROMPT_PATH.is_file()
    assert not (root / "prompts" / "jev.md").exists()


def test_jev_prompt_states_win_by_more_discs() -> None:
    spec = load_json(jev.PROMPT_PATH)
    assert isinstance(spec, dict)
    objective = spec["objective"]
    assert isinstance(objective, str)
    lowered = objective.lower()
    assert "win" in lowered
    assert "more discs" in lowered
    questions = spec["questions"]
    assert isinstance(questions, dict)
    assert len(questions) == 1
    payload = next(iter(questions.values()))
    assert payload["type"] == "choice"
    assert "board[0][0]" not in json.dumps(spec)
    assert "origin" not in spec


def test_jev_questions_do_not_ask_to_count() -> None:
    spec = load_json(jev.PROMPT_PATH)
    assert isinstance(spec, dict)
    questions = spec["questions"]
    assert isinstance(questions, dict)
    blob = json.dumps(questions, ensure_ascii=False).lower()
    for needle in (
        "how many",
        "count the",
        "enumerate",
        "number of legal",
        "len(",
        "which square",
        "best square",
        "best move",
        "legal_places",
        "反転数",
        "着手可能数",
        "数え",
    ):
        assert needle not in blob


def test_jev_missing_prompt_file_is_unplayable_without_calling_openrouter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = tmp_path / "openrouter-api-key"
    secret.write_text(_API_KEY, encoding="utf-8")
    monkeypatch.setattr(jev, "SECRET_PATH", secret)
    monkeypatch.setattr(jev, "PROMPT_PATH", tmp_path / "missing.json")
    called = {"n": 0}

    class Boom:
        def __init__(self, **kwargs: object) -> None:
            del kwargs
            called["n"] += 1
            raise AssertionError("指示ファイル欠落時に OpenRouter を呼んではいけない")

    monkeypatch.setattr(jev, "OpenRouter", Boom)
    with pytest.raises(jev.ExternalModelError, match="着手指示"):
        jev.choose_move(initial_position())
    assert called["n"] == 0


def test_jev_empty_or_incomplete_prompt_is_unplayable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = tmp_path / "openrouter-api-key"
    secret.write_text(_API_KEY, encoding="utf-8")
    monkeypatch.setattr(jev, "SECRET_PATH", secret)
    empty = tmp_path / "empty.json"
    empty.write_text(" \n", encoding="utf-8")
    monkeypatch.setattr(jev, "PROMPT_PATH", empty)
    with pytest.raises(jev.ExternalModelError, match="空"):
        jev.choose_move(initial_position())

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    monkeypatch.setattr(jev, "PROMPT_PATH", invalid)
    with pytest.raises(jev.ExternalModelError, match="JSON"):
        jev.choose_move(initial_position())

    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text('{"objective": "Win."}\n', encoding="utf-8")
    monkeypatch.setattr(jev, "PROMPT_PATH", incomplete)
    with pytest.raises(jev.ExternalModelError, match="不正"):
        jev.choose_move(initial_position())

    wrong_type = _repo_spec()
    questions = wrong_type["questions"]
    assert isinstance(questions, dict)
    first_id = next(iter(questions))
    payload = questions[first_id]
    assert isinstance(payload, dict)
    payload["type"] = "noul"
    noul = tmp_path / "noul.json"
    _write_spec(noul, wrong_type)
    monkeypatch.setattr(jev, "PROMPT_PATH", noul)
    with pytest.raises(jev.ExternalModelError, match="不正"):
        jev.choose_move(initial_position())


def test_markdown_sections_keeps_heading_lines_inside_fences() -> None:
    parts = markdown_sections(
        "## instructions\n\nChoose.\n```\n## instructions\nexample\n```\n"
        "Still here.\n\n## option\n\nPlace on {square}.\n"
    )
    assert "## instructions" in parts["instructions"]
    assert "example" in parts["instructions"]
    assert "Still here." in parts["instructions"]
    assert parts["option"] == "Place on {square}."


def test_markdown_sections_rejects_duplicate_and_unclosed_fence() -> None:
    with pytest.raises(PromptFileError, match="重複"):
        markdown_sections(
            "## instructions\n\nFirst.\n\n## option\n\nX.\n\n## instructions\n\nSecond.\n"
        )
    with pytest.raises(PromptFileError, match="コードフェンス"):
        markdown_sections("## instructions\n\n```\nnot closed\n")


def test_jev_uses_updated_json_on_next_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = tmp_path / "openrouter-api-key"
    secret.write_text(_API_KEY, encoding="utf-8")
    monkeypatch.setattr(jev, "SECRET_PATH", secret)
    spec = _repo_spec()
    questions = spec["questions"]
    assert isinstance(questions, dict)
    question_id = next(iter(questions))
    first_q = questions[question_id]
    assert isinstance(first_q, dict)
    first_q["instructions"] = "First place instruction."
    prompt = _write_spec(tmp_path / "jev.json", spec)
    monkeypatch.setattr(jev, "PROMPT_PATH", prompt)
    position = initial_position()
    places = legal_places(position)

    fake = _fake_openrouter(_respond_with(_choice_answers(places)))
    monkeypatch.setattr(jev, "OpenRouter", fake)
    assert jev.choose_move(position) is not None
    first = fake.last_create
    assert isinstance(first, dict)
    assert first["questions"][question_id]["instructions"] == "First place instruction."

    first_q["instructions"] = "Second place instruction."
    _write_spec(prompt, spec)
    assert jev.choose_move(position) is not None
    second = fake.last_create
    assert isinstance(second, dict)
    assert second["questions"][question_id]["instructions"] == "Second place instruction."


def _fake_chat_openrouter(
    responder: Callable[[dict[str, object]], SimpleNamespace],
) -> type:
    class Fake:
        last_init: dict[str, object] | None = None
        last_send: dict[str, object] | None = None

        def __init__(self, **kwargs: object) -> None:
            type(self).last_init = kwargs
            self.chat = self

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def send(self, **kwargs: object) -> SimpleNamespace:
            type(self).last_send = kwargs
            return responder(kwargs)

    return Fake


def test_extra_genai_chat_uses_https_and_given_model_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = tmp_path / "openrouter-api-key"
    secret.write_text(_API_KEY, encoding="utf-8")
    monkeypatch.setattr(chat_completions, "SECRET_PATH", secret)
    monkeypatch.setenv("OPENROUTER_API_KEY", _ENV_KEY)
    position = initial_position()
    places = legal_places(position)
    chosen = places[0]
    model_id = "vendor/extra-chat-model"

    def respond(kwargs: dict[str, object]) -> SimpleNamespace:
        del kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps({"square": chosen.algebraic}),
                        role="assistant",
                    )
                )
            ]
        )

    fake = _fake_chat_openrouter(respond)
    monkeypatch.setattr(chat_completions, "OpenRouter", fake)
    move = chat_completions.choose_move(position, model_id)
    assert move is not None
    assert move.square == chosen
    init = fake.last_init
    assert isinstance(init, dict)
    assert init["api_key"] == _API_KEY
    assert init["server_url"] == "https://openrouter.ai"
    assert init["timeout_ms"] == chat_completions.CHAT_TIMEOUT_MS == 55_000
    send = fake.last_send
    assert isinstance(send, dict)
    assert send["model"] == model_id
    assert send["timeout_ms"] == chat_completions.CHAT_TIMEOUT_MS
    retries = send["retries"]
    assert getattr(retries, "strategy", None) == "none"
    messages = send["messages"]
    assert isinstance(messages, list)
    assert messages[0]["role"] == "system"
    prompt_text = chat_completions.PROMPT_PATH.read_text(encoding="utf-8")
    assert messages[0]["content"] in prompt_text
    assert "Choose exactly one legal Reversi" in messages[0]["content"]
    assert chosen.algebraic in messages[1]["content"] or "legal_places" in messages[1]["content"]
    fmt = send["response_format"]
    assert isinstance(fmt, dict)
    assert fmt["type"] == "json_schema"
    schema = fmt["json_schema"]
    assert isinstance(schema, dict)
    assert schema["name"] == "chosen_move"
    assert schema["strict"] is True
    assert schema["schema"] == chat_completions.ChosenMove.model_json_schema()
    assert "temperature" not in send


def test_extra_genai_chat_http_error_is_unplayable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = tmp_path / "openrouter-api-key"
    secret.write_text(_API_KEY, encoding="utf-8")
    monkeypatch.setattr(chat_completions, "SECRET_PATH", secret)

    def boom(kwargs: dict[str, object]) -> SimpleNamespace:
        del kwargs
        raise RuntimeError(f"401 unauthorized {_API_KEY}")

    monkeypatch.setattr(chat_completions, "OpenRouter", _fake_chat_openrouter(boom))
    with pytest.raises(jev.ExternalModelError) as err:
        chat_completions.choose_move(initial_position(), "vendor/extra-chat-model")
    assert _API_KEY not in str(err.value)


def test_extra_genai_chat_rejects_choice_outside_legal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = tmp_path / "openrouter-api-key"
    secret.write_text(_API_KEY, encoding="utf-8")
    monkeypatch.setattr(chat_completions, "SECRET_PATH", secret)
    position = initial_position()
    assert Square.parse("a1") not in legal_places(position)

    def illegal(kwargs: dict[str, object]) -> SimpleNamespace:
        del kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps({"square": "a1"}))
                )
            ]
        )

    monkeypatch.setattr(chat_completions, "OpenRouter", _fake_chat_openrouter(illegal))
    with pytest.raises(jev.ExternalModelError, match="合法手"):
        chat_completions.choose_move(position, "vendor/extra-chat-model")


def test_extra_genai_missing_prompt_file_is_unplayable_without_calling_openrouter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = tmp_path / "openrouter-api-key"
    secret.write_text(_API_KEY, encoding="utf-8")
    monkeypatch.setattr(chat_completions, "SECRET_PATH", secret)
    monkeypatch.setattr(chat_completions, "PROMPT_PATH", tmp_path / "missing.md")
    called = {"n": 0}

    class Boom:
        def __init__(self, **kwargs: object) -> None:
            del kwargs
            called["n"] += 1
            raise AssertionError("指示ファイル欠落時に OpenRouter を呼んではいけない")

    monkeypatch.setattr(chat_completions, "OpenRouter", Boom)
    with pytest.raises(jev.ExternalModelError, match="着手指示"):
        chat_completions.choose_move(initial_position(), "vendor/extra-chat-model")
    assert called["n"] == 0


def test_extra_genai_config_path_is_gitignored_data_file() -> None:
    assert extra_genai.CONFIG_PATH.name == "config.toml"
    assert extra_genai.CONFIG_PATH.parent.name == "data"
    assert extra_genai.CONFIG_PATH == (
        Path(__file__).resolve().parents[2] / "data" / "config.toml"
    )


def test_extra_genai_chat_rejects_free_text_first_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = tmp_path / "openrouter-api-key"
    secret.write_text(_API_KEY, encoding="utf-8")
    monkeypatch.setattr(chat_completions, "SECRET_PATH", secret)
    position = initial_position()
    chosen = legal_places(position)[0]

    def free_text(kwargs: dict[str, object]) -> SimpleNamespace:
        del kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=f"{chosen.algebraic} is the best move"
                    )
                )
            ]
        )

    monkeypatch.setattr(chat_completions, "OpenRouter", _fake_chat_openrouter(free_text))
    with pytest.raises(jev.ExternalModelError, match="検証"):
        chat_completions.choose_move(position, "vendor/extra-chat-model")


def test_extra_genai_chat_passes_sampling_parameters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = tmp_path / "openrouter-api-key"
    secret.write_text(_API_KEY, encoding="utf-8")
    monkeypatch.setattr(chat_completions, "SECRET_PATH", secret)
    position = initial_position()
    chosen = legal_places(position)[0]

    def respond(kwargs: dict[str, object]) -> SimpleNamespace:
        del kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps({"square": chosen.algebraic})
                    )
                )
            ]
        )

    fake = _fake_chat_openrouter(respond)
    monkeypatch.setattr(chat_completions, "OpenRouter", fake)
    move = chat_completions.choose_move(
        position,
        "vendor/extra-chat-model",
        parameters={"temperature": 0.0, "max_tokens": 16},
    )
    assert move is not None
    assert move.square == chosen
    send = fake.last_send
    assert isinstance(send, dict)
    assert send["temperature"] == 0.0
    assert send["max_tokens"] == 16
    assert send["response_format"]["type"] == "json_schema"
