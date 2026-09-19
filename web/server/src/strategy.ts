/** Pod 内 FastAPI へ HTTP 中継する。盤の合法手計算は持たない。 */

import { strategyUnreachable } from "./problems.ts";

export type StrategyGateway = {
  request: (path: string, init?: RequestInit) => Promise<Response>;
};

function relayHeaders(res: Response): Headers {
  const headers = new Headers();
  const contentType = res.headers.get("content-type");
  if (contentType !== null) {
    headers.set("content-type", contentType);
  }
  const location = res.headers.get("location");
  if (location !== null) {
    headers.set("location", location);
  }
  return headers;
}

function asRelay(res: Response): Response {
  return new Response(res.body, {
    status: res.status,
    headers: relayHeaders(res),
  });
}

function strategyUrl(baseUrl: string, path: string): string {
  const root = baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`;
  return new URL(path.replace(/^\//, ""), root).toString();
}

export function createStrategyGateway(
  baseUrl: string,
  fetchImpl: typeof fetch = fetch,
  timeoutMs = 60_000,
): StrategyGateway {
  return {
    async request(path, init = {}) {
      const method = init.method ?? "GET";
      const signal = AbortSignal.timeout(timeoutMs);
      try {
        const res = await fetchImpl(strategyUrl(baseUrl, path), {
          ...init,
          signal,
        });
        if (res.status >= 500) {
          return strategyUnreachable(method);
        }
        return asRelay(res);
      } catch {
        return strategyUnreachable(method);
      }
    },
  };
}
