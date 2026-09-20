"""メモリ上の同時 1 局。規則は engine、着手選択は catalog。終局だけ SQLite。"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from random import Random
from threading import Lock, Thread
from uuid import uuid4

from reversi.agents import catalog
from reversi.agents.jev import ExternalModelError
from reversi.api.errors import (
    MoveRejected,
    UnplayableGame,
    external_model_failed,
    game_not_found,
    specimen_not_found,
)
from reversi.api.persist import (
    DEFAULT_DB_PATH,
    MODE_AGENT_VS_AGENT,
    MODE_HUMAN_VS_AGENT,
    save_if_over,
)
from reversi.api.schemas import (
    Cell,
    CreateGameRequest,
    GameResult,
    GameState,
    HumanPlayer,
    Move,
    OfficialScore,
    PassMove,
    PlaceMove,
    PlayerSpec,
    SpecimenPlayer,
)
from reversi.engine.board import Color, Square
from reversi.engine.rules import (
    IllegalMoveError,
    Place,
    Position,
    initial_position,
    is_over,
    legal_places,
    pass_is_legal,
    play,
)
from reversi.engine.rules import (
    PassMove as EnginePass,
)
from reversi.engine.score import official_score, stone_counts

_MAX_AUTO_PLIES = 128


def remaining_autoplay_wait(
    last_applied_at: float | None,
    now: float,
    interval_seconds: float,
) -> float:
    """直前の適用からの経過が間隔に足りないとき、追加で待つ秒数。"""
    if last_applied_at is None or interval_seconds <= 0:
        return 0.0
    return max(0.0, interval_seconds - (now - last_applied_at))


def _autoplay_interval_seconds(
    request: CreateGameRequest,
    both_specimens: bool,
) -> float:
    if not both_specimens or request.move_interval_seconds is None:
        return 0.0
    return request.move_interval_seconds


@dataclass
class Game:
    """進行中または終局した 1 局。着手列は終局の永続化用。"""

    id: str
    position: Position
    last_move: Move | None
    black: PlayerSpec
    white: PlayerSpec
    unplayable_reason: str | None = None
    moves: list[Move] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _AutoplayPlan:
    """ロック外で着手を決めるための、1 手分の計画。"""

    game_id: str
    specimen_id: str
    position: Position
    ply: int


def _player_on(game: Game, color: Color) -> PlayerSpec:
    if color is Color.BLACK:
        return game.black
    return game.white


def _is_specimen(player: PlayerSpec) -> bool:
    return player.kind == "specimen"


def _ensure_known_specimens(request: CreateGameRequest) -> None:
    for player in (request.black, request.white):
        if player.kind != "specimen":
            continue
        assert isinstance(player, SpecimenPlayer)
        try:
            catalog.get(player.specimen_id)
        except KeyError:
            raise specimen_not_found() from None


def _to_engine_move(move: Move) -> Place | EnginePass:
    if isinstance(move, PassMove):
        return EnginePass()
    return Place(Square.parse(move.square))


def _from_engine_place(place: Place) -> PlaceMove:
    return PlaceMove(type="place", square=place.square.algebraic)


def _player_payload(player: PlayerSpec) -> dict[str, str]:
    if isinstance(player, HumanPlayer):
        return {"kind": "human"}
    assert isinstance(player, SpecimenPlayer)
    return {"kind": "specimen", "specimen_id": player.specimen_id}


def _move_payload(move: Move) -> dict[str, str]:
    if isinstance(move, PassMove):
        return {"type": "pass"}
    return {"type": "place", "square": move.square}


def _game_mode(game: Game) -> str:
    if game.black.kind == "specimen" and game.white.kind == "specimen":
        return MODE_AGENT_VS_AGENT
    return MODE_HUMAN_VS_AGENT


def _record_move(game: Game, move: Move, engine_move: Place | EnginePass) -> None:
    game.position = play(game.position, engine_move)
    game.last_move = move
    game.moves.append(move)


def _copy_game(game: Game) -> Game:
    return Game(
        id=game.id,
        position=game.position,
        last_move=game.last_move,
        black=game.black,
        white=game.white,
        unplayable_reason=game.unplayable_reason,
        moves=list(game.moves),
    )


def _board_cells(position: Position) -> list[list[Cell]]:
    return [[stone.value for stone in row] for row in position.board.cells]


def _score_view(position: Position) -> OfficialScore:
    if is_over(position):
        score = official_score(position.board)
        return OfficialScore(black=score.black, white=score.white)
    counts = stone_counts(position.board)
    return OfficialScore(black=counts.black, white=counts.white)


def _result_view(position: Position) -> GameResult | None:
    if not is_over(position):
        return None
    score = official_score(position.board)
    if score.black > score.white:
        return GameResult(winner="black", black="win", white="loss")
    if score.white > score.black:
        return GameResult(winner="white", black="loss", white="win")
    return GameResult(winner="draw", black="draw", white="draw")


def to_game_state(game: Game) -> GameState:
    position = game.position
    over = is_over(position)
    unplayable = game.unplayable_reason is not None
    if unplayable:
        status = "unplayable"
        continuation = False
        reason = "external_model_failed"
    elif over:
        status = "completed"
        continuation = False
        reason = None
    else:
        status = "in_progress"
        continuation = True
        reason = None
    return GameState(
        id=game.id,
        board=_board_cells(position),
        side_to_move=position.side_to_move.value,
        legal_moves=[square.algebraic for square in legal_places(position)],
        pass_is_legal=pass_is_legal(position),
        last_move=game.last_move,
        is_over=over,
        official_score=_score_view(position),
        result=_result_view(position),
        status=status,
        continuation_possible=continuation,
        unplayable_reason=reason,
        black=game.black,
        white=game.white,
    )


def _decide_specimen_move(
    position: Position,
    specimen_id: str,
    rng: Random | None,
) -> Place | EnginePass | None:
    chosen = catalog.choose_move(specimen_id, position, rng)
    if chosen is not None:
        return chosen
    if pass_is_legal(position):
        return EnginePass()
    return None


def _apply_specimen_choice(game: Game, rng: Random | None) -> bool:
    """標本の 1 手を適用する。手番が標本でなければ False。"""
    if game.unplayable_reason is not None:
        return False
    player = _player_on(game, game.position.side_to_move)
    if player.kind != "specimen":
        return False
    assert isinstance(player, SpecimenPlayer)
    chosen = catalog.choose_move(player.specimen_id, game.position, rng)
    if chosen is not None:
        _record_move(game, _from_engine_place(chosen), chosen)
        return True
    if pass_is_legal(game.position):
        _record_move(game, PassMove(type="pass"), EnginePass())
        return True
    return False


def advance_specimens(game: Game, rng: Random | None) -> None:
    """手番が標本であるあいだ、人手を待たず進める。"""
    for _ in range(_MAX_AUTO_PLIES):
        if is_over(game.position) or game.unplayable_reason is not None:
            return
        try:
            if not _apply_specimen_choice(game, rng):
                return
        except ExternalModelError:
            game.unplayable_reason = "external_model_failed"
            return


class GameStore:
    """進行中の局はメモリ上で同時 1。新しい開始は既存を置き換える。"""

    def __init__(
        self,
        rng: Random | None = None,
        db_path: Path | None = DEFAULT_DB_PATH,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._rng = rng
        self._db_path = db_path
        self._monotonic = monotonic
        self._sleep = sleep
        self._lock = Lock()
        self._game: Game | None = None
        self._applied: list[GameState] = []
        self._autoplay_thread: Thread | None = None

    def _persist_finished(self, game: Game) -> None:
        if self._db_path is None:
            return
        save_if_over(
            game.position,
            mode=_game_mode(game),
            black=_player_payload(game.black),
            white=_player_payload(game.white),
            moves=tuple(_move_payload(move) for move in game.moves),
            db_path=self._db_path,
        )

    def _autoplay_plan(self, game_id: str) -> _AutoplayPlan | None:
        with self._lock:
            game = self._game
            if game is None or game.id != game_id:
                return None
            if is_over(game.position) or game.unplayable_reason is not None:
                return None
            player = _player_on(game, game.position.side_to_move)
            if not _is_specimen(player):
                return None
            assert isinstance(player, SpecimenPlayer)
            return _AutoplayPlan(
                game_id=game.id,
                specimen_id=player.specimen_id,
                position=game.position,
                ply=len(game.moves),
            )

    def _game_for_plan(self, plan: _AutoplayPlan) -> Game | None:
        game = self._game
        if game is None or game.id != plan.game_id:
            return None
        if len(game.moves) != plan.ply or game.position != plan.position:
            return None
        if is_over(game.position) or game.unplayable_reason is not None:
            return None
        return game

    def _commit_autoplay_move(
        self,
        plan: _AutoplayPlan,
        choice: Place | EnginePass,
    ) -> bool:
        with self._lock:
            game = self._game_for_plan(plan)
            if game is None:
                return False
            if isinstance(choice, EnginePass):
                _record_move(game, PassMove(type="pass"), choice)
            else:
                _record_move(game, _from_engine_place(choice), choice)
            self._applied.append(to_game_state(game))
            if is_over(game.position):
                try:
                    self._persist_finished(game)
                except (OSError, sqlite3.Error):
                    self._game = None
                return False
            return True

    def _mark_autoplay_unplayable(self, plan: _AutoplayPlan) -> None:
        with self._lock:
            game = self._game_for_plan(plan)
            if game is None:
                return
            game.unplayable_reason = "external_model_failed"
            self._applied.append(to_game_state(game))

    def _autoplay_step(
        self,
        game_id: str,
        last_applied_at: float | None,
        interval_seconds: float,
    ) -> bool:
        """標本の 1 手を進める。続けてよいとき True。着手決定中はロックしない。"""
        plan = self._autoplay_plan(game_id)
        if plan is None:
            return False
        try:
            choice = _decide_specimen_move(
                plan.position,
                plan.specimen_id,
                self._rng,
            )
        except ExternalModelError:
            self._mark_autoplay_unplayable(plan)
            return False
        if choice is None:
            return False
        remaining = remaining_autoplay_wait(
            last_applied_at,
            self._monotonic(),
            interval_seconds,
        )
        if remaining > 0:
            self._sleep(remaining)
        return self._commit_autoplay_move(plan, choice)

    def _run_autoplay(self, game_id: str, interval_seconds: float) -> None:
        last_applied_at: float | None = None
        while self._autoplay_step(game_id, last_applied_at, interval_seconds):
            last_applied_at = self._monotonic()

    def _start_autoplay(self, game_id: str, interval_seconds: float) -> None:
        self._autoplay_thread = Thread(
            target=self._run_autoplay,
            args=(game_id, interval_seconds),
            daemon=True,
        )
        self._autoplay_thread.start()

    def catalog(self) -> list[catalog.CatalogItem]:
        return list(catalog.items())

    def snapshot(self, game_id: str) -> GameState:
        with self._lock:
            game = self._game
            if game is None or game.id != game_id:
                raise game_not_found()
            return to_game_state(game)

    def start(self, request: CreateGameRequest) -> GameState:
        _ensure_known_specimens(request)
        game = Game(
            id=str(uuid4()),
            position=initial_position(),
            last_move=None,
            black=request.black,
            white=request.white,
        )
        both_specimens = _is_specimen(request.black) and _is_specimen(
            request.white,
        )
        if both_specimens:
            interval = _autoplay_interval_seconds(request, both_specimens)
            with self._lock:
                self._game = game
                opening = to_game_state(game)
                self._applied = [opening]
            self._start_autoplay(game.id, interval)
            return opening
        advance_specimens(game, self._rng)
        if game.unplayable_reason is not None:
            raise external_model_failed()
        with self._lock:
            self._persist_finished(game)
            self._game = game
            self._applied = [to_game_state(game)]
        return to_game_state(game)

    def play_move(self, game_id: str, move: Move) -> GameState:
        with self._lock:
            game = self._game
            if game is None or game.id != game_id:
                raise game_not_found()
            snapshot = to_game_state(game)
            if game.unplayable_reason is not None:
                raise UnplayableGame(
                    snapshot,
                    "外部モデルの呼出しに失敗し、この対局は継続できない",
                )
            updated = _copy_game(game)
            try:
                _record_move(updated, move, _to_engine_move(move))
            except IllegalMoveError as exc:
                raise MoveRejected(
                    snapshot,
                    "違法な着手は盤に適用しない",
                ) from exc
            advance_specimens(updated, self._rng)
            self._persist_finished(updated)
            self._game = updated
            return to_game_state(updated)
