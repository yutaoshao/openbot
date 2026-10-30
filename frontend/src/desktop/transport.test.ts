import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, wsBaseUrl } from "../lib/api";
import { pagePath } from "../lib/page-path";
import { readDesktopConnection } from "./native";

const ready = { status: "ready", baseUrl: "http://127.0.0.1:49152", token: "ephemeral-secret", instanceId: "instance-a" };
const invoke = vi.fn();
beforeEach(() => {
  window.history.replaceState(null, "", "/desktop");
  Object.defineProperty(window, "__TAURI_INTERNALS__", { configurable: true, value: { invoke } });
  invoke.mockResolvedValue(ready);
});
afterEach(() => {
  window.history.replaceState(null, "", "/");
  delete window.__TAURI_INTERNALS__;
  vi.unstubAllGlobals(); vi.clearAllMocks();
});

describe("live desktop transport", () => {
  it("uses the validated native address and bearer without storing the token", async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({ ok: true })));
    vi.stubGlobal("fetch", fetch);
    await expect(api.get("/api/desktop/status")).resolves.toEqual({ ok: true });
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://127.0.0.1:49152/api/desktop/status");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer ephemeral-secret");
    expect(init.credentials).toBe("omit");
    expect(JSON.stringify(localStorage)).not.toContain(ready.token);
    expect(JSON.stringify(sessionStorage)).not.toContain(ready.token);
  });

  it.each([
    { ...ready, baseUrl: "http://192.168.1.5:8000" },
    { ...ready, baseUrl: "http://127.0.0.1:8000/other" },
    { ...ready, baseUrl: "http://user:pass@127.0.0.1:8000" },
    { ...ready, token: "" },
    { ...ready, instanceId: "" },
  ])("rejects an invalid native handshake without fetching", async (value) => {
    invoke.mockResolvedValue(value);
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    await expect(api.get("/api/desktop/status")).rejects.toThrow();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("does not fall back to a fixed port or replay a failed mutation", async () => {
    const fetch = vi.fn(async () => { throw new TypeError("Connection interrupted"); });
    vi.stubGlobal("fetch", fetch);
    await expect(api.post("/api/chat/runs", { message: "hello", request_id: "request-1" })).rejects.toThrow();
    expect(fetch).toHaveBeenCalledOnce();
    expect(wsBaseUrl).toThrow("authenticated HTTP");
    invoke.mockResolvedValue({ status: "starting" });
    await expect(api.get("/api/desktop/status")).rejects.toThrow("serviceUnavailable");
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("never authenticates an arbitrary absolute URL", async () => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    await expect(api.get("https://example.com/api/settings")).rejects.toThrow("invalidRequest");
    expect(invoke).not.toHaveBeenCalled(); expect(fetch).not.toHaveBeenCalled();
  });

  it("does not expose validation inputs, and keeps Demo and Web navigation separate", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: [{ input: "private-key" }] }), { status: 422 })));
    await expect(api.post("/api/desktop/setup", {})).rejects.not.toThrow("private-key");
    expect(pagePath("/settings")).toBe("/desktop/manage/settings");
    window.history.replaceState(null, "", "/%64esktop/manage/tools");
    expect(pagePath("/chat")).toBe("/desktop");
    window.history.replaceState(null, "", "/desktop-demo/manage/tools");
    expect(pagePath("/settings")).toBe("/desktop-demo/manage/settings");
    window.history.replaceState(null, "", "/settings");
    expect(pagePath("/chat")).toBe("/chat");
  });

  it("requires the native app instead of accepting browser-injected API addresses", async () => {
    delete window.__TAURI_INTERNALS__;
    await expect(readDesktopConnection()).rejects.toThrow("nativeRequired");
  });
});
