import type {
  CatalogItem,
  CreateGameRequest,
  GameState,
  Move,
} from "./types.ts";

export type GameStreamFailure = "game_not_found" | "internal_error";

export const SSE_RECONNECT_DELAY_MS = 250;
export const SSE_MAX_RECONNECTS = 5;
export const SSE_RECONNECT_DELAY_CAP_MS = 2000;

export type SubscribeGameEventsOptions = {
  reconnectDelayMs?: number;
  maxReconnects?: number;
  sleep?: (ms: number) => Promise<void>;
};

async function defaultSleep(ms: number): Promise<void> {
  if (ms <= 0) {
    return;
  }
  await new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

function reconnectWaitMs(attempt: number, base: number, cap: number): number {
  return Math.min(cap, base * 2 ** (attempt - 1));
}

async function lookupLiveGame(
  id: string,
): Promise<GameState | GameStreamFailure> {
  try {
    const res = await fetch(`/api/games/${id}`);
    if (res.ok) {
      return (await res.json()) as GameState;
    }
    const code = problemCode(await res.json());
    return code === "game_not_found" ? "game_not_found" : "internal_error";
  } catch {
    return "internal_error";
  }
}

function isStreamFailure(
  got: GameState | GameStreamFailure,
): got is GameStreamFailure {
  return got === "game_not_found" || got === "internal_error";
}

async function readJson(res: Response): Promise<unknown> {
  return await res.json();
}

function problemCode(body: unknown): string | undefined {
  if (typeof body !== "object" || body === null || !("code" in body)) {
    return undefined;
  }
  const code = body.code;
  return typeof code === "string" ? code : undefined;
}

export async function fetchCatalog(): Promise<CatalogItem[]> {
  const res = await fetch("/api/catalog");
  if (!res.ok) {
    throw new Error("カタログを取得できませんでした。");
  }
  const body = (await readJson(res)) as { items?: CatalogItem[] };
  if (!Array.isArray(body.items)) {
    throw new Error("カタログの応答が契約と違います。");
  }
  return body.items;
}

export async function createGame(
  request: CreateGameRequest,
): Promise<GameState> {
  const res = await fetch("/api/games", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    throw new Error("対局を開始できませんでした。");
  }
  return (await readJson(res)) as GameState;
}

export class MoveRejectedError extends Error {
  constructor(
    readonly game: GameState,
    detail: string,
    readonly code?: string,
  ) {
    super(detail);
    this.name = "MoveRejectedError";
  }
}

export async function playMove(id: string, move: Move): Promise<GameState> {
  const res = await fetch(`/api/games/${id}/moves`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(move),
  });
  const body = (await readJson(res)) as {
    applied?: boolean;
    game?: GameState;
    detail?: string;
    code?: string;
  };
  if (body.game === undefined) {
    throw new Error("着手に失敗しました。");
  }
  if (body.applied === false) {
    throw new MoveRejectedError(
      body.game,
      body.detail ?? "その手は打てません。",
      body.code,
    );
  }
  return body.game;
}

export function subscribeGameEvents(
  id: string,
  onGame: (game: GameState) => void,
  onFailure?: (code: GameStreamFailure) => void,
  options: SubscribeGameEventsOptions = {},
): () => void {
  const url = `/api/games/${id}/events`;
  const delayMs = options.reconnectDelayMs ?? SSE_RECONNECT_DELAY_MS;
  const maxReconnects = options.maxReconnects ?? SSE_MAX_RECONNECTS;
  const sleep = options.sleep ?? defaultSleep;
  let source: EventSource | null = null;
  let closed = false;
  let terminal = false;
  let failures = 0;
  let classifying = false;
  const handle = (event: MessageEvent<string>) => {
    try {
      const payload = JSON.parse(event.data) as { game?: GameState };
      if (payload.game === undefined) {
        return;
      }
      failures = 0;
      if (payload.game.status !== "in_progress") {
        terminal = true;
      }
      onGame(payload.game);
    } catch {
      return;
    }
  };
  const connect = () => {
    if (closed || terminal) {
      return;
    }
    source?.close();
    const next = new EventSource(url);
    source = next;
    next.addEventListener("snapshot", handle);
    next.addEventListener("move_applied", handle);
    next.addEventListener("game_over", handle);
    next.addEventListener("unplayable", handle);
    next.onerror = () => {
      next.close();
      void classify();
    };
  };
  const fail = (code: GameStreamFailure) => {
    source?.close();
    onFailure?.(code);
  };
  const reconnectIfAllowed = async () => {
    if (failures >= maxReconnects) {
      fail("internal_error");
      return;
    }
    failures += 1;
    await sleep(reconnectWaitMs(failures, delayMs, SSE_RECONNECT_DELAY_CAP_MS));
    if (closed || terminal) {
      return;
    }
    connect();
  };
  const recoverFromDisconnect = async () => {
    const got = await lookupLiveGame(id);
    if (closed || terminal) {
      return;
    }
    if (isStreamFailure(got)) {
      fail(got);
      return;
    }
    if (got.status !== "in_progress") {
      terminal = true;
      onGame(got);
      return;
    }
    onGame(got);
    await reconnectIfAllowed();
  };
  const classify = async () => {
    if (closed || terminal || classifying) {
      return;
    }
    classifying = true;
    try {
      await recoverFromDisconnect();
    } finally {
      classifying = false;
    }
  };
  connect();
  return () => {
    closed = true;
    source?.close();
  };
}
