import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LanguageProvider } from "../i18n";
import { DashboardPage } from "../pages/dashboard";
import { HelpPage } from "../pages/help";
import { ToolsPage } from "../pages/tools";
import { demoRequest, resetDemoBackend } from "./backend";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(<QueryClientProvider client={client}><LanguageProvider><BrowserRouter><Routes>
    <Route path="/desktop-demo/manage/overview" element={<DashboardPage />} />
    <Route path="/desktop-demo/manage/help" element={<HelpPage />} />
    <Route path="/desktop-demo/manage/tools" element={<ToolsPage />} />
    <Route path="/desktop-demo/manage/monitoring" element={<p>Safe monitoring destination</p>} />
    <Route path="/desktop-demo/manage/logs" element={<p>Safe logs destination</p>} />
    <Route path="*" element={<p>Escaped the preview</p>} />
  </Routes></BrowserRouter></LanguageProvider></QueryClientProvider>);
}

beforeEach(() => {
  resetDemoBackend();
  localStorage.setItem("openbot_language", "en-US");
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("Real network forbidden"); }));
  vi.stubGlobal("WebSocket", vi.fn(() => { throw new Error("Real socket forbidden"); }));
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
  window.history.replaceState(null, "", "/");
});

describe("shared management navigation inside the preview", () => {
  it("requires explicit authorization before enabling a synthetic execution tool", async () => {
    window.history.replaceState(null, "", "/desktop-demo/manage/tools");
    renderPage();
    const heading = await screen.findByRole("heading", { name: "bash" });
    const card = heading.closest("section");
    expect(card).not.toBeNull();
    const rows = () => demoRequest<Array<{ name: string; enabled: boolean }>>("/api/tools");
    fireEvent.click(within(card!).getByRole("button", { name: "Enable" }));
    const dialog = screen.getByRole("dialog");
    expect((await rows()).find((item) => item.name === "bash")?.enabled).toBe(false);
    fireEvent.click(within(dialog).getByRole("button", { name: "Not now" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect((await rows()).find((item) => item.name === "bash")?.enabled).toBe(false);

    fireEvent.click(within(card!).getByRole("button", { name: "Enable" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Allow tool" }));
    await waitFor(async () => expect((await rows()).find((item) => item.name === "bash")?.enabled).toBe(true));
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each([
    ["overview", "Open Monitoring", "monitoring"],
    ["overview", "View Logs", "logs"],
    ["help", "Monitoring", "monitoring"],
    ["help", "Logs", "logs"],
  ] as const)("keeps %s → %s within the Demo boundary", async (page, label, destination) => {
    window.history.replaceState(null, "", `/desktop-demo/manage/${page}`);
    renderPage();
    const links = await screen.findAllByRole("link", { name: label });
    fireEvent.click(links[0]);
    await waitFor(() => expect(window.location.pathname).toBe(`/desktop-demo/manage/${destination}`));
    expect(screen.queryByText("Escaped the preview")).not.toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
    expect(WebSocket).not.toHaveBeenCalled();
  });
});
