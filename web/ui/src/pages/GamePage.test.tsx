import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Cell, GameState } from "../types.ts";
import { GamePage, illegalMoveMessage } from "./GamePage.tsx";

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
    black: { kind: "human" },
    white: { kind: "specimen", specimen_id: "random_uniform" },
    ...overrides,
  };
}

const names = new Map([["random_uniform", "ランダム (一様)"]]);

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  readonly listeners = new Map<string, Array<(event: MessageEvent) => void>>();
  closed = false;

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, handler: (event: MessageEvent) => void) {
    const list = this.listeners.get(type) ?? [];
    list.push(handler);
    this.listeners.set(type, list);
  }

  close() {
    this.closed = true;
  }

  emit(type: string, data: unknown) {
    for (const handler of this.listeners.get(type) ?? []) {
      handler({ data: JSON.stringify(data) } as MessageEvent);
    }
  }
}

afterEach(() => {
  cleanup();
  FakeEventSource.instances = [];
  vi.unstubAllGlobals();
});

describe("GamePage", () => {
  it("盤面画面でカタログ一覧を相手選択に使わない", () => {
    render(
      <GamePage
        game={game()}
        specimenNames={names}
        onGame={() => undefined}
        onBack={() => undefined}
      />,
    );
    expect(screen.getByRole("heading", { name: "盤面" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "カタログ" })).toBeNull();
    expect(screen.queryByRole("list")).toBeNull();
    expect(screen.queryByLabelText("対戦相手")).toBeNull();
    expect(screen.getByText(/あなたの入力待ちです/)).toBeTruthy();
  });

  it("終局後にカタログ画面へ戻れる", () => {
    const backs: string[] = [];
    render(
      <GamePage
        game={game({
          is_over: true,
          status: "completed",
          continuation_possible: false,
          legal_moves: [],
          result: { winner: "black", black: "win", white: "loss" },
          official_score: { black: 40, white: 24 },
        })}
        specimenNames={names}
        onGame={() => undefined}
        onBack={() => backs.push("back")}
      />,
    );
    expect(screen.getByText("黒の勝ちです。")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "カタログへ戻る" }));
    expect(backs).toEqual(["back"]);
  });

  it("違法手の案内は illegal_move のときだけ出す", () => {
    expect(illegalMoveMessage("illegal_move")).toBe(
      "その手は打てません。別のマスを指定してください。",
    );
    expect(illegalMoveMessage("external_model_failed")).toBeNull();
    expect(illegalMoveMessage(undefined)).toBeNull();
  });

  it("エージェント対エージェントは人手の着手なしに SSE で盤面を進める", () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    const seen: GameState[] = [];
    const opening = game({
      black: { kind: "specimen", specimen_id: "random_uniform" },
      white: { kind: "specimen", specimen_id: "random_uniform" },
      legal_moves: ["c4", "d3", "e6", "f5"],
    });
    render(
      <GamePage
        game={opening}
        specimenNames={names}
        onGame={(next) => seen.push(next)}
        onBack={() => undefined}
      />,
    );
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0]?.url).toBe(
      `/api/games/${opening.id}/events`,
    );
    const moved = game({
      ...opening,
      last_move: { type: "place", square: "f5" },
      official_score: { black: 4, white: 1 },
    });
    const finished = game({
      ...moved,
      is_over: true,
      status: "completed",
      continuation_possible: false,
      legal_moves: [],
      result: { winner: "black", black: "win", white: "loss" },
    });
    FakeEventSource.instances[0]?.emit("move_applied", {
      type: "move_applied",
      move: moved.last_move,
      game: moved,
    });
    FakeEventSource.instances[0]?.emit("game_over", {
      type: "game_over",
      game: finished,
    });
    expect(seen).toEqual([moved, finished]);
    expect(screen.queryByRole("button", { name: "パス" })).toBeNull();
  });
});
