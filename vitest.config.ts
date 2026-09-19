import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    projects: [
      {
        test: {
          name: "server",
          dir: "web/server",
          environment: "node",
        },
      },
      {
        plugins: [react()],
        test: {
          name: "ui",
          dir: "web/ui",
          environment: "jsdom",
          setupFiles: ["./web/ui/src/test-setup.ts"],
        },
      },
    ],
  },
});
