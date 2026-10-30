import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Settings } from "../lib/settings-view";
import { demoRequest, recordDemoTurn, resetDemoBackend } from "./backend";

const write = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });

beforeEach(() => {
  resetDemoBackend();
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("Real network forbidden"); }));
});
afterEach(() => vi.unstubAllGlobals());

describe("isolated Demo backend", () => {
  it("serves every current management surface without real requests", async () => {
    const paths = ["/api/conversations", "/api/conversations/demo-design", "/api/personal-memory", "/api/personal-memory/topics/qinghe.md", "/api/knowledge", "/api/tools", "/api/schedules", "/api/settings", "/api/settings/secrets", "/api/logs", "/api/logs/stats", "/api/metrics/overview", "/api/metrics/latency?period=30d", "/api/metrics/tools", "/api/metrics/tokens", "/api/metrics/cost"];
    await Promise.all(paths.map((path) => demoRequest(path)));
    expect(fetch).not.toHaveBeenCalled();
  });

  it("rejects unknown routes, unsupported methods and external destinations", async () => {
    await expect(demoRequest("/api/real-production-route")).rejects.toThrow("Demo 未实现");
    await expect(demoRequest("/api/settings", { method: "DELETE" })).rejects.toThrow("Demo 未实现");
    await expect(demoRequest("https://example.com/api/settings")).rejects.toThrow("本地 /api/");
    await expect(demoRequest("//example.com/api/settings")).rejects.toThrow("本地 /api/");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("returns copies so a consumer cannot mutate stored fixture data", async () => {
    const settings = await demoRequest<Settings>("/api/settings");
    settings.model.primary.model = "changed outside backend";
    const next = await demoRequest<Settings>("/api/settings");
    expect(next.model.primary.model).toContain("演示模型");
  });

  it("supports schedule CRUD and resets only the synthetic store", async () => {
    const created = await demoRequest<{ id: string }>("/api/schedules", write("POST", { name: "合成提醒", prompt: "整理演示资料", cron: "0 8 * * *", status: "active" }));
    await demoRequest(`/api/schedules/${created.id}`, write("PUT", { status: "paused" }));
    let rows = await demoRequest<Array<{ id: string; status: string }>>("/api/schedules");
    expect(rows.find((item) => item.id === created.id)?.status).toBe("paused");
    await demoRequest(`/api/schedules/${created.id}`, { method: "DELETE" });
    rows = await demoRequest("/api/schedules");
    expect(rows.some((item) => item.id === created.id)).toBe(false);
    resetDemoBackend();
    expect(await demoRequest("/api/schedules")).toHaveLength(2);
  });

  it("filters knowledge, updates it and deletes it without persistence", async () => {
    const created = await demoRequest<{ id: string }>("/api/knowledge", write("POST", { category: "fact", content: "演示活动的场地已确认", priority: "P2" }));
    await demoRequest(`/api/knowledge/${created.id}`, write("PUT", { content: "演示活动的场地待确认", priority: "P1" }));
    const found = await demoRequest<Array<{ id: string }>>("/api/knowledge/search?q=" + encodeURIComponent("场地待确认"));
    expect(found.map((item) => item.id)).toEqual([created.id]);
    expect(await demoRequest("/api/knowledge?category=preference")).toHaveLength(1);
    await demoRequest(`/api/knowledge/${created.id}`, { method: "DELETE" });
    expect(await demoRequest("/api/knowledge/search?q=" + encodeURIComponent("场地待确认"))).toEqual([]);
  });

  it("preserves Markdown version conflicts rather than silently overwriting", async () => {
    const before = await demoRequest<{ revision: string }>("/api/personal-memory/topics/qinghe.md");
    const updated = await demoRequest<{ revision: string; content: string }>("/api/personal-memory/topics/qinghe.md", write("PUT", { revision: before.revision, content: "# 合成修改" }));
    expect(updated.revision).not.toBe(before.revision);
    await expect(demoRequest("/api/personal-memory/topics/qinghe.md", write("PUT", { revision: before.revision, content: "stale" }))).rejects.toThrow("409");
    expect((await demoRequest<{ content: string }>("/api/personal-memory/topics/qinghe.md")).content).toBe("# 合成修改");
  });

  it("simulates save and apply while refusing secret writes", async () => {
    await demoRequest("/api/settings", write("PUT", { telegram: { enabled: true }, model: { max_retries: 5 } }));
    const saved = await demoRequest<Settings>("/api/settings");
    expect(saved.telegram.enabled).toBe(true);
    expect(saved.runtime.telegram.enabled).toBe(false);
    expect(saved.restart_required).toBe(true);
    await demoRequest("/api/settings/apply", write("POST", {}));
    const applied = await demoRequest<Settings>("/api/settings");
    expect(applied.runtime.telegram.enabled).toBe(true);
    expect(applied.restart_required).toBe(false);
    await expect(demoRequest("/api/settings", write("PUT", { model: { api_key: "must-not-store" } }))).rejects.toThrow("不支持");
    expect(await demoRequest("/api/settings/secrets")).toEqual({ secrets: [] });
  });

  it("supports logs and conversation filtering and deletion", async () => {
    expect(await demoRequest("/api/logs?platform=telegram&level=warning")).toHaveLength(1);
    expect(await demoRequest("/api/logs/stats?platform=telegram")).toMatchObject({ total: 1, by_level: { warning: 1 } });
    expect(await demoRequest("/api/conversations?q=" + encodeURIComponent("周报"))).toHaveLength(1);
    await demoRequest("/api/conversations/demo-weekly", { method: "DELETE" });
    await expect(demoRequest("/api/conversations/demo-weekly")).rejects.toThrow("404");
    expect(await demoRequest("/api/conversations")).toHaveLength(2);
  });

  it("shares simulated chat turns with history and keeps known fixtures after reset", async () => {
    const newId = recordDemoTurn(null, "合成新会话", "演示回答");
    expect(await demoRequest(`/api/conversations/${newId}`)).toMatchObject({
      conversation: { title: "合成新会话", message_count: 2 },
      messages: [{ role: "user", content: "合成新会话" }, { role: "assistant", content: "演示回答" }],
    });
    recordDemoTurn("demo-weekly", "继续整理", "部分输出（已停止）");
    expect(await demoRequest("/api/conversations/demo-weekly")).toMatchObject({ conversation: { message_count: 4 } });
    expect(() => recordDemoTurn("missing", "不会串会话", "未执行")).toThrow("404");
    resetDemoBackend();
    expect(await demoRequest("/api/conversations/demo-weekly")).toMatchObject({ conversation: { message_count: 2 } });
    await expect(demoRequest(`/api/conversations/${newId}`)).rejects.toThrow("404");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("cancels already aborted requests and rejects invalid payloads", async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(demoRequest("/api/settings", { signal: controller.signal })).rejects.toThrow("aborted");
    await expect(demoRequest("/api/schedules", write("POST", { name: "Incomplete" }))).rejects.toThrow("400");
    await expect(demoRequest("/api/settings", write("PUT", { model: { max_retries: -1 } }))).rejects.toThrow("400");
    expect(fetch).not.toHaveBeenCalled();
  });
});
