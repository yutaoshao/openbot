import { useMemo, useState } from "react";

import { useQuery } from "@tanstack/react-query";

import { useI18n } from "../i18n";
import { api } from "../lib/api";

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

function levelColor(level: string): string {
  if (level === "error") return "var(--danger)";
  if (level === "warning") return "#eab308";
  return "var(--text-muted)";
}

function surfaceColor(surface: string | null): string {
  if (surface === "cognitive") return "#8b5cf6";
  if (surface === "operational") return "#3b82f6";
  if (surface === "contextual") return "#10b981";
  return "var(--text-dim)";
}

export function LogsPage(): JSX.Element {
  const { t, formatDateTime, formatNumber } = useI18n();
  const [surface, setSurface] = useState("all");
  const [level, setLevel] = useState("all");
  const [traceFilter, setTraceFilter] = useState("");
  const [limit] = useState(100);

  const params = useMemo(() => {
    const p = new URLSearchParams();
    if (surface !== "all") p.set("surface", surface);
    if (level !== "all") p.set("level", level);
    if (traceFilter.trim()) {
      // Auto-detect: trace_id is 16 hex chars, interaction_id is longer
      if (traceFilter.length <= 16) {
        p.set("trace_id", traceFilter.trim());
      } else {
        p.set("interaction_id", traceFilter.trim());
      }
    }
    p.set("limit", String(limit));
    return p.toString();
  }, [surface, level, traceFilter, limit]);

  const logs = useQuery({
    queryKey: ["logs", params],
    queryFn: () => api.get<LogEntry[]>(`/api/logs?${params}`),
    refetchInterval: 5000,
  });

  const stats = useQuery({
    queryKey: ["logs", "stats"],
    queryFn: () => api.get<LogStats>("/api/logs/stats"),
    refetchInterval: 10000,
  });

  const levelLabel = (value: string) => {
    if (value === "all") {
      return t("logs.filter.all");
    }
    return t(`logs.level.${value}`);
  };

  const surfaceLabel = (value: string) => {
    if (value === "all") {
      return t("logs.filter.all");
    }
    return t(`logs.surface.${value}`);
  };

  return (
    <div>
      {/* Stats row */}
      <div className="grid" style={{ gridTemplateColumns: "repeat(6, 1fr)", marginBottom: "var(--space-4)" }}>
        <div className="card">
          <h3>{t("logs.total")}</h3>
          <strong>{formatNumber(stats.data?.total ?? 0)}</strong>
        </div>
        <div className="card">
          <h3>{t("logs.cognitive")}</h3>
          <strong style={{ color: "#8b5cf6" }}>{formatNumber(stats.data?.by_surface.cognitive ?? 0)}</strong>
        </div>
        <div className="card">
          <h3>{t("logs.operational")}</h3>
          <strong style={{ color: "#3b82f6" }}>{formatNumber(stats.data?.by_surface.operational ?? 0)}</strong>
        </div>
        <div className="card">
          <h3>{t("logs.contextual")}</h3>
          <strong style={{ color: "#10b981" }}>{formatNumber(stats.data?.by_surface.contextual ?? 0)}</strong>
        </div>
        <div className="card">
          <h3>{t("logs.warnings")}</h3>
          <strong style={{ color: "#eab308" }}>{formatNumber(stats.data?.by_level.warning ?? 0)}</strong>
        </div>
        <div className="card">
          <h3>{t("logs.errors")}</h3>
          <strong style={{ color: "var(--danger)" }}>{formatNumber(stats.data?.by_level.error ?? 0)}</strong>
        </div>
      </div>

      {/* Filters */}
      <div className="card" style={{ marginBottom: "var(--space-4)" }}>
        <div style={{ display: "flex", gap: "var(--space-3)", flexWrap: "wrap", alignItems: "center" }}>
          <select className="select" style={{ width: 160 }} value={surface} onChange={(e) => setSurface(e.target.value)}>
            {SURFACES.map((s) => (
              <option key={s} value={s}>{surfaceLabel(s)}</option>
            ))}
          </select>
          <select className="select" style={{ width: 130 }} value={level} onChange={(e) => setLevel(e.target.value)}>
            {LEVELS.map((l) => (
              <option key={l} value={l}>{levelLabel(l)}</option>
            ))}
          </select>
          <input
            className="input"
            style={{ width: 280 }}
            placeholder={t("logs.filter.traceOrInteraction")}
            value={traceFilter}
            onChange={(e) => setTraceFilter(e.target.value)}
          />
          <span className="mono" style={{ color: "var(--text-dim)", fontSize: 12 }}>
            {t("logs.autoRefresh")}
          </span>
        </div>
      </div>

      {/* Log entries */}
      <div className="card">
        <h3>{t("logs.entries", { count: formatNumber(logs.data?.length ?? 0) })}</h3>
        <table className="table">
          <thead>
            <tr>
              <th style={{ width: 170 }}>{t("logs.table.time")}</th>
              <th style={{ width: 60 }}>{t("logs.table.level")}</th>
              <th style={{ width: 100 }}>{t("logs.table.surface")}</th>
              <th style={{ width: 150 }}>{t("logs.table.event")}</th>
              <th style={{ width: 130 }}>{t("logs.table.trace")}</th>
              <th>{t("logs.table.details")}</th>
            </tr>
          </thead>
          <tbody>
            {(logs.data ?? []).map((entry) => (
              <tr key={entry.id}>
                <td className="mono" style={{ fontSize: 12, color: "var(--text-muted)" }}>
                  {formatDateTime(entry.timestamp, { dateStyle: "short", timeStyle: "medium" })}
                </td>
                <td>
                  <span style={{ color: levelColor(entry.level), fontWeight: 500, fontSize: 12, textTransform: "uppercase" }}>
                    {levelLabel(entry.level)}
                  </span>
                </td>
                <td>
                  {entry.surface ? (
                    <span style={{ color: surfaceColor(entry.surface), fontSize: 12 }}>
                      {surfaceLabel(entry.surface)}
                    </span>
                  ) : (
                    <span style={{ color: "var(--text-dim)", fontSize: 12 }}>-</span>
                  )}
                </td>
                <td className="mono" style={{ fontSize: 13 }}>{entry.event}</td>
                <td className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>
                  {entry.trace_id ? (
                    <span
                      role="button"
                      tabIndex={0}
                      style={{ cursor: "pointer", textDecoration: "underline" }}
                      onClick={() => setTraceFilter(entry.trace_id ?? "")}
                      onKeyDown={(e) => { if (e.key === "Enter") setTraceFilter(entry.trace_id ?? ""); }}
                    >
                      {entry.trace_id.slice(0, 8)}
                    </span>
                  ) : "-"}
                  {entry.iteration ? ` #${entry.iteration}` : ""}
                </td>
                <td className="mono" style={{ fontSize: 12, color: "var(--text-muted)", maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {entry.data ? formatData(entry.data) : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {logs.isLoading ? <p style={{ color: "var(--text-muted)" }}>{t("common.loading")}</p> : null}
        {!logs.isLoading && (logs.data?.length ?? 0) === 0 ? (
          <p style={{ color: "var(--text-dim)", textAlign: "center", padding: "var(--space-6)" }}>
            {t("logs.empty")}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function formatData(raw: string): string {
  try {
    const obj = JSON.parse(raw);
    return Object.entries(obj)
      .map(([k, v]) => `${k}=${v}`)
      .join(" ");
  } catch {
    return raw;
  }
}
