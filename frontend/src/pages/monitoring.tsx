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
        borderRadius: 18,
        fontSize: 13,
        color: cssVar("--text"),
      },
      labelStyle: { color: cssVar("--text-muted") },
      itemStyle: { color: cssVar("--text") },
    },
    line1: cssVar("--chart-accent"),
    line2: cssVar("--text-muted"),
  };
}

export function MonitoringPage(): JSX.Element {
  const { t, formatDateTime, formatNumber } = useI18n();
  const latency = useQuery({
    queryKey: ["metrics", "latency", "30d"],
    queryFn: () => api.get<Latency>("/api/metrics/latency?period=30d"),
  });
  const tokens = useQuery({
    queryKey: ["metrics", "tokens", "30d"],
    queryFn: () => api.get<Tokens>("/api/metrics/tokens?period=30d"),
  });

  const tokenDaily = tokens.data?.daily ?? [];
  const last7Tokens = tokenDaily
    .slice(-7)
    .reduce((acc, item) => acc + item.tokens_in + item.tokens_out, 0);
  const prev7Tokens = tokenDaily
    .slice(-14, -7)
    .reduce((acc, item) => acc + item.tokens_in + item.tokens_out, 0);
  const tokenDeltaPct = prev7Tokens > 0 ? ((last7Tokens - prev7Tokens) / prev7Tokens) * 100 : 0;
  const chartTheme = useChartTheme();
  const latencyRows = (latency.data?.daily ?? []).map((item) => ({
    ...item,
    label: formatDateTime(item.date, { month: "numeric", day: "numeric" }),
  }));
  const latestLatencyRow = latencyRows[latencyRows.length - 1];
  const tokenRows = (tokens.data?.daily ?? []).map((item) => ({
    ...item,
    total_tokens: item.tokens_in + item.tokens_out,
    label: formatDateTime(item.date, { month: "numeric", day: "numeric" }),
  }));

  return (
    <div className="stack-layout">
      <section className="page-header">
        <div>
          <p className="page-eyebrow">{t("nav.monitoring")}</p>
          <h1 className="page-title">{t("nav.monitoring")}</h1>
          <p className="page-subtitle">{t("monitoring.subtitle")}</p>
        </div>
      </section>

      <div className="stats-row">
        <section className="metric-card">
          <span>{t("monitoring.avg")}</span>
          <strong>{formatNumber(latestLatencyRow?.avg ?? 0)}ms</strong>
        </section>
        <section className="metric-card">
          <span>{t("monitoring.p95")}</span>
          <strong>{formatNumber(latestLatencyRow?.p95 ?? 0)}ms</strong>
        </section>
        <section className="metric-card">
          <span>{t("monitoring.totalTokens")}</span>
          <strong>{formatNumber(last7Tokens)}</strong>
        </section>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
        <section className="surface-panel chart-panel chart-panel-tall">
          <div className="surface-panel-header">
            <div>
              <p className="surface-panel-label">{t("monitoring.latencyTrend30d")}</p>
              <h3 className="surface-panel-title">{t("monitoring.avg")} / {t("monitoring.p95")}</h3>
            </div>
          </div>
          <ResponsiveContainer width="100%" height="88%">
            <LineChart data={latencyRows}>
              <XAxis dataKey="label" {...chartTheme.axisProps} />
              <YAxis {...chartTheme.axisProps} />
              <Tooltip {...chartTheme.tooltipProps} />
              <Line type="monotone" dataKey="avg" name={t("monitoring.avg")} stroke={chartTheme.line1} strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="p95" name={t("monitoring.p95")} stroke={chartTheme.line2} strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </section>

        <section className="surface-panel chart-panel">
          <div className="surface-panel-header">
            <div>
              <p className="surface-panel-label">{t("monitoring.tokenTrend30d")}</p>
              <h3 className="surface-panel-title">{t("monitoring.tokensIn")} / {t("monitoring.tokensOut")}</h3>
            </div>
          </div>
          <ResponsiveContainer width="100%" height="88%">
            <LineChart data={tokenRows}>
              <XAxis dataKey="label" {...chartTheme.axisProps} />
              <YAxis {...chartTheme.axisProps} />
              <Tooltip {...chartTheme.tooltipProps} />
              <Line type="monotone" dataKey="tokens_in" name={t("monitoring.tokensIn")} stroke={chartTheme.line1} strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="tokens_out" name={t("monitoring.tokensOut")} stroke={chartTheme.line2} strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </section>

        <section className="surface-panel chart-panel">
          <div className="surface-panel-header">
            <div>
              <p className="surface-panel-label">{t("monitoring.tokenVolumeTrend30d")}</p>
              <h3 className="surface-panel-title">{t("monitoring.totalTokens")}</h3>
            </div>
          </div>
          <ResponsiveContainer width="100%" height="88%">
            <LineChart data={tokenRows}>
              <XAxis dataKey="label" {...chartTheme.axisProps} />
              <YAxis {...chartTheme.axisProps} />
              <Tooltip {...chartTheme.tooltipProps} />
              <Line type="monotone" dataKey="total_tokens" name={t("monitoring.totalTokens")} stroke={chartTheme.line1} strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </section>

        <section className="surface-panel">
          <div className="surface-panel-header">
            <div>
              <p className="surface-panel-label">{t("monitoring.history")}</p>
              <h3 className="surface-panel-title">{t("monitoring.delta")}</h3>
            </div>
          </div>
          <p className="surface-panel-note">
            {t("monitoring.last7d")}: {formatNumber(last7Tokens)}
          </p>
          <p className="surface-panel-note">
            {t("monitoring.prev7d")}: {formatNumber(prev7Tokens)}
          </p>
          <p className="surface-panel-note">
            {t("monitoring.delta")}:{" "}
            <span style={{ color: tokenDeltaPct > 0 ? "var(--danger)" : "var(--success)" }}>
              {tokenDeltaPct >= 0 ? "+" : ""}{formatNumber(tokenDeltaPct, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%
            </span>
          </p>
        </section>
      </div>
    </div>
  );
}
