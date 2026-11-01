import type { Settings } from "../lib/settings-view";

export type DemoEntity = Record<string, unknown> & { id: string };
export type DemoProfile = { name: string; content: string; revision: string };

export function createDemoFixtures() {
  const now = "2026-10-29T09:30:00Z";
  const channel = (enabled: boolean, mode: string) => ({
    enabled, mode, status: enabled ? "ready" : "disabled", missing_env_vars: [],
  });
  const settings: Settings = {
    api: { local_only: true },
    telegram: { enabled: false, enable_streaming: true, mode: "polling", bot_token_env: "DEMO_TELEGRAM_TOKEN" },
    feishu: { enabled: false, mode: "long_connection", app_id_env: "DEMO_FEISHU_ID", app_secret_env: "DEMO_FEISHU_SECRET", verification_token_env: "DEMO_FEISHU_VERIFY", encrypt_key_env: "DEMO_FEISHU_ENCRYPT" },
    wechat: { enabled: false, mode: "ilink", state_path: "demo/wechat.json", api_base_url: "https://example.invalid", poll_interval: 3, max_backoff: 60 },
    embedding: { api_key_env: "DEMO_EMBEDDING_KEY" },
    reranker: { api_key_env: "DEMO_RERANKER_KEY" },
    runtime: { telegram: channel(false, "polling"), feishu: channel(false, "long_connection"), wechat: channel(false, "ilink") },
    model: { max_retries: 3, primary: { model: "演示模型 · 无网络调用", api_key_env: "DEMO_MODEL_KEY" }, fallback: null },
    restart_required: false, restart_reasons: [],
  };
  const conversations: DemoEntity[] = [
    { id: "demo-design", title: "青禾设计周", summary: "整理活动介绍与准备事项。", platform: "web", updated_at: now, message_count: 4 },
    { id: "demo-weekly", title: "周报整理", summary: "将本周事项整理成简短周报。", platform: "web", updated_at: "2026-10-28T14:00:00Z", message_count: 2 },
    { id: "demo-notes", title: "阅读笔记", summary: "从笔记中提取下一步行动。", platform: "telegram", updated_at: "2026-10-27T08:00:00Z", message_count: 2 },
  ];
  const messages: Record<string, DemoEntity[]> = {
    "demo-design": [
      { id: "design-u1", role: "user", content: "帮我写一段青禾设计周的活动介绍，简洁一点。", created_at: now },
      { id: "design-a1", role: "assistant", content: "青禾设计周，和有想法的人一起，把日常重新设计。\n\n从一场分享、一件作品开始，发现更好的生活方式。", created_at: now },
      { id: "design-u2", role: "user", content: "再列出准备事项。", created_at: now },
      { id: "design-a2", role: "assistant", content: "| 事项 | 负责人 | 状态 |\n| --- | --- | --- |\n| 活动介绍 | 林禾 | 已完成 |\n| 场地确认 | 陈青 | 进行中 |\n| 参与者通知 | 周宁 | 待开始 |", created_at: now },
    ],
    "demo-weekly": [
      { id: "weekly-u1", role: "user", content: "把本周的事项整理为周报。", created_at: now },
      { id: "weekly-a1", role: "assistant", content: "本周完成活动介绍初稿和资料整理，场地确认正在推进。下一步确认参与名单并发送通知。", created_at: now },
    ],
    "demo-notes": [
      { id: "notes-u1", role: "user", content: "从阅读笔记中提取三个行动项。", created_at: now },
      { id: "notes-a1", role: "assistant", content: "1. 整理术语。\n2. 验证一个例子。\n3. 记录尚未解决的问题。", created_at: now },
    ],
  };
  const knowledge: DemoEntity[] = [
    { id: "knowledge-1", category: "fact", content: "青禾设计周计划包含作品分享与交流环节。", priority: "P1" },
    { id: "knowledge-2", category: "preference", content: "活动文案使用简短、清晰的中文。", priority: "P1" },
  ];
  const schedules: DemoEntity[] = [
    { id: "schedule-weekly", name: "每周整理", prompt: "汇总青禾设计周的准备进度。", cron: "0 17 * * 5", status: "active", next_run_at: "2026-10-30T09:00:00Z" },
    { id: "schedule-reading", name: "阅读提醒", prompt: "整理本周的阅读笔记。", cron: "0 9 * * 1", status: "paused", next_run_at: null },
  ];
  const tools = [
    { name: "file_manager", description: "读取工作目录内的文件（演示）", category: "file", enabled: true, config: {}, last_used: now },
    { name: "grep", description: "搜索文件内容（演示）", category: "file", enabled: true, config: {}, last_used: now },
    { name: "web_search", description: "搜索网页资料（演示）", category: "web", enabled: true, config: {}, last_used: now },
    { name: "bash", description: "本机命令执行，需明确授权（演示）", category: "system", enabled: false, config: {}, last_used: null },
    { name: "python", description: "Python 执行，需明确授权（演示）", category: "system", enabled: false, config: {}, last_used: null },
  ];
  const profiles: Record<string, DemoProfile> = {
    "index.md": { name: "index.md", content: "# 演示档案\n\n- [青禾设计周](topics/qinghe.md)\n\n本页仅含合成示例。", revision: "demo-index-1" },
    "topics/qinghe.md": { name: "topics/qinghe.md", content: "# 青禾设计周\n\n## 已确认事项\n\n活动包含作品分享与交流环节。\n\n## 待确认\n\n场地与参与者名单。", revision: "demo-qinghe-1" },
  };
  const logs = [
    { id: 1, timestamp: now, level: "info", event: "demo.conversation.completed", surface: "cognitive", trace_id: "demo-trace-01", interaction_id: "demo-interaction-01", platform: "web", iteration: 1, data: JSON.stringify({ message: "演示会话已完成，没有调用真实服务。" }) },
    { id: 2, timestamp: "2026-10-29T09:29:00Z", level: "info", event: "demo.memory.retrieved", surface: "contextual", trace_id: "demo-trace-01", interaction_id: "demo-interaction-01", platform: "web", iteration: 1, data: JSON.stringify({ documents: 2 }) },
    { id: 3, timestamp: "2026-10-29T09:28:00Z", level: "warning", event: "demo.channel.not_configured", surface: "operational", trace_id: "demo-trace-02", interaction_id: null, platform: "telegram", iteration: null, data: JSON.stringify({ message: "消息渠道尚未配置（模拟）。" }) },
  ];
  return { settings, conversations, messages, knowledge, schedules, tools, profiles, logs };
}

export type DemoFixtures = ReturnType<typeof createDemoFixtures>;

export function demoMetrics(name: string, period = "30d"): unknown {
  const variation = [0, 120, -80, 210, -120, 50, -180, 90, 160, -110, 40, -50, 70, -200];
  const today = new Date();
  const history = Array.from({ length: 14 }, (_, index) => ({
    date: new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - 13 + index)).toISOString().slice(0, 10),
    avg: 1100 + index * 31 + variation[index], p50: 900 + index * 21 + variation[index], p95: 1900 + index * 42 + variation[index] * 1.8,
    tokens_in: 1800 + index * 240 + variation[index] * 4, tokens_out: 520 + index * 80 + variation[index] * 2,
    cost_usd: Number((0.02 + index * 0.004 + variation[index] * 0.00001).toFixed(4)),
  }));
  const daily = period === "7d" ? history.slice(-7) : period === "today" ? history.slice(-1) : history;
  if (name === "overview") return { total_requests: 24, success_count: 23, error_count: 1, error_rate: 1 / 24, success_rate: 23 / 24, avg_steps: 2.1, avg_turns: 1.4, llm_api_calls: 36 };
  if (name === "latency") return { avg_response_time: 1300, p50: 1100, p95: 2300, p99: 2800, daily };
  if (name === "tokens") return { daily };
  if (name === "cost") return { daily, total_cost_usd: Number(daily.reduce((sum, day) => sum + day.cost_usd, 0).toFixed(4)), avg_cost_usd_per_request: 0.0268 };
  if (name === "tools") return { tools: [{ tool: "file_manager", count: 12, error_rate: 0 }, { tool: "grep", count: 8, error_rate: 0 }, { tool: "web_search", count: 4, error_rate: 0 }] };
  throw new Error(`Demo 未实现指标：${name}`);
}
