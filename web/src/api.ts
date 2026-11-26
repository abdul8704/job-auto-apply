// Thin typed client for the FastAPI backend. The token lives in localStorage (single-user tool).

export const API_BASE: string = import.meta.env.VITE_API_URL ?? "/api";
const TOKEN_KEY = "jaa_token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: stay logged in for this tab only */
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function detail(body: unknown): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((e) => e?.msg ?? JSON.stringify(e)).join("; ");
  }
  return "Request failed";
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData) && !(init.body instanceof URLSearchParams)) {
    headers.set("Content-Type", "application/json");
  }
  const resp = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (resp.status === 401 && token) setToken(null);
  if (!resp.ok) {
    let body: unknown = null;
    try {
      body = await resp.json();
    } catch {
      /* not json */
    }
    throw new ApiError(resp.status, detail(body));
  }
  if (resp.status === 204) return undefined as T;
  const type = resp.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? resp.json() : resp.blob()) as Promise<T>;
}

export const get = <T>(path: string) => request<T>(path);
export const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
export const put = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PUT", body: JSON.stringify(body) });
export const patch = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
export const del = (path: string) => request<void>(path, { method: "DELETE" });

export async function login(email: string, password: string): Promise<void> {
  const form = new URLSearchParams({ username: email, password });
  const out = await request<{ access_token: string }>("/auth/login", { method: "POST", body: form });
  setToken(out.access_token);
}

/** Open an authenticated PDF in a new tab. */
export async function openPdf(path: string): Promise<void> {
  const blob = await request<Blob>(path);
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank", "noopener");
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/** Poll a GET endpoint until `done(value)` is true (background jobs). */
export async function poll<T>(path: string, done: (v: T) => boolean, everyMs = 1500, maxTries = 120): Promise<T> {
  for (let i = 0; ; i++) {
    const v = await get<T>(path);
    if (done(v) || i >= maxTries) return v;
    await new Promise((r) => setTimeout(r, everyMs));
  }
}
