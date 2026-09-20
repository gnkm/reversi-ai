"""対局経路の ML / RL が NN ランタイムや OpenRouter を import しないこと。"""

from __future__ import annotations

import ast
import tomllib
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
    if (_SRC / "agents" / "lgbm.py").is_file():
        names.append("lgbm.py")
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



def test_ml_play_path_does_not_import_nn_runtime_or_sklearn() -> None:
    source = _read("agents", "ml.py")
    roots = _imported_roots(source)
    assert "torch" not in roots
    assert "onnxruntime" not in roots
    assert "sklearn" not in roots
    assert "openrouter" not in roots
    assert "numpy" not in roots
    assert roots.isdisjoint(_NN_RUNTIME_ROOTS)
    modules = _imported_modules(source)
    assert "reversi.train" not in modules
    assert all(not name.startswith("reversi.train") for name in modules)
    for literal in _string_literals(source):
        lowered = literal.lower()
        assert "ffothello.org" not in lowered
        assert ".wtb" not in lowered
        assert "openrouter.ai" not in lowered


def test_ml_training_script_uses_sklearn_and_wthor_and_games() -> None:
    source = _read("train", "ml.py")
    roots = _imported_roots(source)
    modules = _imported_modules(source)
    assert "sklearn" in roots
    assert "torch" not in roots
    assert "onnxruntime" not in roots
    assert roots.isdisjoint(_NN_RUNTIME_ROOTS)
    assert "reversi.train.wthor" in modules or any(
        name.startswith("reversi.train.wthor") for name in modules
    )
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
    assert "--wthor" in option_strings
    assert "--games" in option_strings
    for literal in _string_literals(source):
        lowered = literal.lower()
        assert "openrouter.ai" not in lowered


def test_play_time_ml_and_rl_files_avoid_nn_runtimes() -> None:
    for name in _agent_files():
        source = _read("agents", name)
        roots = _imported_roots(source)
        assert roots.isdisjoint(_NN_RUNTIME_ROOTS), name
        assert "openrouter" not in roots
        assert "sklearn" not in roots
        assert "torch" not in roots
        assert "onnxruntime" not in roots
        assert "joblib" not in roots
        assert "pickle" not in roots


def test_lgbm_play_path_imports_lightgbm_not_nn_runtime() -> None:
    source = _read("agents", "lgbm.py")
    roots = _imported_roots(source)
    assert "lightgbm" in roots
    assert "torch" not in roots
    assert "onnxruntime" not in roots
    assert "sklearn" not in roots
    assert "joblib" not in roots
    assert "pickle" not in roots
    assert "openrouter" not in roots
    assert roots.isdisjoint(_NN_RUNTIME_ROOTS)
    modules = _imported_modules(source)
    assert "reversi.train" not in modules
    assert all(not name.startswith("reversi.train") for name in modules)
    for literal in _string_literals(source):
        lowered = literal.lower()
        assert "ffothello.org" not in lowered
        assert ".wtb" not in lowered
        assert "openrouter.ai" not in lowered


def test_lgbm_training_script_uses_lightgbm_and_wthor_and_games() -> None:
    source = _read("train", "lgbm.py")
    roots = _imported_roots(source)
    modules = _imported_modules(source)
    assert "lightgbm" in roots
    assert "sklearn" not in roots
    assert "torch" not in roots
    assert "onnxruntime" not in roots
    assert "joblib" not in roots
    assert "pickle" not in roots
    assert roots.isdisjoint(_NN_RUNTIME_ROOTS)
    assert "reversi.train.wthor" in modules or any(
        name.startswith("reversi.train.wthor") for name in modules
    )
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
    assert "--wthor" in option_strings
    assert "--games" in option_strings
    for literal in _string_literals(source):
        lowered = literal.lower()
        assert "openrouter.ai" not in lowered


def _train_group_packages() -> tuple[str, ...]:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    names: list[str] = []
    for requirement in data["dependency-groups"]["train"]:
        names.append(requirement.split(">", 1)[0].split("=", 1)[0].split("[", 1)[0])
    return tuple(names)


def test_train_group_includes_onnx_and_torch() -> None:
    packages = _train_group_packages()
    assert "onnx" in packages
    assert "torch" in packages


def test_containerfile_bakes_train_group_only_on_train_target() -> None:
    text = (Path(__file__).resolve().parents[1] / "Containerfile").read_text(
        encoding="utf-8",
    )
    train_stage, _, rest = text.partition("FROM base AS train")
    strategy_stage = rest.partition("FROM base AS strategy")[2]
    assert "uv sync --frozen --no-dev --group train" in rest.partition(
        "FROM base AS strategy",
    )[0]
    assert "--group train" not in strategy_stage
    assert "--group train" not in train_stage
