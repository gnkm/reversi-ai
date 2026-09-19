"""WTHOR の 8×8 棋譜だけを学習入力として読む。"""

from __future__ import annotations

from pathlib import Path

from reversi.engine.board import Color, Square, Stone
from reversi.engine.rules import (
    PassMove,
    Place,
    initial_position,
    is_over,
    legal_places,
    pass_is_legal,
    play,
)
from reversi.train.wthor import (
    DEFAULT_WTHOR_DIR,
    RECORD_SIZE_8X8,
    TrainingGame,
    decode_8x8_move,
    encode_8x8_move,
    replay,
    training_games,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _header(n_games: int, board_size: int) -> bytes:
    buf = bytearray(16)
    buf[0:4] = bytes((20, 26, 9, 19))
    buf[4:8] = n_games.to_bytes(4, "little")
    buf[10:12] = (2026).to_bytes(2, "little")
    buf[12] = board_size
    return bytes(buf)


def _record(squares: tuple[Square, ...], black_discs: int = 0) -> bytes:
    rec = bytearray(RECORD_SIZE_8X8)
    rec[6] = black_discs
    for index, square in enumerate(squares):
        rec[8 + index] = encode_8x8_move(square)
    return bytes(rec)


def _write_wtb(
    path: Path,
    games: tuple[tuple[Square, ...], ...],
    *,
    board_size: int = 8,
    black_discs: int = 0,
) -> Path:
    payload = b"".join(_record(squares, black_discs) for squares in games)
    path.write_bytes(_header(len(games), board_size) + payload)
    return path


def test_wthor_a1_is_bottom_left_from_black() -> None:
    assert encode_8x8_move(Square.parse("a1")) == 11
    assert encode_8x8_move(Square.parse("h1")) == 18
    assert encode_8x8_move(Square.parse("a8")) == 81
    assert encode_8x8_move(Square.parse("h8")) == 88
    assert encode_8x8_move(Square.parse("f5")) == 56
    assert decode_8x8_move(11) == Square.parse("a1")
    assert decode_8x8_move(56) == Square.parse("f5")
    assert decode_8x8_move(0) is None
    assert decode_8x8_move(19) is None


def test_replays_8x8_opening() -> None:
    f5 = Square.parse("f5")
    game = TrainingGame(squares=(f5,), black_discs=4)
    final = replay(game)
    assert final.board.stone_at(f5) is Stone.BLACK
    assert final.board.stone_at(Square.parse("e5")) is Stone.BLACK
    assert final.side_to_move is Color.WHITE


def test_training_games_reads_8x8_wtb(tmp_path: Path) -> None:
    f5 = Square.parse("f5")
    path = _write_wtb(tmp_path / "eight.wtb", ((f5,),), black_discs=4)
    games = training_games(path)
    assert len(games) == 1
    assert games[0].squares == (f5,)
    assert games[0].black_discs == 4
    assert replay(games[0]).side_to_move is Color.WHITE


def test_board_size_zero_is_8x8(tmp_path: Path) -> None:
    f5 = Square.parse("f5")
    path = _write_wtb(tmp_path / "legacy.wtb", ((f5,),), board_size=0)
    games = training_games(path)
    assert len(games) == 1
    assert games[0].squares == (f5,)


def test_non_8x8_records_are_excluded_from_training_input(tmp_path: Path) -> None:
    f5 = Square.parse("f5")
    _write_wtb(tmp_path / "eight.wtb", ((f5,),))
    ten = tmp_path / "ten.wtb"
    ten.write_bytes(_header(1, 10) + bytes(104))
    (tmp_path / "notes.txt").write_text("not a wtb\n", encoding="utf-8")

    assert training_games(ten) == ()
    games = training_games(tmp_path)
    assert len(games) == 1
    assert games[0].squares == (f5,)


def test_unplayable_8x8_record_is_excluded(tmp_path: Path) -> None:
    path = _write_wtb(
        tmp_path / "mixed.wtb",
        (
            (Square.parse("a1"),),
            (Square.parse("f5"),),
        ),
    )
    games = training_games(path)
    assert len(games) == 1
    assert games[0].squares == (Square.parse("f5"),)


def test_first_zero_ends_the_move_list(tmp_path: Path) -> None:
    rec = bytearray(RECORD_SIZE_8X8)
    rec[8] = encode_8x8_move(Square.parse("f5"))
    rec[9] = 0
    rec[10] = encode_8x8_move(Square.parse("d6"))
    path = tmp_path / "padded.wtb"
    path.write_bytes(_header(1, 8) + bytes(rec))
    games = training_games(path)
    assert len(games) == 1
    assert games[0].squares == (Square.parse("f5"),)


def test_replay_inserts_pass_when_wthor_omits_it() -> None:
    squares, expected_passes = _greedy_until_pass()
    game = TrainingGame(squares=tuple(squares), black_discs=0)
    position = initial_position()
    seen_pass = False
    for square in game.squares:
        if pass_is_legal(position):
            position = play(position, PassMove())
            seen_pass = True
        position = play(position, Place(square))
    assert expected_passes >= 1
    assert seen_pass
    assert replay(game) == position


def test_default_directory_is_data_wthor_under_repo() -> None:
    assert DEFAULT_WTHOR_DIR == REPO_ROOT / "data" / "wthor"
    assert DEFAULT_WTHOR_DIR.is_dir()


def test_wthor_originals_are_not_served_as_static_files() -> None:
    models = REPO_ROOT / "models"
    if models.exists():
        assert list(models.glob("*.wtb")) == []
        assert list(models.glob("*.WTB")) == []
    for name in ("public", "static", "www", "dist"):
        folder = REPO_ROOT / name
        if folder.exists():
            assert list(folder.rglob("*.wtb")) == []
            assert list(folder.rglob("*.WTB")) == []
    served = _static_serve_hits(REPO_ROOT)
    assert served == []


def _greedy_until_pass() -> tuple[list[Square], int]:
    position = initial_position()
    squares: list[Square] = []
    passes = 0
    while not is_over(position):
        if pass_is_legal(position):
            position = play(position, PassMove())
            passes += 1
            continue
        square = legal_places(position)[0]
        position = play(position, Place(square))
        squares.append(square)
        if passes:
            break
    return squares, passes


def _static_serve_hits(repo: Path) -> list[str]:
    skip = {".git", "node_modules", ".venv", "__pycache__", ".pytest_cache"}
    needles = (
        "StaticFiles",
        "serveStatic",
        "express.static",
        "send_from_directory",
        "sendFile",
    )
    hits: list[str] = []
    for path in repo.rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".ts", ".js", ".tsx"}:
            continue
        if any(part in skip for part in path.parts):
            continue
        if "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if "wthor" not in text.lower():
            continue
        for needle in needles:
            if needle in text:
                hits.append(f"{path}:{needle}")
    return hits
