import { afterEach, describe, expect, it, vi } from "vitest";
import { subscribeGameEvents } from "./api.ts";
import type { GameState } from "./types.ts";

const GAME_ID = "550e8400-e29b-41d4-a716-446655440000";

function game(overrides: Partial<GameState> = {}): GameState {
  return {
    id: GAME_ID,
    board: Array.from({ length: 8 }, () =>
      Array.from({ length: 8 }, () => "empty" as const),
    ),
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

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onerror: ((event: Event) => void) | null = null;
  closed = false;

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener() {}

  close() {
    this.closed = true;
  }

  error() {
    this.onerror?.(new Event("error"));
  }
}

afterEach(() => {
  FakeEventSource.instances = [];
  vi.unstubAllGlobals();
});

describe("subscribeGameEvents", () => {
  it("再接続上限を超えたら internal_error にし EventSource を増やさない", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    const opening = game();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify(opening), {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
      ),
    );
    const failures: string[] = [];
    subscribeGameEvents(
      GAME_ID,
      () => undefined,
      (code) => failures.push(code),
      { reconnectDelayMs: 0, maxReconnects: 2, sleep: async () => {} },
    );
    expect(FakeEventSource.instances).toHaveLength(1);
    FakeEventSource.instances[0]?.error();
    await vi.waitFor(() => {
      expect(FakeEventSource.instances).toHaveLength(2);
    });
    FakeEventSource.instances[1]?.error();
    await vi.waitFor(() => {
      expect(FakeEventSource.instances).toHaveLength(3);
    });
    FakeEventSource.instances[2]?.error();
    await vi.waitFor(() => {
      expect(failures).toEqual(["internal_error"]);
    });
    expect(FakeEventSource.instances).toHaveLength(3);
  });
});
