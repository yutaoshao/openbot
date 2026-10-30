import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LanguageProvider } from "../i18n";
import { api } from "../lib/api";
import { useDesktopChat } from "./use-desktop-chat";
import type { ChatRun } from "./types";

vi.mock("../lib/api", () => ({ api: { get: vi.fn(), post: vi.fn() } }));
let remote: ChatRun;
let historyMessages = [{ id: "old-user", role: "user", content: "Earlier" }, { id: "old-assistant", role: "assistant", content: "Earlier reply" }];
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}><LanguageProvider>{children}</LanguageProvider></QueryClientProvider>;
  return { client, wrapper };
}
beforeEach(() => {
  localStorage.setItem("openbot_language", "en-US");
  localStorage.setItem("openbot_desktop_selection_v1", "chat-a");
  remote = { run_id: "run-a", request_id: "request-a", conversation_id: "chat-a", status: "running", text: "Partial", tool_events: [] };
  historyMessages = [{ id: "old-user", role: "user", content: "Earlier" }, { id: "old-assistant", role: "assistant", content: "Earlier reply" }];
  vi.mocked(api.get).mockImplementation(async (url) => {
    if (url.startsWith("/api/conversations/")) return { conversation: { id: "chat-a", title: null, message_count: historyMessages.length }, messages: [...historyMessages, { id: "tool-1", role: "tool", content: "not a chat bubble" }] };
    if (url === "/api/chat/runs/run-a") return { ...remote };
    return [];
  });
  vi.mocked(api.post).mockImplementation(async (url) => {
    if (url.endsWith("/stop")) { remote = { ...remote, status: "stopping" }; return remote; }
    return { ...remote };
  });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); localStorage.clear(); sessionStorage.clear(); });

describe("live desktop run lifecycle", () => {
  it("loads all 450 historical messages in order without overlapping the final earlier page", async () => {
    const rows = Array.from({ length: 450 }, (_, index) => ({
      id: `message-${index}`, role: index % 2 ? "assistant" : "user", content: String(index),
    }));
    vi.mocked(api.get).mockImplementation(async (path) => {
      if (!path.startsWith("/api/conversations/")) return [];
      const url = new URL(path, "http://test.invalid");
      const offset = Number(url.searchParams.get("offset"));
      const limit = Number(url.searchParams.get("limit"));
      return { conversation: { id: "chat-a", title: null, message_count: rows.length }, messages: rows.slice(offset, offset + limit) };
    });
    const { result } = renderHook(() => useDesktopChat("instance-a"), { wrapper: setup().wrapper });
    await waitFor(() => expect(result.current.messages).toHaveLength(200));
    expect(result.current.messages[0].id).toBe("message-250");
    await act(async () => { await result.current.loadEarlier?.(); });
    await waitFor(() => expect(result.current.messages).toHaveLength(400));
    expect(result.current.messages[0].id).toBe("message-50");
    await act(async () => { await result.current.loadEarlier?.(); });
    await waitFor(() => expect(result.current.messages).toHaveLength(450));
    const ids = result.current.messages.map((message) => message.id);
    expect(ids).toEqual(rows.map((message) => message.id));
    expect(new Set(ids).size).toBe(450);
    expect(result.current.hasEarlier).toBe(false);
    expect(api.get).toHaveBeenCalledWith("/api/conversations/chat-a?limit=50&offset=0");
  });

  it("waits for the backend terminal state after stop, then reloads persistent history", async () => {
    const { client, wrapper } = setup();
    const { result } = renderHook(() => useDesktopChat("instance-a"), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.messages).toHaveLength(2);
    await act(async () => { await result.current.submit("New request"); });
    expect(api.post).toHaveBeenCalledWith("/api/chat/runs", expect.objectContaining({ message: "New request", conversation_id: "chat-a", request_id: expect.any(String) }));
    expect(result.current.busy).toBe(true);
    act(() => result.current.stop());
    await waitFor(() => expect(result.current.phase).toBe("stopping"));
    expect(result.current.stopped).toBe(false);
    expect(result.current.busy).toBe(true);
    historyMessages.push({ id: "partial-reply", role: "assistant", content: "Partial" });
    remote = { ...remote, status: "cancelled" };
    await act(async () => { await client.invalidateQueries({ queryKey: ["desktop-run", "run-a"] }); });
    await waitFor(() => expect(result.current.busy).toBe(false));
    expect(result.current.stopped).toBe(true);
    expect(result.current.messages.some((message) => message.id === "partial-reply")).toBe(true);
  });

  it("does not cancel on unmount or automatically replay a submitted request", async () => {
    const { wrapper } = setup();
    const first = renderHook(() => useDesktopChat("instance-a"), { wrapper });
    await waitFor(() => expect(first.result.current.loading).toBe(false));
    await act(async () => { await first.result.current.submit("One request"); });
    first.unmount();
    expect(api.post).toHaveBeenCalledOnce();
    vi.mocked(api.get).mockImplementation(async (url) => url.includes("?conversation_id=") ? [remote]
      : url.startsWith("/api/conversations/") ? { conversation: { id: "chat-a", title: null, message_count: 0 }, messages: [] } : remote);
    const next = renderHook(() => useDesktopChat("instance-a"), { wrapper: setup().wrapper });
    await waitFor(() => expect(next.result.current.busy).toBe(true));
    expect(api.post).toHaveBeenCalledOnce();
  });

  it("retains a stop requested before the submission response arrives", async () => {
    let acknowledge!: (run: ChatRun) => void;
    vi.mocked(api.post).mockImplementation(async (url) => url.endsWith("/stop")
      ? { ...remote, status: "stopping" } : await new Promise<ChatRun>((resolve) => { acknowledge = resolve; }));
    const { result } = renderHook(() => useDesktopChat("instance-a"), { wrapper: setup().wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    let submitted!: Promise<void>;
    act(() => { submitted = result.current.submit("Stop before acknowledgment") as Promise<void>; });
    act(() => result.current.stop());
    expect(api.post).toHaveBeenCalledOnce();
    expect(api.get).not.toHaveBeenCalledWith("/api/chat/runs/null");
    await act(async () => { acknowledge(remote); await submitted; });
    expect(api.post).toHaveBeenCalledTimes(2);
    expect(api.post).toHaveBeenLastCalledWith("/api/chat/runs/run-a/stop", {});
    expect(result.current.busy).toBe(true);
    expect(result.current.stopped).toBe(false);
  });

  it("preserves confirmed cancellation when a queued new conversation has no history row", async () => {
    localStorage.removeItem("openbot_desktop_selection_v1");
    remote = { ...remote, conversation_id: "queued-new", status: "queued", text: "" };
    vi.mocked(api.get).mockImplementation(async (url) => {
      if (url.startsWith("/api/conversations/queued-new")) throw new Error("404: Conversation not found");
      if (url === "/api/chat/runs/run-a") return remote;
      if (url.includes("?conversation_id=queued-new")) return [remote];
      return [];
    });
    vi.mocked(api.post).mockImplementation(async (url) => {
      if (url.endsWith("/stop")) remote = { ...remote, status: "cancelled" };
      return remote;
    });
    const { result } = renderHook(() => useDesktopChat("instance-a"), { wrapper: setup().wrapper });
    await act(async () => { await result.current.submit("Cancel before starting"); });
    expect(result.current.phase).toBe("queued");
    act(() => result.current.stop());
    await waitFor(() => expect(result.current.busy).toBe(false));
    await waitFor(() => expect(result.current.selectedId).toBeNull());
    expect(result.current.stopped).toBe(true);
    expect(result.current.failure).toBeNull();
    expect(result.current.messages).toEqual([]);
  });

  it("recovers an ambiguous submission by request ID using GET only", async () => {
    vi.mocked(api.post).mockRejectedValueOnce(new TypeError("Response lost"));
    const { result } = renderHook(() => useDesktopChat("instance-a"), { wrapper: setup().wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => { await result.current.submit("Do not replay"); });
    expect(result.current.busy).toBe(true);
    const stored = JSON.parse(sessionStorage.getItem("openbot_desktop_unconfirmed_v1")!);
    expect(stored).toEqual({ request_id: expect.any(String), instance_id: "instance-a" });
    remote = { ...remote, request_id: stored.request_id };
    vi.mocked(api.get).mockImplementation(async (url) => url.includes("?request_id=") ? [remote]
      : url.startsWith("/api/conversations/") ? { conversation: { id: "chat-a", title: null, message_count: 0 }, messages: [] } : remote);
    await act(async () => { await result.current.recover?.(); });
    expect(result.current.output).toBe("Partial");
    expect(api.post).toHaveBeenCalledOnce();
    expect(sessionStorage.getItem("openbot_desktop_unconfirmed_v1")).toBeNull();
  });

  it("drops an old instance's unconfirmed request without sending it again", async () => {
    sessionStorage.setItem("openbot_desktop_unconfirmed_v1", JSON.stringify({ request_id: "old", instance_id: "old-instance" }));
    const { result } = renderHook(() => useDesktopChat("new-instance"), { wrapper: setup().wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.busy).toBe(false);
    expect(result.current.failure).toContain("restarted");
    expect(api.post).not.toHaveBeenCalled();
  });

  it.each(["not_accepted", "expired"] as const)("unlocks an unresolved request only after withdrawal confirms %s", async (status) => {
    vi.mocked(api.post).mockRejectedValueOnce(new TypeError("Response lost"));
    const { result } = renderHook(() => useDesktopChat("instance-a"), { wrapper: setup().wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => { await result.current.submit("Unknown request"); });
    const unknown = JSON.parse(sessionStorage.getItem("openbot_desktop_unconfirmed_v1")!);
    await act(async () => { await result.current.recover?.(); await result.current.recover?.(); });
    expect(result.current.busy).toBe(true);
    expect(api.post).toHaveBeenCalledOnce();
    vi.mocked(api.post).mockResolvedValueOnce({ request_id: unknown.request_id, status });
    await act(async () => { await result.current.withdraw?.(); });
    expect(api.post).toHaveBeenLastCalledWith(`/api/chat/requests/${unknown.request_id}/stop`, {});
    expect(result.current.busy).toBe(false);
    expect(sessionStorage.getItem("openbot_desktop_unconfirmed_v1")).toBeNull();
    act(() => result.current.selectConversation(null));
    await act(async () => { await result.current.submit("New intentional request"); });
    expect(api.post).toHaveBeenLastCalledWith("/api/chat/runs", expect.objectContaining({
      message: "New intentional request", request_id: expect.not.stringMatching(unknown.request_id),
    }));
    const lastBody = vi.mocked(api.post).mock.calls[2][1] as Record<string, unknown>;
    expect(lastBody).not.toHaveProperty("conversation_id");
  });

  it("keeps a restored unknown request busy until withdrawal is confirmed or the accepted run stops", async () => {
    sessionStorage.setItem("openbot_desktop_unconfirmed_v1", JSON.stringify({ request_id: "request-a", instance_id: "instance-a" }));
    const { client, wrapper } = setup();
    const { result } = renderHook(() => useDesktopChat("instance-a"), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.failure).toContain("status is unknown");
    vi.mocked(api.post).mockRejectedValueOnce(new TypeError("Withdrawal response lost"));
    await act(async () => { await result.current.withdraw?.(); });
    expect(result.current.busy).toBe(true);
    expect(sessionStorage.getItem("openbot_desktop_unconfirmed_v1")).not.toBeNull();
    remote = { ...remote, status: "stopping" };
    vi.mocked(api.post).mockResolvedValueOnce(remote);
    await act(async () => { await result.current.withdraw?.(); });
    expect(result.current.phase).toBe("stopping");
    expect(result.current.busy).toBe(true);
    expect(result.current.stopped).toBe(false);
    remote = { ...remote, status: "cancelled" };
    await act(async () => { await client.invalidateQueries({ queryKey: ["desktop-run", "run-a"] }); });
    await waitFor(() => expect(result.current.busy).toBe(false));
    expect(result.current.stopped).toBe(true);
    expect(api.post).not.toHaveBeenCalledWith("/api/chat/runs", expect.anything());
  });
});
