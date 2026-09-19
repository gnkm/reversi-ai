import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("no legal-move engine in Hono", () => {
  it("web/server は合法手計算も web/ui も持たない", () => {
    const files = [
      "web/server/src/app.ts",
      "web/server/src/strategy.ts",
      "web/server/src/origin.ts",
      "web/server/src/sse.ts",
      "web/server/src/schemas.ts",
      "web/server/src/index.ts",
      "web/server/src/listen.ts",
      "web/server/src/spa.ts",
    ];
    const joined = files.map((path) => readFileSync(path, "utf8")).join("\n");
    expect(joined).not.toMatch(/from ["']web\/ui/);
    expect(joined).not.toMatch(/legal_places|flipped|bitboard/i);
    expect(joined).not.toContain("reversi.engine");
  });
});
