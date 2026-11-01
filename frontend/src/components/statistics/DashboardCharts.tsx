import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useI18n } from "../../i18n";
import { ChartLegend, useStatisticsColors } from "./shared";

type LatencyPoint = { date: string; p95: number };

export function LatencyChart({ rows }: { rows: ReadonlyArray<LatencyPoint> }): JSX.Element {
  const { t, formatDateTime, formatNumber } = useI18n();
  const colors = useStatisticsColors();
  const points = rows.map((row) => ({ ...row, label: formatDateTime(row.date, { month: "numeric", day: "numeric" }) }));
  return <>
    <div className="statistics-chart-meta">
      <ChartLegend items={[{ label: t("monitoring.p95"), color: colors.primary }]} />
      <span>ms</span>
    </div>
    <div className="statistics-chart">
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke={colors.grid} strokeDasharray="3 5" />
          <XAxis dataKey="label" axisLine={false} tickLine={false} tick={{ fill: colors.muted, fontSize: 11 }} tickMargin={12} />
          <YAxis axisLine={false} tickLine={false} tick={{ fill: colors.muted, fontSize: 11 }} width={52} tickCount={4}
            tickFormatter={(value: number) => formatNumber(value, { notation: "compact", maximumFractionDigits: 1 })} />
          <Tooltip cursor={{ fill: colors.grid, opacity: 0.3 }}
            formatter={(value) => [`${formatNumber(Number(value))} ms`, t("monitoring.p95")]}
            contentStyle={{ background: colors.surface, border: `1px solid ${colors.grid}`, borderRadius: 8, fontSize: 12, color: colors.text }} />
          <Bar dataKey="p95" fill={colors.primary} maxBarSize={30} radius={[3, 3, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  </>;
}

export function TokenCompositionChart({ input, output }: { input: number; output: number }): JSX.Element {
  const { t, formatNumber } = useI18n();
  const colors = useStatisticsColors();
  const total = input + output;
  const segments = [
    { name: t("statistics.input"), value: input, color: colors.primary },
    { name: t("statistics.output"), value: output, color: colors.secondary },
  ];
  return <div className="statistics-token-composition">
    <div className="statistics-donut">
      <ResponsiveContainer width="100%" height={168}>
        <PieChart>
          <Pie data={segments} dataKey="value" innerRadius={57} outerRadius={72} startAngle={90} endAngle={-270}
            strokeWidth={0} isAnimationActive={false}>
            {segments.map((segment) => <Cell key={segment.name} fill={segment.color} />)}
          </Pie>
          <Tooltip formatter={(value) => formatNumber(Number(value))}
            contentStyle={{ background: colors.surface, border: `1px solid ${colors.grid}`, borderRadius: 8, fontSize: 12, color: colors.text }} />
        </PieChart>
      </ResponsiveContainer>
      <div className="statistics-donut-label" title={formatNumber(total)}>
        <strong>{formatNumber(total, { notation: "compact", maximumFractionDigits: 1 })}</strong>
        <span>{t("dashboard.tokensTotal")}</span>
      </div>
    </div>
    <dl className="statistics-token-details">
      {segments.map((segment) => <div key={segment.name}>
        <dt><i aria-hidden="true" style={{ background: segment.color }} />{segment.name}</dt>
        <dd>{formatNumber(segment.value)}<small>{formatNumber(total ? segment.value / total : 0, { style: "percent", maximumFractionDigits: 0 })}</small></dd>
      </div>)}
    </dl>
  </div>;
}
