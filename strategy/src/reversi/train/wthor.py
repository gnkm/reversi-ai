"""WTHOR の 8×8 棋譜だけを学習入力として読む。

原本はリポジトリ直下の `data/wthor/` に置く。HTTP の静的ファイルとしては出さない。
ヘッダの盤サイズが 0 または 8 でないファイルと、8×8 として再生できないレコードは捨てる。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from reversi.engine.board import BOARD_SIZE, Square
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

HEADER_SIZE = 16
RECORD_SIZE_8X8 = 68
MOVE_LIST_OFFSET = 8
MOVE_LIST_SIZE = 60
EIGHT_BY_EIGHT_SIZES = frozenset({0, 8})
DEFAULT_WTHOR_DIR = Path(__file__).resolve().parents[4] / "data" / "wthor"


@dataclass(frozen=True, slots=True)
class TrainingGame:
    """8×8 として再生できる対局。`squares` はパスを含まない。"""

    squares: tuple[Square, ...]
    black_discs: int


def encode_8x8_move(square: Square) -> int:
    """列 1–8 が 1 の位、行 1–8 が 10 の位。a1 は 11。"""
    return (square.file + 1) + 10 * (square.rank + 1)


def decode_8x8_move(code: int) -> Square | None:
    """8×8 の着手バイト。0 と盤外は None。"""
    file = code % 10 - 1
    rank = code // 10 - 1
    if not (0 <= file < BOARD_SIZE and 0 <= rank < BOARD_SIZE):
        return None
    if code // 10 == 0 or code % 10 == 0:
        return None
    return Square(file=file, rank=rank)


def replay(game: TrainingGame) -> Position:
    """対局エンジンで再生する。棋譜に無いパスは挿入する。"""
    position = initial_position()
    for square in game.squares:
        position = _advance(position, square)
    return position


def training_games(source: Path | None = None) -> tuple[TrainingGame, ...]:
    """`.wtb` またはそのディレクトリから、8×8 だけを返す。

    `source` が無いときは `data/wthor/` を読む。
    """
    path = DEFAULT_WTHOR_DIR if source is None else source
    if path.is_dir():
        games: list[TrainingGame] = []
        for file in _wtb_files(path):
            games.extend(_games_from_file(file))
        return tuple(games)
    if path.is_file():
        return _games_from_file(path)
    return ()


def _wtb_files(directory: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            file
            for file in directory.iterdir()
            if file.is_file() and file.suffix.lower() == ".wtb"
        )
    )


def _games_from_file(path: Path) -> tuple[TrainingGame, ...]:
    data = path.read_bytes()
    if len(data) < HEADER_SIZE:
        return ()
    board_size = data[12]
    if board_size not in EIGHT_BY_EIGHT_SIZES:
        return ()
    n_declared = int.from_bytes(data[4:8], "little")
    payload = data[HEADER_SIZE:]
    n_records = min(n_declared, len(payload) // RECORD_SIZE_8X8)
    games: list[TrainingGame] = []
    for index in range(n_records):
        start = index * RECORD_SIZE_8X8
        record = payload[start : start + RECORD_SIZE_8X8]
        game = _game_from_record(record)
        if game is not None:
            games.append(game)
    return tuple(games)


def _game_from_record(record: bytes) -> TrainingGame | None:
    codes = record[MOVE_LIST_OFFSET : MOVE_LIST_OFFSET + MOVE_LIST_SIZE]
    squares = _squares_from_codes(codes)
    if squares is None:
        return None
    game = TrainingGame(squares=squares, black_discs=record[6])
    try:
        replay(game)
    except IllegalMoveError:
        return None
    return game


def _squares_from_codes(codes: Iterable[int]) -> tuple[Square, ...] | None:
    squares: list[Square] = []
    for code in codes:
        if code == 0:
            break
        square = decode_8x8_move(code)
        if square is None:
            return None
        squares.append(square)
    return tuple(squares)


def _advance(position: Position, square: Square) -> Position:
    if is_over(position):
        raise IllegalMoveError("終局のあとに着手があります")
    if pass_is_legal(position):
        position = play(position, PassMove())
    return play(position, Place(square))
