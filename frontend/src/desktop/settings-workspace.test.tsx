import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { LanguageProvider } from "../i18n";
import { demoRequest, resetDemoBackend } from "../demo/backend";
import { api } from "../lib/api";
import DesktopApp from "./DesktopApp";
import { desktopInvoke, readDesktopConnection } from "./native";
import type { ServicesSnapshot } from "./service-types";

vi.mock("./native", () => ({ readDesktopConnection: vi.fn(), desktopInvoke: vi.fn() }));
vi.mock("../lib/api", () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } }));

let instanceId: string;
let busy: boolean;
let snapshot: ServicesSnapshot;

function renderDesktop(path = "/desktop") {
  window.history.replaceState(null, "", path);
  render(<LanguageProvider><BrowserRouter><Routes>
    <Route path="/desktop/*" element={<DesktopApp />} />
  </Routes></BrowserRouter></LanguageProvider>);
  return userEvent.setup();
}

function category(name: string) {
  return within(screen.getByRole("navigation", { name: "Settings categories" })).getByRole("link", { name });
}

beforeEach(async () => {
  resetDemoBackend();
  snapshot = await demoRequest<ServicesSnapshot>("/api/desktop/services");
  instanceId = "native-initial";
  busy = false;
  localStorage.setItem("openbot_language", "en-US");
  Object.defineProperty(window, "__TAURI_INTERNALS__", { configurable: true, value: { invoke: vi.fn() } });
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("Real network forbidden"); }));
  vi.stubGlobal("WebSocket", vi.fn(() => { throw new Error("Real socket forbidden"); }));
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  vi.mocked(readDesktopConnection).mockImplementation(async () => ({
    status: "ready", baseUrl: "http://127.0.0.1:12345", token: "synthetic", instanceId,
  }));
  vi.mocked(desktopInvoke).mockImplementation(async (command, args) => {
    if (command === "desktop_autostart") return false;
    if (command === "desktop_set_autostart") return args?.enabled;
    if (command === "desktop_open_web") return undefined;
    throw new Error(`Unexpected native command: ${command}`);
  });
  vi.mocked(api.get).mockImplementation(async (path) => {
    if (path === "/api/desktop/status") return {
      configured: true, data_dir: "/synthetic/native-data", work_dir: "/synthetic/native-work", busy,
      permissions: { bash: false, code_executor: false }, model: {
        provider: "openai_compatible", base_url: "http://127.0.0.1:12345/v1",
        model: `${instanceId}-model`, api_key_set: true,
      },
    };
    if (path === "/api/desktop/services") return snapshot;
    if (path.startsWith("/api/conversations?")) return [{ id: "native-history", title: "Native history", platform: "desktop" }];
    if (path.startsWith("/api/conversations/native-history?")) return {
      conversation: { id: "native-history", title: "Native history", message_count: 0 }, messages: [],
    };
    if (path.startsWith("/api/chat/runs?")) return [];
    if (path === "/api/desktop/wechat/login/native-login") return { session_id: "native-login", status: "wait" };
    throw new Error(`Unexpected live API path: ${path}`);
  });
  vi.mocked(api.post).mockResolvedValue({ session_id: "native-login", status: "wait" });
  vi.mocked(api.del).mockResolvedValue({ session_id: "native-login", status: "cancelled" });
});

afterEach(() => {
  cleanup();
  expect(fetch).not.toHaveBeenCalled();
  expect(WebSocket).not.toHaveBeenCalled();
  delete window.__TAURI_INTERNALS__;
  vi.unstubAllGlobals();
  vi.resetAllMocks();
  localStorage.clear();
  window.history.replaceState(null, "", "/");
});

it("keeps native navigation and the selected conversation when returning from settings", async () => {
  const user = renderDesktop();
  await user.click(await screen.findByRole("button", { name: "Native history" }));
  await user.click(screen.getByRole("link", { name: "Settings" }));
  expect(window.location.pathname).toBe("/desktop/settings/general");
  expect(await screen.findByRole("link", { name: /native-initial-model/ })).toBeInTheDocument();
  for (const link of screen.getAllByRole("link")) {
    expect(link.getAttribute("href")).toMatch(/^\/desktop(?:\/|$)/);
    expect(link.getAttribute("href")).not.toContain("desktop-demo");
  }
  expect(api.get).toHaveBeenCalledWith("/api/desktop/status");
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(window.location.pathname).toBe("/desktop");
  expect(await screen.findByRole("button", { name: "Native history" })).toHaveAttribute("aria-current", "page");
  expect(localStorage.getItem("openbot_desktop_selection_v1")).toBe("native-history");
});

it("preserves native integration commands and explicitly selected theme persistence", async () => {
  const user = renderDesktop("/desktop/settings/general");
  const startup = await screen.findByRole("checkbox", { name: /Start OpenBot when you log in/ });
  await waitFor(() => expect(startup).toBeEnabled());
  expect(startup).not.toBeChecked();
  await user.click(startup);
  await waitFor(() => expect(startup).toBeChecked());
  expect(desktopInvoke).toHaveBeenCalledWith("desktop_set_autostart", { enabled: true });
  await user.click(screen.getByRole("button", { name: /Open Web console/ }));
  expect(desktopInvoke).toHaveBeenCalledWith("desktop_open_web");
  await user.click(category("Appearance"));
  const dark = await screen.findByRole("radio", { name: "Dark" });
  await user.click(dark);
  await user.click(dark);
  expect(dark).toBeChecked();
  expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  expect(localStorage.getItem("openbot_desktop_theme_v1")).toBe("dark");
});

it("redirects legacy settings, retains drafts across categories, and clears them for a new native instance", async () => {
  const user = renderDesktop("/desktop/manage/settings");
  const model = await screen.findByRole("textbox", { name: "Model name" });
  expect(window.location.pathname).toBe("/desktop/settings/connection");
  expect(model).toHaveValue("native-initial-model");
  await user.clear(model);
  await user.type(model, "unsaved-native-model");
  await user.click(category("General"));
  await user.click(category("Connection"));
  expect(await screen.findByRole("textbox", { name: "Model name" })).toHaveValue("unsaved-native-model");
  instanceId = "native-restarted";
  await waitFor(() => expect(screen.getByRole("textbox", { name: "Model name" })).toHaveValue("native-restarted-model"), { timeout: 3000 });
  expect(api.post).not.toHaveBeenCalled();
});

it("cancels a hidden QR login while retaining service drafts and blocking busy saves", async () => {
  busy = true;
  const user = renderDesktop("/desktop/settings/services");
  const ids = await screen.findByRole("textbox", { name: /Allowed Telegram user IDs/ });
  await user.clear(ids);
  await user.type(ids, "12345");
  expect(screen.getByRole("button", { name: "Save and restart service" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Get login QR code" }));
  expect(await screen.findByText("Waiting for scan")).toBeInTheDocument();
  await user.click(category("Connection"));
  await waitFor(() => expect(api.del).toHaveBeenCalledWith("/api/desktop/wechat/login/native-login"));
  await user.click(category("Models & channels"));
  expect(await screen.findByRole("textbox", { name: /Allowed Telegram user IDs/ })).toHaveValue("12345");
  expect(screen.queryByText("Waiting for scan")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Save and restart service" })).toBeDisabled();
  expect(api.put).not.toHaveBeenCalled();
});

it("refreshes saved login state when confirmation wins a delayed cancellation without replacing the service draft", async () => {
  let completeCancellation!: (result: { session_id: string; status: string }) => void;
  vi.mocked(api.del).mockReturnValue(new Promise((resolve) => { completeCancellation = resolve; }));
  const user = renderDesktop("/desktop/settings/services");
  const ids = await screen.findByRole("textbox", { name: /Allowed Telegram user IDs/ });
  await user.clear(ids);
  await user.type(ids, "67890");
  await user.click(screen.getByRole("button", { name: "Get login QR code" }));
  expect(await screen.findByText("Waiting for scan")).toBeInTheDocument();
  await user.click(category("Connection"));
  expect(api.del).toHaveBeenCalledWith("/api/desktop/wechat/login/native-login");
  await user.click(category("Models & channels"));
  expect(await screen.findByRole("textbox", { name: /Allowed Telegram user IDs/ })).toHaveValue("67890");
  snapshot = { ...snapshot, wechat: { ...snapshot.wechat, logged_in: true } };
  completeCancellation({ session_id: "native-login", status: "confirmed" });
  expect(await screen.findByText(/WeChat login information is saved on this Mac/)).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: /Allowed Telegram user IDs/ })).toHaveValue("67890");
  expect(api.put).not.toHaveBeenCalled();
});

it("translates a retained Telegram ID validation error when the interface language changes", async () => {
  localStorage.setItem("openbot_language", "zh-CN");
  const user = renderDesktop("/desktop/settings/services");
  const ids = await screen.findByRole<HTMLInputElement>("textbox", { name: /允许的 Telegram 用户 ID/ });
  await user.clear(ids);
  await user.type(ids, "bad");
  expect(ids.validationMessage).toBe("请填写有效的正整数用户 ID，并用逗号分隔。");
  await user.click(screen.getByRole("link", { name: "常规" }));
  await user.selectOptions(screen.getByRole("combobox", { name: "语言" }), "en-US");
  await user.click(category("Models & channels"));
  expect(ids).toHaveValue("bad");
  expect(ids.validationMessage).toBe("Enter valid positive integer user IDs separated by commas.");
  await user.click(category("General"));
  await user.selectOptions(screen.getByRole("combobox", { name: "Language" }), "zh-CN");
  await user.click(screen.getByRole("link", { name: "模型与渠道" }));
  expect(ids.validationMessage).toBe("请填写有效的正整数用户 ID，并用逗号分隔。");
  await user.clear(ids);
  expect(ids.validity.valid).toBe(true);
  await user.type(ids, "123，456");
  expect(ids.validationMessage).toBe("");
  vi.mocked(api.put).mockResolvedValueOnce({ requires_restart: true });
  await user.click(screen.getByRole("button", { name: "保存并重启服务" }));
  await waitFor(() => expect(api.put).toHaveBeenCalledWith("/api/desktop/services", expect.objectContaining({
    configuration: expect.objectContaining({ telegram: expect.objectContaining({ allowed_user_ids: [123, 456] }) }),
  })));
});

it.each(["1e3", "0x10"])("uses the interface-language error for unsupported numeric ID syntax %s", async (value) => {
  const user = renderDesktop("/desktop/settings/services");
  const ids = await screen.findByRole<HTMLInputElement>("textbox", { name: /Allowed Telegram user IDs/ });
  await user.click(screen.getByRole("checkbox", { name: "Telegram enabled" }));
  await user.clear(ids);
  await user.type(ids, value);
  expect(ids.validity.customError).toBe(true);
  expect(ids.validationMessage).toBe("Enter valid positive integer user IDs separated by commas.");
  await user.click(screen.getByRole("button", { name: "Save and restart service" }));
  expect(api.put).not.toHaveBeenCalled();
});

it("clears the close warning when connection edits are reverted or saved", async () => {
  const user = renderDesktop("/desktop/settings/connection");
  const model = await screen.findByRole("textbox", { name: "Model name" });
  fireEvent.change(model, { target: { value: "changed" } });
  fireEvent.change(model, { target: { value: "native-initial-model" } });
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(window.location.pathname).toBe("/desktop");
  await user.click(screen.getByRole("link", { name: "Settings" }));
  await user.click(category("Connection"));
  fireEvent.change(await screen.findByRole("textbox", { name: "Model name" }), { target: { value: "saved-model" } });
  vi.mocked(api.post).mockResolvedValueOnce({ requires_restart: false });
  await user.click(screen.getByRole("button", { name: "Save and restart service" }));
  await waitFor(() => expect(screen.getByRole("textbox", { name: "Model name" })).toBeEnabled());
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(window.location.pathname).toBe("/desktop");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("retains a failed connection save, asks before discarding, and blocks close during a pending save", async () => {
  const user = renderDesktop("/desktop/settings/connection");
  const model = await screen.findByRole("textbox", { name: "Model name" });
  fireEvent.change(model, { target: { value: "failed-model" } });
  vi.mocked(api.post).mockRejectedValueOnce(new Error("synthetic save failure"));
  await user.click(screen.getByRole("button", { name: "Save and restart service" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("synthetic save failure");
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(screen.getByRole("dialog", { name: "Unsaved configuration changes" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Keep editing" }));
  expect(model).toHaveValue("failed-model");
  let finish!: (value: { requires_restart: boolean }) => void;
  vi.mocked(api.post).mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
  await user.click(screen.getByRole("button", { name: "Save and restart service" }));
  expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();
  fireEvent(screen.getByRole("dialog", { name: "Settings" }), new Event("cancel", { cancelable: true }));
  expect(window.location.pathname).toBe("/desktop/settings/connection");
  finish({ requires_restart: false });
  await waitFor(() => expect(screen.getByRole("button", { name: "Close" })).toBeEnabled());
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(window.location.pathname).toBe("/desktop");
});

it("tracks invalid Telegram drafts even when they never reach the configuration object", async () => {
  const user = renderDesktop("/desktop/settings/services");
  const ids = await screen.findByRole("textbox", { name: /Allowed Telegram user IDs/ });
  const original = (ids as HTMLInputElement).value;
  fireEvent.change(ids, { target: { value: "invalid" } });
  await user.click(screen.getByRole("button", { name: "Close" }));
  await user.click(screen.getByRole("button", { name: "Keep editing" }));
  expect(ids).toHaveValue("invalid");
  fireEvent.change(ids, { target: { value: original } });
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(window.location.pathname).toBe("/desktop");
});

it("keeps secret drafts after a failed save and clears the warning after a successful save", async () => {
  const user = renderDesktop("/desktop/settings/services");
  const secret = await screen.findByLabelText("Telegram Bot Token");
  await user.click(screen.getByText("Secrets", { selector: "summary" }));
  fireEvent.change(secret, { target: { value: "synthetic-secret" } });
  vi.mocked(api.put).mockRejectedValueOnce(new Error("synthetic secret failure"));
  await user.click(screen.getByRole("button", { name: "Save and restart service" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("synthetic secret failure");
  await user.click(screen.getByRole("button", { name: "Close" }));
  await user.click(screen.getByRole("button", { name: "Keep editing" }));
  expect(secret).toHaveValue("synthetic-secret");
  vi.mocked(api.put).mockResolvedValueOnce({ requires_restart: false });
  await user.click(screen.getByRole("button", { name: "Save and restart service" }));
  await waitFor(() => expect(secret).toHaveValue(""));
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(window.location.pathname).toBe("/desktop");
});

it("closes without a warning after immediate preferences and cancels an active QR login on close", async () => {
  const user = renderDesktop("/desktop/settings/appearance");
  await user.click(await screen.findByRole("radio", { name: "Dark" }));
  await user.click(category("General"));
  await user.selectOptions(screen.getByRole("combobox", { name: "Language" }), "zh-CN");
  await user.click(screen.getByRole("button", { name: "关闭" }));
  expect(window.location.pathname).toBe("/desktop");
  await user.click(screen.getByRole("link", { name: "设置" }));
  await user.click(screen.getByRole("link", { name: "模型与渠道" }));
  await user.click(await screen.findByRole("button", { name: "获取登录二维码" }));
  await user.click(screen.getByRole("button", { name: "关闭" }));
  await waitFor(() => expect(api.del).toHaveBeenCalledWith("/api/desktop/wechat/login/native-login"));
  expect(window.location.pathname).toBe("/desktop");
});
