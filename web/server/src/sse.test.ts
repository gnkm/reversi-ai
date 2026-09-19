import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { createApp } from "./app.ts";
import {
  type GameEvent,
  type GameState,
  gameEventSchema,
  gameOverEventSchema,
  moveAppliedEventSchema,
  snapshotEventSchema,
  unplayableEventSchema,
} from "./schemas.ts";
import { streamLiveGameEvents } from "./sse.ts";
import type { StrategyGateway } from "./strategy.ts";

const PUBLIC_ORIGIN = "https://127.0.0.1:3000";
const GAME_ID = "550e8400-e29b-41d4-a716-446655440000";
const EVENTS = `https://127.0.0.1:3000/api/games/${GAME_ID}/events`;

const emptyRow = (): GameState["board"][number] => [
  "empty",
  "empty",
  "empty",
  "empty",
  "empty",
  "empty",
  "empty",
  "empty",
];

function openingBoard(): GameState["board"] {
  const board = Array.from({ length: 8 }, emptyRow);
  board[3][3] = "white";
  board[3][4] = "black";
  board[4][3] = "black";
  board[4][4] = "white";
  return board;
}

function afterF5Board(): GameState["board"] {
  const board = openingBoard();
  board[4][5] = "black";
  board[4][4] = "black";
  return board;
}

function gameState(overrides: Partial<GameState> = {}): GameState {
  return {
    id: GAME_ID,
    board: openingBoard(),
    side_to_move: "black",
    legal_moves: ["c4", "d3", "e6", "f5"],
    pass_is_legal: false,
    last_move: null,
    is_over: false,
    official_score: { black: 2, white: 2 },
    result: null,
    status: "in_progress",
    continuation_possible: true,
    unplayable_reason: null,
    black: { kind: "specimen", specimen_id: "random_uniform" },
    white: { kind: "specimen", specimen_id: "most_flips" },
    ...overrides,
  };
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function problemResponse(status: number, code: string): Response {
  return new Response(
    JSON.stringify({
      type: `urn:reversi-ai:error:${code}`,
      title: "Not Found",
      status,
      detail: "対局が無い",
      code,
    }),
    {
      status,
      headers: { "content-type": "application/problem+json" },
    },
  );
}

function appWith(
  request: StrategyGateway["request"],
  ssePollIntervalMs = 0,
): ReturnType<typeof createApp> {
  return createApp({
    publicOrigin: PUBLIC_ORIGIN,
    strategy: { request },
    ssePollIntervalMs,
  });
}

function parseSse(body: string): GameEvent[] {
  const blocks = body.split("\n\n").filter((block) => block.trim() !== "");
  return blocks.map((block) => {
    const eventLine = block
      .split("\n")
      .find((line) => line.startsWith("event:"));
    const dataLine = block.split("\n").find((line) => line.startsWith("data:"));
    expect(eventLine).toBeDefined();
    expect(dataLine).toBeDefined();
    const parsed = gameEventSchema.parse(
      JSON.parse((dataLine ?? "").slice("data:".length).trim()),
    );
    expect(parsed.type).toBe((eventLine ?? "").slice("event:".length).trim());
    return parsed;
  });
}

describe("sse", () => {
  it("終局したエージェント対エージェントは snapshot と game_over を同一オリジンで返す", async () => {
    const finished = gameState({
      board: afterF5Board(),
      side_to_move: "white",
      legal_moves: [],
      last_move: { type: "place", square: "f5" },
      is_over: true,
      official_score: { black: 33, white: 31 },
      result: { winner: "black", black: "win", white: "loss" },
      status: "completed",
      continuation_possible: false,
    });
    const calls: Array<{ path: string; method: string }> = [];
    const app = appWith(async (path, init) => {
      calls.push({ path, method: init?.method ?? "GET" });
      return jsonResponse(200, finished);
    });
    const res = await app.request(EVENTS);
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toMatch(/text\/event-stream/);
    const events = parseSse(await res.text());
    expect(events.map((event) => event.type)).toEqual([
      "snapshot",
      "game_over",
    ]);
    expect(snapshotEventSchema.parse(events[0]).game.is_over).toBe(true);
    expect(gameOverEventSchema.parse(events[1]).game.result?.winner).toBe(
      "black",
    );
    expect(calls).toEqual([{ path: `/api/games/${GAME_ID}`, method: "GET" }]);
  });

  it("進行中の局は人手の着手 POST なしに戦略の盤面更新を流し終局まで進む", async () => {
    const opening = gameState();
    const mid = gameState({
      board: afterF5Board(),
      side_to_move: "white",
      legal_moves: ["d6", "f4", "f6"],
      last_move: { type: "place", square: "f5" },
      official_score: { black: 4, white: 1 },
    });
    const finished = gameState({
      board: afterF5Board(),
      side_to_move: "black",
      legal_moves: [],
      last_move: { type: "place", square: "d6" },
      is_over: true,
      official_score: { black: 33, white: 31 },
      result: { winner: "black", black: "win", white: "loss" },
      status: "completed",
      continuation_possible: false,
    });
    const states = [opening, mid, finished];
    const calls: Array<{ path: string; method: string }> = [];
    const app = appWith(async (path, init) => {
      calls.push({ path, method: init?.method ?? "GET" });
      const next = states.shift() ?? finished;
      return jsonResponse(200, next);
    });
    const res = await app.request(EVENTS);
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toMatch(/text\/event-stream/);
    const events = parseSse(await res.text());
    expect(events.map((event) => event.type)).toEqual([
      "snapshot",
      "move_applied",
      "move_applied",
      "game_over",
    ]);
    expect(snapshotEventSchema.parse(events[0]).game.last_move).toBeNull();
    expect(moveAppliedEventSchema.parse(events[1]).move).toEqual({
      type: "place",
      square: "f5",
    });
    expect(moveAppliedEventSchema.parse(events[2]).move).toEqual({
      type: "place",
      square: "d6",
    });
    expect(gameOverEventSchema.parse(events[3]).game.is_over).toBe(true);
    expect(calls.every((call) => call.method === "GET")).toBe(true);
    expect(calls.every((call) => call.path === `/api/games/${GAME_ID}`)).toBe(
      true,
    );
    expect(calls.some((call) => call.path.includes("/moves"))).toBe(false);
  });

  it("継続不能なら snapshot と unplayable を返す", async () => {
    const failed = gameState({
      status: "unplayable",
      continuation_possible: false,
      unplayable_reason: "external_model_failed",
    });
    const app = appWith(async () => jsonResponse(200, failed));
    const res = await app.request(EVENTS);
    const events = parseSse(await res.text());
    expect(events.map((event) => event.type)).toEqual([
      "snapshot",
      "unplayable",
    ]);
    expect(unplayableEventSchema.parse(events[1]).reason).toBe(
      "external_model_failed",
    );
  });

  it("進行中の戦略取得失敗は unplayable を流して終える", async () => {
    const opening = gameState();
    let calls = 0;
    const app = appWith(async () => {
      calls += 1;
      if (calls === 1) {
        return jsonResponse(200, opening);
      }
      return problemResponse(500, "internal_error");
    });
    const res = await app.request(EVENTS);
    expect(res.status).toBe(200);
    const events = parseSse(await res.text());
    expect(events.map((event) => event.type)).toEqual([
      "snapshot",
      "unplayable",
    ]);
    const failed = unplayableEventSchema.parse(events[1]);
    expect(failed.reason).toBe("external_model_failed");
    expect(failed.game.status).toBe("unplayable");
    expect(failed.game.continuation_possible).toBe(false);
  });

  it("対局が無ければ戦略の 404 を中継し SSE にしない", async () => {
    const app = appWith(async () => problemResponse(404, "game_not_found"));
    const res = await app.request(EVENTS);
    expect(res.status).toBe(404);
    expect(res.headers.get("content-type")).toMatch(/problem\+json/);
    expect(await res.json()).toMatchObject({ code: "game_not_found" });
  });

  it("streamLiveGameEvents は戦略の後続状態だけを move_applied にする", async () => {
    const written: GameEvent[] = [];
    const opening = gameState();
    const finished = gameState({
      board: afterF5Board(),
      last_move: { type: "place", square: "f5" },
      is_over: true,
      status: "completed",
      continuation_possible: false,
      result: { winner: "black", black: "win", white: "loss" },
      official_score: { black: 4, white: 1 },
    });
    await streamLiveGameEvents(
      async (event, data) => {
        const parsed = gameEventSchema.parse(data);
        expect(parsed.type).toBe(event);
        written.push(parsed);
      },
      async () => {},
      () => false,
      opening,
      async () => finished,
      0,
    );
    expect(written.map((event) => event.type)).toEqual([
      "snapshot",
      "move_applied",
      "game_over",
    ]);
  });

  it("streamLiveGameEvents は後続取得失敗を unplayable にする", async () => {
    const written: GameEvent[] = [];
    await streamLiveGameEvents(
      async (event, data) => {
        const parsed = gameEventSchema.parse(data);
        expect(parsed.type).toBe(event);
        written.push(parsed);
      },
      async () => {},
      () => false,
      gameState(),
      async () => null,
      0,
    );
    expect(written.map((event) => event.type)).toEqual([
      "snapshot",
      "unplayable",
    ]);
    expect(unplayableEventSchema.parse(written[1]).game.status).toBe(
      "unplayable",
    );
  });

  it("Hono の SSE は WebSocket を使わず戦略 GET が更新の源である", () => {
    const sources = [
      "web/server/src/sse.ts",
      "web/server/src/app.ts",
      "web/server/src/strategy.ts",
    ]
      .map((path) => readFileSync(path, "utf8"))
      .join("\n");
    expect(sources).not.toMatch(/WebSocket|websocket|ws:/i);
    expect(sources).toContain("text/event-stream");
    expect(readFileSync("web/server/src/app.ts", "utf8")).toContain(
      "followStrategyGame",
    );
  });
});
