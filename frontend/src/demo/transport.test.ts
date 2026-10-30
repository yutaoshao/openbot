import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, wsBaseUrl } from "../lib/api";
import { resetDemoBackend } from "./backend";

beforeEach(() => {
  resetDemoBackend();
  window.history.replaceState(null, "", "/desktop-demo");
});
afterEach(() => {
  window.history.replaceState(null, "", "/");
  vi.unstubAllGlobals();
});

describe("Demo transport boundary", () => {
  it("keeps encoded preview paths on synthetic data before route effects run", async () => {
    const fetchMock = vi.fn(() => { throw new Error("Real network forbidden"); });
    vi.stubGlobal("fetch", fetchMock);
    for (const path of ["/%64esktop-demo/manage/settings", "/desktop-demo%2Fmanage/settings"]) {
      window.history.replaceState(null, "", path);
      expect(await api.get("/api/conversations")).toHaveLength(3);
      expect(() => wsBaseUrl()).toThrow("does not open real WebSocket");
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("uses local fixtures for known requests and never falls through for unknown ones", async () => {
    const fetchMock = vi.fn(() => { throw new Error("Real network forbidden"); });
    vi.stubGlobal("fetch", fetchMock);
    expect(await api.get("/api/conversations")).toHaveLength(3);
    await expect(api.get("/api/not-in-demo")).rejects.toThrow("Demo 未实现");
    await expect(api.get("https://example.com/api/settings")).rejects.toThrow();
    window.history.replaceState(null, "", "/desktop-demo/manage/settings");
    expect(await api.get("/api/settings")).toHaveProperty("model");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("blocks the real WebSocket URL before any connection can be opened", () => {
    const socket = vi.fn(() => { throw new Error("Real socket forbidden"); });
    vi.stubGlobal("WebSocket", socket);
    expect(() => wsBaseUrl()).toThrow("does not open real WebSocket");
    expect(socket).not.toHaveBeenCalled();
  });

  it("keeps ordinary Web requests and socket addressing working outside the Demo prefix", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ source: "web" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    window.history.replaceState(null, "", "/desktop-demo-other");
    expect(await api.get("/api/settings")).toEqual({ source: "web" });
    expect(fetchMock).toHaveBeenCalledWith("/api/settings", expect.any(Object));
    expect(wsBaseUrl()).toBe(`ws://${window.location.host}`);
  });
});
