import type { DemoEntity, DemoFixtures } from "./fixtures";

type Collection = "knowledge" | "schedules";
type Body = Record<string, unknown>;

function requireStrings(body: Body, keys: string[]): void {
  for (const key of keys) {
    if (typeof body[key] !== "string" || !String(body[key]).trim()) {
      throw new Error(`Demo 400：${key} 必须是非空文本`);
    }
  }
}

/** These simulated mutations replace fixture values; no production persistence is used. */
export function updateCollection(
  state: DemoFixtures,
  request: { collection: Collection; id?: string; method: string; body: Body },
): { state: DemoFixtures; result: unknown } {
  const { collection, id, method, body } = request;
  const rows = state[collection];
  if (!id && method === "POST") {
    const keys = collection === "knowledge" ? ["category", "content", "priority"] : ["name", "prompt", "cron", "status"];
    requireStrings(body, keys);
    const fields = Object.fromEntries(keys.map((key) => [key, body[key]]));
    const item: DemoEntity = { ...fields, id: `demo-${crypto.randomUUID()}`, ...(collection === "schedules" ? { next_run_at: null } : {}) };
    return { state: { ...state, [collection]: [...rows, item] }, result: item };
  }
  const current = rows.find((row) => row.id === id);
  if (!current) throw new Error(`Demo 404：记录不存在 ${id ?? ""}`);
  if (method === "DELETE") {
    return { state: { ...state, [collection]: rows.filter((row) => row.id !== id) }, result: { status: "deleted" } };
  }
  if (method === "PUT") {
    const allowed = collection === "knowledge" ? ["category", "content", "priority"] : ["name", "prompt", "cron", "status"];
    const keys = Object.keys(body);
    if (!keys.length || keys.some((key) => !allowed.includes(key))) throw new Error("Demo 400：不支持的更新字段");
    requireStrings(body, keys);
    const item = { ...current, ...body };
    return { state: { ...state, [collection]: rows.map((row) => row.id === id ? item : row) }, result: item };
  }
  throw new Error(`Demo 未实现请求：${method} /api/${collection}/${id ?? ""}`);
}
