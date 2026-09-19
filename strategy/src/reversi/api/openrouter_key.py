"""Podman secret の OpenRouter API キーだけを読む。環境変数へはコピーしない。"""

from __future__ import annotations

from pathlib import Path

SECRET_PATH = Path("/run/secrets/openrouter-api-key")

__all__ = ["SECRET_PATH", "OpenRouterKeyError", "read_api_key"]


class OpenRouterKeyError(RuntimeError):
    """鍵ファイルが読めない。本文に鍵は含めない。"""


def read_api_key(path: Path | None = None) -> str:
    """`/run/secrets/openrouter-api-key` だけを読む。空なら失敗。"""
    target = SECRET_PATH if path is None else path
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise OpenRouterKeyError("OpenRouter の資格情報ファイルを読めません") from exc
    key = raw.strip()
    if not key:
        raise OpenRouterKeyError("OpenRouter の資格情報ファイルが空です")
    return key
