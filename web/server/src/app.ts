import type { Context } from "hono";
import { Hono } from "hono";
import { streamSSE } from "hono/streaming";
import { isStateChangingMethod, originMatches } from "./origin.ts";
import {
  problemResponse,
  strategyUnreachable,
  validationError,
} from "./problems.ts";
import {
  createGameRequestSchema,
  type GameState,
  gameStateSchema,
  moveSchema,
} from "./schemas.ts";
import { mountUi } from "./spa.ts";
import {
  DEFAULT_SSE_POLL_INTERVAL_MS,
  gameEventsResponse,
  streamLiveGameEvents,
  terminalSseEvent,
} from "./sse.ts";
import type { StrategyGateway } from "./strategy.ts";

export type CreateAppOptions = {
  publicOrigin: string;
  strategy: StrategyGateway;
  uiRoot?: string;
  ssePollIntervalMs?: number;
};

export const PUBLIC_API_ROUTES = [
  ["GET", "/api/catalog"],
  ["POST", "/api/games"],
  ["GET", "/api/games/:id"],
  ["POST", "/api/games/:id/moves"],
  ["GET", "/api/games/:id/events"],
] as const;

function jsonInit(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  };
}

async function readJson(c: Context): Promise<unknown> {
  try {
    return await c.req.json();
  } catch {
    return undefined;
  }
}

async function relay(
  strategy: StrategyGateway,
  path: string,
  init?: RequestInit,
): Promise<Response> {
  try {
    return await strategy.request(path, init);
  } catch {
    return strategyUnreachable(init?.method ?? "GET");
  }
}

async function postGames(
  c: Context,
  strategy: StrategyGateway,
): Promise<Response> {
  const parsed = createGameRequestSchema.safeParse(await readJson(c));
  if (!parsed.success) {
    return validationError();
  }
  return relay(strategy, "/api/games", jsonInit("POST", parsed.data));
}

async function postMove(
  c: Context,
  strategy: StrategyGateway,
): Promise<Response> {
  const parsed = moveSchema.safeParse(await readJson(c));
  if (!parsed.success) {
    return validationError();
  }
  const id = c.req.param("id");
  return relay(
    strategy,
    `/api/games/${id}/moves`,
    jsonInit("POST", parsed.data),
  );
}

async function readStrategyGame(
  strategy: StrategyGateway,
  id: string,
): Promise<Response | GameState> {
  const res = await relay(strategy, `/api/games/${id}`);
  if (!res.ok) {
    return res;
  }
  const parsed = gameStateSchema.safeParse(await res.json());
  if (!parsed.success) {
    return problemResponse(
      500,
      "internal_error",
      "Internal Server Error",
      "戦略プロセスの応答が契約と違う",
    );
  }
  return parsed.data;
}

async function followStrategyGame(
  strategy: StrategyGateway,
  id: string,
): Promise<GameState | undefined> {
  const got = await readStrategyGame(strategy, id);
  if (got instanceof Response) {
    return undefined;
  }
  return got;
}

function liveGameEvents(
  c: Context,
  strategy: StrategyGateway,
  id: string,
  initial: GameState,
  pollIntervalMs: number,
): Response {
  return streamSSE(c, async (stream) => {
    await streamLiveGameEvents(
      (event, data) => stream.writeSSE({ event, data: JSON.stringify(data) }),
      (ms) => stream.sleep(ms),
      () => stream.aborted,
      initial,
      () => followStrategyGame(strategy, id),
      pollIntervalMs,
    );
  });
}

async function getGameEvents(
  c: Context,
  strategy: StrategyGateway,
  pollIntervalMs: number,
): Promise<Response> {
  const id = c.req.param("id");
  const got = await readStrategyGame(strategy, id);
  if (got instanceof Response) {
    return got;
  }
  if (terminalSseEvent(got) !== undefined) {
    return gameEventsResponse(got);
  }
  return liveGameEvents(c, strategy, id, got, pollIntervalMs);
}

export function createApp(options: CreateAppOptions): Hono {
  const app = new Hono();
  const { publicOrigin, strategy, uiRoot } = options;
  const pollIntervalMs =
    options.ssePollIntervalMs ?? DEFAULT_SSE_POLL_INTERVAL_MS;
  app.use("*", async (c, next) => {
    if (
      isStateChangingMethod(c.req.method) &&
      !originMatches(c.req.header("origin"), publicOrigin)
    ) {
      return c.text("Forbidden", 403);
    }
    await next();
  });
  app.get("/api/catalog", () => relay(strategy, "/api/catalog"));
  app.post("/api/games", (c) => postGames(c, strategy));
  app.get("/api/games/:id", (c) =>
    relay(strategy, `/api/games/${c.req.param("id")}`),
  );
  app.post("/api/games/:id/moves", (c) => postMove(c, strategy));
  app.get("/api/games/:id/events", (c) =>
    getGameEvents(c, strategy, pollIntervalMs),
  );
  if (uiRoot !== undefined && uiRoot !== "") {
    mountUi(app, uiRoot);
  }
  return app;
}
