import { NextRequest } from "next/server";
import { isIP } from "node:net";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
let bodyRequests = 0;

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  if (
    path.some(
      (segment) =>
        segment === "." || segment === ".." || /[\\/\u0000]/.test(segment),
    )
  )
    return new Response("Not found", { status: 404 });
  if (path[0] !== "v1" && path.join("/") !== "health/ready")
    return new Response("Not found", { status: 404 });
  const mutation = !["GET", "HEAD"].includes(request.method);
  const expectedOrigin = process.env.APP_ORIGIN || "http://localhost:3000";
  const machine = request.headers
    .get("authorization")
    ?.startsWith("Bearer qk_");
  if (
    mutation &&
    !machine &&
    request.headers.get("origin") !== expectedOrigin
  ) {
    return Response.json(
      { detail: "Cross-origin request rejected" },
      { status: 403 },
    );
  }
  const headers = new Headers();
  for (const key of [
    "content-type",
    "cookie",
    "authorization",
    "idempotency-key",
    "last-event-id",
    "origin",
  ]) {
    if (machine && key === "cookie") continue;
    const value = request.headers.get(key);
    if (value) headers.set(key, value);
  }
  const api = process.env.API_URL || "http://api:8000";
  const clientIP = request.headers.get("x-quarry-client-ip") || "";
  if (isIP(clientIP) && process.env.PROXY_SECRET) {
    headers.set("x-quarry-client-ip", clientIP);
    headers.set("x-quarry-proxy-secret", process.env.PROXY_SECRET);
  }
  const target = new URL("/" + path.map(encodeURIComponent).join("/"), api);
  target.search = request.nextUrl.search;
  if (mutation && bodyRequests >= 8)
    return Response.json(
      { detail: "Request capacity is busy; retry shortly" },
      { status: 503, headers: { "Retry-After": "1" } },
    );
  if (mutation) bodyRequests++;
  let bodyTimedOut = false;
  let upstreamTimedOut = false;
  let bodyTimer: ReturnType<typeof setTimeout> | undefined;
  let upstreamTimer: ReturnType<typeof setTimeout> | undefined;
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  const controller = new AbortController();
  const signal = AbortSignal.any([request.signal, controller.signal]);
  const cancelBody = () => {
    controller.abort();
    if (reader) void reader.cancel().catch(() => {});
  };
  request.signal.addEventListener("abort", cancelBody, { once: true });
  try {
    let body: ArrayBuffer | undefined;
    if (mutation && request.body) {
      reader = request.body.getReader();
      bodyTimer = setTimeout(() => {
        bodyTimedOut = true;
        cancelBody();
      }, 15_000);
      if (signal.aborted) cancelBody();
      const chunks: Uint8Array[] = [];
      let size = 0;
      while (true) {
        const { done, value } = await reader.read();
        if (signal.aborted) throw new Error("Body interrupted");
        if (done) break;
        size += value.byteLength;
        if (size > 10 * 1024 * 1024 + 64000) {
          void reader.cancel().catch(() => {});
          return Response.json(
            { detail: "Upload exceeds 10 MiB" },
            { status: 413 },
          );
        }
        chunks.push(value);
      }
      clearTimeout(bodyTimer);
      bodyTimer = undefined;
      body = new ArrayBuffer(size);
      const buffer = new Uint8Array(body);
      let offset = 0;
      for (const chunk of chunks) {
        buffer.set(chunk, offset);
        offset += chunk.byteLength;
      }
    }
    upstreamTimer = setTimeout(() => {
      upstreamTimedOut = true;
      controller.abort();
    }, 30_000);
    const response = await fetch(target, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      redirect: "manual",
      signal,
    });
    clearTimeout(upstreamTimer);
    upstreamTimer = undefined;
    const outgoing = new Headers();
    for (const key of [
      "content-type",
      "content-disposition",
      "cache-control",
      "x-request-id",
      "retry-after",
    ]) {
      const value = response.headers.get(key);
      if (value) outgoing.set(key, value);
    }
    for (const cookie of response.headers.getSetCookie())
      outgoing.append("set-cookie", cookie);
    outgoing.set("x-accel-buffering", "no");
    return new Response(response.body, {
      status: response.status,
      headers: outgoing,
    });
  } catch {
    if (bodyTimedOut)
      return Response.json(
        { detail: "Request body deadline exceeded" },
        { status: 408 },
      );
    if (upstreamTimedOut)
      return Response.json(
        { detail: "Research service response deadline exceeded" },
        { status: 504 },
      );
    return Response.json(
      {
        detail:
          "Research service is unavailable. Your stored work is safe; retry shortly.",
      },
      { status: 503 },
    );
  } finally {
    clearTimeout(bodyTimer);
    clearTimeout(upstreamTimer);
    request.signal.removeEventListener("abort", cancelBody);
    if (reader) reader.releaseLock();
    if (mutation) bodyRequests--;
  }
}
export const GET = proxy;
export const POST = proxy;
export const DELETE = proxy;
export const PATCH = proxy;
