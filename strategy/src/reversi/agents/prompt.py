"""対局時に読む生成 AI の固定指示。リポジトリの `prompts/`。"""

from __future__ import annotations

from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[4] / "prompts"

__all__ = [
    "PROMPTS_DIR",
    "PromptFileError",
    "load_sections",
    "markdown_sections",
    "read_text",
]


class PromptFileError(RuntimeError):
    """指示ファイルの欠落または不正。着手は採用しない。"""


def read_text(path: Path) -> str:
    """UTF-8 の指示ファイルを読む。無い・空なら継続不能とする。"""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptFileError("着手指示ファイルを読めません") from exc
    if not raw.strip():
        raise PromptFileError("着手指示ファイルが空です")
    return raw


def markdown_sections(text: str) -> dict[str, str]:
    """`##` 見出しを小文字の節名として本文を取る。"""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip().lower()
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return {name: "\n".join(body).strip() for name, body in sections.items()}


def load_sections(path: Path, *names: str) -> dict[str, str]:
    """指定した節を読む。欠けるか空なら失敗する。"""
    sections = markdown_sections(read_text(path))
    loaded: dict[str, str] = {}
    for name in names:
        value = sections.get(name, "").strip()
        if not value:
            raise PromptFileError(f"着手指示に {name} がありません")
        loaded[name] = value
    return loaded
