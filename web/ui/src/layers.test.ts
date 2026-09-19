import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

function walk(dir: string): string[] {
  const entries = readdirSync(dir);
  const files: string[] = [];
  for (const entry of entries) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      files.push(...walk(path));
    } else {
      files.push(path);
    }
  }
  return files;
}

describe("web/ui の層", () => {
  it("web/server を import せず、HTML をスクリプトとして埋め込まない", () => {
    const files = walk("web/ui/src").filter((path) =>
      /\.(ts|tsx|css|html)$/.test(path),
    );
    expect(files.length).toBeGreaterThan(0);
    const joined = files.map((path) => readFileSync(path, "utf8")).join("\n");
    const forbidden = ["dangerously", "SetInnerHTML"].join("");
    expect(joined).not.toMatch(/from ["'][^"']*web\/server/);
    expect(joined).not.toContain(forbidden);
  });
});
