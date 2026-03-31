import { useQuery } from "@tanstack/react-query";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useI18n } from "../i18n";
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
  const { t, formatDateTime, formatNumber } = useI18n();
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
  const latencyRows = (latency.data?.daily ?? []).map((item) => ({
    ...item,
    label: formatDateTime(item.date, { month: "numeric", day: "numeric" }),
  }));
  const tokenRows = (tokens.data?.daily ?? []).map((item) => ({
    ...item,
    label: formatDateTime(item.date, { month: "numeric", day: "numeric" }),
  }));
  const costRows = (cost.data?.daily ?? []).map((item) => ({
    ...item,
    label: formatDateTime(item.date, { month: "numeric", day: "numeric" }),
  }));
  const formatCurrency = (value: number) =>
    formatNumber(value, {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 4,
      maximumFractionDigits: 4,
    });

  return (
    <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
      <section className="card" style={{ height: 320, gridColumn: "1 / -1" }}>
        <h3>{t("monitoring.latencyTrend30d")}</h3>
        <ResponsiveContainer width="100%" height="85%">
          <LineChart data={latencyRows}>
            <XAxis dataKey="label" {...ct.axisProps} />
            <YAxis {...ct.axisProps} />
            <Tooltip {...ct.tooltipProps} />
            <Line type="monotone" dataKey="avg" name={t("monitoring.avg")} stroke={ct.line1} strokeWidth={1.5} dot={false} />
            <Line type="monotone" dataKey="p95" name={t("monitoring.p95")} stroke={ct.line2} strokeWidth={1.5} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </section>
      <section className="card" style={{ height: 300 }}>
        <h3>{t("monitoring.tokenTrend30d")}</h3>
        <ResponsiveContainer width="100%" height="85%">
          <LineChart data={tokenRows}>
            <XAxis dataKey="label" {...ct.axisProps} />
            <YAxis {...ct.axisProps} />
            <Tooltip {...ct.tooltipProps} />
            <Line type="monotone" dataKey="tokens_in" name={t("monitoring.tokensIn")} stroke={ct.line1} strokeWidth={1.5} dot={false} />
            <Line type="monotone" dataKey="tokens_out" name={t("monitoring.tokensOut")} stroke={ct.line2} strokeWidth={1.5} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </section>
      <section className="card" style={{ height: 300 }}>
        <h3>{t("monitoring.costTrend30d")}</h3>
        <ResponsiveContainer width="100%" height="85%">
          <LineChart data={costRows}>
            <XAxis dataKey="label" {...ct.axisProps} />
            <YAxis {...ct.axisProps} />
            <Tooltip {...ct.tooltipProps} />
            <Line type="monotone" dataKey="cost" name={t("monitoring.cost")} stroke={ct.line1} strokeWidth={1.5} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </section>
      <section className="card" style={{ gridColumn: "1 / -1" }}>
        <h3>{t("monitoring.history")}</h3>
        <p className="mono" style={{ margin: 0, color: "var(--text-muted)" }}>
          {t("monitoring.last7d")}: {formatCurrency(last7Cost)}
          {" / "}{t("monitoring.prev7d")}: {formatCurrency(prev7Cost)}
          {" / "}{t("monitoring.delta")}:{" "}
          <span style={{ color: costDeltaPct > 0 ? "var(--danger)" : "var(--success)" }}>
            {costDeltaPct >= 0 ? "+" : ""}{formatNumber(costDeltaPct, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%
          </span>
        </p>
      </section>
    </div>
  );
}
