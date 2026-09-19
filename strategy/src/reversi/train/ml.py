"""sklearn で線形モデルを学習し、対局用の係数 JSON を書く。

データ源は WTHOR と永続化対局。成果物は models/ml.json。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import numpy as np
from sklearn.linear_model import Ridge

from reversi.agents.ml import ALGORITHM, LinearModel, load_model
from reversi.encode import VECTOR_SIZE, encode
from reversi.engine.board import Board, Square
from reversi.engine.rules import (
    IllegalMoveError,
    PassMove,
    Place,
    initial_position,
    is_over,
    pass_is_legal,
    play,
)
from reversi.engine.score import official_score
from reversi.train.wthor import DEFAULT_WTHOR_DIR, TrainingGame, training_games

DEFAULT_OUT = Path(__file__).resolve().parents[4] / "models" / "ml.json"
DEFAULT_GAMES_DB = Path(__file__).resolve().parents[4] / "data" / "games.sqlite"
DEFAULT_ALPHA = 1.0

__all__ = [
    "DEFAULT_GAMES_DB",
    "DEFAULT_OUT",
    "dump_model",
    "train",
    "train_and_write",
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


def _examples_from_wthor_game(game: TrainingGame) -> tuple[tuple[np.ndarray, float], ...]:
    boards = _afterstates_from_squares(game.squares)
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
        boards = _replay_persisted_moves(moves)
        if boards is None:
            continue
        label = _black_label(str(winner), boards[-1])
        examples.extend(
            (np.asarray(encode(board).as_vector(), dtype=np.float64), label)
            for board in boards
        )
    return tuple(examples)


def _collect_examples(
    wthor: Path,
    games: Path,
) -> tuple[np.ndarray, np.ndarray]:
    collected = _examples_from_wthor(wthor) + _examples_from_games(games)
    if not collected:
        raise ValueError("学習例がありません。WTHOR または永続化対局が必要です")
    features = np.stack([row for row, _ in collected])
    labels = np.asarray([label for _, label in collected], dtype=np.float64)
    return features, labels


def _fit_ridge(features: np.ndarray, labels: np.ndarray, alpha: float) -> LinearModel:
    estimator = Ridge(alpha=alpha)
    estimator.fit(features, labels)
    weights = tuple(float(value) for value in np.asarray(estimator.coef_).ravel())
    intercept = np.asarray(estimator.intercept_).reshape(-1)
    return LinearModel(weights=weights, bias=float(intercept[0]))


def train(
    *,
    wthor: Path | None = None,
    games: Path | None = None,
    alpha: float = DEFAULT_ALPHA,
) -> LinearModel:
    """WTHOR と永続化対局から Ridge を学習し、対局用の係数を返す。"""
    features, labels = _collect_examples(
        DEFAULT_WTHOR_DIR if wthor is None else wthor,
        DEFAULT_GAMES_DB if games is None else games,
    )
    if features.shape[1] != VECTOR_SIZE:
        raise ValueError(f"特徴量の長さは {VECTOR_SIZE} でなければなりません")
    return _fit_ridge(features, labels, alpha)


def dump_model(path: Path, model: LinearModel) -> None:
    """対局経路が読む JSON を書く。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "algorithm": ALGORITHM,
        "weights": [float(value) for value in model.weights],
        "bias": float(model.bias),
    }
    path.write_text(
        json.dumps(payload, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def train_and_write(
    path: Path,
    *,
    wthor: Path | None = None,
    games: Path | None = None,
    alpha: float = DEFAULT_ALPHA,
) -> LinearModel:
    """学習して `path` に書き、読めることを確認する。"""
    model = train(wthor=wthor, games=games, alpha=alpha)
    dump_model(path, model)
    load_model(path)
    return model


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="WTHOR と永続化対局から sklearn の線形モデルを学習し、対局用係数を書く。",
    )
    parser.add_argument("--wthor", type=Path, default=DEFAULT_WTHOR_DIR)
    parser.add_argument("--games", type=Path, default=DEFAULT_GAMES_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--alpha", type=float, default=DEFAULT_ALPHA)
    args = parser.parse_args(argv)
    train_and_write(args.out, wthor=args.wthor, games=args.games, alpha=args.alpha)


if __name__ == "__main__":
    main()
