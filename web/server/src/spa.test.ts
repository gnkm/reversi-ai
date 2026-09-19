import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { createApp } from "./app.ts";
import type { StrategyGateway } from "./strategy.ts";

const PUBLIC_ORIGIN = "https://127.0.0.1:3000";

function appWith(
  request: StrategyGateway["request"],
  uiRoot?: string,
): ReturnType<typeof createApp> {
  return createApp({
    publicOrigin: PUBLIC_ORIGIN,
    strategy: { request },
    uiRoot,
  });
}

describe("SPA 静的配信", () => {
  it("GET / と GET /game は index.html を返し /api は中継する", async () => {
    const root = mkdtempSync(join(tmpdir(), "reversi-ui-"));
    writeFileSync(
      join(root, "index.html"),
      "<!doctype html><title>リバーシ対局</title>",
    );
    mkdirSync(join(root, "assets"));
    writeFileSync(join(root, "assets", "app.js"), "console.log(1)");
    let catalogCalls = 0;
    const app = appWith(async (path) => {
      catalogCalls += 1;
      expect(path).toBe("/api/catalog");
      return new Response(JSON.stringify({ items: [] }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }, root);

    const home = await app.request("https://127.0.0.1:3000/");
    expect(home.status).toBe(200);
    expect(await home.text()).toContain("リバーシ対局");

    const game = await app.request("https://127.0.0.1:3000/game");
    expect(game.status).toBe(200);
    expect(await game.text()).toContain("リバーシ対局");

    const asset = await app.request("https://127.0.0.1:3000/assets/app.js");
    expect(asset.status).toBe(200);
    expect(await asset.text()).toBe("console.log(1)");

    const catalog = await app.request("https://127.0.0.1:3000/api/catalog");
    expect(catalog.status).toBe(200);
    expect(catalogCalls).toBe(1);
  });
});
