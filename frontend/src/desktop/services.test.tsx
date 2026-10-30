import { useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LanguageProvider } from "../i18n";
import { demoRequest, resetDemoBackend } from "../demo/backend";
import { api } from "../lib/api";
import { DesktopServices } from "./DesktopServices";
import { DesktopImport } from "./DesktopImport";
import { WeChatLogin } from "./WeChatLogin";
import type { ServicesSnapshot } from "./service-types";

vi.mock("../lib/api", () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } }));
function Wrapper({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } }));
  return <QueryClientProvider client={client}><LanguageProvider>{children}</LanguageProvider></QueryClientProvider>;
}
let snapshot: ServicesSnapshot;
beforeEach(async () => {
  resetDemoBackend(); localStorage.setItem("openbot_language", "en-US");
  snapshot = await demoRequest<ServicesSnapshot>("/api/desktop/services");
  vi.mocked(api.get).mockResolvedValue(snapshot);
  vi.mocked(api.put).mockResolvedValue({ requires_restart: true });
  vi.mocked(api.del).mockResolvedValue({ status: "cancelled" });
});
afterEach(() => { cleanup(); vi.resetAllMocks(); localStorage.clear(); });

describe("service setup transactions", () => {
  it("keeps credentials private and preserves the draft when saving fails", async () => {
    vi.mocked(api.put).mockRejectedValue(new Error("409: still running"));
    render(<Wrapper><DesktopServices busy={false} /></Wrapper>);
    const key = await screen.findByLabelText("Telegram Bot Token");
    fireEvent.click(screen.getByText("Secrets", { selector: "summary" }));
    fireEvent.change(key, { target: { value: "synthetic-token" } });
    fireEvent.click(screen.getByRole("button", { name: "Save and restart service" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("409: still running");
    expect(key).toHaveValue("synthetic-token");
    expect(screen.getByLabelText("Primary model API Key")).toHaveValue("");
    expect(api.put).toHaveBeenCalledWith("/api/desktop/services", expect.objectContaining({ secrets: { "telegram.bot_token": "synthetic-token" }, clear_secrets: [] }));
  });

  it("clears a saved credential only with an explicit selection and blocks duplicate saves", async () => {
    render(<Wrapper><DesktopServices busy={false} /></Wrapper>);
    await screen.findByLabelText("Primary model API Key");
    fireEvent.click(screen.getByText("Secrets", { selector: "summary" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Clear Primary model API Key when saving" }));
    fireEvent.click(screen.getByRole("button", { name: "Save and restart service" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/api/desktop/services", expect.objectContaining({ secrets: {}, clear_secrets: ["model.primary"] })));
    expect(await screen.findByText(/Waiting for the local service to restart/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save and restart service" })).toBeDisabled();
  });
});

it("invalidates the import preview when the selected source changes", async () => {
  vi.mocked(api.post).mockResolvedValue({ preview_id: "synthetic-preview", source_dir: "/old", schema_version: 11,
    files: [{ path: "data/openbot.db", bytes: 1024 }], warnings: [], expires_at: Date.now() / 1000 + 600 });
  render(<Wrapper><DesktopImport /></Wrapper>);
  const source = screen.getByRole("textbox");
  const preview = screen.getByRole("button", { name: "Preview import" });
  fireEvent.change(source, { target: { value: "/old" } });
  expect(preview).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox")); fireEvent.click(preview);
  await screen.findByRole("button", { name: "Copy and restart" });
  fireEvent.change(source, { target: { value: "/different" } });
  expect(screen.queryByRole("button", { name: "Copy and restart" })).not.toBeInTheDocument();
  expect(api.post).toHaveBeenCalledTimes(1);
});

it("does not leave a QR login running after its component closes", async () => {
  vi.mocked(api.post).mockResolvedValue({ session_id: "synthetic-login", status: "wait", expires_in: 480 });
  vi.mocked(api.get).mockResolvedValue({ session_id: "synthetic-login", status: "wait" });
  const view = render(<Wrapper><WeChatLogin enabled={false} loggedIn={false} /></Wrapper>);
  fireEvent.click(screen.getByRole("button", { name: "Get login QR code" }));
  await screen.findByText("Waiting for scan");
  view.unmount();
  expect(api.del).toHaveBeenCalledWith("/api/desktop/wechat/login/synthetic-login");
});

it("reports confirmed login when confirmation wins a concurrent cancel", async () => {
  vi.mocked(api.post).mockResolvedValue({ session_id: "synthetic-login", status: "wait" });
  vi.mocked(api.get).mockResolvedValue({ session_id: "synthetic-login", status: "wait" });
  vi.mocked(api.del).mockResolvedValue({ session_id: "synthetic-login", status: "confirmed" });
  render(<Wrapper><WeChatLogin enabled={false} loggedIn={false} /></Wrapper>);
  fireEvent.click(screen.getByRole("button", { name: "Get login QR code" }));
  await screen.findByText("Waiting for scan");
  fireEvent.click(screen.getByRole("button", { name: "Cancel login" }));
  expect(await screen.findByText("Login information saved")).toBeInTheDocument();
  expect(screen.queryByText("Login cancelled")).not.toBeInTheDocument();
});

it("freezes a successful simulated import and reports that no files changed", async () => {
  vi.mocked(api.post).mockImplementation(async (url) => url.endsWith("/preview")
    ? { preview_id: "synthetic-preview", source_dir: "/old", schema_version: 11, files: [], warnings: [], expires_at: Date.now() / 1000 + 600 }
    : { status: "staged", requires_restart: false });
  render(<Wrapper><DesktopImport /></Wrapper>);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "/old" } });
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Preview import" }));
  await screen.findByRole("button", { name: "Copy and restart" });
  fireEvent.click(screen.getAllByRole("checkbox")[1]);
  fireEvent.click(screen.getByRole("button", { name: "Copy and restart" }));
  expect(await screen.findByText("Simulated copy ended; no local files were read or written.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Copy and restart" })).toBeDisabled();
  expect(api.post).toHaveBeenCalledTimes(2);
});
