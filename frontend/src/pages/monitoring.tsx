import { useQuery } from "@tanstack/react-query";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { ChartLegend, StatisticValue, StatisticsPage, useStatisticsColors } from "../components/statistics/shared";
import { useI18n } from "../i18n";
import { api } from "../lib/api";
import { formatMetricValue, partitionWeeklyMetrics } from "../lib/metric-values";
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
  const colors = useStatisticsColors();
  return {
    axisProps: {
      stroke: colors.grid,
      tick: { fill: colors.muted, fontSize: 11 },
      tickLine: false as const,
    },
    tooltipProps: {
      contentStyle: {
        background: colors.surface,
        border: `1px solid ${colors.grid}`,
        borderRadius: 8,
        fontSize: 13,
        color: colors.text,
      },
      labelStyle: { color: colors.muted },
      itemStyle: { color: colors.text },
    },
    line1: colors.primary,
    line2: colors.secondary,
    grid: colors.grid,
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
  const metricWindowDate = new Date();
  const tokenWeeks = partitionWeeklyMetrics(tokenDaily, metricWindowDate);
  const last7Tokens = tokenWeeks.current
    .reduce((acc, item) => acc + item.tokens_in + item.tokens_out, 0);
  const prev7Tokens = tokenWeeks.previous
    .reduce((acc, item) => acc + item.tokens_in + item.tokens_out, 0);
  const tokenDeltaPct = prev7Tokens > 0 ? ((last7Tokens - prev7Tokens) / prev7Tokens) * 100 : null;
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
  const costWeeks = partitionWeeklyMetrics(costRows, metricWindowDate);
  const last7Cost = costWeeks.current.reduce((acc, item) => acc + item.cost_usd, 0);

  return (
    <StatisticsPage><div className="stack-layout statistics-monitoring">
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
          <StatisticValue unit="ms">{formatMetricValue(latency.isError ? undefined : latestLatencyRow?.avg, formatNumber)}</StatisticValue><small className="statistics-period">{t("statistics.latestDay")}</small>
        </section>
        <section className="metric-card">
          <span>{t("monitoring.p95")}</span>
          <StatisticValue unit="ms">{formatMetricValue(latency.isError ? undefined : latestLatencyRow?.p95, formatNumber)}</StatisticValue><small className="statistics-period">{t("statistics.latestDay")}</small>
        </section>
        <section className="metric-card">
          <span>{t("monitoring.totalTokens")}</span>
          <StatisticValue>{tokens.data?.daily.length && !tokens.isError ? formatNumber(last7Tokens) : "—"}</StatisticValue><small className="statistics-period" title={t("statistics.calendarHint")}>{t("statistics.calendar7d")}</small>
        </section>
        <section className="metric-card">
          <span>{t("monitoring.totalCost")}</span>
          <StatisticValue unit="USD">{cost.data?.daily.length && !cost.isError ? formatNumber(last7Cost, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—"}</StatisticValue><small className="statistics-period" title={t("statistics.calendarHint")}>{t("statistics.calendar7d")}</small>
        </section>
      </div>

      <div className="grid monitoring-grid">
        <section className="surface-panel chart-panel chart-panel-tall">
          <div className="surface-panel-header">
            <div>
              <p className="surface-panel-label">{t("monitoring.latencyTrend30d")}</p>
              <h3 className="surface-panel-title">{t("monitoring.avg")} / {t("monitoring.p95")}</h3>
            </div>
            <ChartLegend items={[{ label: t("monitoring.avg"), color: chartTheme.line1 }, { label: t("monitoring.p95"), color: chartTheme.line2, dashed: true }]} />
          </div>
          {latency.isError ? (
            <div className="empty-state">{t("common.dataUnavailable")}</div>
          ) : latency.isPending ? (
            <p className="surface-panel-note">{t("common.dataLoading")}</p>
          ) : latencyRows.length === 0 ? (
            <div className="empty-state">{t("common.noData")}</div>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={latencyRows} margin={{ top: 12, right: 8, bottom: 0, left: -12 }}>
                <CartesianGrid stroke={chartTheme.grid} strokeDasharray="3 5" vertical={false} />
                <XAxis dataKey="label" {...chartTheme.axisProps} minTickGap={28} axisLine={false} />
                <YAxis {...chartTheme.axisProps} axisLine={false} tickFormatter={(value: number) => formatNumber(value, { notation: "compact", maximumFractionDigits: value !== 0 && Math.abs(value) < 1 ? 3 : 1 })} />
                <Tooltip {...chartTheme.tooltipProps} />
                <Line isAnimationActive={false} type="monotone" dataKey="avg" name={t("monitoring.avg")} stroke={chartTheme.line1} strokeWidth={2} dot={false} />
                <Line isAnimationActive={false} type="monotone" dataKey="p95" name={t("monitoring.p95")} stroke={chartTheme.line2} strokeDasharray="5 4" strokeWidth={2} dot={false} />
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
            <ChartLegend items={[{ label: t("monitoring.tokensIn"), color: chartTheme.line1 }, { label: t("monitoring.tokensOut"), color: chartTheme.line2, dashed: true }]} />
          </div>
          {tokens.isError ? (
            <div className="empty-state">{t("common.dataUnavailable")}</div>
          ) : tokens.isPending ? (
            <p className="surface-panel-note">{t("common.dataLoading")}</p>
          ) : tokenRows.length === 0 ? (
            <div className="empty-state">{t("common.noData")}</div>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={tokenRows} margin={{ top: 12, right: 8, bottom: 0, left: -12 }}>
                <CartesianGrid stroke={chartTheme.grid} strokeDasharray="3 5" vertical={false} />
                <XAxis dataKey="label" {...chartTheme.axisProps} minTickGap={28} axisLine={false} />
                <YAxis {...chartTheme.axisProps} axisLine={false} tickFormatter={(value: number) => formatNumber(value, { notation: "compact", maximumFractionDigits: value !== 0 && Math.abs(value) < 1 ? 3 : 1 })} />
                <Tooltip {...chartTheme.tooltipProps} />
                <Line isAnimationActive={false} type="monotone" dataKey="tokens_in" name={t("monitoring.tokensIn")} stroke={chartTheme.line1} strokeWidth={2} dot={false} />
                <Line isAnimationActive={false} type="monotone" dataKey="tokens_out" name={t("monitoring.tokensOut")} stroke={chartTheme.line2} strokeDasharray="5 4" strokeWidth={2} dot={false} />
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
            <ChartLegend items={[{ label: "USD", color: chartTheme.line1 }]} />
          </div>
          {cost.isError ? (
            <div className="empty-state">{t("common.dataUnavailable")}</div>
          ) : cost.isPending ? (
            <p className="surface-panel-note">{t("common.dataLoading")}</p>
          ) : costRows.length === 0 ? (
            <div className="empty-state">{t("common.noData")}</div>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={costRows} margin={{ top: 12, right: 8, bottom: 0, left: -12 }}>
                <CartesianGrid stroke={chartTheme.grid} strokeDasharray="3 5" vertical={false} />
                <XAxis dataKey="label" {...chartTheme.axisProps} minTickGap={28} axisLine={false} />
                <YAxis {...chartTheme.axisProps} axisLine={false} tickFormatter={(value: number) => formatNumber(value, { notation: "compact", maximumFractionDigits: value !== 0 && Math.abs(value) < 1 ? 3 : 1 })} />
                <Tooltip {...chartTheme.tooltipProps} />
                <Line isAnimationActive={false} type="monotone" dataKey="cost_usd" name={t("monitoring.costUsd")} stroke={chartTheme.line1} strokeWidth={2} dot={false} />
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
            <ChartLegend items={[{ label: t("monitoring.totalTokens"), color: chartTheme.line1 }]} />
          </div>
          {tokens.isError ? (
            <div className="empty-state">{t("common.dataUnavailable")}</div>
          ) : tokens.isPending ? (
            <p className="surface-panel-note">{t("common.dataLoading")}</p>
          ) : tokenRows.length === 0 ? (
            <div className="empty-state">{t("common.noData")}</div>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={tokenRows} margin={{ top: 12, right: 8, bottom: 0, left: -12 }}>
                <CartesianGrid stroke={chartTheme.grid} strokeDasharray="3 5" vertical={false} />
                <XAxis dataKey="label" {...chartTheme.axisProps} minTickGap={28} axisLine={false} />
                <YAxis {...chartTheme.axisProps} axisLine={false} tickFormatter={(value: number) => formatNumber(value, { notation: "compact", maximumFractionDigits: value !== 0 && Math.abs(value) < 1 ? 3 : 1 })} />
                <Tooltip {...chartTheme.tooltipProps} />
                <Line isAnimationActive={false} type="monotone" dataKey="total_tokens" name={t("monitoring.totalTokens")} stroke={chartTheme.line1} strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </section>

        <section className="surface-panel statistics-comparison">
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
              <p className="surface-panel-note" title={t("statistics.calendarHint")}>
                {t("statistics.calendar7d")}: {formatNumber(last7Tokens)}
              </p>
              <p className="surface-panel-note">
                {t("statistics.previousCalendar7d")}: {formatNumber(prev7Tokens)}
              </p>
              <p className="surface-panel-note">
                {t("monitoring.delta")}:{" "}
                <span className="statistics-change">
                  {tokenDeltaPct == null ? t("statistics.noComparison") : `${tokenDeltaPct >= 0 ? "+" : ""}${formatNumber(tokenDeltaPct, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`}
                </span>
              </p>
              <p className="surface-panel-note">
                {t("monitoring.avgCost")}: {cost.data ? formatNumber(cost.data.avg_cost_usd_per_request, { style: "currency", currency: "USD" }) : "—"}
              </p>
            </>
          )}
        </section>
      </div>
    </div></StatisticsPage>
  );
}
