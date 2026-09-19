"""Podman secret の OpenRouter API キーだけを読む。環境変数へはコピーしない。"""

from __future__ import annotations

from pathlib import Path

from reversi.agents.jev import SECRET_PATH, ExternalModelError, read_secret

__all__ = ["SECRET_PATH", "OpenRouterKeyError", "read_api_key"]


class OpenRouterKeyError(RuntimeError):
    """鍵ファイルが読めない。本文に鍵は含めない。"""


def read_api_key(path: Path | None = None) -> str:
    """`/run/secrets/openrouter-api-key` だけを読む。空なら失敗。"""
    try:
        return read_secret(SECRET_PATH if path is None else path)
    except ExternalModelError as exc:
        raise OpenRouterKeyError(*exc.args) from None
