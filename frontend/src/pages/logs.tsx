import { useMemo, useState, type ReactNode } from "react";

import { useQuery } from "@tanstack/react-query";

import { StatisticValue, StatisticsPage } from "../components/statistics/shared";
import { useI18n } from "../i18n";
import { api } from "../lib/api";
import { liveLogsQueryDefaults } from "../lib/query-defaults";

type LogEntry = {
  id: number;
  timestamp: string;
  level: string;
  event: string;
  surface: string | null;
  trace_id: string | null;
  interaction_id: string | null;
  platform: string | null;
  iteration: number | null;
  data: string | null;
};

type LogStats = {
  total: number;
  by_surface: { cognitive: number; operational: number; contextual: number };
  by_level: { error: number; warning: number; info: number };
};

const SURFACES = ["all", "cognitive", "operational", "contextual"] as const;
const LEVELS = ["all", "info", "warning", "error"] as const;
const PLATFORMS = ["all", "web", "telegram", "feishu", "wechat", "scheduler"] as const;

function logTone(level: string): string {
  if (level === "error") return "statistics-tone-error";
  if (level === "warning") return "statistics-tone-warning";
  return "statistics-tone-neutral";
}

export function LogsPage(): JSX.Element {
  const { t, formatDateTime, formatNumber } = useI18n();
  const [surface, setSurface] = useState("all");
  const [level, setLevel] = useState("all");
  const [platform, setPlatform] = useState("all");
  const [traceFilter, setTraceFilter] = useState("");
  const limit = 100;

  const params = useMemo(() => {
    const url = new URLSearchParams();
    if (surface !== "all") url.set("surface", surface);
    if (level !== "all") url.set("level", level);
    if (platform !== "all") url.set("platform", platform);
    if (traceFilter.trim()) {
      if (traceFilter.length <= 16) {
        url.set("trace_id", traceFilter.trim());
      } else {
        url.set("interaction_id", traceFilter.trim());
      }
    }
    url.set("limit", String(limit));
    return url.toString();
  }, [level, platform, surface, traceFilter]);

  const logs = useQuery({
    ...liveLogsQueryDefaults,
    queryKey: ["logs", params],
    queryFn: () => api.get<LogEntry[]>(`/api/logs?${params}`),
    refetchInterval: 5000,
  });

  const stats = useQuery({
    ...liveLogsQueryDefaults,
    queryKey: ["logs", "stats", platform],
    queryFn: () => api.get<LogStats>(`/api/logs/stats${platform !== "all" ? `?platform=${platform}` : ""}`),
    refetchInterval: 10000,
  });

  const statsSnapshot = stats.isError ? undefined : stats.data;
  const formatLogCount = (value: number | undefined) => value == null ? "—" : formatNumber(value);

  const surfaceLabel = (value: string) => (
    value === "all" ? t("logs.filter.all") : t(`logs.surface.${value}`)
  );
  const levelLabel = (value: string) => (
    value === "all" ? t("logs.filter.all") : t(`logs.level.${value}`)
  );
  const platformLabel = (value: string) => (
    value === "all" ? t("logs.filter.all") : t(`logs.platform.${value}`)
  );

  return (
    <StatisticsPage><div className="stack-layout statistics-logs">
      <section className="page-header">
        <div>
          <p className="page-eyebrow">{t("nav.logs")}</p>
          <h1 className="page-title">{t("nav.logs")}</h1>
          <p className="page-subtitle">{t("logs.subtitle")}</p>
        </div>
      </section>

      <div className="stats-row statistics-log-metrics">
        <MetricLogCard label={t("logs.total")} value={formatLogCount(statsSnapshot?.total)} />
        <MetricLogCard label={t("logs.cognitive")} value={formatLogCount(statsSnapshot?.by_surface.cognitive)} />
        <MetricLogCard label={t("logs.operational")} value={formatLogCount(statsSnapshot?.by_surface.operational)} />
        <MetricLogCard label={t("logs.contextual")} value={formatLogCount(statsSnapshot?.by_surface.contextual)} />
        <MetricLogCard label={t("logs.warnings")} value={formatLogCount(statsSnapshot?.by_level.warning)} tone={(statsSnapshot?.by_level.warning ?? 0) > 0 ? "warning" : "neutral"} />
        <MetricLogCard label={t("logs.errors")} value={formatLogCount(statsSnapshot?.by_level.error)} tone={(statsSnapshot?.by_level.error ?? 0) > 0 ? "error" : "neutral"} />
      </div>

      {stats.isPending && <p className="surface-panel-note" role="status">{t("common.dataLoading")}</p>}
      {stats.isError && <div role="alert"><p>{t("common.dataUnavailable")}</p>
        <button className="btn secondary" type="button" disabled={stats.isFetching} onClick={() => void stats.refetch()}>{t("desktop.reconnect")}</button>
      </div>}

      <section className="surface-panel statistics-log-toolbar">
        <div className="filter-row statistics-log-filters">
          <LogFilter label={t("logs.table.platform")}>
            <select className="select" aria-label={t("logs.filter.platform")} value={platform} onChange={(event) => setPlatform(event.target.value)}>
              {PLATFORMS.map((item) => (
                <option key={item} value={item}>{platformLabel(item)}</option>
              ))}
            </select>
          </LogFilter>
          <LogFilter label={t("logs.table.surface")}>
            <select className="select" aria-label={t("logs.filter.surface")} value={surface} onChange={(event) => setSurface(event.target.value)}>
              {SURFACES.map((item) => (
                <option key={item} value={item}>{surfaceLabel(item)}</option>
              ))}
            </select>
          </LogFilter>
          <LogFilter label={t("logs.table.level")}>
            <select className="select" aria-label={t("logs.filter.level")} value={level} onChange={(event) => setLevel(event.target.value)}>
              {LEVELS.map((item) => (
                <option key={item} value={item}>{levelLabel(item)}</option>
              ))}
            </select>
          </LogFilter>
          <LogFilter label={t("logs.table.trace")} className="statistics-trace-field">
            <input
              className="input"
              placeholder={t("logs.filter.traceOrInteraction")}
              aria-label={t("logs.filter.traceOrInteraction")}
              value={traceFilter}
              onChange={(event) => setTraceFilter(event.target.value)}
            />
          </LogFilter>
          <span className="statistics-refresh">{t("logs.autoRefresh")}</span>
        </div>
      </section>

      <section className="surface-panel statistics-log-results">
        <div className="surface-panel-header">
          <div>
            <p className="surface-panel-label">{t("logs.entries", { count: logs.data ? formatNumber(logs.data.length) : "—" })}</p>
            <h3 className="surface-panel-title">{t("nav.logs")}</h3>
          </div>
        </div>
        <table className="table table-ops statistics-log-table">
          <thead>
            <tr>
              <th>{t("logs.table.time")}</th>
              <th>{t("logs.table.level")}</th>
              <th>{t("logs.table.surface")}</th>
              <th>{t("logs.table.platform")}</th>
              <th>{t("logs.table.event")}</th>
              <th>{t("logs.table.trace")}</th>
              <th>{t("logs.table.details")}</th>
            </tr>
          </thead>
          <tbody>
            {(logs.data ?? []).map((entry) => (
              <tr key={entry.id}>
                <td className="mono">{formatDateTime(entry.timestamp, { dateStyle: "short", timeStyle: "medium" })}</td>
                <td>
                  <span className={`status-badge ${logTone(entry.level)}`}>{levelLabel(entry.level)}</span>
                </td>
                <td>{entry.surface ? surfaceLabel(entry.surface) : "-"}</td>
                <td>{entry.platform ? platformLabel(entry.platform) : "-"}</td>
                <td className="table-title-cell">{entry.event}</td>
                <td className="mono">
                  {entry.trace_id ? (
                    <button
                      className="trace-filter-button"
                      type="button"
                      aria-label={t("logs.filterTrace")}
                      title={entry.trace_id}
                      onClick={() => setTraceFilter(entry.trace_id ?? "")}
                    >
                      {entry.trace_id.slice(0, 8)}
                    </button>
                  ) : "-"}
                </td>
                <td className="mono">{entry.data ? formatData(entry.data) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {logs.isLoading && <p className="surface-panel-note" role="status">{t("common.loading")}</p>}
        {logs.isError && <div role="alert"><p>{t("common.dataUnavailable")}</p>
          <button className="btn secondary" type="button" disabled={logs.isFetching} onClick={() => void logs.refetch()}>{t("desktop.reconnect")}</button>
        </div>}
        {logs.isSuccess && logs.data.length === 0 ? (
          <div className="empty-state">{t("logs.empty")}</div>
        ) : null}
      </section>
    </div></StatisticsPage>
  );
}

function LogFilter({ label, children, className = "" }: { label: string; children: ReactNode; className?: string }): JSX.Element {
  return <label className={`statistics-filter ${className}`}><span>{label}</span>{children}</label>;
}

function MetricLogCard({ label, value, tone = "neutral" }: {
  label: string; value: string; tone?: "neutral" | "warning" | "error";
}): JSX.Element {
  return <section className={`metric-card statistics-tone-${tone}`}>
    <span>{label}</span>
    <StatisticValue>{value}</StatisticValue>
  </section>;
}

function formatData(raw: string): string {
  try {
    const obj = JSON.parse(raw);
    return Object.entries(obj).map(([key, value]) => `${key}=${value}`).join(" ");
  } catch {
    return raw;
  }
}
