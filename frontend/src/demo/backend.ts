import type { Settings } from "../lib/settings-view";
import { updateCollection } from "./backend-collections";
import { createDemoFixtures, demoMetrics } from "./fixtures";
import { desktopSettingsRequest, resetDesktopSettings } from "./desktop-settings";

// This store belongs exclusively to the isolated Demo transport. Never persist it.
let state = createDemoFixtures();

export function resetDemoBackend(): void {
  state = createDemoFixtures();
  resetDesktopSettings();
}

/** Share completed/partially stopped Demo turns with the existing history pages. */
export function recordDemoTurn(
  conversationId: string | null,
  userText: string,
  assistantText: string,
): string {
  if (!userText.trim()) throw new Error("Demo 400：消息不能为空");
  const previous = conversationId
    ? state.conversations.find((item) => item.id === conversationId)
    : undefined;
  if (conversationId && !previous) throw new Error("Demo 404：会话不存在");
  const id = conversationId ?? `demo-${crypto.randomUUID()}`;
  const timestamp = new Date().toISOString();
  const messages = [
    ...(state.messages[id] ?? []),
    { id: `demo-${crypto.randomUUID()}`, role: "user", content: userText, created_at: timestamp },
    { id: `demo-${crypto.randomUUID()}`, role: "assistant", content: assistantText, created_at: timestamp },
  ];
  const conversation = {
    ...(previous ?? { id, title: userText.trim().slice(0, 30), platform: "web" }),
    summary: assistantText.slice(0, 100), updated_at: timestamp, message_count: messages.length,
  };
  state = {
    ...state,
    conversations: previous
      ? state.conversations.map((item) => item.id === id ? conversation : item)
      : [conversation, ...state.conversations],
    messages: { ...state.messages, [id]: messages },
  };
  return id;
}

function parseBody(init: RequestInit): Record<string, unknown> {
  if (init.body === undefined) return {};
  if (typeof init.body !== "string") throw new Error("Demo 400：仅接受 JSON 请求体");
  const value: unknown = JSON.parse(init.body);
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Demo 400：请求体必须是对象");
  return value as Record<string, unknown>;
}

function updateSettings(body: Record<string, unknown>): unknown {
  if (Object.keys(body).some((key) => !["telegram", "model"].includes(key))) throw new Error("Demo 400：不支持的设置字段");
  const telegram = (body.telegram ?? {}) as Partial<Settings["telegram"]>;
  const model = (body.model ?? {}) as Partial<Settings["model"]>;
  if (Object.keys(telegram).some((key) => !["enabled", "enable_streaming", "mode"].includes(key))
    || Object.keys(model).some((key) => key !== "max_retries")) throw new Error("Demo 400：不支持的设置字段");
  if (model.max_retries !== undefined && (!Number.isInteger(model.max_retries) || model.max_retries < 0 || model.max_retries > 10)) throw new Error("Demo 400：max_retries 必须介于 0 到 10");
  if (telegram.enabled !== undefined && typeof telegram.enabled !== "boolean") throw new Error("Demo 400：enabled 必须是布尔值");
  if (telegram.enable_streaming !== undefined && typeof telegram.enable_streaming !== "boolean") throw new Error("Demo 400：enable_streaming 必须是布尔值");
  if (telegram.mode !== undefined && !["polling", "webhook"].includes(telegram.mode)) throw new Error("Demo 400：未知 Telegram 模式");
  const settings = {
    ...state.settings, telegram: { ...state.settings.telegram, ...telegram },
    model: { ...state.settings.model, ...model }, restart_required: true,
    restart_reasons: Object.keys(body),
  };
  state = { ...state, settings };
  return { status: "updated", settings, runtime: settings.runtime, restart_required: true, restart_reasons: settings.restart_reasons };
}

function readLogs(path: string, params: URLSearchParams): unknown {
  const rows = state.logs.filter((row) => ["surface", "level", "platform", "trace_id", "interaction_id"].every((key) => {
    const value = params.get(key);
    return !value || row[key as keyof typeof row] === value;
  }));
  if (path === "/api/logs/stats") {
    const count = (key: "surface" | "level", value: string) => rows.filter((row) => row[key] === value).length;
    return { total: rows.length, by_surface: { cognitive: count("surface", "cognitive"), operational: count("surface", "operational"), contextual: count("surface", "contextual") }, by_level: { error: count("level", "error"), warning: count("level", "warning"), info: count("level", "info") } };
  }
  return rows.slice(0, Math.max(0, Number(params.get("limit") ?? 100)));
}

function dispatch(path: string, init: RequestInit): unknown {
  if (!path.startsWith("/api/") || path.includes("\\") || path.includes("#")) throw new Error("Demo 请求必须使用本地 /api/ 路径");
  const url = new URL(path, "https://demo.invalid");
  const route = url.pathname;
  const method = (init.method ?? "GET").toUpperCase();
  const body = parseBody(init);
  if (route.startsWith("/api/desktop/")) return desktopSettingsRequest(route, method, body);
  const idAfter = (prefix: string) => decodeURIComponent(route.slice(prefix.length));

  if (method === "GET" && route.startsWith("/api/metrics/")) return demoMetrics(idAfter("/api/metrics/"));
  if (method === "GET" && ["/api/logs", "/api/logs/stats"].includes(route)) return readLogs(route, url.searchParams);
  if (route === "/api/settings") {
    if (method === "GET") return state.settings;
    if (method === "PUT") return updateSettings(body);
  }
  if (route === "/api/settings/secrets" && method === "GET") return { secrets: [] };
  if (route === "/api/settings/apply" && method === "POST") {
    const settings = { ...state.settings, runtime: { ...state.settings.runtime, telegram: { ...state.settings.runtime.telegram, enabled: state.settings.telegram.enabled, mode: state.settings.telegram.mode, status: state.settings.telegram.enabled ? "ready" : "disabled" } }, restart_required: false, restart_reasons: [] };
    state = { ...state, settings };
    return { status: "restarting", restart_required: false, restart_reasons: [] };
  }
  if (route === "/api/tools" && method === "GET") return state.tools;
  if (route.startsWith("/api/tools/") && route.endsWith("/config") && method === "PUT") {
    const name = decodeURIComponent(route.slice("/api/tools/".length, -"/config".length));
    const tool = state.tools.find((item) => item.name === name);
    if (!tool) throw new Error("Demo 404：工具不存在");
    if (typeof body.enabled !== "boolean" || Object.keys(body).length !== 1) throw new Error("Demo 400：仅支持切换工具状态");
    const updated = { ...tool, enabled: body.enabled };
    state = { ...state, tools: state.tools.map((item) => item.name === name ? updated : item) };
    return updated;
  }
  if (route === "/api/personal-memory" && method === "GET") return { documents: Object.keys(state.profiles) };
  if (route.startsWith("/api/personal-memory/")) {
    const name = idAfter("/api/personal-memory/");
    const document = Object.prototype.hasOwnProperty.call(state.profiles, name) ? state.profiles[name] : undefined;
    if (!document) throw new Error("Demo 404：档案不存在");
    if (method === "GET") return document;
    if (method === "PUT") {
      if (body.revision !== document.revision) throw new Error("Demo 409：档案已修改，请重新加载");
      if (typeof body.content !== "string") throw new Error("Demo 400：档案内容必须是文本");
      const updated = { name, content: body.content, revision: `demo-${crypto.randomUUID()}` };
      state = { ...state, profiles: { ...state.profiles, [name]: updated } };
      return updated;
    }
  }
  if (route === "/api/conversations" && method === "GET") {
    const query = url.searchParams.get("q")?.toLowerCase() ?? "";
    return state.conversations.filter((item) => `${item.title} ${item.summary}`.toLowerCase().includes(query));
  }
  if (route.startsWith("/api/conversations/")) {
    const id = idAfter("/api/conversations/");
    const conversation = state.conversations.find((item) => item.id === id);
    if (!conversation) throw new Error("Demo 404：会话不存在");
    if (method === "GET") return { conversation, messages: state.messages[id] ?? [] };
    if (method === "DELETE") {
      const messages = Object.fromEntries(Object.entries(state.messages).filter(([key]) => key !== id));
      state = { ...state, conversations: state.conversations.filter((item) => item.id !== id), messages };
      return { status: "deleted" };
    }
  }
  const match = route.match(/^\/api\/(knowledge|schedules)(?:\/(.+))?$/);
  if (match) {
    const collection = match[1] as "knowledge" | "schedules";
    const id = match[2] ? decodeURIComponent(match[2]) : undefined;
    if (method === "GET" && (!id || (collection === "knowledge" && id === "search"))) {
      return state[collection].filter((item) => {
        const query = url.searchParams.get("q")?.toLowerCase() ?? "";
        return (!query || String(item.content ?? item.name).toLowerCase().includes(query))
          && ["category", "priority"].every((key) => !url.searchParams.has(key) || item[key] === url.searchParams.get(key));
      });
    }
    if (["POST", "PUT", "DELETE"].includes(method)) {
      const result = updateCollection(state, { collection, id, method, body });
      state = result.state;
      return result.result;
    }
  }
  throw new Error(`Demo 未实现请求：${method} ${route}`);
}

export async function demoRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (init.signal?.aborted) throw new DOMException("Demo request aborted", "AbortError");
  return structuredClone(dispatch(path, init)) as T;
}
