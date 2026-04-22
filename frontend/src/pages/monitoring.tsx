import { useQuery } from "@tanstack/react-query";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useI18n } from "../i18n";
import { api, cssVar } from "../lib/api";
import { formatMetricValue } from "../lib/metric-values";
import { metricsQueryDefaults } from "../lib/query-defaults";

type Latency = {
  daily: Array<{ date: string; avg: number; p50: number; p95: number }>;
};

type Tokens = {
  daily: Array<{ date: string; tokens_in: number; tokens_out: number }>;
};

type Cost = {
  daily: Array<{ date: string; cost_usd: number }>;
  total_cost_usd: number;
  avg_cost_usd_per_request: number;
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
    ...metricsQueryDefaults,
    queryKey: ["metrics", "latency", "30d"],
    queryFn: () => api.get<Latency>("/api/metrics/latency?period=30d"),
  });
  const tokens = useQuery({
    ...metricsQueryDefaults,
    queryKey: ["metrics", "tokens", "30d"],
    queryFn: () => api.get<Tokens>("/api/metrics/tokens?period=30d"),
  });
  const cost = useQuery({
    ...metricsQueryDefaults,
    queryKey: ["metrics", "cost", "30d"],
    queryFn: () => api.get<Cost>("/api/metrics/cost?period=30d"),
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
  const costRows = (cost.data?.daily ?? []).map((item) => ({
    ...item,
    label: formatDateTime(item.date, { month: "numeric", day: "numeric" }),
  }));
  const metricsLoading = latency.isPending || tokens.isPending || cost.isPending;
  const metricsError = latency.isError || tokens.isError || cost.isError;
  const last7Cost = costRows.slice(-7).reduce((acc, item) => acc + item.cost_usd, 0);

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
          <strong>{formatMetricValue(latestLatencyRow?.avg, formatNumber, undefined, "ms")}</strong>
        </section>
        <section className="metric-card">
          <span>{t("monitoring.p95")}</span>
          <strong>{formatMetricValue(latestLatencyRow?.p95, formatNumber, undefined, "ms")}</strong>
        </section>
        <section className="metric-card">
          <span>{t("monitoring.totalTokens")}</span>
          <strong>{tokens.data ? formatNumber(last7Tokens) : "—"}</strong>
        </section>
        <section className="metric-card">
          <span>{t("monitoring.totalCost")}</span>
          <strong>{cost.data ? formatNumber(last7Cost, { style: "currency", currency: "USD" }) : "—"}</strong>
        </section>
      </div>

      <div className="grid monitoring-grid">
        <section className="surface-panel chart-panel chart-panel-tall">
          <div className="surface-panel-header">
            <div>
              <p className="surface-panel-label">{t("monitoring.latencyTrend30d")}</p>
              <h3 className="surface-panel-title">{t("monitoring.avg")} / {t("monitoring.p95")}</h3>
            </div>
          </div>
          {latency.isError ? (
            <div className="empty-state">{t("common.dataUnavailable")}</div>
          ) : latency.isPending ? (
            <p className="surface-panel-note">{t("common.dataLoading")}</p>
          ) : latencyRows.length === 0 ? (
            <div className="empty-state">{t("common.noData")}</div>
          ) : (
            <ResponsiveContainer width="100%" height="88%">
              <LineChart data={latencyRows}>
                <XAxis dataKey="label" {...chartTheme.axisProps} />
                <YAxis {...chartTheme.axisProps} />
                <Tooltip {...chartTheme.tooltipProps} />
                <Line type="monotone" dataKey="avg" name={t("monitoring.avg")} stroke={chartTheme.line1} strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="p95" name={t("monitoring.p95")} stroke={chartTheme.line2} strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </section>

        <section className="surface-panel chart-panel">
          <div className="surface-panel-header">
            <div>
              <p className="surface-panel-label">{t("monitoring.tokenTrend30d")}</p>
              <h3 className="surface-panel-title">{t("monitoring.tokensIn")} / {t("monitoring.tokensOut")}</h3>
            </div>
          </div>
          {tokens.isError ? (
            <div className="empty-state">{t("common.dataUnavailable")}</div>
          ) : tokens.isPending ? (
            <p className="surface-panel-note">{t("common.dataLoading")}</p>
          ) : tokenRows.length === 0 ? (
            <div className="empty-state">{t("common.noData")}</div>
          ) : (
            <ResponsiveContainer width="100%" height="88%">
              <LineChart data={tokenRows}>
                <XAxis dataKey="label" {...chartTheme.axisProps} />
                <YAxis {...chartTheme.axisProps} />
                <Tooltip {...chartTheme.tooltipProps} />
                <Line type="monotone" dataKey="tokens_in" name={t("monitoring.tokensIn")} stroke={chartTheme.line1} strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="tokens_out" name={t("monitoring.tokensOut")} stroke={chartTheme.line2} strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </section>

        <section className="surface-panel chart-panel">
          <div className="surface-panel-header">
            <div>
              <p className="surface-panel-label">{t("monitoring.costTrend30d")}</p>
              <h3 className="surface-panel-title">{t("monitoring.costUsd")}</h3>
            </div>
          </div>
          {cost.isError ? (
            <div className="empty-state">{t("common.dataUnavailable")}</div>
          ) : cost.isPending ? (
            <p className="surface-panel-note">{t("common.dataLoading")}</p>
          ) : costRows.length === 0 ? (
            <div className="empty-state">{t("common.noData")}</div>
          ) : (
            <ResponsiveContainer width="100%" height="88%">
              <LineChart data={costRows}>
                <XAxis dataKey="label" {...chartTheme.axisProps} />
                <YAxis {...chartTheme.axisProps} />
                <Tooltip {...chartTheme.tooltipProps} />
                <Line type="monotone" dataKey="cost_usd" name={t("monitoring.costUsd")} stroke={chartTheme.line1} strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </section>

        <section className="surface-panel chart-panel">
          <div className="surface-panel-header">
            <div>
              <p className="surface-panel-label">{t("monitoring.tokenVolumeTrend30d")}</p>
              <h3 className="surface-panel-title">{t("monitoring.totalTokens")}</h3>
            </div>
          </div>
          {tokens.isError ? (
            <div className="empty-state">{t("common.dataUnavailable")}</div>
          ) : tokens.isPending ? (
            <p className="surface-panel-note">{t("common.dataLoading")}</p>
          ) : tokenRows.length === 0 ? (
            <div className="empty-state">{t("common.noData")}</div>
          ) : (
            <ResponsiveContainer width="100%" height="88%">
              <LineChart data={tokenRows}>
                <XAxis dataKey="label" {...chartTheme.axisProps} />
                <YAxis {...chartTheme.axisProps} />
                <Tooltip {...chartTheme.tooltipProps} />
                <Line type="monotone" dataKey="total_tokens" name={t("monitoring.totalTokens")} stroke={chartTheme.line1} strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </section>

        <section className="surface-panel">
          <div className="surface-panel-header">
            <div>
              <p className="surface-panel-label">{t("monitoring.history")}</p>
              <h3 className="surface-panel-title">{t("monitoring.delta")}</h3>
            </div>
          </div>
          {metricsError ? (
            <div className="empty-state">{t("common.dataUnavailable")}</div>
          ) : metricsLoading ? (
            <p className="surface-panel-note">{t("common.dataLoading")}</p>
          ) : tokenRows.length === 0 ? (
            <div className="empty-state">{t("common.noData")}</div>
          ) : (
            <>
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
              <p className="surface-panel-note">
                {t("monitoring.avgCost")}: {cost.data ? formatNumber(cost.data.avg_cost_usd_per_request, { style: "currency", currency: "USD" }) : "—"}
              </p>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
