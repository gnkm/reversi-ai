"""PyTorch CPU で教師あり学習し、対局用 ONNX を書く。

データ源は WTHOR と永続化対局。自己対局は使わない。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from reversi.agents.nn import (
    DEFAULT_MODEL_PATH,
    INPUT_NAME,
    OUTPUT_NAME,
    OUTPUT_SIZE,
    infer_logits,
    square_index,
)
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
from reversi.train.wthor import DEFAULT_WTHOR_DIR, training_games

DEFAULT_GAMES_DB = Path(__file__).resolve().parents[4] / "data" / "games.sqlite"
DEFAULT_HIDDEN = 32
DEFAULT_EPOCHS = 8
DEFAULT_SEED = 0
PLANES = 3
BOARD = 8

__all__ = [
    "DEFAULT_GAMES_DB",
    "DEFAULT_HIDDEN",
    "Example",
    "collect_examples",
    "train_and_write",
]


@dataclass(frozen=True, slots=True)
class Example:
    """着手直前の盤と、棋譜の合法手。"""

    board: Board
    square: Square


def _require_torch():
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError(
            "NN の学習には PyTorch CPU が必要です。"
            "`podman compose run --rm train python -m reversi.train.nn` を使います。"
            "対局用の strategy イメージには torch を入れません。"
        ) from exc
    return torch


def _planes(board: Board) -> list[list[list[int]]]:
    encoded = encode(board)
    return [[list(row) for row in plane] for plane in encoded.planes]


def _examples_from_squares(squares: Sequence[Square]) -> tuple[Example, ...]:
    position = initial_position()
    examples: list[Example] = []
    for square in squares:
        if is_over(position):
            break
        if pass_is_legal(position):
            position = play(position, PassMove())
        if is_over(position):
            break
        before = position
        try:
            position = play(position, Place(square))
        except IllegalMoveError:
            return ()
        examples.append(Example(board=before.board, square=square))
    return tuple(examples)


def _examples_from_payloads(
    moves: Sequence[Mapping[str, str]],
) -> tuple[Example, ...]:
    position = initial_position()
    examples: list[Example] = []
    try:
        for move in moves:
            if is_over(position):
                break
            kind = move.get("type")
            if kind == "pass":
                position = play(position, PassMove())
                continue
            if kind != "place" or "square" not in move:
                return ()
            square = Square.parse(move["square"])
            before = position
            position = play(position, Place(square))
            examples.append(Example(board=before.board, square=square))
    except (IllegalMoveError, ValueError):
        return ()
    return tuple(examples)


def _examples_from_wthor(path: Path) -> tuple[Example, ...]:
    examples: list[Example] = []
    for game in training_games(path):
        examples.extend(_examples_from_squares(game.squares))
    return tuple(examples)


def _move_list_from_payload(payload: object) -> tuple[Mapping[str, str], ...] | None:
    """1 局の着手列。壊れた JSON や形の違う行は捨てる。"""
    try:
        moves = json.loads(str(payload))
    except json.JSONDecodeError:
        return None
    if not isinstance(moves, list):
        return None
    parsed: list[Mapping[str, str]] = []
    for move in moves:
        if not isinstance(move, dict):
            return None
        parsed.append(move)
    return tuple(parsed)


def _finished_move_lists(db_path: Path) -> tuple[tuple[Mapping[str, str], ...], ...]:
    if not db_path.exists():
        return ()
    with sqlite3.connect(db_path) as conn:
        try:
            rows = conn.execute("SELECT moves FROM games ORDER BY id").fetchall()
        except sqlite3.Error:
            return ()
    games: list[tuple[Mapping[str, str], ...]] = []
    for (payload,) in rows:
        moves = _move_list_from_payload(payload)
        if moves is not None:
            games.append(moves)
    return tuple(games)


def _examples_from_games(db_path: Path) -> tuple[Example, ...]:
    examples: list[Example] = []
    for moves in _finished_move_lists(db_path):
        examples.extend(_examples_from_payloads(moves))
    return tuple(examples)


def collect_examples(
    wthor: Path | None = None,
    games: Path | None = None,
) -> tuple[Example, ...]:
    """WTHOR と永続化対局から (盤, 着手) を集める。"""
    wthor_path = DEFAULT_WTHOR_DIR if wthor is None else wthor
    games_path = DEFAULT_GAMES_DB if games is None else games
    return _examples_from_wthor(wthor_path) + _examples_from_games(games_path)


def _policy_net(torch, hidden: int):
    class PolicyNet(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.hidden = torch.nn.Linear(VECTOR_SIZE, hidden)
            self.out = torch.nn.Linear(hidden, OUTPUT_SIZE)

        def forward(self, board: torch.Tensor) -> torch.Tensor:
            flat = board.reshape(board.shape[0], -1)
            return self.out(torch.relu(self.hidden(flat)))

    return PolicyNet()


def _fit(torch, model, examples: tuple[Example, ...], epochs: int, seed: int) -> None:
    torch.manual_seed(seed)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
    loss_fn = torch.nn.CrossEntropyLoss()
    boards = torch.tensor(
        [_planes(example.board) for example in examples],
        dtype=torch.float32,
    )
    targets = torch.tensor(
        [square_index(example.square) for example in examples],
        dtype=torch.long,
    )
    model.train()
    for _ in range(epochs):
        optimizer.zero_grad()
        loss = loss_fn(model(boards), targets)
        loss.backward()
        optimizer.step()


def _export_onnx(torch, model, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    dummy = torch.zeros(1, PLANES, BOARD, BOARD)
    model.eval()
    kwargs = {
        "input_names": [INPUT_NAME],
        "output_names": [OUTPUT_NAME],
        "opset_version": 17,
    }
    try:
        torch.onnx.export(model, dummy, str(path), dynamo=False, **kwargs)
    except TypeError:
        torch.onnx.export(model, dummy, str(path), **kwargs)


def train_and_write(
    path: Path,
    *,
    wthor: Path | None = None,
    games: Path | None = None,
    hidden: int = DEFAULT_HIDDEN,
    epochs: int = DEFAULT_EPOCHS,
    seed: int = DEFAULT_SEED,
) -> int:
    """教師あり学習して ONNX を書き、対局経路で読めることを確認する。

    棋譜が空でも初期重みを書き出し、再学習なしでカタログが動くようにする。
    """
    torch = _require_torch()
    torch.manual_seed(seed)
    examples = collect_examples(wthor, games)
    model = _policy_net(torch, hidden)
    if examples:
        _fit(torch, model, examples, epochs, seed)
    _export_onnx(torch, model, path)
    infer_logits(initial_position().board, path)
    return len(examples)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="WTHOR と永続化対局で教師あり学習し、対局用 ONNX を書く。",
    )
    parser.add_argument("--wthor", type=Path, default=DEFAULT_WTHOR_DIR)
    parser.add_argument("--games", type=Path, default=DEFAULT_GAMES_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--hidden", type=int, default=DEFAULT_HIDDEN)
    parser.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args(argv)
    n_examples = train_and_write(
        args.out,
        wthor=args.wthor,
        games=args.games,
        hidden=args.hidden,
        epochs=args.epochs,
        seed=args.seed,
    )
    print(f"wrote {args.out} from {n_examples} examples")


if __name__ == "__main__":
    main()
