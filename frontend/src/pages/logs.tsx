import { useMemo, useState } from "react";

import { useQuery } from "@tanstack/react-query";

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

function levelTone(level: string): string {
  if (level === "error") return "degraded";
  if (level === "warning") return "stable";
  return "stable";
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
    queryKey: ["logs", "stats"],
    queryFn: () => api.get<LogStats>(`/api/logs/stats${platform !== "all" ? `?platform=${platform}` : ""}`),
    refetchInterval: 10000,
  });

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
    <div className="stack-layout">
      <section className="page-header">
        <div>
          <p className="page-eyebrow">{t("nav.logs")}</p>
          <h1 className="page-title">{t("nav.logs")}</h1>
          <p className="page-subtitle">{t("logs.subtitle")}</p>
        </div>
      </section>

      <div className="stats-row">
        <MetricLogCard label={t("logs.total")} value={formatNumber(stats.data?.total ?? 0)} tone="stable" badge={t("dashboard.statusStable")} />
        <MetricLogCard label={t("logs.cognitive")} value={formatNumber(stats.data?.by_surface.cognitive ?? 0)} tone="stable" badge={t("dashboard.statusStable")} />
        <MetricLogCard label={t("logs.operational")} value={formatNumber(stats.data?.by_surface.operational ?? 0)} tone="stable" badge={t("dashboard.statusStable")} />
        <MetricLogCard label={t("logs.contextual")} value={formatNumber(stats.data?.by_surface.contextual ?? 0)} tone="stable" badge={t("dashboard.statusStable")} />
        <MetricLogCard label={t("logs.warnings")} value={formatNumber(stats.data?.by_level.warning ?? 0)} tone="stable" badge={t("logs.level.warning")} />
        <MetricLogCard label={t("logs.errors")} value={formatNumber(stats.data?.by_level.error ?? 0)} tone="degraded" badge={t("dashboard.statusDegraded")} />
      </div>

      <section className="surface-panel">
        <div className="filter-row">
          <select className="select" aria-label={t("logs.filter.platform")} value={platform} onChange={(event) => setPlatform(event.target.value)}>
            {PLATFORMS.map((item) => (
              <option key={item} value={item}>{platformLabel(item)}</option>
            ))}
          </select>
          <select className="select" aria-label={t("logs.filter.surface")} value={surface} onChange={(event) => setSurface(event.target.value)}>
            {SURFACES.map((item) => (
              <option key={item} value={item}>{surfaceLabel(item)}</option>
            ))}
          </select>
          <select className="select" aria-label={t("logs.filter.level")} value={level} onChange={(event) => setLevel(event.target.value)}>
            {LEVELS.map((item) => (
              <option key={item} value={item}>{levelLabel(item)}</option>
            ))}
          </select>
          <input
            className="input"
            placeholder={t("logs.filter.traceOrInteraction")}
            aria-label={t("logs.filter.traceOrInteraction")}
            value={traceFilter}
            onChange={(event) => setTraceFilter(event.target.value)}
          />
          <span className="status-badge stable">{t("logs.autoRefresh")}</span>
        </div>
      </section>

      <section className="surface-panel">
        <div className="surface-panel-header">
          <div>
            <p className="surface-panel-label">{t("logs.entries", { count: formatNumber(logs.data?.length ?? 0) })}</p>
            <h3 className="surface-panel-title">{t("nav.logs")}</h3>
          </div>
        </div>
        <table className="table table-ops">
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
                  <span className={`status-badge ${levelTone(entry.level)}`}>{levelLabel(entry.level)}</span>
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
        {logs.isLoading ? <p className="surface-panel-note">{t("common.loading")}</p> : null}
        {!logs.isLoading && (logs.data?.length ?? 0) === 0 ? (
          <div className="empty-state">{t("logs.empty")}</div>
        ) : null}
      </section>
    </div>
  );
}

function MetricLogCard(
  { label, value, tone, badge }: { label: string; value: string; tone: "stable" | "degraded"; badge: string },
): JSX.Element {
  return (
    <section className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
      <div>
        <span className={`status-badge ${tone}`}>{badge}</span>
      </div>
    </section>
  );
}

function formatData(raw: string): string {
  try {
    const obj = JSON.parse(raw);
    return Object.entries(obj).map(([key, value]) => `${key}=${value}`).join(" ");
  } catch {
    return raw;
  }
}
