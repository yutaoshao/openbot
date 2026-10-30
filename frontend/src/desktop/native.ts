export type DesktopConnection = {
  status: "starting" | "ready" | "failed";
  baseUrl?: string;
  token?: string;
  instanceId?: string;
  error?: string;
};

type NativeBridge = { invoke: <T>(command: string, args?: Record<string, unknown>) => Promise<T> };
declare global { interface Window { __TAURI_INTERNALS__?: NativeBridge } }

export async function desktopInvoke<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  if (!window.__TAURI_INTERNALS__) throw new Error("desktopLive.nativeRequired");
  try {
    return await window.__TAURI_INTERNALS__.invoke<T>(command, args);
  } catch (error) {
    throw error instanceof Error ? error : new Error(typeof error === "string" ? error : "desktopLive.requestFailed");
  }
}

/** Only a validated native connection may choose the live service address. */
export async function readDesktopConnection(): Promise<DesktopConnection> {
  const value = await desktopInvoke<DesktopConnection>("desktop_connection");
  if (!["starting", "ready", "failed"].includes(value.status)) throw new Error("desktopLive.invalidConnection");
  if (value.status !== "ready") return value;
  const url = new URL(value.baseUrl ?? "");
  if (url.protocol !== "http:" || url.hostname !== "127.0.0.1" || !url.port
    || url.username || url.password || url.pathname !== "/" || url.search || url.hash || !value.token || !value.instanceId) {
    throw new Error("desktopLive.invalidConnection");
  }
  return { ...value, baseUrl: url.origin };
}

export async function readyDesktopConnection(): Promise<Required<Pick<DesktopConnection, "baseUrl" | "token">>> {
  const connection = await readDesktopConnection();
  if (connection.status !== "ready" || !connection.baseUrl || !connection.token) {
    throw new Error(connection.error || "desktopLive.serviceUnavailable");
  }
  return { baseUrl: connection.baseUrl, token: connection.token };
}
