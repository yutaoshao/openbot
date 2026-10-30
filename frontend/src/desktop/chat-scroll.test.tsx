import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatWorkspace } from "../components/desktop/ChatWorkspace";
import type { ChatViewModel } from "../components/desktop/chat-view";
import { LanguageProvider } from "../i18n";

vi.mock("streamdown", () => ({ Streamdown: ({ children }: { children: string }) => <div>{children}</div> }));
function model(overrides: Partial<ChatViewModel> = {}): ChatViewModel {
  return { selectedId: "a", title: "Chat", scenario: "ready", phase: "streaming", messages: [{ id: "m2", role: "assistant", content: "Current" }],
    pendingInput: "", output: "Partial", busy: true, loading: false, error: false, stopped: false, failure: null,
    selectConversation: vi.fn(), submit: vi.fn(), stop: vi.fn(), ...overrides };
}
const view = (chat: ChatViewModel) => <LanguageProvider><ChatWorkspace chat={chat} /></LanguageProvider>;
beforeEach(() => localStorage.setItem("openbot_language", "en-US"));
afterEach(() => { cleanup(); localStorage.clear(); });

describe("shared desktop reading position", () => {
  it("keeps the reader's position when real output changes", () => {
    const initial = model();
    const result = render(view(initial));
    const node = result.container.querySelector<HTMLDivElement>(".demo-messages-scroll")!;
    Object.defineProperties(node, { scrollHeight: { configurable: true, value: 2000 }, clientHeight: { value: 400 } });
    node.scrollTop = 300;
    fireEvent.scroll(node);
    result.rerender(view({ ...initial, output: "A longer real model reply" }));
    expect(node.scrollTop).toBe(300);
    fireEvent.click(screen.getByRole("button", { name: "Jump to latest" }));
    expect(node.scrollTop).toBe(2000);
  });

  it("preserves the visible anchor when earlier history is prepended", () => {
    const initial = model({ busy: false, phase: "idle", hasEarlier: true, loadEarlier: vi.fn(async () => {}) });
    const result = render(view(initial));
    const node = result.container.querySelector<HTMLDivElement>(".demo-messages-scroll")!;
    Object.defineProperties(node, { scrollHeight: { configurable: true, value: 1000 }, clientHeight: { value: 400 } });
    node.scrollTop = 0;
    fireEvent.scroll(node);
    fireEvent.click(screen.getByRole("button", { name: "Load earlier messages" }));
    Object.defineProperty(node, "scrollHeight", { configurable: true, value: 1600 });
    result.rerender(view({ ...initial, messages: [{ id: "m1", role: "user", content: "Earlier" }, ...initial.messages] }));
    expect(node.scrollTop).toBe(600);
  });
});
