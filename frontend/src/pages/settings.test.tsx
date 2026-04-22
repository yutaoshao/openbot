import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LanguageProvider } from "../i18n";
import { SettingsPage } from "./settings";

function renderSettingsPage() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <LanguageProvider>
        <SettingsPage />
      </LanguageProvider>
    </QueryClientProvider>,
  );
}

function buildSettings(overrides: Record<string, unknown> = {}) {
  return {
    api: { local_only: true },
    telegram: {
      enabled: true,
      enable_streaming: false,
      mode: "polling",
      bot_token_env: "TELEGRAM_BOT_TOKEN",
    },
    feishu: {
      enabled: false,
      mode: "long_connection",
      app_id_env: "FEISHU_APP_ID",
      app_secret_env: "FEISHU_APP_SECRET",
      verification_token_env: "FEISHU_VERIFICATION_TOKEN",
      encrypt_key_env: "FEISHU_ENCRYPT_KEY",
    },
    wechat: {
      enabled: false,
      mode: "ilink_polling",
      state_path: "data/wechat/ilink_state.json",
      api_base_url: "https://ilinkai.weixin.qq.com",
      poll_interval: 2,
      max_backoff: 30,
    },
    embedding: { api_key_env: "DASHSCOPE_API_KEY" },
    reranker: { api_key_env: "SILICONFLOW_API_KEY" },
    runtime: {
      telegram: { enabled: true, mode: "polling", status: "ready", missing_env_vars: [] },
      feishu: { enabled: false, mode: "long_connection", status: "disabled", missing_env_vars: [] },
      wechat: { enabled: false, mode: "ilink_polling", status: "disabled", missing_env_vars: [] },
    },
    model: {
      max_retries: 3,
      primary: { model: "claude-test", api_key_env: "ANTHROPIC_API_KEY" },
      fallback: null,
    },
    restart_required: false,
    restart_reasons: [],
    ...overrides,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SettingsPage", () => {
  it("reveals actual secret values on demand", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/settings")) {
        return new Response(JSON.stringify(buildSettings()), { status: 200 });
      }
      if (url.endsWith("/api/settings/secrets")) {
        return new Response(
          JSON.stringify({
            secrets: [
              {
                env_name: "ANTHROPIC_API_KEY",
                value: "sk-local-secret",
                is_set: true,
              },
            ],
          }),
          { status: 200 },
        );
      }
      throw new Error(`Unhandled fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsPage();
    await screen.findByRole("heading", { name: "Settings" });

    await userEvent.click(screen.getByRole("button", { name: "Show actual values" }));

    expect(await screen.findByText("sk-local-secret")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/settings/secrets",
      expect.objectContaining({ headers: expect.any(Object) }),
    );
  });

  it("applies saved config by calling the restart endpoint", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/settings")) {
        return new Response(
          JSON.stringify(
            buildSettings({
              restart_required: true,
              restart_reasons: ["telegram"],
            }),
          ),
          { status: 200 },
        );
      }
      if (url.endsWith("/api/settings/apply")) {
        return new Response(
          JSON.stringify({
            status: "restarting",
            restart_required: true,
            restart_reasons: ["telegram"],
          }),
          { status: 200 },
        );
      }
      throw new Error(`Unhandled fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsPage();
    await screen.findByText("Restart Required");

    await userEvent.click(screen.getByRole("button", { name: "Apply saved config now" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings/apply",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({}),
        }),
      ),
    );
    expect(await screen.findByText("Restarting OpenBot...")).toBeInTheDocument();
  });
});
