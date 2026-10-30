import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LanguageProvider } from "../i18n";
import { api } from "../lib/api";
import { DesktopSettings, DesktopSetupForm } from "./DesktopSettings";
import { ExecutionPermissions } from "./ExecutionPermissions";
import type { DesktopStatus } from "./types";

vi.mock("../lib/api", () => ({ api: { get: vi.fn(), post: vi.fn() } }));
const status: DesktopStatus = {
  configured: true, work_dir: "/chosen/work", data_dir: "/app/data", model: {
    provider: "openai_compatible", base_url: "http://127.0.0.1:9000/v1", model: "local-model", api_key_set: true,
  }, permissions: { bash: false, code_executor: false }, busy: false,
};
const invoke = vi.fn();
function Wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return <QueryClientProvider client={client}><LanguageProvider>{children}</LanguageProvider></QueryClientProvider>;
}
beforeEach(() => {
  localStorage.setItem("openbot_language", "en-US");
  Object.defineProperty(window, "__TAURI_INTERNALS__", { configurable: true, value: { invoke } });
  invoke.mockResolvedValue(false);
  vi.mocked(api.get).mockResolvedValue(status);
  vi.mocked(api.post).mockResolvedValue({ requires_restart: true });
});
afterEach(() => { cleanup(); localStorage.clear(); delete window.__TAURI_INTERNALS__; vi.clearAllMocks(); });

describe("desktop settings", () => {
  it("does not authorize execution until explicit confirmation", async () => {
    render(<Wrapper><ExecutionPermissions permissions={status.permissions} /></Wrapper>);
    fireEvent.click(screen.getAllByRole("checkbox")[0]);
    expect(api.post).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Not now" }));
    expect(api.post).not.toHaveBeenCalled();
    fireEvent.click(screen.getAllByRole("checkbox")[0]);
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Allow tool" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/desktop/permissions", {
      tool: "bash", authorized: true, acknowledgement: "current-user-permissions",
    }));
  });

  it("preserves saved keys and supports the existing Responses provider", async () => {
    render(<Wrapper><DesktopSetupForm status={status} /></Wrapper>);
    expect(screen.getByPlaceholderText("Saved; leave blank to keep it")).toHaveValue("");
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "openai_responses" } });
    invoke.mockResolvedValueOnce("/new/work");
    fireEvent.click(screen.getByRole("button", { name: "Choose folder" }));
    await waitFor(() => expect(screen.getByDisplayValue("/new/work")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Save and restart service" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/desktop/setup", {
      model: { provider: "openai_responses", base_url: "http://127.0.0.1:9000/v1", model: "local-model" }, work_dir: "/new/work",
    }));
    expect(await screen.findByRole("status")).toHaveTextContent("Waiting for the local service to restart");
  });

  it("keeps login startup off when the native change fails", async () => {
    render(<Wrapper><DesktopSettings /></Wrapper>);
    const login = await screen.findByRole("checkbox", { name: /Start OpenBot when you log in/ });
    await waitFor(() => expect(login).toBeEnabled());
    expect(login).not.toBeChecked();
    invoke.mockRejectedValueOnce(new Error("OS refused change"));
    fireEvent.click(login);
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be read or changed");
    expect(login).not.toBeChecked();
  });
});
