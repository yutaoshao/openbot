import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LanguageProvider } from "../i18n";
import DesktopDemo from "./DesktopDemo";
import { demoRequest, resetDemoBackend } from "./backend";

function renderDemo(path = "/desktop-demo") {
  window.history.replaceState(null, "", path);
  render(<LanguageProvider><BrowserRouter><Routes>
    <Route path="/desktop-demo/*" element={<DesktopDemo />} />
  </Routes></BrowserRouter></LanguageProvider>);
  return userEvent.setup();
}

function categories() {
  return screen.getByRole("navigation", { name: /^(Settings categories|设置分类)$/ });
}

function tab(path: string): HTMLAnchorElement {
  const link = within(categories()).getAllByRole<HTMLAnchorElement>("link")
    .find((item) => item.getAttribute("href") === path);
  if (!link) throw new Error(`Missing settings tab: ${path}`);
  return link;
}

beforeEach(() => {
  resetDemoBackend();
  localStorage.setItem("openbot_language", "en-US");
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("Real network forbidden"); }));
  vi.stubGlobal("WebSocket", vi.fn(() => { throw new Error("Real socket forbidden"); }));
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

afterEach(() => {
  expect(fetch).not.toHaveBeenCalled();
  expect(WebSocket).not.toHaveBeenCalled();
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  localStorage.clear();
  window.history.replaceState(null, "", "/");
});

describe("complete Demo settings workspace", () => {
  it("warns before discarding edits and supports Escape without losing the draft on cancel", async () => {
    const user = renderDemo("/desktop-demo/settings/connection");
    const model = await screen.findByRole("textbox", { name: "Model name" });
    await user.clear(model);
    await user.type(model, "changed-model");
    fireEvent(screen.getByRole("dialog", { name: "Settings" }), new Event("cancel", { cancelable: true }));
    expect(model).toHaveValue("changed-model");
    await user.click(screen.getByRole("button", { name: "Keep editing" }));
    expect(model).toHaveValue("changed-model");
    fireEvent(screen.getByRole("dialog", { name: "Settings" }), new Event("cancel", { cancelable: true }));
    await user.click(screen.getByRole("button", { name: "Discard" }));
    expect(window.location.pathname).toBe("/desktop-demo");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens a modal and returns to the selected conversation; new-chat shortcuts still work", async () => {
    const user = renderDemo();
    const selected = await screen.findByRole("button", { name: "周报整理" });
    expect(selected).toHaveAttribute("aria-current", "page");
    const composer = screen.getByRole("textbox", { name: "Message" });
    await user.type(composer, "保留这段未发送内容");
    await user.click(screen.getByRole("link", { name: "Settings" }));
    expect(window.location.pathname).toBe("/desktop-demo/settings/general");
    expect(categories()).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Settings" })).toBeInTheDocument();
    expect(selected).toBeInTheDocument();
    await user.keyboard("{Control>}n{/Control}");
    expect(window.location.pathname).toBe("/desktop-demo/settings/general");
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(window.location.pathname).toBe("/desktop-demo");
    expect(composer).toHaveValue("保留这段未发送内容");
    expect(await screen.findByRole("button", { name: "周报整理" })).toHaveAttribute("aria-current", "page");
    await user.keyboard("{Control>}n{/Control}");
    expect(screen.getByRole("button", { name: "周报整理" })).not.toHaveAttribute("aria-current");
    expect(await screen.findByRole("heading", { name: "What would you like to work on?" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "周报整理" }));
    await user.keyboard("{Meta>}n{/Meta}");
    expect(screen.getByRole("button", { name: "周报整理" })).not.toHaveAttribute("aria-current");
  });

  it("switches every preference and management tab inside the Demo", async () => {
    const user = renderDemo("/desktop-demo/settings/general");
    for (const key of ["appearance", "connection", "services", "execution", "data-import", "updates", "general"]) {
      const path = `/desktop-demo/settings/${key}`;
      await user.click(tab(path));
      expect(window.location.pathname).toBe(path);
      expect(tab(path)).toHaveAttribute("aria-current", "page");
      expect(screen.getByRole("dialog", { name: "Settings" })).toBeInTheDocument();
    }
    for (const key of ["overview", "conversations", "memory", "tools", "scheduler", "monitoring", "logs"]) {
      const path = `/desktop-demo/manage/${key}`;
      await user.click(tab(path));
      expect(window.location.pathname).toBe(path);
      expect(tab(path)).toHaveAttribute("aria-current", "page");
      await within(screen.getByRole("main")).findAllByRole("heading");
    }
    await user.click(screen.getByRole("link", { name: "Help" }));
    expect(window.location.pathname).toBe("/desktop-demo/manage/help");
    expect(await screen.findByRole("heading", { name: "Operator Help" })).toBeInTheDocument();
  });

  it("preserves explicit theme and language selection across tabs", async () => {
    const user = renderDemo("/desktop-demo/settings/appearance");
    const light = await screen.findByRole("radio", { name: "Light" });
    expect(light).toBeChecked();
    await user.click(light);
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    await user.click(screen.getByRole("radio", { name: "Dark" }));
    expect(screen.getByRole("radio", { name: "Dark" })).toBeChecked();
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    await user.click(tab("/desktop-demo/settings/general"));
    await user.selectOptions(screen.getByRole("combobox", { name: "Language" }), "zh-CN");
    expect(screen.getByRole("combobox", { name: "语言" })).toHaveValue("zh-CN");
    await user.click(tab("/desktop-demo/settings/appearance"));
    const night = screen.getByRole("radio", { name: "夜间" });
    expect(night).toBeChecked();
    await user.click(night);
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    await user.click(tab("/desktop-demo/settings/general"));
    await user.selectOptions(screen.getByRole("combobox", { name: "语言" }), "en-US");
    expect(screen.getByRole("combobox", { name: "Language" })).toHaveValue("en-US");
  });

  it("filters categories without changing the current content and clears the search", async () => {
    const user = renderDemo("/desktop-demo/settings/general");
    const search = screen.getByRole("textbox", { name: "Search settings" });
    await user.type(search, "updates");
    expect(window.location.pathname).toBe("/desktop-demo/settings/general");
    expect(screen.getByRole("combobox", { name: "Language" })).toBeInTheDocument();
    expect(within(categories()).getAllByRole("link")).toHaveLength(1);
    expect(tab("/desktop-demo/settings/updates")).toBeInTheDocument();
    await user.clear(search);
    await user.type(search, "no-matching-setting");
    expect(within(categories()).queryByRole("link")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear search" }));
    expect(search).toHaveValue("");
    expect(tab("/desktop-demo/settings/general")).toHaveAttribute("aria-current", "page");
  });

  it("runs the simulated update workflow from the real update component", async () => {
    const user = renderDemo("/desktop-demo/settings/updates");
    await user.click(await screen.findByRole("button", { name: "Check for updates" }));
    expect(await screen.findByText("Version 0.1.1 is available.")).toBeInTheDocument();
    const install = screen.getByRole("button", { name: "Install update and restart" });
    await user.click(install);
    expect(await screen.findByText("Simulated installation ended; the local app was not changed.")).toBeInTheDocument();
    expect(install).toBeDisabled();
  });

  it("uses the actual permission component and Demo backend for explicit authorization", async () => {
    const user = renderDemo("/desktop-demo/settings/execution");
    const shell = await screen.findByRole("checkbox", { name: /Shell/ });
    expect(shell).not.toBeChecked();
    await user.click(shell);
    fireEvent(screen.getByRole("dialog", { name: "Settings" }), new Event("cancel", { cancelable: true }));
    expect(window.location.pathname).toBe("/desktop-demo/settings/execution");
    expect(screen.getByRole("dialog", { name: /Allow Shell/ })).toBeInTheDocument();
    await user.click(within(screen.getByRole("dialog", { name: /Allow Shell/ })).getByRole("button", { name: "Not now" }));
    expect(shell).not.toBeChecked();
    await user.click(shell);
    await user.click(within(screen.getByRole("dialog", { name: /Allow Shell/ })).getByRole("button", { name: "Allow tool" }));
    await waitFor(() => expect(shell).toBeChecked());
    expect((await demoRequest<{ permissions: { bash: boolean } }>("/api/desktop/status")).permissions.bash).toBe(true);
    expect(screen.getByRole("dialog", { name: "Settings" })).toBeInTheDocument();
    await user.click(shell);
    await waitFor(() => expect(shell).not.toBeChecked());
    expect((await demoRequest<{ permissions: { bash: boolean } }>("/api/desktop/status")).permissions.bash).toBe(false);
  });

  it("redirects the old management-settings route into the full connection tab", async () => {
    renderDemo("/desktop-demo/manage/settings");
    await waitFor(() => expect(window.location.pathname).toBe("/desktop-demo/settings/connection"));
    expect(await screen.findByRole("textbox", { name: "Model name" })).toHaveValue("demo-model");
    expect(categories()).toBeInTheDocument();
  });

  it("retains an unsaved connection draft while switching settings tabs", async () => {
    const user = renderDemo("/desktop-demo/settings/connection");
    const model = await screen.findByRole("textbox", { name: "Model name" });
    await user.clear(model);
    await user.type(model, "unsaved-review-model");
    await user.click(tab("/desktop-demo/settings/general"));
    expect(screen.queryByRole("textbox", { name: "Model name" })).not.toBeInTheDocument();
    await user.click(tab("/desktop-demo/settings/services"));
    await user.click(tab("/desktop-demo/settings/connection"));
    expect(await screen.findByRole("textbox", { name: "Model name" })).toHaveValue("unsaved-review-model");
    expect((await demoRequest<{ model: { model: string } }>("/api/desktop/status")).model.model).toBe("demo-model");
  });

  it("keeps the first-import scenario through the old redirect, settings tabs, shared links, and chat", async () => {
    const user = renderDemo("/desktop-demo/manage/settings?preview=import");
    await waitFor(() => expect(window.location.pathname).toBe("/desktop-demo/settings/connection"));
    expect(window.location.search).toBe("?preview=import");
    await user.click(tab("/desktop-demo/settings/data-import?preview=import"));
    expect(await screen.findByRole("textbox", { name: /Old OpenBot folder/ })).toBeEnabled();
    await user.click(tab("/desktop-demo/manage/overview?preview=import"));
    await user.click(await screen.findByRole("link", { name: "View Logs" }));
    expect(window.location.pathname).toBe("/desktop-demo/manage/logs");
    expect(window.location.search).toBe("?preview=import");
    await user.click(tab("/desktop-demo/settings/data-import?preview=import"));
    expect(window.location.search).toBe("?preview=import");
    expect((await demoRequest<{ configured: boolean }>("/api/desktop/status")).configured).toBe(false);
    const source = await screen.findByRole("textbox", { name: /Old OpenBot folder/ });
    await user.clear(source);
    await user.type(source, "/demo/old-openbot");
    await user.click(screen.getByRole("checkbox", { name: /I stopped the old OpenBot instance/ }));
    expect(screen.getByRole("button", { name: "Preview import" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Close" }));
    await user.click(screen.getByRole("button", { name: "Discard" }));
    expect(window.location.search).toBe("?preview=import");
    await user.click(screen.getByRole("link", { name: "Settings" }));
    expect(window.location.pathname).toBe("/desktop-demo/settings/general");
    expect(window.location.search).toBe("?preview=import");
  });
});

it("retains management drafts across categories and clears their warnings after successful saves", async () => {
  const user = renderDemo("/desktop-demo/manage/memory");
  const knowledge = await screen.findByRole("textbox", { name: "Knowledge content..." });
  fireEvent.change(knowledge, { target: { value: "synthetic knowledge draft" } });
  await user.click(tab("/desktop-demo/manage/scheduler"));
  const createSection = (await screen.findByRole("heading", { name: "Create Task" })).closest("section")!;
  const name = within(createSection).getAllByRole("textbox")[0];
  fireEvent.change(name, { target: { value: "synthetic schedule draft" } });
  await user.click(tab("/desktop-demo/settings/general"));
  await user.click(screen.getByRole("button", { name: "Close" }));
  await user.click(screen.getByRole("button", { name: "Keep editing" }));
  await user.click(tab("/desktop-demo/manage/memory"));
  expect(knowledge).toHaveValue("synthetic knowledge draft");
  await user.click(within(knowledge.closest("section")!).getByRole("button", { name: "Save" }));
  await waitFor(() => expect(knowledge).toHaveValue(""));
  await user.click(tab("/desktop-demo/manage/scheduler"));
  expect(name).toHaveValue("synthetic schedule draft");
  await user.click(within(createSection).getByRole("button", { name: "Create" }));
  await waitFor(() => expect(within(createSection).getByRole("button", { name: "Create" })).toBeEnabled());
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(window.location.pathname).toBe("/desktop-demo");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
