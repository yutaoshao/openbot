import { StatisticValue } from "./statistics/shared";

export function toolStatus(errorRate: number): "stable" | "degraded" {
  return errorRate >= 0.03 ? "degraded" : "stable";
}

export function MetricCard({ label, value, unit }: { label: string; value: string; unit?: string }): JSX.Element {
  return (
    <section className="metric-card">
      <span>{label}</span>
      <StatisticValue unit={unit}>{value}</StatisticValue>
    </section>
  );
}
