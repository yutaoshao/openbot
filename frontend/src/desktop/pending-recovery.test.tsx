import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LanguageProvider } from "../i18n";
import { api } from "../lib/api";
import { forgetPendingRequest, readPendingRequest, rememberPendingRequest } from "./pending-request";
import { useDesktopChat } from "./use-desktop-chat";
import type { ChatRun } from "./types";

vi.mock("../lib/api", () => ({ api: { get: vi.fn(), post: vi.fn() } }));
const pending = { request_id: "older-request", instance_id: "instance-a" };
const older: ChatRun = { run_id: "older-run", request_id: pending.request_id, conversation_id: "chat-a", status: "running", text: "Older partial", tool_events: [] };
let resolveLookup: (rows: ChatRun[]) => void;
let remote: ChatRun;
function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}><LanguageProvider>{children}</LanguageProvider></QueryClientProvider>;
}
beforeEach(() => {
  localStorage.setItem("openbot_language", "en-US");
  localStorage.setItem("openbot_desktop_selection_v1", "chat-a");
  rememberPendingRequest(pending);
  remote = older;
  vi.mocked(api.get).mockImplementation(async (url) => {
    if (url.includes("?request_id=")) return await new Promise<ChatRun[]>((resolve) => { resolveLookup = resolve; });
    if (url === "/api/chat/runs/older-run") return remote;
    if (url.startsWith("/api/conversations/")) return { conversation: { id: "chat-a", title: "Saved", message_count: 0 }, messages: [] };
    return [];
  });
  vi.mocked(api.post).mockRejectedValue(new TypeError("Response lost"));
});
afterEach(() => { cleanup(); localStorage.clear(); sessionStorage.clear(); vi.clearAllMocks(); });

describe("pending request ownership", () => {
  it("does not let an unmounted old instance's late recovery clear a new pending request", async () => {
    const previous = renderHook(() => useDesktopChat("instance-a"), { wrapper: wrapper() });
    await waitFor(() => expect(previous.result.current.loading).toBe(false));
    let recovery!: Promise<void>;
    act(() => { recovery = previous.result.current.recover!() as Promise<void>; });
    previous.unmount();
    const current = renderHook(() => useDesktopChat("instance-b"), { wrapper: wrapper() });
    await waitFor(() => expect(current.result.current.loading).toBe(false));
    await act(async () => { await current.result.current.submit("New pending request"); });
    const newer = readPendingRequest();
    expect(newer?.instance_id).toBe("instance-b");
    await act(async () => { resolveLookup([older]); await recovery; });
    expect(readPendingRequest()).toEqual(newer);
    expect(current.result.current.busy).toBe(true);
    expect(current.result.current.failure).toContain("status is unknown");
  });

  it("does not let a same-instance old recovery erase or accept a later request", async () => {
    const current = renderHook(() => useDesktopChat("instance-a"), { wrapper: wrapper() });
    await waitFor(() => expect(current.result.current.loading).toBe(false));
    let recovery!: Promise<void>;
    act(() => { recovery = current.result.current.recover!() as Promise<void>; });
    remote = { ...older, status: "cancelled" };
    vi.mocked(api.post).mockResolvedValueOnce(remote);
    await act(async () => { await current.result.current.withdraw?.(); });
    await waitFor(() => expect(current.result.current.busy).toBe(false));
    await act(async () => { await current.result.current.submit("A later pending request"); });
    const newer = readPendingRequest();
    expect(newer?.request_id).not.toBe(pending.request_id);
    await act(async () => { resolveLookup([older]); await recovery; });
    expect(readPendingRequest()).toEqual(newer);
    expect(current.result.current.output).toBe("");
    expect(current.result.current.failure).toContain("status is unknown");
    expect(current.result.current.busy).toBe(true);
  });

  it("only removes a stored record with matching request and instance IDs", () => {
    const later = { request_id: "later-request", instance_id: "instance-a" };
    rememberPendingRequest(later);
    forgetPendingRequest(pending);
    expect(readPendingRequest()).toEqual(later);
    forgetPendingRequest({ ...later, instance_id: "different-instance" });
    expect(readPendingRequest()).toEqual(later);
    forgetPendingRequest(later);
    expect(readPendingRequest()).toBeNull();
  });
});
