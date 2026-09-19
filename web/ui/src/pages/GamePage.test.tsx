import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Cell, GameState } from "../types.ts";
import {
  GamePage,
  illegalMoveMessage,
  streamFailureMessage,
} from "./GamePage.tsx";

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

function problemResponse(status: number, code: string): Response {
  return new Response(
    JSON.stringify({
      type: `urn:reversi-ai:error:${code}`,
      title: "Error",
      status,
      detail: "x",
      code,
    }),
    {
      status,
      headers: { "content-type": "application/problem+json" },
    },
  );
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

const names = new Map([["random_uniform", "ランダム (一様)"]]);

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  readonly listeners = new Map<string, Array<(event: MessageEvent) => void>>();
  closed = false;
  onerror: ((event: Event) => void) | null = null;

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

  error() {
    this.onerror?.(new Event("error"));
  }
}

function renderAgents() {
  const opening = game({
    black: { kind: "specimen", specimen_id: "random_uniform" },
    white: { kind: "specimen", specimen_id: "random_uniform" },
    legal_moves: ["c4", "d3", "e6", "f5"],
  });
  const seen: GameState[] = [];
  render(
    <GamePage
      game={opening}
      specimenNames={names}
      onGame={(next) => seen.push(next)}
      onBack={() => undefined}
    />,
  );
  return { opening, seen };
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

  it("SSE 切断の案内は game_not_found と内部障害を分ける", () => {
    expect(streamFailureMessage("game_not_found")).toBe("対局がありません。");
    expect(streamFailureMessage("internal_error")).toBe(
      "対局の更新を取得できませんでした。",
    );
  });

  it("エージェント対エージェントは人手の着手なしに SSE で盤面を進める", () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    const { opening, seen } = renderAgents();
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

  it("SSE 切断後の 404 は対局なしと案内し外部モデル失敗にしない", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    const fetchMock = vi.fn(async () => problemResponse(404, "game_not_found"));
    vi.stubGlobal("fetch", fetchMock);
    const { opening } = renderAgents();
    FakeEventSource.instances[0]?.error();
    await waitFor(() => {
      expect(screen.getByText("対局がありません。")).toBeTruthy();
    });
    expect(screen.queryByText(/外部モデル/)).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(`/api/games/${opening.id}`);
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it("SSE 切断後の 500 は内部障害と案内し外部モデル失敗にしない", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => problemResponse(500, "internal_error")),
    );
    renderAgents();
    FakeEventSource.instances[0]?.error();
    await waitFor(() => {
      expect(
        screen.getByText("対局の更新を取得できませんでした。"),
      ).toBeTruthy();
    });
    expect(screen.queryByText(/外部モデル/)).toBeNull();
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it("SSE 切断後も進行中なら再接続し盤面更新を続ける", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    const { opening, seen } = renderAgents();
    const progressed = game({
      ...opening,
      last_move: { type: "place", square: "f5" },
      official_score: { black: 4, white: 1 },
    });
    const fetchMock = vi.fn(async () => jsonResponse(progressed));
    vi.stubGlobal("fetch", fetchMock);
    FakeEventSource.instances[0]?.error();
    await waitFor(() => {
      expect(FakeEventSource.instances).toHaveLength(2);
    });
    expect(fetchMock).toHaveBeenCalledWith(`/api/games/${opening.id}`);
    expect(seen).toEqual([progressed]);
    expect(screen.queryByText("対局の更新を取得できませんでした。")).toBeNull();
    expect(screen.queryByText(/外部モデル/)).toBeNull();
    const later = game({
      ...progressed,
      last_move: { type: "place", square: "d6" },
      official_score: { black: 3, white: 3 },
    });
    FakeEventSource.instances[1]?.emit("move_applied", {
      type: "move_applied",
      move: later.last_move,
      game: later,
    });
    expect(seen).toEqual([progressed, later]);
    expect(FakeEventSource.instances[0]?.closed).toBe(true);
    expect(FakeEventSource.instances[1]?.closed).toBe(false);
  });

  it("unplayable は外部モデル失敗として案内する", () => {
    render(
      <GamePage
        game={game({
          status: "unplayable",
          continuation_possible: false,
          unplayable_reason: "external_model_failed",
        })}
        specimenNames={names}
        onGame={() => undefined}
        onBack={() => undefined}
      />,
    );
    expect(
      screen.getByText("外部モデルの失敗により、この対局は続けられません。"),
    ).toBeTruthy();
  });

  it("終局イベントのあとの SSE 切断では GET しない", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { opening, seen } = renderAgents();
    const finished = game({
      ...opening,
      is_over: true,
      status: "completed",
      continuation_possible: false,
      legal_moves: [],
      result: { winner: "black", black: "win", white: "loss" },
    });
    FakeEventSource.instances[0]?.emit("game_over", {
      type: "game_over",
      game: finished,
    });
    FakeEventSource.instances[0]?.error();
    await Promise.resolve();
    expect(seen).toEqual([finished]);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryByText("対局がありません。")).toBeNull();
    expect(screen.queryByText("対局の更新を取得できませんでした。")).toBeNull();
  });
});
