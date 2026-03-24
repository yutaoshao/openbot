import { useQuery } from "@tanstack/react-query";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api, cssVar } from "../lib/api";

type Latency = {
  daily: Array<{ date: string; avg: number; p50: number; p95: number }>;
};

type Tokens = {
  daily: Array<{ date: string; tokens_in: number; tokens_out: number }>;
};

type Cost = {
  daily: Array<{ date: string; cost: number }>;
};

function useChartTheme() {
  return {
    axisProps: {
      stroke: cssVar("--border"),
      tick: { fill: cssVar("--text-muted"), fontSize: 11 },
      tickLine: false as const,
    },
    tooltipProps: {
      contentStyle: {
        background: cssVar("--surface"),
        border: `1px solid ${cssVar("--border")}`,
        borderRadius: 6,
        fontSize: 13,
        color: cssVar("--text"),
      },
      labelStyle: { color: cssVar("--text-muted") },
      itemStyle: { color: cssVar("--text") },
    },
    line1: cssVar("--chart-1"),
    line2: cssVar("--chart-2"),
  };
}

export function MonitoringPage(): JSX.Element {
  const latency = useQuery({
    queryKey: ["metrics", "latency", "30d"],
    queryFn: () => api.get<Latency>("/api/metrics/latency?period=30d"),
  });
  const tokens = useQuery({
    queryKey: ["metrics", "tokens"],
    queryFn: () => api.get<Tokens>("/api/metrics/tokens?period=30d"),
  });
  const cost = useQuery({
    queryKey: ["metrics", "cost"],
    queryFn: () => api.get<Cost>("/api/metrics/cost?period=30d"),
  });

  const last7Cost = (cost.data?.daily ?? []).slice(-7).reduce((acc, item) => acc + item.cost, 0);
  const prev7Cost = (cost.data?.daily ?? []).slice(-14, -7).reduce((acc, item) => acc + item.cost, 0);
  const costDeltaPct = prev7Cost > 0 ? ((last7Cost - prev7Cost) / prev7Cost) * 100 : 0;

  const ct = useChartTheme();

  return (
    <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
      <section className="card" style={{ height: 320, gridColumn: "1 / -1" }}>
        <h3>Latency Trend (30d)</h3>
        <ResponsiveContainer width="100%" height="85%">
          <LineChart data={latency.data?.daily ?? []}>
            <XAxis dataKey="date" {...ct.axisProps} />
            <YAxis {...ct.axisProps} />
            <Tooltip {...ct.tooltipProps} />
            <Line type="monotone" dataKey="avg" stroke={ct.line1} strokeWidth={1.5} dot={false} />
            <Line type="monotone" dataKey="p95" stroke={ct.line2} strokeWidth={1.5} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </section>
      <section className="card" style={{ height: 300 }}>
        <h3>Token Trend (30d)</h3>
        <ResponsiveContainer width="100%" height="85%">
          <LineChart data={tokens.data?.daily ?? []}>
            <XAxis dataKey="date" {...ct.axisProps} />
            <YAxis {...ct.axisProps} />
            <Tooltip {...ct.tooltipProps} />
            <Line type="monotone" dataKey="tokens_in" stroke={ct.line1} strokeWidth={1.5} dot={false} />
            <Line type="monotone" dataKey="tokens_out" stroke={ct.line2} strokeWidth={1.5} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </section>
      <section className="card" style={{ height: 300 }}>
        <h3>Cost Trend (30d)</h3>
        <ResponsiveContainer width="100%" height="85%">
          <LineChart data={cost.data?.daily ?? []}>
            <XAxis dataKey="date" {...ct.axisProps} />
            <YAxis {...ct.axisProps} />
            <Tooltip {...ct.tooltipProps} />
            <Line type="monotone" dataKey="cost" stroke={ct.line1} strokeWidth={1.5} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </section>
      <section className="card" style={{ gridColumn: "1 / -1" }}>
        <h3>Historical Comparison</h3>
        <p className="mono" style={{ margin: 0, color: "var(--text-muted)" }}>
          Last 7d: ${last7Cost.toFixed(4)}
          {" / "}Prev 7d: ${prev7Cost.toFixed(4)}
          {" / "}Delta:{" "}
          <span style={{ color: costDeltaPct > 0 ? "var(--danger)" : "var(--success)" }}>
            {costDeltaPct >= 0 ? "+" : ""}{costDeltaPct.toFixed(1)}%
          </span>
        </p>
      </section>
    </div>
  );
}
