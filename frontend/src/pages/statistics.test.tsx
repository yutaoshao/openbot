import { type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LanguageProvider } from "../i18n";
import { DashboardPage } from "./dashboard";
import { LogsPage } from "./logs";
import { resetDemoBackend } from "../demo/backend";
import { createDemoFixtures } from "../demo/fixtures";

vi.mock("../desktop/native", () => ({
  readyDesktopConnection: async () => ({ baseUrl: "http://127.0.0.1:18181", token: "statistics-test-token", instanceId: "statistics-test" }),
}));

function mount(page: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(<QueryClientProvider client={client}><LanguageProvider><BrowserRouter>{page}</BrowserRouter></LanguageProvider></QueryClientProvider>);
}

function productionResponse(input: RequestInfo | URL): Response {
  const url = new URL(String(input), "http://localhost");
  const day = { date: "2026-11-01", avg: 1200, p50: 1100, p95: 2100, tokens_in: 4100, tokens_out: 900 };
  const logs = createDemoFixtures().logs.filter((row) => ["platform", "level", "surface"].every((key) => {
    const value = url.searchParams.get(key);
    return !value || row[key as "platform" | "level" | "surface"] === value;
  }));
  const payloads: Record<string, unknown> = {
    "/api/metrics/overview": { total_requests: 83, error_rate: 0.01, success_rate: 0.99 },
    "/api/metrics/latency": { avg_response_time: 1200, p50: 1100, p95: 2100, daily: [day] },
    "/api/metrics/tokens": { daily: [day] },
    "/api/metrics/cost": { total_cost_usd: 0.75, daily: [{ date: day.date, cost_usd: 0.75 }] },
    "/api/metrics/tools": { tools: [{ tool: "file_manager", count: 5, error_rate: 0 }] },
    "/api/logs": logs,
    "/api/logs/stats": {
      total: logs.length,
      by_surface: Object.fromEntries(["cognitive", "operational", "contextual"].map((key) => [key, logs.filter((row) => row.surface === key).length])),
      by_level: Object.fromEntries(["error", "warning", "info"].map((key) => [key, logs.filter((row) => row.level === key).length])),
    },
  };
  if (!(url.pathname in payloads)) throw new Error(`Unexpected HTTP request: ${url.pathname}`);
  return new Response(JSON.stringify(payloads[url.pathname]), { status: 200, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  resetDemoBackend();
  localStorage.setItem("openbot_language", "en-US");
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => productionResponse(input)));
  vi.stubGlobal("WebSocket", vi.fn(() => { throw new Error("Unexpected socket"); }));
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
  window.history.replaceState(null, "", "/");
});

describe("shared production statistics", () => {
  it("renders the approved layout with Web HTTP data and requests the stated seven-day window", async () => {
    window.history.replaceState(null, "", "/");
    mount(<DashboardPage />);
    expect(await screen.findByText("83")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Response latency" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View Logs" })).toHaveAttribute("href", "/logs");
    const requests = vi.mocked(fetch).mock.calls.map(([input]) => String(input));
    expect(requests).toContain("/api/metrics/latency?period=7d");
    expect(requests).toContain("/api/metrics/tokens?period=7d");
    expect(requests).not.toContain("/api/metrics/latency?period=30d");
  });

  it("uses the native authenticated service without changing the approved presentation", async () => {
    window.history.replaceState(null, "", "/desktop/manage/overview");
    mount(<DashboardPage />);
    expect(await screen.findByText("83")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Response latency" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View Logs" })).toHaveAttribute("href", "/desktop/manage/logs");
    for (const [input, init] of vi.mocked(fetch).mock.calls) {
      expect(String(input)).toMatch(/^http:\/\/127\.0\.0\.1:18181\/api\//);
      expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer statistics-test-token");
    }
  });

  it("keeps Demo navigation and data isolated with the same shared page", async () => {
    window.history.replaceState(null, "", "/desktop-demo/manage/overview");
    vi.mocked(fetch).mockImplementation(async () => { throw new Error("Real network forbidden"); });
    mount(<DashboardPage />);
    expect(await screen.findByText("24")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Response latency" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "View Logs" }));
    await waitFor(() => expect(window.location.pathname).toBe("/desktop-demo/manage/logs"));
    expect(fetch).not.toHaveBeenCalled();
    expect(WebSocket).not.toHaveBeenCalled();
  });

  it("updates platform totals and filters production log records", async () => {
    window.history.replaceState(null, "", "/logs");
    mount(<LogsPage />);
    await screen.findByText("demo.conversation.completed");
    const total = screen.getByText("Total").closest("section")!;
    expect(within(total).getByText("3")).toBeInTheDocument();
    expect(screen.queryByText("Degraded")).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Filter logs by platform" }), { target: { value: "telegram" } });
    await waitFor(() => expect(within(total).getByText("1")).toBeInTheDocument());
    await waitFor(() => expect(screen.queryByText("demo.conversation.completed")).not.toBeInTheDocument());
    expect(screen.getByText("demo.channel.not_configured")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Filter logs by level" }), { target: { value: "error" } });
    await waitFor(() => expect(screen.queryByText("demo.channel.not_configured")).not.toBeInTheDocument());
    expect(await screen.findByText("No log entries yet. Logs will appear once agent processes messages.")).toBeInTheDocument();
  });

  it("shows unavailable values and a retry action instead of zero records after a failure", async () => {
    window.history.replaceState(null, "", "/logs");
    let failing = true;
    vi.mocked(fetch).mockImplementation(async (input) => failing ? new Response("unavailable", { status: 503 }) : productionResponse(input));
    mount(<LogsPage />);
    await waitFor(() => expect(screen.getAllByRole("alert")).toHaveLength(2), { timeout: 3000 });
    const total = screen.getByText("Total").closest("section")!;
    expect(within(total).getByText("—")).toBeInTheDocument();
    expect(within(total).queryByText("0")).not.toBeInTheDocument();
    expect(screen.queryByText("No log entries yet. Logs will appear once agent processes messages.")).not.toBeInTheDocument();
    failing = false;
    for (const button of screen.getAllByRole("button")) fireEvent.click(button);
    await waitFor(() => expect(within(total).getByText("3")).toBeInTheDocument());
    expect(await screen.findByText("demo.conversation.completed")).toBeInTheDocument();
  });
});
