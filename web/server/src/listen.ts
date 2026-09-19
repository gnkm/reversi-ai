/** 利用者向け待ち受け。既定はループバック HTTPS。0.0.0.0 は置かない。 */

export const LISTEN_HOST = "127.0.0.1";
export const DEFAULT_PORT = 3000;
export const DEFAULT_STRATEGY_BASE_URL = "http://127.0.0.1:8000";
export const DEFAULT_CERT_FILE = "data/certs/cert.pem";
export const DEFAULT_KEY_FILE = "data/certs/key.pem";

export function listenPort(env: NodeJS.ProcessEnv = process.env): number {
  const raw = env.PORT;
  if (raw === undefined || raw === "") {
    return DEFAULT_PORT;
  }
  const port = Number(raw);
  if (!Number.isInteger(port) || port <= 0 || port > 65535) {
    return DEFAULT_PORT;
  }
  return port;
}

export function publicOrigin(
  env: NodeJS.ProcessEnv = process.env,
  port = listenPort(env),
): string {
  return env.PUBLIC_ORIGIN ?? `https://${LISTEN_HOST}:${port}`;
}

export function strategyBaseUrl(env: NodeJS.ProcessEnv = process.env): string {
  return env.STRATEGY_BASE_URL ?? DEFAULT_STRATEGY_BASE_URL;
}

export function certPaths(env: NodeJS.ProcessEnv = process.env): {
  cert: string;
  key: string;
} {
  return {
    cert: env.TLS_CERT_FILE ?? DEFAULT_CERT_FILE,
    key: env.TLS_KEY_FILE ?? DEFAULT_KEY_FILE,
  };
}
