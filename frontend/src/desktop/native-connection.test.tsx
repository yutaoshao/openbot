import { focusManager, onlineManager } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { LanguageProvider } from "../i18n";
import { api } from "../lib/api";
import DesktopApp from "./DesktopApp";
import { readDesktopConnection } from "./native";

vi.mock("./native", () => ({ readDesktopConnection: vi.fn(), desktopInvoke: vi.fn() }));
vi.mock("../lib/api", () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } }));
afterEach(() => { cleanup(); focusManager.setFocused(undefined); onlineManager.setOnline(true); localStorage.clear(); vi.resetAllMocks(); });

it.each([
  { focused: false, online: true },
  { focused: true, online: false },
])("follows the new native instance with WebView focused=$focused, online=$online", async ({ focused, online }) => {
  localStorage.setItem("openbot_language", "en-US");
  focusManager.setFocused(focused); onlineManager.setOnline(online);
  let generation = 0;
  vi.mocked(readDesktopConnection).mockImplementation(async () => {
    generation += 1;
    return { status: "ready", baseUrl: "http://127.0.0.1:12345", token: "synthetic", instanceId: generation === 1 ? "before" : "after" };
  });
  vi.mocked(api.get).mockImplementation(async () => ({
    configured: false, data_dir: "/synthetic/app", work_dir: "/synthetic/work", busy: false,
    permissions: { bash: false, code_executor: false }, model: {
      provider: "openai_compatible", base_url: "http://127.0.0.1:12345/v1",
      model: generation === 1 ? "initial-model" : "restarted-model", api_key_set: false,
    },
  }));
  render(<LanguageProvider><MemoryRouter><DesktopApp /></MemoryRouter></LanguageProvider>);
  expect(await screen.findByDisplayValue("initial-model")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByDisplayValue("restarted-model")).toBeInTheDocument(), { timeout: 3000 });
  expect(readDesktopConnection).toHaveBeenCalledTimes(2);
});
