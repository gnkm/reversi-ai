import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "@playwright/test";

const e2eDir = dirname(fileURLToPath(import.meta.url));

/**
 * 既に Podman で上がっていればそれを使う（docs/ARCHITECTURE.md 8.4）。
 * 無いときはホストで戦略プロセスと Hono を上げ、検証コマンド単体でも通るようにする。
 */
const hostStackCommand = `
set -euo pipefail
pnpm run build:ui
mkdir -p data/certs
if [ ! -f data/certs/cert.pem ] || [ ! -f data/certs/key.pem ]; then
  openssl req -x509 -nodes -newkey rsa:2048 \\
    -keyout data/certs/key.pem -out data/certs/cert.pem \\
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
`;

const stackCommand = `
if command -v podman >/dev/null 2>&1 && [ -z "\${E2E_HOST_STACK:-}" ]; then
  exec podman compose up --build
fi
${hostStackCommand}
`;

export default defineConfig({
  testDir: e2eDir,
  testMatch: /.*\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: "list",
  timeout: 30_000,
  use: {
    baseURL: "https://127.0.0.1:3000",
    ignoreHTTPSErrors: true,
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chrome",
      use: {
        browserName: "chromium",
        channel: "chrome",
        launchOptions: {
          args: ["--ignore-certificate-errors"],
        },
      },
    },
  ],
  webServer: {
    command: `bash -c ${JSON.stringify(stackCommand)}`,
    url: "https://127.0.0.1:3000",
    reuseExistingServer: true,
    ignoreHTTPSErrors: true,
    timeout: 180_000,
  },
});
