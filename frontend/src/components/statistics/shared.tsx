import { useSyncExternalStore, type ReactNode } from "react";

import { cssVar } from "../../lib/api";

/** All entries share presentation; the API client owns their transport boundaries. */
export function StatisticsPage({ children }: { children: ReactNode }): JSX.Element {
  return <div className="statistics-page">{children}</div>;
}

function subscribeTheme(listener: () => void): () => void {
  const observer = new MutationObserver(listener);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => observer.disconnect();
}

/** Chart SVG attributes must be refreshed after the root theme changes. */
export function useStatisticsColors() {
  useSyncExternalStore(subscribeTheme, () => document.documentElement.getAttribute("data-theme"), () => null);
  return {
    primary: cssVar("--statistics-primary"),
    secondary: cssVar("--statistics-secondary"),
    grid: cssVar("--statistics-border"),
    text: cssVar("--statistics-text"),
    muted: cssVar("--statistics-text-muted"),
    surface: cssVar("--statistics-surface"),
  };
}

export function StatisticValue({ children, unit }: { children: ReactNode; unit?: string }): JSX.Element {
  return <strong className="statistics-value">{children}{unit && <small className="statistics-unit">{unit}</small>}</strong>;
}

export type LegendItem = { label: string; color: string; dashed?: boolean };

export function ChartLegend({ items }: { items: ReadonlyArray<LegendItem> }): JSX.Element {
  return <ul className="statistics-legend">
    {items.map((item) => <li key={item.label}>
      <span aria-hidden="true" style={{ borderColor: item.color, borderTopStyle: item.dashed ? "dashed" : "solid" }} />
      {item.label}
    </li>)}
  </ul>;
}
