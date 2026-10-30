import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LanguageProvider } from "../i18n";
import { demoRequest, resetDemoBackend } from "./backend";
import { useDemoChat } from "./use-demo-chat";

function wrapper({ children }: { children: ReactNode }): JSX.Element {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })}>
    <LanguageProvider>{children}</LanguageProvider>
  </QueryClientProvider>;
}

beforeEach(() => {
  resetDemoBackend();
  window.history.replaceState(null, "", "/desktop-demo");
  localStorage.setItem("openbot_language", "en-US");
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("Real network forbidden"); }));
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  localStorage.clear();
  window.history.replaceState(null, "", "/");
});

describe("Demo turn lifecycle", () => {
  it("recovers when the current conversation is deleted during a generation", async () => {
    const { result } = renderHook(() => useDemoChat(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => { result.current.chooseScenario("long"); });
    let first: Promise<void>;
    act(() => { first = result.current.submit("Synthetic work"); });
    expect(result.current.busy).toBe(true);
    await demoRequest("/api/conversations/demo-weekly", { method: "DELETE" });
    await act(async () => { result.current.stop(); await first!; });
    expect(result.current.busy).toBe(false);
    expect(result.current.failure).toBeTruthy();
    const after = await demoRequest<unknown[]>("/api/conversations");
    expect(after).toHaveLength(2);

    act(() => { result.current.selectConversation(null); });
    let second: Promise<void>;
    act(() => { second = result.current.submit("A fresh synthetic request"); });
    expect(result.current.busy).toBe(true);
    await act(async () => { result.current.stop(); await second!; });
    expect(result.current.busy).toBe(false);
    const rows = await demoRequest<Array<{ id: string }>>("/api/conversations");
    expect(rows).toHaveLength(3);
    const created = rows.find((row) => !["demo-design", "demo-notes"].includes(row.id));
    const detail = await demoRequest<{ messages: unknown[] }>(`/api/conversations/${created?.id}`);
    expect(detail.messages).toHaveLength(2);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("cancels pending simulation work on unmount without writing a partial turn", async () => {
    const { result, unmount } = renderHook(() => useDemoChat(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    vi.useFakeTimers();
    let pending: Promise<void>;
    act(() => { pending = result.current.submit("Unmounted request"); });
    unmount();
    await act(async () => { await pending!; });
    await vi.advanceTimersByTimeAsync(0);
    expect(vi.getTimerCount()).toBe(0);
    const detail = await demoRequest<{ messages: unknown[] }>("/api/conversations/demo-weekly");
    expect(detail.messages).toHaveLength(2);
    expect(fetch).not.toHaveBeenCalled();
  });
});
