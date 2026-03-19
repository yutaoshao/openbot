import { useQuery } from "@tanstack/react-query";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { api } from "../lib/api";

type Overview = {
  total_requests: number;
  success_count: number;
  error_count: number;
  error_rate: number;
  success_rate?: number;
  avg_steps?: number;
  avg_turns?: number;
  llm_api_calls?: number;
};

type Latency = {
  avg_response_time: number;
  p50: number;
  p95: number;
  p99: number;
};

type Cost = {
  total_cost: number;
  per_request_cost?: number;
  monthly_budget?: number | null;
  budget_progress?: number | null;
};

type ToolStats = {
  tools: Array<{ tool: string; count: number; error_rate: number }>;
};

type Tokens = {
  daily: Array<{ date: string; tokens_in: number; tokens_out: number }>;
};

export function DashboardPage(): JSX.Element {
  const overview = useQuery({
    queryKey: ["metrics", "overview"],
    queryFn: () => api.get<Overview>("/api/metrics/overview?period=today"),
  });
  const latency = useQuery({
    queryKey: ["metrics", "latency"],
    queryFn: () => api.get<Latency>("/api/metrics/latency?period=7d"),
  });
  const cost = useQuery({
    queryKey: ["metrics", "cost"],
    queryFn: () => api.get<Cost>("/api/metrics/cost?period=30d"),
  });
  const tools = useQuery({
    queryKey: ["metrics", "tools"],
    queryFn: () => api.get<ToolStats>("/api/metrics/tools?period=7d"),
  });
  const tokens = useQuery({
    queryKey: ["metrics", "tokens"],
    queryFn: () => api.get<Tokens>("/api/metrics/tokens?period=7d"),
  });

  const successRate = overview.data?.success_rate ?? (1 - (overview.data?.error_rate ?? 0));
  const budget = cost.data?.monthly_budget ?? 1;
  const budgetUsed = Math.min(1, cost.data?.budget_progress ?? ((cost.data?.total_cost ?? 0) / budget));
  const pieData = [
    { name: "used", value: +(cost.data?.total_cost ?? 0).toFixed(4) },
    { name: "remaining", value: +Math.max(0, budget - (cost.data?.total_cost ?? 0)).toFixed(4) },
  ];

  return (
    <div className="grid">
      <section className="card">
        <h3>Total Requests (Today)</h3>
        <strong>{overview.data?.total_requests ?? 0}</strong>
      </section>
      <section className="card">
        <h3>Success Rate</h3>
        <strong>{(successRate * 100).toFixed(1)}%</strong>
      </section>
      <section className="card">
        <h3>Avg Response</h3>
        <strong>{latency.data?.avg_response_time ?? 0} ms</strong>
      </section>
      <section className="card">
        <h3>30d Cost</h3>
        <strong>${(cost.data?.total_cost ?? 0).toFixed(4)}</strong>
      </section>
      <section className="card" style={{ gridColumn: "1 / -1" }}>
        <h3>Latency Snapshot</h3>
        <p className="mono">
          avg: {latency.data?.avg_response_time ?? 0}ms · p50: {latency.data?.p50 ?? 0}ms · p95: {latency.data?.p95 ?? 0}ms · p99: {latency.data?.p99 ?? 0}ms
        </p>
        <p className="mono">
          avg steps: {(overview.data?.avg_steps ?? 0).toFixed(2)} · avg turns: {(overview.data?.avg_turns ?? 0).toFixed(2)} · llm calls: {overview.data?.llm_api_calls ?? 0}
        </p>
      </section>
      <section className="card" style={{ height: 260 }}>
        <h3>Budget Progress</h3>
        <div style={{ height: 140 }}>
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={pieData} dataKey="value" innerRadius={40} outerRadius={60}>
                <Cell fill="#0f5be0" />
                <Cell fill="#d7dfec" />
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <div
          style={{
            height: 10,
            borderRadius: 999,
            background: "var(--line)",
            overflow: "hidden",
            marginTop: 8,
          }}
        >
          <div style={{ width: `${(budgetUsed * 100).toFixed(1)}%`, height: "100%", background: "var(--brand)" }} />
        </div>
        <p className="mono" style={{ marginTop: 6 }}>
          ${(cost.data?.total_cost ?? 0).toFixed(4)} / ${budget.toFixed(2)}
        </p>
      </section>
      <section className="card" style={{ gridColumn: "1 / -1" }}>
        <h3>7d Token Usage</h3>
        <div style={{ display: "grid", gap: 4 }}>
          {(tokens.data?.daily ?? []).map((day) => (
            <div key={day.date} style={{ display: "grid", gridTemplateColumns: "100px 1fr 1fr", gap: 8 }}>
              <span className="mono">{day.date}</span>
              <span>in: {day.tokens_in}</span>
              <span>out: {day.tokens_out}</span>
            </div>
          ))}
        </div>
      </section>
      <section className="card" style={{ gridColumn: "1 / -1" }}>
        <h3>Tool Performance (7d)</h3>
        <table className="table">
          <thead>
            <tr>
              <th>Tool</th>
              <th>Calls</th>
              <th>Error Rate</th>
            </tr>
          </thead>
          <tbody>
            {(tools.data?.tools ?? []).map((row) => (
              <tr key={row.tool}>
                <td>{row.tool}</td>
                <td>{row.count}</td>
                <td>{(row.error_rate * 100).toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
        {overview.isLoading || latency.isLoading || cost.isLoading || tools.isLoading ? <p>Loading metrics...</p> : null}
      </section>
    </div>
  );
}
