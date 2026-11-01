import { describe, expect, it } from "vitest";

import { partitionWeeklyMetrics } from "./metric-values";

describe("weekly statistics windows", () => {
  it("uses calendar dates rather than the last seven sparse records", () => {
    const rows = [
      { date: "2026-10-01", value: 1000 }, { date: "2026-10-19", value: 20 },
      { date: "2026-10-25", value: 30 }, { date: "2026-10-26", value: 3 },
      { date: "2026-11-01", value: 4 }, { date: "2026-11-02", value: 999 },
    ];
    const result = partitionWeeklyMetrics(rows, new Date("2026-11-01T17:00:00Z"));
    expect(result.current.map((row) => row.value)).toEqual([3, 4]);
    expect(result.previous.map((row) => row.value)).toEqual([20, 30]);
    expect(rows).toHaveLength(6);
  });

  it("keeps adjacent UTC windows disjoint across a year boundary", () => {
    const rows = ["2025-12-20", "2025-12-26", "2025-12-27", "2026-01-02"].map((date) => ({ date }));
    const result = partitionWeeklyMetrics(rows, new Date("2026-01-01T20:00:00-10:00"));
    expect(result.previous.map((row) => row.date)).toEqual(["2025-12-20", "2025-12-26"]);
    expect(result.current.map((row) => row.date)).toEqual(["2025-12-27", "2026-01-02"]);
  });
});
