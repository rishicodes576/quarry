// Independent AI component probe. Never connects to the application or database.
const fs = require("node:fs");
const cp = require("node:child_process");
const vm = require("node:vm");
const root = require("node:path").resolve(__dirname, "../..");
const ts = require(
  require("node:path").join(root, "frontend/node_modules/typescript"),
);
const source = cp.execFileSync(
  "git",
  ["show", "9e7833d:frontend/src/app/api/[...path]/route.ts"],
  { cwd: root, encoding: "utf8" },
);
const js = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;
const exportsObject = {};
const context = {
  exports: exportsObject,
  require,
  Response,
  Headers,
  URL,
  process: { env: { APP_ORIGIN: "http://localhost:3000" } },
  fetch: async () => new Response("unauthenticated", { status: 401 }),
};
vm.runInNewContext(js, context);
const releases = [];
function request(block) {
  return {
    method: "POST",
    headers: new Headers({ origin: "http://localhost:3000" }),
    nextUrl: new URL("http://localhost:3000/api/v1/auth/login"),
    signal: new AbortController().signal,
    body: {
      getReader() {
        return {
          read() {
            return block
              ? new Promise((resolve) => releases.push(resolve))
              : Promise.resolve({ done: true });
          },
        };
      },
    },
  };
}
(async () => {
  const pending = Array.from({ length: 8 }, () =>
    exportsObject.POST(request(true), {
      params: Promise.resolve({ path: ["v1", "auth", "login"] }),
    }),
  );
  await new Promise((r) => setTimeout(r, 300));
  const ninth = await exportsObject.POST(request(false), {
    params: Promise.resolve({ path: ["v1", "auth", "login"] }),
  });
  releases.forEach((resolve) => resolve({ done: true }));
  const finished = await Promise.all(pending);
  const result = {
    reviewed_commit: "9e7833d6ae90c27c0d5338da22855524bc4047bd",
    probe:
      "original BFF transpiled with fake fetch and bounded stalled streams; no sockets/database",
    held_unauthenticated_mutations: 8,
    held_ms: 300,
    ninth_status: ninth.status,
    released_statuses: finished.map((r) => r.status),
  };
  fs.writeFileSync(
    require("node:path").join(
      root,
      "evaluation/results/independent-review-bff.json",
    ),
    JSON.stringify(result, null, 2),
  );
  console.log(JSON.stringify(result));
  clearTimeout(harnessTimer);
})();

// Bound the harness itself if a future regression leaves test streams unresolved.
const harnessTimer = setTimeout(() => {
  console.error("Probe exceeded five seconds");
  process.exit(1);
}, 5000);
