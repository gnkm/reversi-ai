"""OpenRouter の鍵ファイルと Jev Decisions 呼出し境界。"""

from __future__ import annotations

import ast
import os
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from reversi.agents import jev
from reversi.api import openrouter_key
from reversi.engine.board import Square
from reversi.engine.rules import initial_position, legal_places

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
    assert jev.SECRET_PATH == openrouter_key.SECRET_PATH
    assert jev.DECISIONS_SERVER.startswith("https://")
    assert jev.DECISIONS_SERVER == "https://openrouter.ai"
    assert jev.MODEL_ID == "typesafe/jev-1.13"


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
    chosen = places[0]

    def respond(kwargs: dict[str, object]) -> SimpleNamespace:
        del kwargs
        return SimpleNamespace(
            answers={"move": SimpleNamespace(choice=chosen.algebraic, type="choice")},
            api_key=_API_KEY,
        )

    fake = _fake_openrouter(respond)
    monkeypatch.setattr(jev, "OpenRouter", fake)
    move = jev.choose_move(position)
    assert move is not None
    assert move.square == chosen
    init = fake.last_init
    assert isinstance(init, dict)
    assert init["api_key"] == _API_KEY
    assert init["server_url"] == "https://openrouter.ai"
    create = fake.last_create
    assert isinstance(create, dict)
    assert create["model"] == "typesafe/jev-1.13"
    questions = create["questions"]
    assert isinstance(questions, dict)
    criteria = questions["move"]["criteria"]
    assert set(criteria) == {square.algebraic for square in places}


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


def test_jev_rejects_choice_outside_legal_from_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = tmp_path / "openrouter-api-key"
    secret.write_text(_API_KEY, encoding="utf-8")
    monkeypatch.setattr(jev, "SECRET_PATH", secret)
    position = initial_position()
    assert Square.parse("a1") not in legal_places(position)

    def illegal(kwargs: dict[str, object]) -> SimpleNamespace:
        del kwargs
        return SimpleNamespace(
            answers={"move": SimpleNamespace(choice="a1", type="choice")}
        )

    monkeypatch.setattr(jev, "OpenRouter", _fake_openrouter(illegal))
    with pytest.raises(jev.ExternalModelError, match="合法手"):
        jev.choose_move(position)
