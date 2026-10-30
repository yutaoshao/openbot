import { useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatWorkspace } from "../components/desktop/ChatWorkspace";
import { DesktopSidebar } from "../components/desktop/DesktopSidebar";
import type { ChatViewModel } from "../components/desktop/chat-view";
import { LanguageProvider } from "../i18n";
import { api } from "../lib/api";
import { ConversationsPage } from "../pages/conversations";
import { useDesktopChat } from "./use-desktop-chat";

vi.mock("../lib/api", () => ({ api: { get: vi.fn(), post: vi.fn(), del: vi.fn() } }));
vi.mock("streamdown", () => ({ Streamdown: ({ children }: { children: string }) => <div>{children}</div> }));
const rows = Array.from({ length: 100 }, (_, index) => ({ id: index ? `chat-${index}` : "chat-a", title: `Chat ${index}`,
  summary: null, platform: "web", message_count: 2, updated_at: "2026-10-30T00:00:00Z" }));
const messages = [{ id: "u1", role: "user", content: "Saved question" }, { id: "a1", role: "assistant", content: "Saved reply" }];
const emptyChat: ChatViewModel = { selectedId: null, title: "New", scenario: "ready", phase: "idle", messages: [], pendingInput: "", output: "",
  busy: false, loading: false, error: false, stopped: false, failure: null, selectConversation: vi.fn(), submit: vi.fn(), stop: vi.fn() };
let deleted: boolean;

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const Wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>
    <LanguageProvider><BrowserRouter>{children}</BrowserRouter></LanguageProvider>
  </QueryClientProvider>;
  return { client, Wrapper };
}
function DesktopHarness(): JSX.Element {
  const chat = useDesktopChat("instance-a");
  const [management, setManagement] = useState(false);
  return <>
    <button onClick={() => setManagement(true)}>Open conversation management</button><button onClick={() => setManagement(false)}>Back to chat</button>
    <output data-testid="selection">{chat.selectedId ?? "new"}</output>
    <DesktopSidebar chat={chat} theme="light" toggleTheme={() => {}} basePath="/desktop" />
    {management ? <div data-testid="management-view"><ConversationsPage /></div> : <ChatWorkspace chat={chat} />}
  </>;
}
beforeEach(() => {
  deleted = false;
  localStorage.setItem("openbot_language", "en-US");
  localStorage.setItem("openbot_desktop_selection_v1", "chat-a");
  window.history.replaceState(null, "", "/desktop");
  vi.mocked(api.get).mockImplementation(async (path) => {
    if (path.startsWith("/api/conversations/")) {
      const id = path.split("/")[3].split("?")[0];
      if (deleted && id === "chat-a") throw new Error("404: Conversation not found");
      return { conversation: { id, title: id === "chat-a" ? "Chat 0" : "Older chat", message_count: messages.length }, messages };
    }
    if (path.startsWith("/api/conversations")) return (path.includes("limit=100") ? rows : rows.slice(0, 20)).filter((row) => !deleted || row.id !== "chat-a");
    if (path === "/api/chat/runs/new-run") return { run_id: "new-run", conversation_id: "new-chat", status: "running", text: "", tool_events: [] };
    return [];
  });
  vi.mocked(api.del).mockImplementation(async () => { deleted = true; return { status: "deleted", conversation_id: "chat-a" }; });
  vi.mocked(api.post).mockResolvedValue({ run_id: "new-run", conversation_id: "new-chat", status: "running", text: "", tool_events: [] });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); localStorage.clear(); sessionStorage.clear(); window.history.replaceState(null, "", "/"); });

describe("desktop conversation boundaries", () => {
  it("keeps the sidebar's 100 rows separate from the management page's 20 rows on refresh", async () => {
    const { client, Wrapper } = setup();
    render(<Wrapper><DesktopSidebar chat={emptyChat} theme="light" toggleTheme={() => {}} basePath="/desktop" /><ConversationsPage /></Wrapper>);
    await waitFor(() => {
      expect(client.getQueryData(["conversations", "desktop-sidebar", ""])).toHaveLength(100);
      expect(client.getQueryData(["conversations", ""])).toHaveLength(20);
    });
    await act(async () => { await client.invalidateQueries({ queryKey: ["conversations"] }); });
    expect(client.getQueryData(["conversations", "desktop-sidebar", ""])).toHaveLength(100);
    expect(client.getQueryData(["conversations", ""])).toHaveLength(20);
    expect(vi.mocked(api.get).mock.calls.filter(([path]) => path === "/api/conversations?limit=100")).toHaveLength(2);
    expect(vi.mocked(api.get).mock.calls.filter(([path]) => path === "/api/conversations")).toHaveLength(2);
  });

  it("clears a deleted idle conversation before returning to chat and never resubmits its old ID", async () => {
    const { Wrapper } = setup();
    render(<Wrapper><DesktopHarness /></Wrapper>);
    expect(await screen.findByText("Saved reply")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open conversation management" }));
    const management = screen.getByTestId("management-view");
    fireEvent.click(await within(management).findByRole("button", { name: /Chat 0/ }));
    fireEvent.click(await within(management).findByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.getByTestId("selection")).toHaveTextContent("new"));
    fireEvent.click(screen.getByRole("button", { name: "Back to chat" }));
    expect(screen.queryByText("Saved reply")).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), { target: { value: "A new request" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/chat/runs", expect.objectContaining({ message: "A new request" })));
    expect(vi.mocked(api.post).mock.calls[0][1]).not.toHaveProperty("conversation_id");
  });

  it("keeps a real older conversation even when it is absent from the sidebar's first 100", async () => {
    localStorage.setItem("openbot_desktop_selection_v1", "chat-999");
    const { Wrapper } = setup();
    render(<Wrapper><DesktopHarness /></Wrapper>);
    expect(await screen.findByText("Saved reply")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("selection")).toHaveTextContent("chat-999"));
    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), { target: { value: "Continue older conversation" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/chat/runs", expect.objectContaining({ conversation_id: "chat-999" })));
  });

  it("keeps the conversation selected and reports a rejected busy deletion", async () => {
    vi.mocked(api.del).mockRejectedValueOnce(new Error("409: Conversation is busy"));
    const { Wrapper } = setup();
    render(<Wrapper><DesktopHarness /></Wrapper>);
    await screen.findByText("Saved reply");
    fireEvent.click(screen.getByRole("button", { name: "Open conversation management" }));
    const management = screen.getByTestId("management-view");
    fireEvent.click(await within(management).findByRole("button", { name: /Chat 0/ }));
    fireEvent.click(await within(management).findByRole("button", { name: "Delete" }));
    expect(await within(management).findByRole("alert")).toHaveTextContent("Conversation is busy");
    expect(screen.getByTestId("selection")).toHaveTextContent("chat-a");
  });
});
