import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { createApp, PUBLIC_API_ROUTES } from "./app.ts";
import type { GameState } from "./schemas.ts";
import { createStrategyGateway, type StrategyGateway } from "./strategy.ts";

const PUBLIC_ORIGIN = "https://127.0.0.1:3000";
const GAME_ID = "550e8400-e29b-41d4-a716-446655440000";

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
    black: { kind: "human" },
    white: { kind: "specimen", specimen_id: "random_uniform" },
    ...overrides,
  };
}

function jsonResponse(
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

function appWith(
  request: StrategyGateway["request"],
): ReturnType<typeof createApp> {
  return createApp({
    publicOrigin: PUBLIC_ORIGIN,
    strategy: { request },
  });
}

function originHeaders(origin = PUBLIC_ORIGIN): Record<string, string> {
  return {
    origin,
    "content-type": "application/json",
  };
}

describe("origin", () => {
  it("状態変更 POST の Origin が自オリジンと一致しなければ 403 で戦略を呼ばない", async () => {
    const calls: string[] = [];
    const app = appWith(async (path) => {
      calls.push(path);
      return jsonResponse(200, { items: [] });
    });
    const res = await app.request(`https://127.0.0.1:3000/api/games`, {
      method: "POST",
      headers: originHeaders("https://evil.example"),
      body: JSON.stringify({
        black: { kind: "human" },
        white: { kind: "specimen", specimen_id: "random_uniform" },
      }),
    });
    expect(res.status).toBe(403);
    expect(calls).toEqual([]);
  });

  it("Origin が無い状態変更 POST も 403 である", async () => {
    const app = appWith(async () => jsonResponse(201, gameState()));
    const res = await app.request(`https://127.0.0.1:3000/api/games`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        black: { kind: "human" },
        white: { kind: "human" },
      }),
    });
    expect(res.status).toBe(403);
  });

  it("GET は Origin 無しでもカタログを中継する", async () => {
    const app = appWith(async () => jsonResponse(200, { items: [] }));
    const res = await app.request("https://127.0.0.1:3000/api/catalog");
    expect(res.status).toBe(200);
    await expect(res.json()).resolves.toEqual({ items: [] });
  });

  it("一致する Origin の POST は戦略へ中継する", async () => {
    const app = appWith(async () =>
      jsonResponse(201, gameState(), {
        location: `/api/games/${GAME_ID}`,
      }),
    );
    const res = await app.request("https://127.0.0.1:3000/api/games", {
      method: "POST",
      headers: originHeaders(),
      body: JSON.stringify({
        black: { kind: "human" },
        white: { kind: "human" },
      }),
    });
    expect(res.status).toBe(201);
    expect(res.headers.get("location")).toBe(`/api/games/${GAME_ID}`);
  });
});

describe("strategy relay", () => {
  it("人間の違法着手は戦略の拒否をそのまま返し、盤を書き換えない", async () => {
    const before = gameState();
    const rejection = {
      applied: false,
      code: "illegal_move",
      detail: "違法な着手は盤に適用しない",
      game: before,
    };
    const app = appWith(async (path, init) => {
      expect(path).toBe(`/api/games/${GAME_ID}/moves`);
      expect(init?.method).toBe("POST");
      return jsonResponse(409, rejection);
    });
    const res = await app.request(
      `https://127.0.0.1:3000/api/games/${GAME_ID}/moves`,
      {
        method: "POST",
        headers: originHeaders(),
        body: JSON.stringify({ type: "place", square: "a1" }),
      },
    );
    expect(res.status).toBe(409);
    const body = await res.json();
    expect(body).toEqual(rejection);
    expect(body.applied).toBe(false);
    expect(body.game.board).toEqual(before.board);
    expect(body.game.side_to_move).toBe("black");
  });

  it("戦略呼出し失敗時は部分適用せず継続不能を返す", async () => {
    let calls = 0;
    const app = appWith(async () => {
      calls += 1;
      throw new Error("strategy down");
    });
    const create = await app.request("https://127.0.0.1:3000/api/games", {
      method: "POST",
      headers: originHeaders(),
      body: JSON.stringify({
        black: { kind: "human" },
        white: { kind: "human" },
      }),
    });
    expect(create.status).toBe(422);
    const created = await create.json();
    expect(created.code).toBe("external_model_failed");
    expect(created.applied).toBeUndefined();
    expect(calls).toBe(1);

    const move = await app.request(
      `https://127.0.0.1:3000/api/games/${GAME_ID}/moves`,
      {
        method: "POST",
        headers: originHeaders(),
        body: JSON.stringify({ type: "place", square: "d3" }),
      },
    );
    expect(move.status).toBe(422);
    const moved = await move.json();
    expect(moved.code).toBe("external_model_failed");
    expect(moved.applied).toBeUndefined();
    expect(calls).toBe(2);
  });

  it("戦略の 5xx も継続不能にし、本文は転送しない", async () => {
    const app = createApp({
      publicOrigin: PUBLIC_ORIGIN,
      strategy: createStrategyGateway("http://strategy.test", async () => {
        return new Response("traceback", {
          status: 500,
          headers: { "content-type": "text/plain" },
        });
      }),
    });
    const res = await app.request("https://127.0.0.1:3000/api/games", {
      method: "POST",
      headers: originHeaders(),
      body: JSON.stringify({
        black: { kind: "human" },
        white: { kind: "human" },
      }),
    });
    expect(res.status).toBe(422);
    const body = await res.json();
    expect(body.code).toBe("external_model_failed");
    expect(JSON.stringify(body)).not.toContain("traceback");
  });

  it("形が契約と違う POST は 400 で戦略を呼ばない", async () => {
    let calls = 0;
    const app = appWith(async () => {
      calls += 1;
      return jsonResponse(201, gameState());
    });
    const res = await app.request("https://127.0.0.1:3000/api/games", {
      method: "POST",
      headers: originHeaders(),
      body: JSON.stringify({ black: { kind: "human" } }),
    });
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.code).toBe("validation_error");
    expect(calls).toBe(0);
  });
});

describe("public /api paths", () => {
  it("公開する /api/* は openapi.yml の経路と一致し /decide は出さない", () => {
    const openapi = readFileSync("docs/openapi.yml", "utf8");
    const documented = [...openapi.matchAll(/^ {2}(\/api\/[^:]+):$/gm)].map(
      (match) => match[1],
    );
    expect(documented).toEqual([
      "/api/catalog",
      "/api/games",
      "/api/games/{id}",
      "/api/games/{id}/moves",
      "/api/games/{id}/events",
    ]);
    const honoPaths = PUBLIC_API_ROUTES.map(([, path]) =>
      path.replaceAll(":id", "{id}"),
    );
    expect(honoPaths).toEqual(documented);

    const app = appWith(async () => jsonResponse(200, { items: [] }));
    const decide = app.routes.filter((route) => route.path.includes("decide"));
    expect(decide).toEqual([]);
    const apiPaths = new Set(
      app.routes
        .filter((route) => route.path.startsWith("/api/"))
        .map((route) => `${route.method} ${route.path}`),
    );
    for (const [method, path] of PUBLIC_API_ROUTES) {
      expect(apiPaths.has(`${method} ${path}`)).toBe(true);
    }
  });

  it("対局イベントは戦略の状態を SSE で返す", async () => {
    const finished = gameState({
      is_over: true,
      status: "completed",
      continuation_possible: false,
      result: { winner: "draw", black: "draw", white: "draw" },
    });
    const app = appWith(async () => jsonResponse(200, finished));
    const res = await app.request(
      `https://127.0.0.1:3000/api/games/${GAME_ID}/events`,
    );
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toMatch(/text\/event-stream/);
    const body = await res.text();
    expect(body).toContain("event: snapshot");
    expect(body).toContain("event: game_over");
    expect(body).toContain(`"id":"${GAME_ID}"`);
  });
});
