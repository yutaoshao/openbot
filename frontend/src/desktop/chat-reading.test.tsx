import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";

import { LanguageProvider } from "../i18n";
import { api } from "../lib/api";
import DesktopApp from "./DesktopApp";
import { readDesktopConnection } from "./native";

vi.mock("./native", () => ({ readDesktopConnection: vi.fn(), desktopInvoke: vi.fn() }));
vi.mock("../lib/api", () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } }));
const clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, "clipboard");

afterEach(() => {
  cleanup(); localStorage.clear(); sessionStorage.clear(); vi.resetAllMocks(); vi.restoreAllMocks();
  if (clipboardDescriptor) Object.defineProperty(navigator, "clipboard", clipboardDescriptor);
  else Reflect.deleteProperty(navigator, "clipboard");
});

it("renders saved replies with the confirmed Markdown behavior through the live desktop entry", async () => {
  localStorage.setItem("openbot_language", "zh-CN");
  localStorage.setItem("openbot_desktop_selection_v1", "reading-test");
  vi.mocked(readDesktopConnection).mockResolvedValue({ status: "ready", baseUrl: "http://127.0.0.1:12345", token: "synthetic", instanceId: "reading-test" });
  const content = "**中文提示。**后面紧接正文。\n\n```text\n  保留缩进\n```\n\n[来源](https://example.com/source)\n\n| 款式 | 用途 |\n| --- | --- |\n| 薄款 | 通勤 |";
  vi.mocked(api.get).mockImplementation(async (path) => {
    if (path === "/api/desktop/status") return { configured: true, busy: false };
    if (path.startsWith("/api/conversations/reading-test?")) return {
      conversation: { id: "reading-test", title: "阅读验证", message_count: 1 },
      messages: [{ id: "saved-reply", role: "assistant", content }],
    };
    if (path === "/api/conversations?limit=100") return [{ id: "reading-test", title: "阅读验证", platform: "web" }];
    if (path === "/api/chat/runs?conversation_id=reading-test") return [];
    throw new Error(`Unexpected desktop request: ${path}`);
  });
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
  const open = vi.spyOn(window, "open").mockImplementation(() => null);
  const { container } = render(<LanguageProvider><MemoryRouter initialEntries={["/desktop"]}><DesktopApp /></MemoryRouter></LanguageProvider>);
  expect(await screen.findByText("中文提示。")).toHaveAttribute("data-streamdown", "strong");
  expect(document.documentElement).toHaveAttribute("data-desktop", "true");
  expect(document.documentElement).not.toHaveAttribute("data-desktop-demo");
  expect(screen.getByRole("table")).toHaveTextContent("薄款");
  expect(container.querySelector('[data-streamdown="code-block"]')).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "复制代码" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith("  保留缩进\n"));
  expect(await screen.findByText("已复制")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "来源" }));
  expect(screen.getByText("打开外部链接？")).toBeInTheDocument();
  expect(open).not.toHaveBeenCalled();
  expect(api.post).not.toHaveBeenCalled();
});
