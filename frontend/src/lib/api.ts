import { isDesktopDemoPath } from "../demo/location";
import { isDesktopPath } from "../desktop/location";
import { readyDesktopConnection } from "../desktop/native";
import { browserSessionBearer, ensureBrowserSession, expireBrowserSession } from "../desktop/browser-session";

export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  if (isDesktopDemoPath(window.location.pathname)) {
    const { demoRequest } = await import("../demo/backend");
    return demoRequest<T>(url, init);
  }

  const desktop = isDesktopPath(window.location.pathname);
  const headers = new Headers(init?.headers);
  headers.set("Content-Type", "application/json");
  let endpoint = url;
  let browserBearer: string | undefined;
  if (desktop) {
    if (!url.startsWith("/api/") || url.startsWith("//")) throw new Error("desktopLive.invalidRequest");
    const connection = await readyDesktopConnection();
    endpoint = `${connection.baseUrl}${url}`;
    headers.set("Authorization", `Bearer ${connection.token}`);
  } else {
    await ensureBrowserSession();
    browserBearer = browserSessionBearer();
    if (browserBearer) {
      if (!url.startsWith("/api/") || url.startsWith("//")) throw new Error("desktopLive.invalidRequest");
      headers.set("Authorization", `Bearer ${browserBearer}`);
    }
  }
  const response = await fetch(endpoint, {
    ...init,
    headers,
    ...(desktop || browserBearer ? { credentials: "omit", signal: init?.signal ?? AbortSignal.timeout(30_000) } : {}),
  });

  if (!response.ok) {
    if (!desktop && response.status === 401) expireBrowserSession(response.headers.get("X-OpenBot-Desktop") === "1");
    const body = await response.text();
    if (desktop) {
      let detail = "desktopLive.requestFailed";
      try {
        const parsed = JSON.parse(body) as { detail?: unknown };
        if (typeof parsed.detail === "string") detail = parsed.detail;
      } catch { /* Do not display raw pages or validation inputs containing credentials. */ }
      throw new Error(`${response.status}: ${detail}`);
    }
    throw new Error(`${response.status} ${response.statusText}: ${body}`);
  }

  return (await response.json()) as T;
}

export const api = {
  get: <T>(url: string) => request<T>(url),
  post: <T>(url: string, body: JsonValue) =>
    request<T>(url, { method: "POST", body: JSON.stringify(body) }),
  put: <T>(url: string, body: JsonValue) =>
    request<T>(url, { method: "PUT", body: JSON.stringify(body) }),
  del: <T>(url: string) => request<T>(url, { method: "DELETE" }),
};

export function wsBaseUrl(): string {
  if (isDesktopDemoPath(window.location.pathname)) {
    throw new Error("Desktop Demo does not open real WebSocket connections");
  }
  if (isDesktopPath(window.location.pathname)) {
    throw new Error("The desktop uses authenticated HTTP run snapshots, not WebSocket fallback");
  }
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${window.location.host}`;
}

export function wsProtocols(): string[] | undefined {
  if (isDesktopDemoPath(window.location.pathname) || isDesktopPath(window.location.pathname)) {
    throw new Error("Desktop screens do not open WebSocket connections");
  }
  const bearer = browserSessionBearer();
  return bearer ? [`openbot.auth.${bearer}`] : undefined;
}

/** Read a CSS custom property from :root (for Recharts which can't use var()). */
export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
