import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "@playwright/test";

const e2eDir = dirname(fileURLToPath(import.meta.url));

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
    command: "bash e2e/start-stack.sh",
    url: "https://127.0.0.1:3000",
    reuseExistingServer: true,
    ignoreHTTPSErrors: true,
    timeout: 180_000,
  },
});
