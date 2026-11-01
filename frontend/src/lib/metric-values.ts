type NumberFormatter = (value: number, options?: Intl.NumberFormatOptions) => string;

export const UNAVAILABLE_VALUE = "—";

export function formatMetricValue(
  value: number | null | undefined,
  formatNumber: NumberFormatter,
  options?: Intl.NumberFormatOptions,
  suffix = "",
): string {
  if (value == null || Number.isNaN(value)) {
    return UNAVAILABLE_VALUE;
  }
  return `${formatNumber(value, options)}${suffix}`;
}

/** Missing dates count as zero; array position is not a calendar boundary. */
export function partitionWeeklyMetrics<T extends { date: string }>(rows: ReadonlyArray<T>, asOf = new Date()): { current: T[]; previous: T[] } {
  const dayAt = (offset: number) => new Date(Date.UTC(asOf.getUTCFullYear(), asOf.getUTCMonth(), asOf.getUTCDate() + offset)).toISOString().slice(0, 10);
  const today = dayAt(0);
  const currentStart = dayAt(-6);
  const previousStart = dayAt(-13);
  return {
    current: rows.filter((row) => row.date >= currentStart && row.date <= today),
    previous: rows.filter((row) => row.date >= previousStart && row.date < currentStart),
  };
}
