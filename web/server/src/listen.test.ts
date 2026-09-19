import { readFileSync } from "node:fs";
import { createServer } from "node:https";
import { describe, expect, it } from "vitest";
import {
  DEFAULT_CERT_FILE,
  DEFAULT_KEY_FILE,
  DEFAULT_STRATEGY_TIMEOUT_MS,
  LISTEN_HOST,
  listenPort,
  publicOrigin,
  strategyTimeoutMs,
  uiRoot,
} from "./listen.ts";

describe("listen", () => {
  it("既定の待ち受けは 127.0.0.1 であり 0.0.0.0 を置かない", () => {
    expect(LISTEN_HOST).toBe("127.0.0.1");
    expect(LISTEN_HOST).not.toBe("0.0.0.0");
    expect(listenPort({})).toBe(3000);
    expect(publicOrigin({})).toBe("https://127.0.0.1:3000");
    expect(DEFAULT_CERT_FILE).toBe("data/certs/cert.pem");
    expect(DEFAULT_KEY_FILE).toBe("data/certs/key.pem");
    expect(strategyTimeoutMs({})).toBe(DEFAULT_STRATEGY_TIMEOUT_MS);
    expect(DEFAULT_STRATEGY_TIMEOUT_MS).toBe(60_000);
    expect(uiRoot({})).toBe("web/ui/dist");
    expect(uiRoot({ UI_ROOT: "" })).toBe("web/ui/dist");
    expect(uiRoot({ UI_ROOT: "/app/web/ui/dist" })).toBe("/app/web/ui/dist");
  });

  it("入口は node:https の createServer に PEM を渡す", () => {
    const src = readFileSync("web/server/src/index.ts", "utf8");
    expect(src).toContain('from "node:https"');
    expect(src).toContain("createServer");
    expect(src).toContain("hostname: LISTEN_HOST");
    expect(src).not.toContain("0.0.0.0");
    expect(src).not.toContain("node:http'");
    expect(createServer).toBeTypeOf("function");
  });
});
