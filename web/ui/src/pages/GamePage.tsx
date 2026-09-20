import { useEffect, useRef, useState } from "react";
import {
  type GameStreamFailure,
  MoveRejectedError,
  playMove,
  subscribeGameEvents,
} from "../api.ts";
import { Board } from "../components/Board.tsx";
import type { Color, GameState, PlayerSpec } from "../types.ts";

type GamePageProps = {
  game: GameState;
  specimenNames: ReadonlyMap<string, string>;
  onGame: (game: GameState) => void;
  onBack: () => void;
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
}: GamePageProps) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [streamError, setStreamError] = useState<GameStreamFailure | null>(
    null,
  );
  const onGameRef = useRef(onGame);
  onGameRef.current = onGame;
  const humanTurn = isHumanTurn(game);
  const vsAgents =
    game.black.kind === "specimen" && game.white.kind === "specimen";
  const finished = game.is_over || game.status !== "in_progress";

  useEffect(() => {
    if (!vsAgents || finished) {
      return;
    }
    const stop = subscribeGameEvents(
      game.id,
      (next) => {
        onGameRef.current(next);
      },
      (code) => {
        setStreamError(code);
      },
    );
    return () => {
      stop();
    };
  }, [vsAgents, finished, game.id]);

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
    <main className="page page-game">
      <h1>盤面</h1>
      <div className="game-layout">
        <div className="board-pane">
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
              className="btn-quiet"
              disabled={busy}
              onClick={() => {
                void submitMove({ type: "pass" });
              }}
            >
              パス
            </button>
          ) : null}
        </div>
        <aside className="game-sidebar">
          <PlayerCard
            color="black"
            name={playerLabel(game.black, specimenNames)}
            stones={game.official_score.black}
            toMove={!finished && game.side_to_move === "black"}
          />
          <PlayerCard
            color="white"
            name={playerLabel(game.white, specimenNames)}
            stones={game.official_score.white}
            toMove={!finished && game.side_to_move === "white"}
          />
          <p className="turn">{turnMessage(game)}</p>
          {alert !== null ? <p className="error">{alert}</p> : null}
          {outcome !== null ? (
            <p className="result-banner" role="status">
              {outcome}
            </p>
          ) : null}
          {finished || streamError !== null ? (
            <button type="button" className="btn-primary" onClick={onBack}>
              カタログへ戻る
            </button>
          ) : null}
        </aside>
      </div>
    </main>
  );
}

function PlayerCard({
  color,
  name,
  stones,
  toMove,
}: {
  color: Color;
  name: string;
  stones: number;
  toMove: boolean;
}) {
  const colorName = color === "black" ? "黒" : "白";
  const className = toMove ? "player-card is-to-move" : "player-card";
  return (
    <div className={className}>
      <span className={`stone stone-${color}`} aria-hidden="true" />
      <div className="player-copy">
        <p className="player-color">
          {colorName}
          {toMove ? "（手番）" : ""}
        </p>
        <p className="player-name">{name}</p>
      </div>
      <p className="player-stones">{stones} 石</p>
    </div>
  );
}
