"""WTHOR と永続化対局から教師あり学習例を集める。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np

from reversi.encode import VECTOR_SIZE, encode
from reversi.engine.board import Board, Color, Square
from reversi.engine.rules import (
    IllegalMoveError,
    PassMove,
    Place,
    Position,
    initial_position,
    is_over,
    pass_is_legal,
    play,
)
from reversi.engine.score import official_score
from reversi.train.wthor import DEFAULT_WTHOR_DIR, TrainingGame, training_games

DEFAULT_GAMES_DB = Path(__file__).resolve().parents[4] / "data" / "games.sqlite"

__all__ = [
    "DEFAULT_GAMES_DB",
    "collect_examples",
]


def _black_label(winner: str | None, board: Board) -> float:
    if winner == "black":
        return 1.0
    if winner == "white":
        return -1.0
    if winner == "draw":
        return 0.0
    score = official_score(board)
    if score.black > score.white:
        return 1.0
    if score.white > score.black:
        return -1.0
    return 0.0


def _afterstates_from_squares(squares: tuple[Square, ...]) -> tuple[Board, ...] | None:
    position = initial_position()
    boards: list[Board] = []
    for square in squares:
        if is_over(position):
            return None
        if pass_is_legal(position):
            position = play(position, PassMove())
        try:
            position = play(position, Place(square))
        except IllegalMoveError:
            return None
        boards.append(position.board)
    if not boards:
        return None
    return tuple(boards)


def _finished_boards(boards: tuple[Board, ...] | None) -> tuple[Board, ...] | None:
    """終局していない再生は学習に使わない。"""
    if boards is None:
        return None
    if not is_over(Position(boards[-1], Color.BLACK)):
        return None
    return boards


def _examples_from_wthor_game(game: TrainingGame) -> tuple[tuple[np.ndarray, float], ...]:
    boards = _finished_boards(_afterstates_from_squares(game.squares))
    if boards is None:
        return ()
    label = _black_label(None, boards[-1])
    return tuple(
        (np.asarray(encode(board).as_vector(), dtype=np.float64), label) for board in boards
    )


def _examples_from_wthor(source: Path) -> tuple[tuple[np.ndarray, float], ...]:
    examples: list[tuple[np.ndarray, float]] = []
    for game in training_games(source):
        examples.extend(_examples_from_wthor_game(game))
    return tuple(examples)


def _replay_persisted_moves(
    moves: tuple[object, ...],
) -> tuple[Board, ...] | None:
    position = initial_position()
    boards: list[Board] = []
    for raw in moves:
        if not isinstance(raw, dict):
            return None
        move_type = raw.get("type")
        if move_type == "pass":
            if not pass_is_legal(position):
                return None
            position = play(position, PassMove())
            continue
        if move_type != "place":
            return None
        square_text = raw.get("square")
        if not isinstance(square_text, str):
            return None
        try:
            square = Square.parse(square_text)
            position = play(position, Place(square))
        except (IllegalMoveError, ValueError):
            return None
        boards.append(position.board)
    if not boards:
        return None
    return tuple(boards)


def _examples_from_games(db_path: Path) -> tuple[tuple[np.ndarray, float], ...]:
    if not db_path.is_file():
        return ()
    with sqlite3.connect(db_path) as conn:
        try:
            rows = conn.execute("SELECT moves, winner FROM games").fetchall()
        except sqlite3.Error:
            return ()
    examples: list[tuple[np.ndarray, float]] = []
    for moves_json, winner in rows:
        try:
            moves = tuple(json.loads(str(moves_json)))
        except json.JSONDecodeError:
            continue
        boards = _finished_boards(_replay_persisted_moves(moves))
        if boards is None:
            continue
        label = _black_label(str(winner), boards[-1])
        examples.extend(
            (np.asarray(encode(board).as_vector(), dtype=np.float64), label)
            for board in boards
        )
    return tuple(examples)


def collect_examples(
    wthor: Path | None = None,
    games: Path | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """終局棋譜の着手後盤と、黒から見た勝敗ラベルを返す。"""
    collected = _examples_from_wthor(
        DEFAULT_WTHOR_DIR if wthor is None else wthor,
    ) + _examples_from_games(DEFAULT_GAMES_DB if games is None else games)
    if not collected:
        raise ValueError("学習例がありません。WTHOR または永続化対局が必要です")
    features = np.stack([row for row, _ in collected])
    labels = np.asarray([label for _, label in collected], dtype=np.float64)
    if features.shape[1] != VECTOR_SIZE:
        raise ValueError(f"特徴量の長さは {VECTOR_SIZE} でなければなりません")
    return features, labels
