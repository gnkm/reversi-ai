#!/usr/bin/env bash
# Playwright が叩く HTTPS スタックを上げる。
# Podman があれば compose を正とする（docs/ARCHITECTURE.md 8.4）。
set -euo pipefail

if command -v podman >/dev/null 2>&1 && [ -z "${E2E_HOST_STACK:-}" ]; then
  exec podman compose up --build
fi

pnpm run build:ui
mkdir -p data/certs
if [ ! -f data/certs/cert.pem ] || [ ! -f data/certs/key.pem ]; then
  openssl req -x509 -nodes -newkey rsa:2048 \
    -keyout data/certs/key.pem -out data/certs/cert.pem \
    -days 1 -subj /CN=127.0.0.1
fi

uv run --directory strategy python -m reversi.api &
for _ in $(seq 1 50); do
  if curl -sf http://127.0.0.1:8000/api/catalog >/dev/null; then
    break
  fi
  sleep 0.2
done

exec node --experimental-strip-types web/server/src/index.ts
