import type {
  CatalogItem,
  CreateGameRequest,
  GameState,
  Move,
} from "./types.ts";

async function readJson(res: Response): Promise<unknown> {
  return await res.json();
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
  };
  if (body.game === undefined) {
    throw new Error("着手に失敗しました。");
  }
  if (body.applied === false) {
    throw new MoveRejectedError(
      body.game,
      body.detail ?? "その手は打てません。",
    );
  }
  return body.game;
}

export function subscribeGameEvents(
  id: string,
  onGame: (game: GameState) => void,
): () => void {
  const source = new EventSource(`/api/games/${id}/events`);
  const handle = (event: MessageEvent<string>) => {
    try {
      const payload = JSON.parse(event.data) as { game?: GameState };
      if (payload.game !== undefined) {
        onGame(payload.game);
      }
    } catch {
      return;
    }
  };
  source.addEventListener("snapshot", handle);
  source.addEventListener("game_over", handle);
  source.addEventListener("unplayable", handle);
  return () => source.close();
}
