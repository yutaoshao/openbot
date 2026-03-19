import { useQuery } from "@tanstack/react-query";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api } from "../lib/api";

type Latency = {
  daily: Array<{ date: string; avg: number; p50: number; p95: number }>;
};

type Tokens = {
  daily: Array<{ date: string; tokens_in: number; tokens_out: number }>;
};

type Cost = {
  daily: Array<{ date: string; cost: number }>;
};

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

  return (
    <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
      <section className="card" style={{ height: 320, gridColumn: "1 / -1" }}>
        <h3>Latency Trend (30d)</h3>
        <ResponsiveContainer width="100%" height="90%">
          <LineChart data={latency.data?.daily ?? []}>
            <XAxis dataKey="date" />
            <YAxis />
            <Tooltip />
            <Line type="monotone" dataKey="avg" stroke="#0f5be0" dot={false} />
            <Line type="monotone" dataKey="p95" stroke="#d44747" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </section>
      <section className="card" style={{ height: 320 }}>
        <h3>Token Trend (30d)</h3>
        <ResponsiveContainer width="100%" height="90%">
          <LineChart data={tokens.data?.daily ?? []}>
            <XAxis dataKey="date" />
            <YAxis />
            <Tooltip />
            <Line type="monotone" dataKey="tokens_in" stroke="#0f5be0" dot={false} />
            <Line type="monotone" dataKey="tokens_out" stroke="#1f8b4c" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </section>
      <section className="card" style={{ height: 320 }}>
        <h3>Cost Trend (30d)</h3>
        <ResponsiveContainer width="100%" height="90%">
          <LineChart data={cost.data?.daily ?? []}>
            <XAxis dataKey="date" />
            <YAxis />
            <Tooltip />
            <Line type="monotone" dataKey="cost" stroke="#d44747" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </section>
      <section className="card" style={{ gridColumn: "1 / -1" }}>
        <h3>Historical Comparison</h3>
        <p className="mono">
          Last 7d cost: ${last7Cost.toFixed(4)} · Previous 7d: ${prev7Cost.toFixed(4)} · Delta: {costDeltaPct.toFixed(1)}%
        </p>
      </section>
    </div>
  );
}
