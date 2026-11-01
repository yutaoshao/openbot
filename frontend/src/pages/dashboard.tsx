import { Link } from "react-router-dom";
import { ArrowUpRight } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { MetricCard, toolStatus } from "../components/dashboard-helpers";
import { LatencyChart, TokenCompositionChart } from "../components/statistics/DashboardCharts";
import { StatisticsPage } from "../components/statistics/shared";
import { useI18n } from "../i18n";
import { api } from "../lib/api";
import { pagePath } from "../lib/page-path";
import { formatMetricValue } from "../lib/metric-values";
import { metricsQueryDefaults } from "../lib/query-defaults";

type Overview = { total_requests: number; error_rate: number; success_rate?: number };
type Latency = {
  avg_response_time: number; p50: number; p95: number;
  daily: Array<{ date: string; avg: number; p50: number; p95: number }>;
};
type ToolStats = { tools: Array<{ tool: string; count: number; error_rate: number }> };
type Tokens = { daily: Array<{ date: string; tokens_in: number; tokens_out: number }> };
type Cost = { total_cost_usd: number };

export function DashboardPage(): JSX.Element {
  const { t, formatDateTime, formatNumber } = useI18n();
  const overview = useQuery({
    ...metricsQueryDefaults,
    queryKey: ["metrics", "overview"],
    queryFn: () => api.get<Overview>("/api/metrics/overview?period=today"),
  });
  const latency = useQuery({
    ...metricsQueryDefaults,
    queryKey: ["metrics", "latency", "7d"],
    queryFn: () => api.get<Latency>("/api/metrics/latency?period=7d"),
  });
  const tools = useQuery({
    ...metricsQueryDefaults,
    queryKey: ["metrics", "tools"],
    queryFn: () => api.get<ToolStats>("/api/metrics/tools?period=7d"),
  });
  const tokens = useQuery({
    ...metricsQueryDefaults,
    queryKey: ["metrics", "tokens", "30d"],
    queryFn: () => api.get<Tokens>("/api/metrics/tokens?period=30d"),
  });
  const dailyTokens = useQuery({
    ...metricsQueryDefaults,
    queryKey: ["metrics", "tokens", "7d"],
    queryFn: () => api.get<Tokens>("/api/metrics/tokens?period=7d"),
  });
  const cost = useQuery({
    ...metricsQueryDefaults,
    queryKey: ["metrics", "cost", "30d"],
    queryFn: () => api.get<Cost>("/api/metrics/cost?period=30d"),
  });

  const primaryLoading = overview.isPending || latency.isPending;
  const primaryError = overview.isError || latency.isError;
  const overviewData = overview.isError ? undefined : overview.data;
  const latencyData = latency.isError ? undefined : latency.data;
  const successRate = overviewData?.success_rate ?? (overviewData ? 1 - overviewData.error_rate : undefined);
  const systemHealthy = successRate != null && successRate >= 0.98;
  const noActivity = !primaryLoading && !primaryError && overviewData?.total_requests === 0;
  const totalTokensIn = (tokens.data?.daily ?? []).reduce((sum, day) => sum + day.tokens_in, 0);
  const totalTokensOut = (tokens.data?.daily ?? []).reduce((sum, day) => sum + day.tokens_out, 0);
  const totalCost = cost.data && !cost.isError ? formatNumber(cost.data.total_cost_usd, { style: "currency", currency: "USD" }) : "—";
  const stateLabel = primaryError ? "dashboard.metricsUnavailable"
    : primaryLoading ? "dashboard.loadingMetrics"
    : noActivity ? "dashboard.idleTitle"
    : systemHealthy ? "dashboard.systemNominal" : "dashboard.systemAttention";

  return <StatisticsPage><div className="dashboard-shell">
    <section className="page-header">
      <h1 className="page-title">{t("nav.dashboard")}</h1>
      <p className="page-subtitle">{t("statistics.overviewHint")}</p>
    </section>

    <div className="dashboard-top">
      <section className="statistics-statusbar">
        <div className="statistics-run-state" role="status" data-tone={primaryError || primaryLoading || noActivity ? "unknown" : systemHealthy ? "healthy" : "attention"}>
          <span className="statistics-run-dot" aria-hidden="true" /><span>{t(stateLabel)}</span>
        </div>
        <div className="statistics-run-actions">
          <Link to={pagePath("/monitoring")}>{t("dashboard.openMonitoring")}<ArrowUpRight size={13} /></Link>
          <Link to={pagePath("/logs")}>{t("dashboard.viewLogs")}<ArrowUpRight size={13} /></Link>
        </div>
      </section>
      <div className="dashboard-stat-grid">
        <MetricCard label={t("dashboard.requestsToday")} value={formatMetricValue(overviewData?.total_requests, formatNumber)} />
        <MetricCard label={t("dashboard.successRate")} value={formatMetricValue(noActivity || successRate == null ? undefined : successRate * 100, formatNumber, { maximumFractionDigits: 1 })}
          unit={!noActivity && successRate != null ? "%" : undefined} />
        <MetricCard label={t("dashboard.avgResponse")} value={formatMetricValue(noActivity ? undefined : latencyData?.avg_response_time, formatNumber)}
          unit={!noActivity && latencyData ? "ms" : undefined} />
        <MetricCard label={t("dashboard.activeTools")} value={tools.data && !tools.isError ? formatNumber(tools.data.tools.length) : "—"} />
      </div>
    </div>

    <section className="surface-panel statistics-latency-panel">
      <div className="surface-panel-header">
        <h2 className="surface-panel-title">{t("statistics.latencyTitle")}</h2>
        <span className="statistics-period">{t("statistics.period7d")}</span>
      </div>
      {latency.isError ? <div className="empty-state" role="alert">{t("common.dataUnavailable")}</div>
        : latency.isPending ? <p className="surface-panel-note" role="status">{t("common.dataLoading")}</p>
        : !latencyData?.daily.length ? <div className="empty-state">{t("common.noData")}</div>
        : <>
          <LatencyChart rows={latencyData.daily} />
          <div className="statistics-latency-summary">
            <span>{t("dashboard.latency.avg")}<strong>{formatMetricValue(latencyData.avg_response_time, formatNumber)} <small>ms</small></strong></span>
            <span>{t("dashboard.latency.p50")}<strong>{formatMetricValue(latencyData.p50, formatNumber)} <small>ms</small></strong></span>
            <span>{t("dashboard.latency.p95")}<strong>{formatMetricValue(latencyData.p95, formatNumber)} <small>ms</small></strong></span>
          </div>
        </>}
    </section>

    <section className="surface-panel budget-panel">
      <div className="surface-panel-header">
        <h2 className="surface-panel-title">{t("statistics.tokenTitle")}</h2>
        <span className="statistics-period">{t("statistics.period30d")}</span>
      </div>
      {tokens.isError ? <div className="empty-state" role="alert">{t("common.dataUnavailable")}</div>
        : tokens.isPending ? <p className="surface-panel-note" role="status">{t("common.dataLoading")}</p>
        : totalTokensIn + totalTokensOut === 0 ? <div className="empty-state">{t("common.noData")}</div>
        : <>
          <TokenCompositionChart input={totalTokensIn} output={totalTokensOut} />
          <p className="surface-panel-note statistics-cost-note"><span>{t("monitoring.totalCost")}</span><strong>{totalCost}</strong></p>
        </>}
    </section>

    <section className="surface-panel">
      <div className="surface-panel-header">
        <h2 className="surface-panel-title">{t("statistics.dailyUsage")}</h2>
        <span className="statistics-period">{t("statistics.period7d")}</span>
      </div>
      {dailyTokens.isError ? <div className="empty-state" role="alert">{t("common.dataUnavailable")}</div>
        : dailyTokens.isPending ? <p className="surface-panel-note" role="status">{t("common.dataLoading")}</p>
        : !dailyTokens.data?.daily.length ? <div className="empty-state">{t("common.noData")}</div>
        : <div className="token-summary-list">
          <div className="token-summary-row statistics-table-head"><span>{t("statistics.date")}</span><span>{t("statistics.input")}</span><span>{t("statistics.output")}</span></div>
          {dailyTokens.data.daily.map((day) => <div className="token-summary-row" key={day.date}>
            <span>{formatDateTime(day.date, { month: "numeric", day: "numeric" })}</span>
            <span>{formatNumber(day.tokens_in)}</span><span>{formatNumber(day.tokens_out)}</span>
          </div>)}
        </div>}
    </section>

    <section className="surface-panel">
      <div className="surface-panel-header">
        <h2 className="surface-panel-title">{t("statistics.toolsTitle")}</h2>
        <span className="statistics-period">{t("statistics.period7d")}</span>
      </div>
      <table className="table table-ops">
        <thead><tr><th>{t("dashboard.table.tool")}</th><th>{t("dashboard.table.calls")}</th><th>{t("dashboard.table.errorRate")}</th><th>{t("tools.status")}</th></tr></thead>
        <tbody>{tools.isError ? <tr><td colSpan={4}><div className="empty-state" role="alert">{t("common.dataUnavailable")}</div></td></tr>
          : tools.isPending ? <tr><td colSpan={4}><p className="surface-panel-note" role="status">{t("common.dataLoading")}</p></td></tr>
          : !tools.data?.tools.length ? <tr><td colSpan={4}><div className="empty-state">{t("common.noData")}</div></td></tr>
          : tools.data.tools.map((row) => {
            const status = toolStatus(row.error_rate);
            return <tr key={row.tool}>
              <td className="table-title-cell">{row.tool}</td><td>{formatNumber(row.count)}</td>
              <td>{formatNumber(row.error_rate * 100, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%</td>
              <td><span className={`status-badge ${status}`}>{t(status === "stable" ? "dashboard.statusStable" : "dashboard.statusDegraded")}</span></td>
            </tr>;
          })}</tbody>
      </table>
    </section>
  </div></StatisticsPage>;
}
