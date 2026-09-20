import { useEffect, useRef, useState } from "react";
import {
  type GameStreamFailure,
  MoveRejectedError,
  playMove,
  subscribeGameEvents,
} from "../api.ts";
import { Board } from "../components/Board.tsx";
import {
  createMovePresenter,
  DEFAULT_AGENT_MOVE_INTERVAL_MS,
} from "../moveInterval.ts";
import type { GameState, PlayerSpec } from "../types.ts";

type GamePageProps = {
  game: GameState;
  specimenNames: ReadonlyMap<string, string>;
  onGame: (game: GameState) => void;
  onBack: () => void;
  moveIntervalMs?: number;
};

export function isHumanTurn(game: GameState): boolean {
  if (game.is_over || !game.continuation_possible) {
    return false;
  }
  const player = game.side_to_move === "black" ? game.black : game.white;
  return player.kind === "human";
}

export function playerLabel(
  player: PlayerSpec,
  names: ReadonlyMap<string, string>,
): string {
  if (player.kind === "human") {
    return "あなた";
  }
  return names.get(player.specimen_id) ?? player.specimen_id;
}

export function turnMessage(game: GameState): string {
  if (game.status === "unplayable") {
    return "対局を継続できません。";
  }
  if (game.is_over) {
    return "終局です。";
  }
  const color = game.side_to_move === "black" ? "黒" : "白";
  if (isHumanTurn(game)) {
    return `手番は${color}です。あなたの入力待ちです。`;
  }
  return `手番は${color}です。相手の着手を待っています。`;
}

export function resultMessage(game: GameState): string | null {
  if (game.status === "unplayable") {
    return "外部モデルの失敗により、この対局は続けられません。";
  }
  if (!game.is_over || game.result === null) {
    return null;
  }
  if (game.result.winner === "draw") {
    return "引き分けです。";
  }
  if (game.result.winner === "black") {
    return "黒の勝ちです。";
  }
  return "白の勝ちです。";
}

export function illegalMoveMessage(code: string | undefined): string | null {
  if (code === "illegal_move") {
    return "その手は打てません。別のマスを指定してください。";
  }
  return null;
}

export function streamFailureMessage(code: GameStreamFailure): string {
  if (code === "game_not_found") {
    return "対局がありません。";
  }
  return "対局の更新を取得できませんでした。";
}

export function GamePage({
  game,
  specimenNames,
  onGame,
  onBack,
  moveIntervalMs = DEFAULT_AGENT_MOVE_INTERVAL_MS,
}: GamePageProps) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [streamError, setStreamError] = useState<GameStreamFailure | null>(
    null,
  );
  const onGameRef = useRef(onGame);
  onGameRef.current = onGame;
  const gameRef = useRef(game);
  gameRef.current = game;
  const humanTurn = isHumanTurn(game);
  const vsAgents =
    game.black.kind === "specimen" && game.white.kind === "specimen";
  const finished = game.is_over || game.status !== "in_progress";

  useEffect(() => {
    if (!vsAgents || finished) {
      return;
    }
    const presenter = createMovePresenter(
      (next) => {
        onGameRef.current(next);
      },
      { intervalMs: moveIntervalMs, initial: gameRef.current },
    );
    const stop = subscribeGameEvents(game.id, presenter.enqueue, (code) => {
      setStreamError(code);
    });
    return () => {
      presenter.dispose();
      stop();
    };
  }, [vsAgents, finished, game.id, moveIntervalMs]);

  async function submitMove(move: Parameters<typeof playMove>[1]) {
    if (!humanTurn || busy) {
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      onGame(await playMove(game.id, move));
    } catch (error) {
      if (error instanceof MoveRejectedError) {
        onGame(error.game);
        const text = illegalMoveMessage(error.code);
        if (text !== null) {
          setMessage(text);
        }
      } else {
        setMessage("着手を送れませんでした。");
      }
    } finally {
      setBusy(false);
    }
  }

  const outcome = resultMessage(game);
  const alert =
    message ??
    (streamError !== null ? streamFailureMessage(streamError) : null);

  return (
    <main className="page">
      <h1>盤面</h1>
      <p className="players">
        黒: {playerLabel(game.black, specimenNames)} / 白:{" "}
        {playerLabel(game.white, specimenNames)}
      </p>
      <p className="turn">{turnMessage(game)}</p>
      <p className="score">
        黒 {game.official_score.black} 石 / 白 {game.official_score.white} 石
      </p>
      <Board
        board={game.board}
        legalMoves={game.legal_moves}
        lastMove={game.last_move}
        showLegal={humanTurn}
        onPlace={(square) => {
          void submitMove({ type: "place", square });
        }}
      />
      {humanTurn && game.pass_is_legal ? (
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            void submitMove({ type: "pass" });
          }}
        >
          パス
        </button>
      ) : null}
      {alert !== null ? <p className="error">{alert}</p> : null}
      {outcome !== null ? <p className="result">{outcome}</p> : null}
      {finished || streamError !== null ? (
        <button type="button" onClick={onBack}>
          カタログへ戻る
        </button>
      ) : null}
    </main>
  );
}
