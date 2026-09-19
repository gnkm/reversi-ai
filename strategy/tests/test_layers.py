"""対局経路の ML / RL が NN ランタイムや OpenRouter を import しないこと。"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src" / "reversi"
_NN_RUNTIME_ROOTS = frozenset(
    {
        "torch",
        "onnxruntime",
        "onnx",
        "tensorflow",
        "keras",
        "openrouter",
    }
)
_WTHOR_ROOTS = frozenset({"wthor"})


def _read(package: str, name: str) -> str:
    return (_SRC / package / name).read_text(encoding="utf-8")


def _imported_roots(source: str) -> set[str]:
    tree = ast.parse(source)
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
            if node.module.startswith("reversi.train"):
                parts = node.module.split(".")
                if len(parts) >= 3:
                    roots.add(parts[2])
    return roots


def _imported_modules(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(
                f"{node.module}.{alias.name}" for alias in node.names if alias.name
            )
    return names


def _string_literals(source: str) -> tuple[str, ...]:
    tree = ast.parse(source)
    values: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            values.append(node.value)
    return tuple(values)


def _agent_files() -> tuple[str, ...]:
    names = ["rl.py"]
    if (_SRC / "agents" / "ml.py").is_file():
        names.append("ml.py")
    return tuple(names)


def test_rl_play_path_does_not_import_nn_runtime_or_openrouter() -> None:
    source = _read("agents", "rl.py")
    roots = _imported_roots(source)
    assert "torch" not in roots
    assert "onnxruntime" not in roots
    assert "openrouter" not in roots
    assert roots.isdisjoint(_NN_RUNTIME_ROOTS)
    assert "numpy" not in roots
    modules = _imported_modules(source)
    assert "reversi.train" not in modules
    assert all(not name.startswith("reversi.train") for name in modules)
    for literal in _string_literals(source):
        lowered = literal.lower()
        assert "ffothello.org" not in lowered
        assert ".wtb" not in lowered
        assert "openrouter.ai" not in lowered


def test_rl_training_script_does_not_read_wthor() -> None:
    source = _read("train", "rl.py")
    roots = _imported_roots(source)
    modules = _imported_modules(source)
    assert roots.isdisjoint(_NN_RUNTIME_ROOTS)
    assert roots.isdisjoint(_WTHOR_ROOTS)
    assert "openrouter" not in roots
    assert "torch" not in roots
    assert "onnxruntime" not in roots
    assert all(not name.endswith(".wthor") and ".wthor." not in name for name in modules)
    assert "reversi.train.wthor" not in modules
    tree = ast.parse(source)
    option_strings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            attr = func.attr if isinstance(func, ast.Attribute) else ""
            if attr == "add_argument":
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        option_strings.append(arg.value)
    assert "--wthor" not in option_strings
    for literal in _string_literals(source):
        lowered = literal.lower()
        assert ".wtb" not in lowered
        assert "ffothello.org" not in lowered
        assert "data/wthor" not in lowered



def test_play_time_ml_and_rl_files_avoid_nn_runtimes() -> None:
    for name in _agent_files():
        source = _read("agents", name)
        roots = _imported_roots(source)
        assert roots.isdisjoint(_NN_RUNTIME_ROOTS), name
        assert "openrouter" not in roots
