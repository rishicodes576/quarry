import type { components } from "./api.generated";
export type User = components["schemas"]["UserOut"];
export type Document = components["schemas"]["DocumentOut"];
export type Run = components["schemas"]["RunOut"];
export type Evidence = components["schemas"]["EvidenceOut"];
export type Conversation = components["schemas"]["ConversationOut"];
export type RunEvent = components["schemas"]["EventOut"];

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData))
    headers.set("content-type", "application/json");
  const response = await fetch("/api/v1" + path, {
    ...options,
    headers,
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!response.ok) {
    let message = "Request failed";
    try {
      const value = await response.json();
      message =
        typeof value.detail === "string"
          ? value.detail
          : "Check the submitted fields and try again";
    } catch {
      message = `Service returned HTTP ${response.status}`;
    }
    throw new ApiError(message, response.status);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
