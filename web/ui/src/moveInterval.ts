import type { GameState } from "./types.ts";

export const DEFAULT_AGENT_MOVE_INTERVAL_SECONDS = 1;
export const DEFAULT_AGENT_MOVE_INTERVAL_MS = 1000;
export const MIN_AGENT_MOVE_INTERVAL_SECONDS = 0;
export const MAX_AGENT_MOVE_INTERVAL_SECONDS = 60;

export function parseMoveIntervalSeconds(raw: string): number {
  const trimmed = raw.trim();
  if (trimmed === "") {
    return DEFAULT_AGENT_MOVE_INTERVAL_SECONDS;
  }
  const n = Number(trimmed);
  if (!Number.isFinite(n)) {
    return DEFAULT_AGENT_MOVE_INTERVAL_SECONDS;
  }
  return Math.min(
    MAX_AGENT_MOVE_INTERVAL_SECONDS,
    Math.max(MIN_AGENT_MOVE_INTERVAL_SECONDS, n),
  );
}

export function moveIntervalMsFromSeconds(seconds: number): number {
  return Math.round(parseMoveIntervalSeconds(String(seconds)) * 1000);
}

export function isBoardMoveUpdate(
  previous: GameState,
  next: GameState,
): boolean {
  return (
    JSON.stringify(previous.last_move) !== JSON.stringify(next.last_move) ||
    JSON.stringify(previous.board) !== JSON.stringify(next.board)
  );
}

export function delayBeforeNextMoveMs(
  lastPresentedAtMs: number,
  nowMs: number,
  intervalMs: number,
): number {
  return Math.max(0, intervalMs - (nowMs - lastPresentedAtMs));
}

export type MovePresenterClock = {
  now: () => number;
  schedule: (fn: () => void, ms: number) => number;
  cancel: (id: number) => void;
};

const defaultClock: MovePresenterClock = {
  now: () => Date.now(),
  schedule: (fn, ms) => window.setTimeout(fn, ms),
  cancel: (id) => {
    window.clearTimeout(id);
  },
};

export function createMovePresenter(
  onPresent: (game: GameState) => void,
  options: {
    intervalMs: number;
    initial: GameState;
    clock?: MovePresenterClock;
  },
): { enqueue: (game: GameState) => void; dispose: () => void } {
  const clock = options.clock ?? defaultClock;
  const queue: GameState[] = [];
  let lastPresented = options.initial;
  let lastPresentedAt = clock.now();
  let timer: number | null = null;
  let disposed = false;

  const present = (next: GameState, countsAsMove: boolean) => {
    lastPresented = next;
    if (countsAsMove) {
      lastPresentedAt = clock.now();
    }
    onPresent(next);
  };

  const pump = () => {
    if (disposed || timer !== null) {
      return;
    }
    while (queue.length > 0) {
      const next = queue[0];
      if (next === undefined) {
        return;
      }
      const move = isBoardMoveUpdate(lastPresented, next);
      if (!move) {
        queue.shift();
        present(next, false);
        continue;
      }
      const wait = delayBeforeNextMoveMs(
        lastPresentedAt,
        clock.now(),
        options.intervalMs,
      );
      if (wait > 0) {
        timer = clock.schedule(() => {
          timer = null;
          pump();
        }, wait);
        return;
      }
      queue.shift();
      present(next, true);
    }
  };

  return {
    enqueue(game) {
      if (disposed) {
        return;
      }
      queue.push(game);
      pump();
    },
    dispose() {
      disposed = true;
      queue.length = 0;
      if (timer !== null) {
        clock.cancel(timer);
        timer = null;
      }
    },
  };
}
