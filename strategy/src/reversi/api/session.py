"""メモリ上の同時 1 局。規則は engine、着手選択は catalog。終局だけ SQLite。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from random import Random
from threading import Lock
from uuid import uuid4

from reversi.agents import catalog
from reversi.api.errors import MoveRejected, game_not_found, specimen_not_found
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


@dataclass
class Game:
    """進行中または終局した 1 局。着手列は終局の永続化用。"""

    id: str
    position: Position
    last_move: Move | None
    black: PlayerSpec
    white: PlayerSpec
    moves: list[Move] = field(default_factory=list)


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
        status="completed" if over else "in_progress",
        continuation_possible=not over,
        unplayable_reason=None,
        black=game.black,
        white=game.white,
    )


def _apply_specimen_choice(game: Game, rng: Random | None) -> bool:
    """標本の 1 手を適用する。手番が標本でなければ False。"""
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
        if is_over(game.position):
            return
        if not _apply_specimen_choice(game, rng):
            return


class GameStore:
    """進行中の局はメモリ上で同時 1。新しい開始は既存を置き換える。"""

    def __init__(
        self,
        rng: Random | None = None,
        db_path: Path | None = DEFAULT_DB_PATH,
    ) -> None:
        self._rng = rng
        self._db_path = db_path
        self._lock = Lock()
        self._game: Game | None = None

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
        advance_specimens(game, self._rng)
        with self._lock:
            self._game = game
            self._persist_finished(game)
        return to_game_state(game)

    def play_move(self, game_id: str, move: Move) -> GameState:
        with self._lock:
            game = self._game
            if game is None or game.id != game_id:
                raise game_not_found()
            snapshot = to_game_state(game)
            try:
                _record_move(game, move, _to_engine_move(move))
            except IllegalMoveError as exc:
                raise MoveRejected(
                    snapshot,
                    "違法な着手は盤に適用しない",
                ) from exc
            advance_specimens(game, self._rng)
            self._persist_finished(game)
            return to_game_state(game)
