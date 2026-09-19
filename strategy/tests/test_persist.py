"""終局対局の SQLite 永続化。進行中は書かない。個人識別子の列は無い。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from random import Random

from reversi.agents.random_uniform import SPECIMEN_ID
from reversi.api.persist import (
    DEFAULT_DB_PATH,
    MODE_AGENT_VS_AGENT,
    MODE_HUMAN_VS_AGENT,
    column_names,
    load,
    save_if_over,
)
from reversi.api.schemas import CreateGameRequest, HumanPlayer, SpecimenPlayer
from reversi.api.session import GameStore
from reversi.engine.board import Color, Square, Stone, empty_board
from reversi.engine.rules import Position, initial_position, is_over
from reversi.engine.score import official_score

_HUMAN = {"kind": "human"}
_SPECIMEN = {"kind": "specimen", "specimen_id": SPECIMEN_ID}
_PII_COLUMNS = (
    "user_id",
    "userid",
    "user",
    "name",
    "email",
    "mail",
    "氏名",
    "メール",
    "username",
    "full_name",
)


def _terminal_white_win() -> Position:
    board = empty_board().replacing(
        {
            Square.parse("a1"): Stone.EMPTY,
            Square.parse("h8"): Stone.EMPTY,
            **{
                Square(file=file, rank=rank): Stone.WHITE
                for rank in range(8)
                for file in range(8)
                if (file, rank) not in {(0, 0), (7, 7)}
            },
        }
    )
    return Position(board, Color.BLACK)


def test_default_path_is_data_games_sqlite() -> None:
    assert DEFAULT_DB_PATH.name == "games.sqlite"
    assert DEFAULT_DB_PATH.suffix == ".sqlite"
    assert DEFAULT_DB_PATH.parts[-2:] == ("data", "games.sqlite")
    assert DEFAULT_DB_PATH.suffix != ".wtb"


def test_finished_game_persists_required_fields(tmp_path: Path) -> None:
    path = tmp_path / "games.sqlite"
    position = _terminal_white_win()
    assert is_over(position)
    moves = (
        {"type": "place", "square": "f5"},
        {"type": "pass"},
    )
    written = save_if_over(
        position,
        mode=MODE_HUMAN_VS_AGENT,
        black=_HUMAN,
        white=_SPECIMEN,
        moves=moves,
        db_path=path,
    )
    assert written is True
    assert path.is_file()
    assert path.read_bytes()[:16] == b"SQLite format 3\x00"
    games = load(path)
    assert len(games) == 1
    game = games[0]
    score = official_score(position.board)
    assert game.mode == MODE_HUMAN_VS_AGENT
    assert dict(game.black) == _HUMAN
    assert dict(game.white) == _SPECIMEN
    assert tuple(dict(move) for move in game.moves) == moves
    assert game.final_board[0][0] == "empty"
    assert game.final_board[7][7] == "empty"
    assert game.final_board[0][1] == "white"
    assert game.score_black == score.black
    assert game.score_white == score.white
    assert game.winner == "white"
    assert game.score_black == 0
    assert game.score_white == 64


def test_schema_has_no_personal_identifier_columns(tmp_path: Path) -> None:
    path = tmp_path / "games.sqlite"
    save_if_over(
        _terminal_white_win(),
        mode=MODE_AGENT_VS_AGENT,
        black=_SPECIMEN,
        white=_SPECIMEN,
        moves=(),
        db_path=path,
    )
    names = column_names(path)
    lowered = {name.lower() for name in names}
    for forbidden in _PII_COLUMNS:
        assert forbidden not in lowered
        assert forbidden not in names
    required = {
        "mode",
        "black",
        "white",
        "moves",
        "final_board",
        "score_black",
        "score_white",
        "winner",
    }
    assert required <= set(names)


def test_in_progress_game_is_not_written(tmp_path: Path) -> None:
    path = tmp_path / "games.sqlite"
    written = save_if_over(
        initial_position(),
        mode=MODE_HUMAN_VS_AGENT,
        black=_HUMAN,
        white=_SPECIMEN,
        moves=(),
        db_path=path,
    )
    assert written is False
    assert not path.exists()
    assert load(path) == ()


def test_in_progress_does_not_append_to_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "games.sqlite"
    save_if_over(
        _terminal_white_win(),
        mode=MODE_AGENT_VS_AGENT,
        black=_SPECIMEN,
        white=_SPECIMEN,
        moves=(),
        db_path=path,
    )
    before = path.read_bytes()
    written = save_if_over(
        initial_position(),
        mode=MODE_HUMAN_VS_AGENT,
        black=_HUMAN,
        white=_SPECIMEN,
        moves=({"type": "place", "square": "f5"},),
        db_path=path,
    )
    assert written is False
    assert len(load(path)) == 1
    with sqlite3.connect(path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    assert count == 1
    assert path.read_bytes() == before


def test_session_persists_finished_agent_game_only(tmp_path: Path) -> None:
    path = tmp_path / "games.sqlite"
    store = GameStore(rng=Random(0), db_path=path)
    opening = store.start(
        CreateGameRequest(
            black=HumanPlayer(kind="human"),
            white=SpecimenPlayer(kind="specimen", specimen_id=SPECIMEN_ID),
        )
    )
    assert opening.is_over is False
    assert not path.exists()

    finished = store.start(
        CreateGameRequest(
            black=SpecimenPlayer(kind="specimen", specimen_id=SPECIMEN_ID),
            white=SpecimenPlayer(kind="specimen", specimen_id=SPECIMEN_ID),
        )
    )
    assert finished.is_over is True
    games = load(path)
    assert len(games) == 1
    game = games[0]
    assert game.mode == MODE_AGENT_VS_AGENT
    assert dict(game.black) == _SPECIMEN
    assert dict(game.white) == _SPECIMEN
    assert game.moves
    assert all(move["type"] in {"place", "pass"} for move in game.moves)
    assert len(game.final_board) == 8
    assert all(len(row) == 8 for row in game.final_board)
    assert game.score_black + game.score_white == 64
    assert game.winner in {"black", "white", "draw"}
    assert finished.result is not None
    assert game.winner == finished.result.winner
    assert game.score_black == finished.official_score.black
    assert game.score_white == finished.official_score.white
