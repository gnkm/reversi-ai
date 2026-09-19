import type { GameState } from "./schemas.ts";

function sseBlock(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

export function gameEventsBody(game: GameState): string {
  const chunks = [sseBlock("snapshot", { type: "snapshot", game })];
  if (game.status === "completed" || game.is_over) {
    chunks.push(sseBlock("game_over", { type: "game_over", game }));
  } else if (game.status === "unplayable") {
    chunks.push(
      sseBlock("unplayable", {
        type: "unplayable",
        reason: game.unplayable_reason ?? "external_model_failed",
        game,
      }),
    );
  }
  return chunks.join("");
}

export function gameEventsResponse(game: GameState): Response {
  return new Response(gameEventsBody(game), {
    status: 200,
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache",
    },
  });
}
