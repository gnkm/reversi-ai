"""組込み個体の解説 Markdown。カード説明ではなく docs/catalog に置く。"""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_CATALOG_DOCS = _REPO / "docs" / "catalog"
_BUILTIN = (
    "random_uniform",
    "most_flips",
    "positional",
    "minimax",
    "alphabeta",
    "opening",
    "ml",
    "lgbm",
    "rl",
    "rl_search",
    "rl_tied",
    "nn",
    "jev",
)
_FORBIDDEN = ("対象読者", "理系国立大学受験生", "受験生")


def test_catalog_markdown_explains_each_builtin_specimen() -> None:
    for specimen_id in _BUILTIN:
        path = _CATALOG_DOCS / f"{specimen_id}.md"
        assert path.is_file(), path
        text = path.read_text(encoding="utf-8")
        assert text.strip(), path
        for word in _FORBIDDEN:
            assert word not in text, (path, word)
