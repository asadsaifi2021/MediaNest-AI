import { apiUrl, demoOnly } from "./config";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function request<T>(
  path: string,
  token?: string,
  options: RequestInit = {},
): Promise<T> {
  if (demoOnly)
    throw new Error("Server access is disabled in the public demo.");
  const controller = new AbortController();
  const cancel = () => controller.abort();
  if (options.signal?.aborted) controller.abort();
  options.signal?.addEventListener("abort", cancel, { once: true });
  const timeout = window.setTimeout(cancel, 15000);
  try {
    const headers = new Headers(options.headers);
    if (token) headers.set("Authorization", `Bearer ${token}`);
    if (options.body) headers.set("Content-Type", "application/json");
    const response = await fetch(`${apiUrl}${path}`, {
      ...options,
      headers,
      signal: controller.signal,
      cache: "no-store",
    });
    if (!response.ok) {
      const data = await response.json().catch(() => null);
      const detail =
        typeof data?.detail === "string"
          ? data.detail
          : "The request could not be completed.";
      throw new ApiError(
        response.status === 401
          ? "Your session is no longer valid. Please sign out and sign in again."
          : detail,
        response.status,
      );
    }
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (options.signal?.aborted) throw error;
    throw new Error(
      "Cannot reach the metadata server. Check the connection and try again.",
    );
  } finally {
    clearTimeout(timeout);
    options.signal?.removeEventListener("abort", cancel);
  }
}

export function parseEmbedding(text: string): number[] {
  const value: unknown = JSON.parse(text);
  if (
    !Array.isArray(value) ||
    value.length !== 512 ||
    !value.every((n) => typeof n === "number" && Number.isFinite(n))
  ) {
    throw new Error("Provide a JSON array of exactly 512 finite numbers.");
  }
  if (value.every((n) => n === 0))
    throw new Error("An all-zero vector cannot be used for face similarity.");
  return value;
}
