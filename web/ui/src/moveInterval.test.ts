import { describe, expect, it } from "vitest";
import {
  createMovePresenter,
  DEFAULT_AGENT_MOVE_INTERVAL_MS,
  DEFAULT_AGENT_MOVE_INTERVAL_SECONDS,
  delayBeforeNextMoveMs,
  isBoardMoveUpdate,
  type MovePresenterClock,
  moveIntervalMsFromSeconds,
  parseMoveIntervalSeconds,
} from "./moveInterval.ts";
import type { Cell, GameState } from "./types.ts";

function emptyBoard(): Cell[][] {
  return Array.from({ length: 8 }, () =>
    Array.from({ length: 8 }, () => "empty" as const),
  );
}

function game(overrides: Partial<GameState> = {}): GameState {
  return {
    id: "550e8400-e29b-41d4-a716-446655440000",
    board: emptyBoard(),
    side_to_move: "black",
    legal_moves: ["c4"],
    pass_is_legal: false,
    last_move: null,
    is_over: false,
    official_score: { black: 2, white: 2 },
    result: null,
    status: "in_progress",
    continuation_possible: true,
    unplayable_reason: null,
    black: { kind: "specimen", specimen_id: "random_uniform" },
    white: { kind: "specimen", specimen_id: "random_uniform" },
    ...overrides,
  };
}

function fakeClock(): {
  clock: MovePresenterClock;
  advance: (ms: number) => void;
} {
  let now = 0;
  let nextId = 1;
  const timers = new Map<number, { fn: () => void; at: number }>();
  return {
    clock: {
      now: () => now,
      schedule: (fn, ms) => {
        const id = nextId;
        nextId += 1;
        timers.set(id, { fn, at: now + ms });
        return id;
      },
      cancel: (id) => {
        timers.delete(id);
      },
    },
    advance(ms) {
      now += ms;
      const due = [...timers.entries()]
        .filter(([, timer]) => timer.at <= now)
        .sort((a, b) => a[1].at - b[1].at);
      for (const [id, timer] of due) {
        timers.delete(id);
        timer.fn();
      }
    },
  };
}

describe("着手間隔", () => {
  it("未変更時の間隔は 1 秒である", () => {
    expect(DEFAULT_AGENT_MOVE_INTERVAL_SECONDS).toBe(1);
    expect(DEFAULT_AGENT_MOVE_INTERVAL_MS).toBe(1000);
    expect(parseMoveIntervalSeconds("")).toBe(1);
    expect(moveIntervalMsFromSeconds(1)).toBe(1000);
  });

  it("連続する着手の提示は設定した間隔以上空ける", () => {
    expect(delayBeforeNextMoveMs(0, 0, 1000)).toBe(1000);
    expect(delayBeforeNextMoveMs(0, 400, 1000)).toBe(600);
    expect(delayBeforeNextMoveMs(0, 1000, 1000)).toBe(0);
    expect(delayBeforeNextMoveMs(0, 1500, 1000)).toBe(0);
  });

  it("パスも着手更新として扱う", () => {
    const opening = game();
    const placed = game({ last_move: { type: "place", square: "f5" } });
    const passed = game({ last_move: { type: "pass" } });
    expect(isBoardMoveUpdate(opening, placed)).toBe(true);
    expect(isBoardMoveUpdate(placed, passed)).toBe(true);
    expect(isBoardMoveUpdate(placed, placed)).toBe(false);
  });

  it("未変更の 1 秒間隔では次の着手まで待ってから提示する", () => {
    const { clock, advance } = fakeClock();
    const opening = game();
    const moved = game({ last_move: { type: "place", square: "f5" } });
    const passed = game({ last_move: { type: "pass" } });
    const seen: GameState[] = [];
    const presenter = createMovePresenter((next) => seen.push(next), {
      intervalMs: DEFAULT_AGENT_MOVE_INTERVAL_MS,
      initial: opening,
      clock,
    });
    presenter.enqueue(moved);
    presenter.enqueue(passed);
    expect(seen).toEqual([]);
    advance(999);
    expect(seen).toEqual([]);
    advance(1);
    expect(seen).toEqual([moved]);
    advance(999);
    expect(seen).toEqual([moved]);
    advance(1);
    expect(seen).toEqual([moved, passed]);
  });

  it("間隔 0 では人手の着手指示なしに連続更新をすぐ提示する", () => {
    const { clock } = fakeClock();
    const opening = game();
    const moved = game({ last_move: { type: "place", square: "f5" } });
    const finished = game({
      last_move: { type: "place", square: "f5" },
      is_over: true,
      status: "completed",
    });
    const seen: GameState[] = [];
    const presenter = createMovePresenter((next) => seen.push(next), {
      intervalMs: 0,
      initial: opening,
      clock,
    });
    presenter.enqueue(moved);
    presenter.enqueue(finished);
    expect(seen).toEqual([moved, finished]);
  });
});
