"""Pod 内 HTTP。`python -m reversi.api` で待ち受ける。"""

from __future__ import annotations

import uvicorn

from reversi.api.app import app

HOST = "0.0.0.0"
PORT = 8000


def main() -> None:
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
