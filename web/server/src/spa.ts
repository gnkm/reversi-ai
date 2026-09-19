import { readFileSync } from "node:fs";
import { join } from "node:path";
import { serveStatic } from "@hono/node-server/serve-static";
import type { Context, Hono } from "hono";

function spaIndex(uiRoot: string) {
  const indexPath = join(uiRoot, "index.html");
  return (c: Context) => {
    try {
      return c.html(readFileSync(indexPath, "utf8"));
    } catch {
      return c.text("Not Found", 404);
    }
  };
}

export function mountUi(app: Hono, uiRoot: string): void {
  const index = spaIndex(uiRoot);
  app.use(
    "/assets/*",
    serveStatic({
      root: uiRoot,
      rewriteRequestPath: (filename) => filename.replace(/^\//, ""),
    }),
  );
  app.get("/", index);
  app.get("/game", index);
}
