"""終局対局を SQLite へ書く。形式は .wtb ではない。"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from reversi.engine.board import Board
from reversi.engine.rules import Position, is_over
from reversi.engine.score import official_score

DEFAULT_DB_PATH: Final[Path] = (
    Path(__file__).resolve().parents[4] / "data" / "games.sqlite"
)
MODE_HUMAN_VS_AGENT = "human_vs_agent"
MODE_AGENT_VS_AGENT = "agent_vs_agent"
MODES: Final[frozenset[str]] = frozenset(
    {MODE_HUMAN_VS_AGENT, MODE_AGENT_VS_AGENT}
)
WINNERS: Final[frozenset[str]] = frozenset({"black", "white", "draw"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY,
    mode TEXT NOT NULL,
    black TEXT NOT NULL,
    white TEXT NOT NULL,
    moves TEXT NOT NULL,
    final_board TEXT NOT NULL,
    score_black INTEGER NOT NULL,
    score_white INTEGER NOT NULL,
    winner TEXT NOT NULL
)
"""

_INSERT = """
INSERT INTO games (
    mode, black, white, moves, final_board,
    score_black, score_white, winner
) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""

_SELECT = """
SELECT mode, black, white, moves, final_board,
       score_black, score_white, winner
FROM games
ORDER BY id
"""


@dataclass(frozen=True, slots=True)
class FinishedGame:
    """SRS-DAT-004 が求める終局棋譜。個人識別子は持たない。"""

    mode: str
    black: Mapping[str, str]
    white: Mapping[str, str]
    moves: tuple[Mapping[str, str], ...]
    final_board: tuple[tuple[str, ...], ...]
    score_black: int
    score_white: int
    winner: str


def board_cells(board: Board) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(stone.value for stone in row) for row in board.cells)


def winner_of(score_black: int, score_white: int) -> str:
    if score_black > score_white:
        return "black"
    if score_white > score_black:
        return "white"
    return "draw"


def save(game: FinishedGame, db_path: Path | None = None) -> None:
    """終局棋譜を 1 行書く。"""
    if game.mode not in MODES:
        raise ValueError(f"未知の対局モードです: {game.mode!r}")
    if game.winner not in WINNERS:
        raise ValueError(f"未知の勝敗です: {game.winner!r}")
    path = db_path if db_path is not None else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        game.mode,
        json.dumps(dict(game.black), ensure_ascii=False),
        json.dumps(dict(game.white), ensure_ascii=False),
        json.dumps([dict(move) for move in game.moves], ensure_ascii=False),
        json.dumps([list(row) for row in game.final_board], ensure_ascii=False),
        game.score_black,
        game.score_white,
        game.winner,
    )
    with sqlite3.connect(path) as conn:
        conn.execute(_SCHEMA)
        conn.execute(_INSERT, payload)


def save_if_over(
    position: Position,
    *,
    mode: str,
    black: Mapping[str, str],
    white: Mapping[str, str],
    moves: Sequence[Mapping[str, str]],
    db_path: Path | None = None,
) -> bool:
    """終局なら書き、進行中ならファイルにも行にも触れない。"""
    if not is_over(position):
        return False
    score = official_score(position.board)
    save(
        FinishedGame(
            mode=mode,
            black=black,
            white=white,
            moves=tuple(moves),
            final_board=board_cells(position.board),
            score_black=score.black,
            score_white=score.white,
            winner=winner_of(score.black, score.white),
        ),
        db_path,
    )
    return True


def load(db_path: Path | None = None) -> tuple[FinishedGame, ...]:
    path = db_path if db_path is not None else DEFAULT_DB_PATH
    if not path.exists():
        return ()
    with sqlite3.connect(path) as conn:
        rows = conn.execute(_SELECT).fetchall()
    return tuple(_from_row(row) for row in rows)


def column_names(db_path: Path) -> tuple[str, ...]:
    with sqlite3.connect(db_path) as conn:
        info = conn.execute("PRAGMA table_info(games)").fetchall()
    return tuple(str(row[1]) for row in info)


def _from_row(row: tuple[object, ...]) -> FinishedGame:
    mode, black, white, moves, final_board, score_black, score_white, winner = row
    return FinishedGame(
        mode=str(mode),
        black=json.loads(str(black)),
        white=json.loads(str(white)),
        moves=tuple(json.loads(str(moves))),
        final_board=tuple(tuple(cell) for cell in json.loads(str(final_board))),
        score_black=int(score_black),  # type: ignore[arg-type]
        score_white=int(score_white),  # type: ignore[arg-type]
        winner=str(winner),
    )
