import { Link } from "react-router-dom";

import { useQuery } from "@tanstack/react-query";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { Icon, type IconName } from "../components/Icon";
import { MetricCard, toolStatus, tooltipStyle } from "../components/dashboard-helpers";
import { useI18n } from "../i18n";
import { api, cssVar } from "../lib/api";
import { formatMetricValue, formatPercentValue } from "../lib/metric-values";
import { metricsQueryDefaults } from "../lib/query-defaults";

type Overview = { total_requests: number; success_count: number; error_count: number; error_rate: number; success_rate?: number; avg_steps?: number; avg_turns?: number; llm_api_calls?: number };
type LatencySummary = { avg_response_time: number; p50: number; p95: number; p99: number };
type LatencyTrend = { daily: Array<{ date: string; avg: number; p50: number; p95: number }> };
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
    queryKey: ["metrics", "latency"],
    queryFn: () => api.get<LatencySummary>("/api/metrics/latency?period=7d"),
  });
  const latencyTrend = useQuery({
    ...metricsQueryDefaults,
    queryKey: ["metrics", "latency", "30d"],
    queryFn: () => api.get<LatencyTrend>("/api/metrics/latency?period=30d"),
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
  const cost = useQuery({
    ...metricsQueryDefaults,
    queryKey: ["metrics", "cost", "30d"],
    queryFn: () => api.get<Cost>("/api/metrics/cost?period=30d"),
  });

  const primaryLoading = overview.isPending || latency.isPending;
  const primaryError = overview.isError || latency.isError;
  const successRate =
    overview.data?.success_rate ??
    (overview.data ? 1 - overview.data.error_rate : undefined);
  const systemHealthy = successRate == null ? null : successRate >= 0.98;
  const latestTokenDays = (tokens.data?.daily ?? []).slice(-7);
  const totalTokensIn = (tokens.data?.daily ?? []).reduce((acc, item) => acc + item.tokens_in, 0);
  const totalTokensOut = (tokens.data?.daily ?? []).reduce((acc, item) => acc + item.tokens_out, 0);
  const totalTokens = totalTokensIn + totalTokensOut;
  const latencyRows = (latencyTrend.data?.daily ?? []).slice(-14);
  const maxLatency = Math.max(...latencyRows.map((item) => item.p95), 1);
  const noActivity = !primaryLoading && !primaryError && (overview.data?.total_requests ?? 0) === 0;
  const heroIcon: IconName = primaryError ? "rocket" : primaryLoading ? "spark" : systemHealthy ? "shield" : "rocket";
  const heroTitle = noActivity
    ? t("dashboard.idleTitle")
    : primaryError
    ? t("dashboard.metricsUnavailable")
    : primaryLoading
      ? t("dashboard.loadingMetrics")
      : systemHealthy
        ? t("dashboard.systemNominal")
        : t("dashboard.systemAttention");
  const heroSummary = noActivity
    ? t("dashboard.idleSummary")
    : primaryError
    ? t("dashboard.summaryUnavailable")
    : primaryLoading
      ? t("dashboard.summaryLoading")
      : t("dashboard.heroSummary", {
          requests: formatNumber(overview.data?.total_requests ?? 0),
          success: formatNumber((successRate ?? 0) * 100, { maximumFractionDigits: 1 }),
          latency: formatNumber(latency.data?.avg_response_time ?? 0),
        });

  return (
    <div className="dashboard-shell">
      <section className="page-header">
        <div>
          <p className="page-eyebrow">{t("layout.consoleLabel")}</p>
          <h1 className="page-title">{t("nav.dashboard")}</h1>
          <p className="page-subtitle">{t("dashboard.subtitle")}</p>
        </div>
      </section>

      <div className="dashboard-top">
        <section className="dashboard-hero">
          <div className="dashboard-hero-kicker">
            <Icon name={heroIcon} className="icon-sm" />
            {t("dashboard.operationalState")}
          </div>
          <h2 className="dashboard-hero-title">{heroTitle}</h2>
          <p className="dashboard-hero-text">{heroSummary}</p>
          <div className="dashboard-hero-actions">
            <Link className="btn" to="/monitoring" viewTransition>{t("dashboard.openMonitoring")}</Link>
            <Link className="btn secondary" to="/logs" viewTransition>{t("dashboard.viewLogs")}</Link>
          </div>
        </section>

        <div className="dashboard-stat-grid">
          <MetricCard label={t("dashboard.requestsToday")} value={formatMetricValue(overview.data?.total_requests, formatNumber)} />
          <MetricCard label={t("dashboard.successRate")} value={noActivity ? "—" : formatPercentValue(successRate, formatNumber, { maximumFractionDigits: 1 })} />
          <MetricCard label={t("dashboard.avgResponse")} value={noActivity ? "—" : formatMetricValue(latency.data?.avg_response_time, formatNumber, undefined, "ms")} />
          <MetricCard label={t("dashboard.activeTools")} value={tools.data ? formatNumber(tools.data.tools.length) : "—"} />
        </div>
      </div>

      <div className="dashboard-grid">
        <section className="surface-panel">
          <div className="surface-panel-header">
            <div>
              <p className="surface-panel-label">{t("dashboard.latencySnapshot")}</p>
              <h3 className="surface-panel-title">{t("monitoring.last7d")}</h3>
            </div>
          </div>
          {latency.isError || latencyTrend.isError ? (
            <div className="empty-state">{t("common.dataUnavailable")}</div>
          ) : latency.isPending || latencyTrend.isPending ? (
            <p className="surface-panel-note">{t("common.dataLoading")}</p>
          ) : latencyRows.length === 0 ? (
            <div className="empty-state">{t("common.noData")}</div>
          ) : (
            <>
              <div className="dashboard-bars">
                {latencyRows.map((item) => (
                  <div className="dashboard-bar-group" key={item.date}>
                    <div
                      className="dashboard-bar"
                      style={{ height: `${Math.max(18, (item.p95 / maxLatency) * 100)}%` }}
                    />
                    <span>{formatDateTime(item.date, { month: "numeric", day: "numeric" })}</span>
                  </div>
                ))}
              </div>
              <p className="surface-panel-note">
                {t("dashboard.latency.avg")} {formatMetricValue(latency.data?.avg_response_time, formatNumber, undefined, "ms")}
                {" / "}{t("dashboard.latency.p50")} {formatMetricValue(latency.data?.p50, formatNumber, undefined, "ms")}
                {" / "}{t("dashboard.latency.p95")} {formatMetricValue(latency.data?.p95, formatNumber, undefined, "ms")}
              </p>
            </>
          )}
        </section>

        <section className="surface-panel budget-panel">
          <div className="surface-panel-header">
            <div>
              <p className="surface-panel-label">{t("dashboard.tokenMix")}</p>
              <h3 className="surface-panel-title">{t("dashboard.tokens30d")}</h3>
            </div>
          </div>
          {tokens.isError ? (
            <div className="empty-state">{t("common.dataUnavailable")}</div>
          ) : tokens.isPending ? (
            <p className="surface-panel-note">{t("common.dataLoading")}</p>
          ) : totalTokens === 0 ? (
            <div className="empty-state">{t("common.noData")}</div>
          ) : (
            <>
              <div className="budget-chart">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={[
                        { name: t("dashboard.tokensIn"), value: totalTokensIn },
                        { name: t("dashboard.tokensOut"), value: totalTokensOut },
                      ]}
                      dataKey="value"
                      innerRadius={44}
                      outerRadius={62}
                      strokeWidth={0}
                    >
                      <Cell fill={cssVar("--chart-accent")} />
                      <Cell fill={cssVar("--chart-soft")} />
                    </Pie>
                    <Tooltip {...tooltipStyle(cssVar)} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="budget-chart-center">
                  <strong>{formatNumber(totalTokens)}</strong>
                  <span>{t("dashboard.tokensTotal")}</span>
                </div>
              </div>
              <p className="surface-panel-note">
                {t("dashboard.tokensIn")} {formatNumber(totalTokensIn)}
                {" / "}
                {t("dashboard.tokensOut")} {formatNumber(totalTokensOut)}
              </p>
              <p className="surface-panel-note">
                {t("monitoring.totalCost")}{" "}
                {cost.data
                  ? formatNumber(cost.data.total_cost_usd, {
                      style: "currency",
                      currency: "USD",
                    })
                  : "—"}
              </p>
            </>
          )}
        </section>

        <section className="surface-panel">
          <div className="surface-panel-header">
            <div>
              <p className="surface-panel-label">{t("dashboard.tokenUsage7d")}</p>
              <h3 className="surface-panel-title">{t("dashboard.tokensOut")}</h3>
            </div>
          </div>
          {tokens.isError ? (
            <div className="empty-state">{t("common.dataUnavailable")}</div>
          ) : tokens.isPending ? (
            <p className="surface-panel-note">{t("common.dataLoading")}</p>
          ) : latestTokenDays.length === 0 ? (
            <div className="empty-state">{t("common.noData")}</div>
          ) : (
            <div className="token-summary-list">
              {latestTokenDays.map((day) => (
                <div className="token-summary-row" key={day.date}>
                  <span>{formatDateTime(day.date, { month: "numeric", day: "numeric" })}</span>
                  <span>{t("dashboard.tokensIn")}: {formatNumber(day.tokens_in)}</span>
                  <span>{t("dashboard.tokensOut")}: {formatNumber(day.tokens_out)}</span>
                </div>
              ))}
            </div>
          )}
        </section>

      </div>

      <section className="surface-panel">
        <div className="surface-panel-header">
          <div>
            <p className="surface-panel-label">{t("dashboard.toolPerformance7d")}</p>
            <h3 className="surface-panel-title">{t("dashboard.activeTools")}</h3>
          </div>
        </div>
        <table className="table table-ops">
          <thead>
            <tr>
              <th>{t("dashboard.table.tool")}</th>
              <th>{t("dashboard.table.calls")}</th>
              <th>{t("dashboard.table.errorRate")}</th>
              <th>{t("tools.status")}</th>
            </tr>
          </thead>
          {tools.isError ? (
            <tbody><tr><td colSpan={4}><div className="empty-state">{t("common.dataUnavailable")}</div></td></tr></tbody>
          ) : tools.isPending ? (
            <tbody><tr><td colSpan={4}><p className="surface-panel-note">{t("common.dataLoading")}</p></td></tr></tbody>
          ) : (tools.data?.tools.length ?? 0) === 0 ? (
            <tbody><tr><td colSpan={4}><div className="empty-state">{t("common.noData")}</div></td></tr></tbody>
          ) : (
            <tbody>
              {(tools.data?.tools ?? []).map((row) => {
                const status = toolStatus(row.error_rate);
                return (
                  <tr key={row.tool}>
                    <td className="table-title-cell">{row.tool}</td>
                    <td>{formatNumber(row.count)}</td>
                    <td>{formatNumber(row.error_rate * 100, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%</td>
                    <td>
                      <span className={`status-badge ${status}`}>
                        {status === "stable" ? t("dashboard.statusStable") : t("dashboard.statusDegraded")}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          )}
        </table>
      </section>
    </div>
  );
}
