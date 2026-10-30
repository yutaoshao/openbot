import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let location: URL;
let replaceState: ReturnType<typeof vi.fn>;
beforeEach(() => {
  vi.resetModules();
  location = new URL("http://127.0.0.1:49152/#openbot-desktop-token=secret-fragment");
  replaceState = vi.fn((_state, _unused, path: string) => { location.href = new URL(path, location).href; });
  vi.stubGlobal("window", { location, history: { replaceState } });
});
afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

describe("desktop browser session exchange", () => {
  it("removes the fragment and exchanges it exactly once for concurrent callers", async () => {
    const fetch = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetch);
    const { ensureBrowserSession } = await import("./browser-session");
    await Promise.all([ensureBrowserSession(), ensureBrowserSession(), ensureBrowserSession()]);
    expect(location.hash).toBe("");
    expect(fetch).toHaveBeenCalledOnce();
    expect(fetch).toHaveBeenCalledWith("http://127.0.0.1:49152/api/desktop/browser-session", expect.objectContaining({
      method: "POST", credentials: "omit", headers: { Authorization: "Bearer secret-fragment", "Content-Type": "application/json" },
    }));
  });

  it("never exchanges a credential on a non-loopback page", async () => {
    location.href = "https://example.com/#openbot-desktop-token=secret-fragment";
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    const { ensureBrowserSession } = await import("./browser-session");
    await expect(ensureBrowserSession()).rejects.toThrow("browserSessionError");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("keeps failures closed instead of trying anonymous requests", async () => {
    const fetch = vi.fn(async () => new Response(null, { status: 401 }));
    vi.stubGlobal("fetch", fetch);
    const { ensureBrowserSession, browserSessionError } = await import("./browser-session");
    await expect(ensureBrowserSession()).rejects.toThrow();
    await expect(ensureBrowserSession()).rejects.toThrow();
    expect(fetch).toHaveBeenCalledOnce();
    expect(browserSessionError()).toBe("desktopLive.browserSessionError");
  });

  it("sends the verified bearer only through same-origin API headers and WS protocols", async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({ ok: true })));
    vi.stubGlobal("fetch", fetch);
    const { ensureBrowserSession } = await import("./browser-session");
    const { api, wsProtocols } = await import("../lib/api");
    await ensureBrowserSession();
    expect(await api.get("/api/settings")).toEqual({ ok: true });
    expect(wsProtocols()).toEqual(["openbot.auth.secret-fragment"]);
    const calls = fetch.mock.calls as unknown as Array<[string, RequestInit]>;
    expect(calls[1][0]).toBe("/api/settings");
    expect(new Headers(calls[1][1].headers).get("Authorization")).toBe("Bearer secret-fragment");
    expect(calls[1][1].credentials).toBe("omit");
    await expect(api.get("http://127.0.0.1:8001/api/settings")).rejects.toThrow("invalidRequest");
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("marks a credential lost on refresh using the desktop service's 401 marker", async () => {
    location.hash = "";
    const fetch = vi.fn(async () => new Response(JSON.stringify({ detail: "Authentication required" }), {
      status: 401, headers: { "X-OpenBot-Desktop": "1" },
    }));
    vi.stubGlobal("fetch", fetch);
    const { api } = await import("../lib/api");
    const { browserSessionError } = await import("./browser-session");
    await expect(api.get("/api/settings")).rejects.toThrow();
    expect(browserSessionError()).toBe("desktopLive.browserSessionError");
    await expect(api.get("/api/settings")).rejects.toThrow("browserSessionError");
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("leaves source Web deployments untouched and rejects an expired desktop session", async () => {
    location.hash = "";
    const fetch = vi.fn(async () => new Response(null, { status: 204 })); vi.stubGlobal("fetch", fetch);
    const { ensureBrowserSession, expireBrowserSession } = await import("./browser-session");
    await ensureBrowserSession(); expect(fetch).not.toHaveBeenCalled();
    location.hash = "#openbot-desktop-token=secret-fragment";
    await ensureBrowserSession(); expireBrowserSession();
    await expect(ensureBrowserSession()).rejects.toThrow("browserSessionError");
    expect(fetch).toHaveBeenCalledOnce();
  });
});
