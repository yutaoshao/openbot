import { newModelEndpoint, type ServicesSnapshot } from "../desktop/service-types";
import type { DesktopStatus } from "../desktop/types";

function fixtures(): ServicesSnapshot {
  return {
    configuration: {
      model: { primary: { ...newModelEndpoint(), model: "demo-model" }, fallback: null, max_retries: 3, retry_base_delay: 1,
        routing: { enabled: false, default_tier: "complex", tiers: {}, rules: {
          simple_max_chars: 120, complex_min_chars: 600, tool_count_complex_threshold: 2, simple_keywords: ["翻译"], complex_keywords: ["实现"],
        } } },
      telegram: { enabled: false, mode: "polling", bot_token_env: "DEMO_TELEGRAM_TOKEN", webhook_url: null, webhook_secret: null, allowed_user_ids: [], stream_throttle: 0.5, enable_streaming: false },
      feishu: { enabled: false, mode: "long_connection", app_id_env: "DEMO_FEISHU_ID", app_secret_env: "DEMO_FEISHU_SECRET", verification_token_env: "DEMO_FEISHU_VERIFY", encrypt_key_env: "DEMO_FEISHU_ENCRYPT" },
      wechat: { enabled: false, mode: "ilink_polling", state_path: "/demo/OpenBot/data/wechat/ilink_state.json", api_base_url: "https://example.invalid", poll_interval: 2, max_backoff: 30 },
      embedding: { enabled: false, provider: "openai_compatible", model: "demo-embedding", base_url: null, api_key_env: "DEMO_EMBEDDING_KEY", dimensions: 1024 },
      reranker: { enabled: false, model: "demo-reranker", base_url: "https://example.invalid/v1", api_key_env: "DEMO_RERANKER_KEY", top_n: 5 },
    },
    secrets: [{ key: "model.primary", is_set: true }], wechat: { logged_in: false },
  };
}

let services = fixtures();
let status: DesktopStatus;
let previewId: string | null = null;
let login: { session_id: string; status: string; qr_image: string; expires_in: number } | null = null;
const demoQr = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAXIAAAFyAQAAAADAX2ykAAAC3UlEQVR4nO1bzW3rMAwmaQM5KkAH6CjOBp2pI70NolE6QADnGMAGH0hJTuoCsnx4fnbF7+DI4ncgTPBXCjKsgadVdADj50EL8jmMnwctyOcwfh60IJ/D+HnQgnwO49fwfTCilVULeLm3ABAeSXbZUJ9y0ApuxfyOBT0AX/XdDYAX90AAaFTE+9a/GFQp/z55qBuAP88gjyZYVX16Y31KQcXMOvnt7B3BjS10X+2AXT+2vHf9yfir7AuSddmfAcFj9N9X2PfMg3bKd8wh9Xa9votp3SPEbGYettanFFTMrNp/vVRSAI0+JDS/AXR/TowAI26pDxn/H9iXnxv+rEYekcPKfY/R9v3zoJ3xITQ/0h/F0OxiL8TXtAp72kJd96Y/GT8Pjs2tJlyxoBukHdaE28ScrDD7Hte+LKON2SyDudf6Oe2ZfQ/M92f1UB1YCcSJvQw5xH8Rz1ORtVP9i0GV9r/u1rIW0f5DXVnD9Q0BXC/V15hKsL3pT8bPg0NAltQbV0McQncvgdvy78HzL0tVJQk3VNJaX7kku4o7W/49rn1BV1I6a1UVT5JcnFpF61t/dODzwV4Srh74woiI6eiIpyY4dko71b8YVPN8gyX1hllGDNcc8m/oiW2+cVT78jMqTwWVZt20Z/n36PwREd/jJCul3jGcH6WbHJvqUwgqJVbNx2DaO0rDO50FOuYw+PApHe9V/3JQlXwOYZiZ8aJem67WwcvBw4b6lINWcOudX2F8awY9CZaBVYtdL757f5O9Ztip/mT8dfcnOXVK/Pk+TKWz5d+D90f91ASH/PtcCXTwYf3RL+BzHF09ELqvU+yJxaftfvuvsC94PAVbhiZJS2ePUlj/H30WQEuEGWrlu+/3J++n2Bp10/xqW31KQcXMOvnt7P6k/CL7jxvGjvcuVnbTFby96U/GzwLt/91ZUF78A8bPgxbkcxg/D1qQz2H8PGhBPofx86AFOVTO/wsTd6mEsJwoGAAAAABJRU5ErkJggg==";

export function resetDesktopSettings() {
  services = fixtures(); previewId = null; login = null;
  status = { configured: true, work_dir: "/demo/workspace", data_dir: "/demo/OpenBot", busy: false,
    model: { provider: "openai_compatible", model: "demo-model", base_url: "https://example.invalid/v1", api_key_set: true },
    permissions: { bash: false, code_executor: false } };
}
resetDesktopSettings();

/** Only synthetic settings are changed; no filesystem, native, or network capability is used. */
export function desktopSettingsRequest(route: string, method: string, body: Record<string, unknown>): unknown {
  if (route === "/api/desktop/status" && method === "GET") return new URLSearchParams(window.location.search).get("preview") === "import" ? { ...status, configured: false } : status;
  if (route === "/api/desktop/services") {
    if (method === "GET") return services;
    if (method === "PUT") {
      const configuration = body.configuration as ServicesSnapshot["configuration"];
      if (!configuration?.model || !configuration.wechat) throw new Error("Demo 400: invalid service configuration");
      const presence = Object.fromEntries(services.secrets.map((item) => [item.key, item.is_set]));
      for (const [key, value] of Object.entries((body.secrets ?? {}) as Record<string, string>)) if (value) presence[key] = true;
      for (const key of (body.clear_secrets ?? []) as string[]) presence[key] = false;
      services = { ...services, configuration, secrets: Object.entries(presence).map(([key, is_set]) => ({ key, is_set })) };
      return { status: "saved", requires_restart: false };
    }
  }
  if (route === "/api/desktop/setup" && method === "POST") {
    const model = body.model as DesktopStatus["model"];
    status = { ...status, work_dir: String(body.work_dir), model: { ...model, api_key_set: true } };
    return { status: "saved", requires_restart: false };
  }
  if (route === "/api/desktop/permissions" && method === "POST") {
    if (body.acknowledgement !== "current-user-permissions" || !["bash", "code_executor"].includes(String(body.tool))) throw new Error("Demo 400: explicit permission required");
    status = { ...status, permissions: { ...status.permissions, [String(body.tool)]: body.authorized === true } };
    return { authorized: body.authorized === true };
  }
  if (route === "/api/desktop/import/preview" && method === "POST") {
    if (body.acknowledgement !== "source-stopped") throw new Error("Demo 400: source acknowledgement required");
    previewId = crypto.randomUUID();
    return { preview_id: previewId, source_dir: String(body.source_dir), schema_version: 11,
      expires_at: Date.now() / 1000 + 600, warnings: ["仅演示：不会读取或复制任何文件。", "导入的渠道和定时任务保持关闭。"],
      files: [{ path: "config.yaml", bytes: 1024 }, { path: "data/openbot.db", bytes: 24576 }, { path: "data/personal_memory/profile.md", bytes: 320 }] };
  }
  if (route === "/api/desktop/import/confirm" && method === "POST") {
    if (body.preview_id !== previewId || body.acknowledgement !== "copy-and-pause") throw new Error("Demo 409: preview required");
    previewId = null;
    return { status: "staged", requires_restart: false };
  }
  if (route === "/api/desktop/wechat/login" && method === "POST") {
    login = { session_id: crypto.randomUUID(), status: "wait", qr_image: demoQr, expires_in: 480 };
    return login;
  }
  if (login && route === `/api/desktop/wechat/login/${login.session_id}`) {
    if (method === "GET") return login;
    if (method === "DELETE") { login = { ...login, status: "cancelled" }; return login; }
  }
  throw new Error(`Demo 未实现请求：${method} ${route}`);
}
