import type {
  CatalogItem,
  CreateGameRequest,
  GameState,
  Move,
} from "./types.ts";

export type GameStreamFailure = "game_not_found" | "internal_error";

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
): () => void {
  const url = `/api/games/${id}/events`;
  let source: EventSource | null = null;
  let closed = false;
  let terminal = false;
  const handle = (event: MessageEvent<string>) => {
    try {
      const payload = JSON.parse(event.data) as { game?: GameState };
      if (payload.game === undefined) {
        return;
      }
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
  const classify = async () => {
    if (closed || terminal) {
      return;
    }
    try {
      const res = await fetch(`/api/games/${id}`);
      if (res.ok) {
        const game = (await res.json()) as GameState;
        if (game.status !== "in_progress") {
          terminal = true;
          onGame(game);
          return;
        }
        onGame(game);
        connect();
        return;
      }
      const code = problemCode(await res.json());
      fail(code === "game_not_found" ? "game_not_found" : "internal_error");
    } catch {
      fail("internal_error");
    }
  };
  connect();
  return () => {
    closed = true;
    source?.close();
  };
}
