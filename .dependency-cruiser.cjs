/** @type {import("dependency-cruiser").IConfiguration} */
module.exports = {
  forbidden: [
    {
      name: "no-circular",
      comment: "循環依存を禁止する",
      severity: "error",
      from: {},
      to: { circular: true },
    },
    {
      name: "web-not-to-server",
      comment: "UI は HTTP 経由だけ。web/server を import しない",
      severity: "error",
      from: { path: "^web/ui" },
      to: { path: "^web/server" },
    },
    {
      name: "server-not-to-web",
      comment: "Hono は React を import しない",
      severity: "error",
      from: { path: "^web/server" },
      to: { path: "^web/ui" },
    },
  ],
  options: {
    doNotFollow: {
      path: "node_modules",
    },
    tsPreCompilationDeps: true,
  },
};
