// Independent AI component probe. Never connects to the application or database.
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const crypto = require("node:crypto");
const root = path.resolve(__dirname, "../..");
const ts = require(path.join(root, "frontend/node_modules/typescript"));
const source = fs.readFileSync(
  path.join(root, "frontend/src/app/api/[...path]/route.ts"),
  "utf8",
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
  AbortSignal,
  AbortController,
  clearTimeout,
  setTimeout: (fn, ms) =>
    setTimeout(fn, ms === 15000 ? 50 : ms === 30000 ? 100 : ms),
  process: { env: { APP_ORIGIN: "http://localhost:3000" } },
  fetch: async () => new Response("unauthenticated", { status: 401 }),
};
vm.runInNewContext(js, context);
function request(block) {
  return {
    method: "POST",
    headers: new Headers({ origin: "http://localhost:3000" }),
    nextUrl: new URL("http://localhost:3000/api/v1/auth/login"),
    signal: new AbortController().signal,
    body: new ReadableStream({
      start(c) {
        if (!block) c.close();
      },
    }),
  };
}
(async () => {
  const pending = Array.from({ length: 8 }, () =>
    exportsObject.POST(request(true), {
      params: Promise.resolve({ path: ["v1", "auth", "login"] }),
    }),
  );
  await new Promise((r) => setTimeout(r, 10));
  const busy = await exportsObject.POST(request(false), {
    params: Promise.resolve({ path: ["v1", "auth", "login"] }),
  });
  const finished = await Promise.all(pending);
  const recovered = await exportsObject.POST(request(false), {
    params: Promise.resolve({ path: ["v1", "auth", "login"] }),
  });
  const loginPath = {
    params: Promise.resolve({ path: ["v1", "auth", "login"] }),
  };
  const crossOrigin = request(false);
  crossOrigin.headers.set("origin", "https://attacker.example");
  const csrf = await exportsObject.POST(crossOrigin, loginPath);
  const blockedPath = await exportsObject.POST(request(false), {
    params: Promise.resolve({ path: ["metrics"] }),
  });
  const traversal = await exportsObject.POST(request(false), {
    params: Promise.resolve({ path: ["v1", "..", "auth"] }),
  });
  let machineCookieForwarded = false;
  context.fetch = async (_url, options) => {
    machineCookieForwarded = options.headers.has("cookie");
    return new Response("unauthenticated", { status: 401 });
  };
  const machine = request(false);
  machine.headers.set("authorization", "Bearer qk_invalid");
  machine.headers.set("cookie", "quarry_session=inert");
  machine.headers.delete("origin");
  const machineResponse = await exportsObject.POST(machine, loginPath);
  context.fetch = async (_url, options) =>
    new Promise((_resolve, reject) => {
      options.signal.addEventListener(
        "abort",
        () => reject(new Error("inert upstream aborted")),
        { once: true },
      );
    });
  const upstreamDeadline = await exportsObject.POST(request(false), loginPath);
  // Header arrival must disarm the upstream timer without cutting a durable SSE stream.
  let streamAborted = false;
  let streamController;
  context.fetch = async (_url, options) => {
    options.signal.addEventListener(
      "abort",
      () => {
        streamAborted = true;
      },
      { once: true },
    );
    return new Response(
      new ReadableStream({
        start(controller) {
          streamController = controller;
          controller.enqueue(
            new TextEncoder().encode("event: update\ndata: first\n\n"),
          );
        },
      }),
      { headers: { "content-type": "text/event-stream" } },
    );
  };
  const streamRequest = request(false);
  streamRequest.method = "GET";
  streamRequest.body = undefined;
  const sse = await exportsObject.GET(streamRequest, {
    params: Promise.resolve({ path: ["v1", "runs", "inert", "stream"] }),
  });
  const sseReader = sse.body.getReader();
  const firstEvent = await sseReader.read();
  await new Promise((resolve) => setTimeout(resolve, 160));
  streamController.enqueue(
    new TextEncoder().encode("event: update\ndata: second\n\n"),
  );
  streamController.close();
  const secondEvent = await sseReader.read();
  const streamDone = await sseReader.read();
  sseReader.releaseLock();
  const sseSurvivedDeadline =
    !streamAborted &&
    !firstEvent.done &&
    !secondEvent.done &&
    streamDone.done &&
    new TextDecoder().decode(secondEvent.value).includes("second");
  const result = {
    probe:
      "current original BFF transpiled; real inert Web Streams, mocked fetch, timers scaled15s->50ms; no database/network",
    source_sha256: crypto.createHash("sha256").update(source).digest("hex"),
    busy_status: busy.status,
    timeout_statuses: finished.map((r) => r.status),
    recovered_status: recovered.status,
    csrf_status: csrf.status,
    blocked_path_status: blockedPath.status,
    traversal_status: traversal.status,
    invalid_machine_status: machineResponse.status,
    machine_cookie_forwarded: machineCookieForwarded,
    upstream_deadline_status: upstreamDeadline.status,
    sse_survived_scaled_header_deadline: sseSurvivedDeadline,
    sse_abort_observed: streamAborted,
  };
  result.status =
    busy.status === 503 &&
    finished.every((r) => r.status === 408) &&
    recovered.status === 401 &&
    csrf.status === 403 &&
    blockedPath.status === 404 &&
    traversal.status === 404 &&
    machineResponse.status === 401 &&
    !machineCookieForwarded &&
    upstreamDeadline.status === 504 &&
    sseSurvivedDeadline
      ? "passed"
      : "failed";
  fs.writeFileSync(
    path.join(root, "evaluation/results/independent-review-bff-patch.json"),
    JSON.stringify(result, null, 2),
  );
  console.log(JSON.stringify(result));
  clearTimeout(harnessTimer);
  process.exitCode = result.status === "passed" ? 0 : 1;
})();

// Bound the harness itself if a future regression leaves test streams unresolved.
const harnessTimer = setTimeout(() => {
  console.error("Probe exceeded five seconds");
  process.exit(1);
}, 5000);
