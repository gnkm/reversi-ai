import { readFileSync } from "node:fs";
import { createServer } from "node:https";
import { fileURLToPath } from "node:url";
import { serve } from "@hono/node-server";
import { createApp } from "./app.ts";
import {
  certPaths,
  LISTEN_HOST,
  listenPort,
  publicOrigin,
  strategyBaseUrl,
  strategyTimeoutMs,
} from "./listen.ts";
import { createStrategyGateway } from "./strategy.ts";

export function startServer(
  env: NodeJS.ProcessEnv = process.env,
): ReturnType<typeof serve> {
  const port = listenPort(env);
  const paths = certPaths(env);
  const app = createApp({
    publicOrigin: publicOrigin(env, port),
    strategy: createStrategyGateway(
      strategyBaseUrl(env),
      fetch,
      strategyTimeoutMs(env),
    ),
  });
  return serve({
    fetch: app.fetch,
    hostname: LISTEN_HOST,
    port,
    createServer,
    serverOptions: {
      cert: readFileSync(paths.cert),
      key: readFileSync(paths.key),
    },
  });
}

function isDirectRun(): boolean {
  const entry = process.argv[1];
  if (entry === undefined) {
    return false;
  }
  return fileURLToPath(import.meta.url) === entry;
}

if (isDirectRun()) {
  startServer();
}
