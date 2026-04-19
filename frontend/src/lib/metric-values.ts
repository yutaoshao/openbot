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

export function formatPercentValue(
  value: number | null | undefined,
  formatNumber: NumberFormatter,
  options?: Intl.NumberFormatOptions,
): string {
  if (value == null || Number.isNaN(value)) {
    return UNAVAILABLE_VALUE;
  }
  return `${formatNumber(value * 100, options)}%`;
}
