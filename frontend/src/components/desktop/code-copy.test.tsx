import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LanguageProvider } from "../../i18n";
import { ChatMarkdown } from "./ChatMarkdown";

const clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, "clipboard");
const writeText = vi.fn();
const content = "第一行\n  第二行\n\n**literal**";
const fence = (language: string) => `\`\`\`${language}\n${content}\n\`\`\``;

beforeEach(() => {
  localStorage.setItem("openbot_language", "zh-CN");
  writeText.mockReset().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
});
afterEach(() => {
  cleanup(); localStorage.clear();
  if (clipboardDescriptor) Object.defineProperty(navigator, "clipboard", clipboardDescriptor);
  else Reflect.deleteProperty(navigator, "clipboard");
});

describe("code block copy in desktop chat", () => {
  it.each(["text", "markdown", "python", ""])("copies the original %s block without its fences", async (language) => {
    render(<LanguageProvider><ChatMarkdown mode="static">{fence(language)}</ChatMarkdown></LanguageProvider>);
    fireEvent.click(screen.getByRole("button", { name: "复制代码" }));
    expect(writeText).toHaveBeenCalledOnce();
    expect(writeText).toHaveBeenCalledWith(`${content}\n`);
    expect(await screen.findByText("已复制")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Download|下载/ })).not.toBeInTheDocument();
  });

  it("reports a failed clipboard write and allows retry", async () => {
    writeText.mockRejectedValueOnce(new Error("Permission denied"));
    render(<LanguageProvider><ChatMarkdown mode="static">{fence("text")}</ChatMarkdown></LanguageProvider>);
    const copy = screen.getByRole("button", { name: "复制代码" });
    fireEvent.click(copy);
    expect(await screen.findByRole("alert")).toHaveTextContent("复制失败");
    expect(screen.queryByText("已复制")).not.toBeInTheDocument();
    fireEvent.click(copy);
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(await screen.findByText("已复制")).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledTimes(2);
  });

  it("reports an unavailable clipboard without claiming success", async () => {
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined });
    render(<LanguageProvider><ChatMarkdown mode="static">{fence("text")}</ChatMarkdown></LanguageProvider>);
    fireEvent.click(screen.getByRole("button", { name: "复制代码" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("复制失败");
    expect(screen.queryByText("已复制")).not.toBeInTheDocument();
  });

  it("disables copy during generation and enables it when the reply settles", () => {
    const view = (streaming: boolean) => <LanguageProvider>
      <ChatMarkdown mode={streaming ? "streaming" : "static"} isAnimating={streaming}>{fence("text")}</ChatMarkdown>
    </LanguageProvider>;
    const result = render(view(true));
    expect(screen.getByRole("button", { name: "复制代码" })).toBeDisabled();
    result.rerender(view(false));
    expect(screen.getByRole("button", { name: "复制代码" })).toBeEnabled();
  });

  it("does not add copy buttons to ordinary paragraphs or tables", () => {
    render(<LanguageProvider><ChatMarkdown mode="static">{"正文和 `行内代码`。\n\n| A | B |\n| --- | --- |\n| 1 | 2 |"}</ChatMarkdown></LanguageProvider>);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
