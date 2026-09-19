"""メモリ上の同時 1 局。規則は engine、着手選択は catalog。"""

from __future__ import annotations

from dataclasses import dataclass
from random import Random
from threading import Lock
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
from reversi.api.schemas import (
    Cell,
    CreateGameRequest,
    GameResult,
    GameState,
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
    """進行中または終局した 1 局。"""

    id: str
    position: Position
    last_move: Move | None
    black: PlayerSpec
    white: PlayerSpec
    unplayable_reason: str | None = None


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
        game.position = play(game.position, chosen)
        game.last_move = _from_engine_place(chosen)
        return True
    if pass_is_legal(game.position):
        game.position = play(game.position, EnginePass())
        game.last_move = PassMove(type="pass")
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

    def __init__(self, rng: Random | None = None) -> None:
        self._rng = rng
        self._lock = Lock()
        self._game: Game | None = None

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
        if game.unplayable_reason is not None:
            raise external_model_failed()
        with self._lock:
            self._game = game
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
            try:
                game.position = play(game.position, _to_engine_move(move))
            except IllegalMoveError as exc:
                raise MoveRejected(
                    snapshot,
                    "違法な着手は盤に適用しない",
                ) from exc
            game.last_move = move
            advance_specimens(game, self._rng)
            return to_game_state(game)
