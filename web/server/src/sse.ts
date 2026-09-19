import type { GameState, Move } from "./schemas.ts";

export const DEFAULT_SSE_POLL_INTERVAL_MS = 50;

export type SseWrite = (event: string, data: unknown) => Promise<void>;

function sseBlock(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

function snapshotEvent(game: GameState) {
  return { type: "snapshot" as const, game };
}

function moveAppliedEvent(game: GameState, move: Move) {
  return { type: "move_applied" as const, move, game };
}

function gameOverEvent(game: GameState) {
  return { type: "game_over" as const, game };
}

function unplayableEvent(game: GameState) {
  return {
    type: "unplayable" as const,
    reason: game.unplayable_reason ?? "external_model_failed",
    game,
  };
}

export function terminalSseEvent(
  game: GameState,
): { event: string; data: unknown } | undefined {
  if (game.status === "completed" || game.is_over) {
    return { event: "game_over", data: gameOverEvent(game) };
  }
  if (game.status === "unplayable") {
    return { event: "unplayable", data: unplayableEvent(game) };
  }
  return undefined;
}

export function gameEventsBody(game: GameState): string {
  const chunks = [sseBlock("snapshot", snapshotEvent(game))];
  const terminal = terminalSseEvent(game);
  if (terminal !== undefined) {
    chunks.push(sseBlock(terminal.event, terminal.data));
  }
  return chunks.join("");
}

export function gameEventsResponse(game: GameState): Response {
  return new Response(gameEventsBody(game), {
    status: 200,
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache",
    },
  });
}

function progressed(previous: GameState, next: GameState): boolean {
  return (
    JSON.stringify(previous.last_move) !== JSON.stringify(next.last_move) ||
    JSON.stringify(previous.board) !== JSON.stringify(next.board)
  );
}

async function emitMoveApplied(
  write: SseWrite,
  previous: GameState,
  next: GameState,
): Promise<void> {
  if (!progressed(previous, next) || next.last_move === null) {
    return;
  }
  await write("move_applied", moveAppliedEvent(next, next.last_move));
}

export async function streamLiveGameEvents(
  write: SseWrite,
  sleep: (ms: number) => Promise<void>,
  aborted: () => boolean,
  initial: GameState,
  followUp: () => Promise<GameState | undefined>,
  pollIntervalMs: number,
): Promise<void> {
  await write("snapshot", snapshotEvent(initial));
  let previous = initial;
  while (!aborted()) {
    await sleep(pollIntervalMs);
    if (aborted()) {
      return;
    }
    const next = await followUp();
    if (next === undefined) {
      return;
    }
    await emitMoveApplied(write, previous, next);
    const terminal = terminalSseEvent(next);
    if (terminal !== undefined) {
      await write(terminal.event, terminal.data);
      return;
    }
    previous = next;
  }
}
