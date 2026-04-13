import { useMemo } from "react";
import { Link } from "react-router-dom";

import { useQuery } from "@tanstack/react-query";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { Icon } from "../components/Icon";
import { useI18n } from "../i18n";
import { api, cssVar } from "../lib/api";

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

type LatencySummary = {
  avg_response_time: number;
  p50: number;
  p95: number;
  p99: number;
};

type LatencyTrend = {
  daily: Array<{ date: string; avg: number; p50: number; p95: number }>;
};

type ToolStats = {
  tools: Array<{ tool: string; count: number; error_rate: number }>;
};

type Tokens = {
  daily: Array<{ date: string; tokens_in: number; tokens_out: number }>;
};

function toolStatus(errorRate: number): "stable" | "degraded" {
  return errorRate >= 0.03 ? "degraded" : "stable";
}

function tooltipStyle() {
  return {
    contentStyle: {
      background: cssVar("--surface"),
      border: `1px solid ${cssVar("--border")}`,
      borderRadius: 20,
      color: cssVar("--text"),
    },
    labelStyle: { color: cssVar("--text-muted") },
    itemStyle: { color: cssVar("--text") },
  };
}

export function DashboardPage(): JSX.Element {
  const { t, formatDateTime, formatNumber } = useI18n();
  const overview = useQuery({
    queryKey: ["metrics", "overview"],
    queryFn: () => api.get<Overview>("/api/metrics/overview?period=today"),
  });
  const latency = useQuery({
    queryKey: ["metrics", "latency"],
    queryFn: () => api.get<LatencySummary>("/api/metrics/latency?period=7d"),
  });
  const latencyTrend = useQuery({
    queryKey: ["metrics", "latency", "30d"],
    queryFn: () => api.get<LatencyTrend>("/api/metrics/latency?period=30d"),
  });
  const tools = useQuery({
    queryKey: ["metrics", "tools"],
    queryFn: () => api.get<ToolStats>("/api/metrics/tools?period=7d"),
  });
  const tokens = useQuery({
    queryKey: ["metrics", "tokens", "30d"],
    queryFn: () => api.get<Tokens>("/api/metrics/tokens?period=30d"),
  });

  const successRate = overview.data?.success_rate ?? (1 - (overview.data?.error_rate ?? 0));
  const systemHealthy = successRate >= 0.98;
  const latestTokenDays = (tokens.data?.daily ?? []).slice(-7);
  const latestTokenDay = latestTokenDays[latestTokenDays.length - 1];
  const totalTokensIn = (tokens.data?.daily ?? []).reduce((acc, item) => acc + item.tokens_in, 0);
  const totalTokensOut = (tokens.data?.daily ?? []).reduce((acc, item) => acc + item.tokens_out, 0);
  const totalTokens = totalTokensIn + totalTokensOut;
  const maxLatency = Math.max(...(latencyTrend.data?.daily ?? []).map((item) => item.p95), 1);
  const terminalLines = useMemo(
    () => [
      `[today] requests=${formatNumber(overview.data?.total_requests ?? 0)}`,
      `[latency] avg=${formatNumber(latency.data?.avg_response_time ?? 0)}ms p95=${formatNumber(latency.data?.p95 ?? 0)}ms`,
      `[tokens] in=${formatNumber(latestTokenDay?.tokens_in ?? 0)} out=${formatNumber(latestTokenDay?.tokens_out ?? 0)}`,
      `[tokens-30d] total=${formatNumber(totalTokens)} in=${formatNumber(totalTokensIn)} out=${formatNumber(totalTokensOut)}`,
      `[tools] active=${formatNumber((tools.data?.tools ?? []).length)} top=${tools.data?.tools?.[0]?.tool ?? "-"}`,
    ],
    [formatNumber, latency.data?.avg_response_time, latency.data?.p95, latestTokenDay?.tokens_in, latestTokenDay?.tokens_out, overview.data?.total_requests, tools.data?.tools, totalTokens, totalTokensIn, totalTokensOut],
  );

  return (
    <div className="dashboard-shell">
      <section className="page-header">
        <div>
          <p className="page-eyebrow">{t("layout.consoleLabel")}</p>
          <h1 className="page-title">{t("nav.dashboard")}</h1>
          <p className="page-subtitle">{t("dashboard.heroSummary", {
            requests: formatNumber(overview.data?.total_requests ?? 0),
            success: formatNumber(successRate * 100, { maximumFractionDigits: 1 }),
            latency: formatNumber(latency.data?.avg_response_time ?? 0),
          })}</p>
        </div>
      </section>

      <div className="dashboard-top">
        <section className="dashboard-hero">
          <div className="dashboard-hero-kicker">
            <Icon name={systemHealthy ? "shield" : "rocket"} className="icon-sm" />
            {t("dashboard.operationalState")}
          </div>
          <h2 className="dashboard-hero-title">
            {systemHealthy ? t("dashboard.systemNominal") : t("dashboard.systemAttention")}
          </h2>
          <p className="dashboard-hero-text">{t("dashboard.heroSummary", {
            requests: formatNumber(overview.data?.total_requests ?? 0),
            success: formatNumber(successRate * 100, { maximumFractionDigits: 1 }),
            latency: formatNumber(latency.data?.avg_response_time ?? 0),
          })}</p>
          <div className="dashboard-hero-actions">
            <Link className="btn" to="/monitoring">{t("dashboard.openMonitoring")}</Link>
            <Link className="btn secondary" to="/logs">{t("dashboard.viewLogs")}</Link>
          </div>
        </section>

        <div className="dashboard-stat-grid">
          <MetricCard label={t("dashboard.requestsToday")} value={formatNumber(overview.data?.total_requests ?? 0)} />
          <MetricCard label={t("dashboard.successRate")} value={`${formatNumber(successRate * 100, { maximumFractionDigits: 1 })}%`} />
          <MetricCard label={t("dashboard.avgResponse")} value={`${formatNumber(latency.data?.avg_response_time ?? 0)}ms`} />
          <MetricCard label={t("dashboard.activeTools")} value={formatNumber((tools.data?.tools ?? []).length)} />
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
          <div className="dashboard-bars">
            {(latencyTrend.data?.daily ?? []).slice(-14).map((item) => (
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
            {t("dashboard.latency.avg")} {formatNumber(latency.data?.avg_response_time ?? 0)}ms
            {" / "}{t("dashboard.latency.p50")} {formatNumber(latency.data?.p50 ?? 0)}ms
            {" / "}{t("dashboard.latency.p95")} {formatNumber(latency.data?.p95 ?? 0)}ms
          </p>
        </section>

        <section className="surface-panel budget-panel">
          <div className="surface-panel-header">
            <div>
              <p className="surface-panel-label">{t("dashboard.tokenMix")}</p>
              <h3 className="surface-panel-title">{t("dashboard.tokens30d")}</h3>
            </div>
          </div>
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
                <Tooltip {...tooltipStyle()} />
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
        </section>

        <section className="surface-panel">
          <div className="surface-panel-header">
            <div>
              <p className="surface-panel-label">{t("dashboard.tokenUsage7d")}</p>
              <h3 className="surface-panel-title">{t("dashboard.tokensOut")}</h3>
            </div>
          </div>
          <div className="token-summary-list">
            {latestTokenDays.map((day) => (
              <div className="token-summary-row" key={day.date}>
                <span>{formatDateTime(day.date, { month: "numeric", day: "numeric" })}</span>
                <span>{t("dashboard.tokensIn")}: {formatNumber(day.tokens_in)}</span>
                <span>{t("dashboard.tokensOut")}: {formatNumber(day.tokens_out)}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="surface-panel terminal-panel">
          <div className="surface-panel-header">
            <div>
              <p className="surface-panel-label">{t("dashboard.terminalOutput")}</p>
              <h3 className="surface-panel-title">{t("dashboard.metricsDerived")}</h3>
            </div>
          </div>
          <div className="terminal-output">
            {terminalLines.map((line) => (
              <div key={line}>{line}</div>
            ))}
            <div className="terminal-cursor">_</div>
          </div>
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
        </table>
      </section>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }): JSX.Element {
  return (
    <section className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
    </section>
  );
}
