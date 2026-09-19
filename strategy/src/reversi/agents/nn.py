"""ONNX の順伝播で合法手を選ぶ個体。対局時は PyTorch を使わない。"""

from __future__ import annotations

from pathlib import Path
from random import Random

import numpy as np
import onnxruntime as ort

from reversi.encode import encode
from reversi.engine.board import BOARD_SIZE, Board, Square
from reversi.engine.rules import Place, Position, legal_places

SPECIMEN_ID = "nn"
CATEGORY = "neural_network"
DISPLAY_NAME = "ニューラルネットワーク (棋譜)"
DESCRIPTION = (
    "WTHOR と永続化した対局から対局前に学習したニューラルネットワークで着手する。"
    "対局時は ONNX の順伝播のみを用い、合法手の外は選ばない。"
)
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[4] / "models" / "nn.onnx"
INPUT_NAME = "board"
OUTPUT_NAME = "logits"
OUTPUT_SIZE = BOARD_SIZE * BOARD_SIZE

__all__ = [
    "CATEGORY",
    "DEFAULT_MODEL_PATH",
    "DESCRIPTION",
    "DISPLAY_NAME",
    "INPUT_NAME",
    "OUTPUT_NAME",
    "OUTPUT_SIZE",
    "SPECIMEN_ID",
    "choose_move",
    "infer_logits",
    "masked_place",
    "square_index",
]

_SESSION: ort.InferenceSession | None = None
_SESSION_PATH: Path | None = None


def square_index(square: Square) -> int:
    """平面内のマス番号。a1 が 0、h8 が 63。"""
    return square.rank * BOARD_SIZE + square.file


def _board_batch(board: Board) -> np.ndarray:
    encoded = encode(board)
    return np.asarray(encoded.planes, dtype=np.float32)[np.newaxis, ...]


def load_session(path: Path | None = None) -> ort.InferenceSession:
    """CPU 実行プロバイダだけで ONNX を読む。"""
    global _SESSION, _SESSION_PATH
    model_path = DEFAULT_MODEL_PATH if path is None else path
    if _SESSION is None or _SESSION_PATH != model_path:
        _SESSION = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )
        _SESSION_PATH = model_path
    return _SESSION


def infer_logits(board: Board, path: Path | None = None) -> tuple[float, ...]:
    """64 マスのロジット。入力は 1×3×8×8。"""
    session = load_session(path)
    raw = session.run([OUTPUT_NAME], {INPUT_NAME: _board_batch(board)})[0]
    logits = np.asarray(raw, dtype=np.float64).reshape(-1)
    if logits.size != OUTPUT_SIZE:
        raise ValueError(f"ロジットの長さは {OUTPUT_SIZE} でなければなりません")
    return tuple(float(value) for value in logits)


def masked_place(position: Position, logits: tuple[float, ...]) -> Place | None:
    """合法手へマスクした最大ロジット。同点は a1…h8。"""
    if len(logits) != OUTPUT_SIZE:
        raise ValueError(f"ロジットの長さは {OUTPUT_SIZE} でなければなりません")
    best_square = None
    best_logit: float | None = None
    for square in legal_places(position):
        logit = logits[square_index(square)]
        if best_logit is None or logit > best_logit:
            best_logit = logit
            best_square = square
    if best_square is None:
        return None
    return Place(best_square)


def choose_move(
    position: Position,
    rng: Random | None = None,
    *,
    path: Path | None = None,
    logits: tuple[float, ...] | None = None,
) -> Place | None:
    """ONNX の順伝播を合法手にマスクする。合法手が無ければ着手しない。"""
    del rng
    scores = infer_logits(position.board, path) if logits is None else logits
    return masked_place(position, scores)
