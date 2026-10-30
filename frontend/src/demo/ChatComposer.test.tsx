import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LanguageProvider } from "../i18n";
import { ChatComposer } from "../components/desktop/ChatComposer";
import type { DemoChat } from "./use-demo-chat";

function chatState(overrides: Partial<DemoChat> = {}): DemoChat {
  return {
    selectedId: null, scenario: "ready", phase: "idle", pendingInput: "", output: "",
    messages: [], title: "New chat", loading: false, error: false, stopped: false,
    busy: false, failure: null, selectConversation: vi.fn(), chooseScenario: vi.fn(),
    submit: vi.fn(async () => {}), stop: vi.fn(), reconnect: vi.fn(), ...overrides,
  };
}

beforeEach(() => localStorage.setItem("openbot_language", "en-US"));
afterEach(() => { cleanup(); localStorage.clear(); });

describe("Demo composer", () => {
  it("preserves IME composition and multiline Enter, then submits normal Enter", () => {
    const chat = chatState();
    render(<LanguageProvider><ChatComposer chat={chat} /></LanguageProvider>);
    const input = screen.getByRole("textbox", { name: "Message" });
    fireEvent.change(input, { target: { value: "整理中文笔记" } });
    fireEvent.compositionStart(input);
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.compositionEnd(input);
    fireEvent.keyDown(input, { key: "Enter", keyCode: 229 });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(chat.submit).not.toHaveBeenCalled();
    expect(input).toHaveValue("整理中文笔记");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(chat.submit).toHaveBeenCalledOnce();
    expect(chat.submit).toHaveBeenCalledWith("整理中文笔记");
    expect(input).toHaveValue("");
  });

  it("sends using the button and prevents blank or disconnected submissions", () => {
    const chat = chatState();
    const view = render(<LanguageProvider><ChatComposer chat={chat} /></LanguageProvider>);
    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(chat.submit).toHaveBeenCalledOnce();
    expect(chat.submit).toHaveBeenCalledWith("Draft");
    view.rerender(<LanguageProvider><ChatComposer chat={chatState({ scenario: "offline" })} /></LanguageProvider>);
    expect(screen.getByRole("textbox")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
  });

  it("keeps a queued draft while busy and routes the action to stop", () => {
    const chat = chatState({ busy: true, phase: "streaming" });
    render(<LanguageProvider><ChatComposer chat={chat} /></LanguageProvider>);
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "Next question" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(chat.submit).not.toHaveBeenCalled();
    expect(input).toHaveValue("Next question");
    fireEvent.click(screen.getByRole("button", { name: "Stop generating" }));
    expect(chat.stop).toHaveBeenCalledOnce();
  });
});
