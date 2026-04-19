export function toolStatus(errorRate: number): "stable" | "degraded" {
  return errorRate >= 0.03 ? "degraded" : "stable";
}

export function tooltipStyle(readCssVar: (name: string) => string) {
  return {
    contentStyle: {
      background: readCssVar("--surface"),
      border: `1px solid ${readCssVar("--border")}`,
      borderRadius: 20,
      color: readCssVar("--text"),
    },
    labelStyle: { color: readCssVar("--text-muted") },
    itemStyle: { color: readCssVar("--text") },
  };
}

export function MetricCard({ label, value }: { label: string; value: string }): JSX.Element {
  return (
    <section className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
    </section>
  );
}
