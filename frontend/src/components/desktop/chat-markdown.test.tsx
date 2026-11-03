import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatWorkspace } from "./ChatWorkspace";
import type { ChatViewModel } from "./chat-view";
import { LanguageProvider } from "../../i18n";
import { markdownReply } from "../../demo/markdown-fixture";

function model(streaming: boolean, content = markdownReply): ChatViewModel {
  return {
    selectedId: "demo-markdown", title: "Markdown", scenario: "ready", phase: streaming ? "streaming" : "idle",
    messages: streaming ? [] : [{ id: "reply", role: "assistant", content }],
    pendingInput: "", output: streaming ? content : "", busy: streaming,
    loading: false, error: false, stopped: false, failure: null,
    selectConversation: vi.fn(), submit: vi.fn(), stop: vi.fn(),
  };
}
const view = (chat: ChatViewModel) =>
  <LanguageProvider><ChatWorkspace chat={chat} /></LanguageProvider>;

beforeEach(() => {
  localStorage.setItem("openbot_language", "en-US");
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("Real network forbidden"); }));
  vi.stubGlobal("WebSocket", vi.fn(() => { throw new Error("Real socket forbidden"); }));
});
afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("Chinese Markdown in the shared desktop chat layout", () => {
  it.each([false, true])("renders emphasis, links and literal code (streaming=%s)", (streaming) => {
    const { container } = render(view(model(streaming)));
    const emphasis = [...container.querySelectorAll('[data-streamdown="strong"]')].map((node) => node.textContent);
    expect(emphasis).toContain("先选 KIPRUN RUN500 的“轻薄透气款跑步袜”，买两双试穿就够。");
    expect(emphasis).toContain("特别注意：RUN500 同时有薄款和厚款，不能只按数字选。");
    expect(emphasis).toContain("重要提示（Important Note）：");
    expect(container.querySelector("em")).toHaveTextContent("轻薄（非加厚）。");
    expect(container.querySelector("del")).toHaveTextContent("厚款（旧建议）。");
    expect(container.querySelector('[data-streamdown="strong"] [data-streamdown="link"]')).toHaveTextContent("款式说明");
    expect(screen.getByRole("button", { name: "https://example.com/product" })).toBeInTheDocument();
    expect(screen.getByText("**literal**")).toBeInTheDocument();
    expect(container.querySelector("pre")).toHaveTextContent("**代码里的星号保持原样。**");
    expect(screen.getAllByRole("table")).toHaveLength(2);
    expect(fetch).not.toHaveBeenCalled();
    expect(WebSocket).not.toHaveBeenCalled();
  });

  it("keeps external links behind confirmation", () => {
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    render(view(model(false, "[官方款式参考](https://example.com/run500)")));
    fireEvent.click(screen.getByRole("button", { name: "官方款式参考" }));
    expect(screen.getByText("https://example.com/run500")).toBeInTheDocument();
    expect(open).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByText("https://example.com/run500")).not.toBeInTheDocument();
    expect(open).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "官方款式参考" }));
    fireEvent.click(screen.getByRole("button", { name: "Open link" }));
    expect(open).toHaveBeenCalledOnce();
  });

  it("preserves sanitization of model HTML and unsafe link schemes", () => {
    const content = '**中文提示。**继续。\n\n[危险链接](javascript:alert(1))\n\n<script>alert(1)</script><img src="x" onerror="alert(1)">';
    const { container } = render(view(model(false, content)));
    expect(container.querySelector("script, [onerror], [onclick]")).toBeNull();
    expect(container.querySelector('[href^="javascript:"]')).toBeNull();
    expect(screen.queryByRole("button", { name: "危险链接" })).not.toBeInTheDocument();
  });

  it("shows the safety confirmation in the selected language", () => {
    localStorage.setItem("openbot_language", "zh-CN");
    render(view(model(false, "[参考链接](https://example.com)")));
    fireEvent.click(screen.getByRole("button", { name: "参考链接" }));
    expect(screen.getByText("打开外部链接？")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "复制链接" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "打开链接" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    expect(screen.queryByText("打开外部链接？")).not.toBeInTheDocument();
  });

  it("uses the same parser while streaming, after completion and after history reload", () => {
    const content = "**中文句子。**后面紧接正文。";
    const result = render(view(model(true, content.slice(0, 6))));
    result.rerender(view(model(true, content)));
    expect(result.container.querySelector('[data-streamdown="strong"]')).toHaveTextContent("中文句子。");
    result.rerender(view(model(false, content)));
    expect(result.container.querySelector('[data-streamdown="strong"]')).toHaveTextContent("中文句子。");
    result.unmount();
    const reloaded = render(view(model(false, content)));
    expect(reloaded.container.querySelector('[data-streamdown="strong"]')).toHaveTextContent("中文句子。");
  });

  it("keeps Markdown in user messages as literal text", () => {
    const chat: ChatViewModel = { ...model(false), messages: [{ id: "input", role: "user", content: "**中文句子。**后面紧接正文。" }] };
    const { container } = render(view(chat));
    expect(container.querySelector('[data-streamdown="strong"]')).toBeNull();
    expect(container).toHaveTextContent("**中文句子。**后面紧接正文。");
  });
});
