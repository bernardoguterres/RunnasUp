import { describe, expect, it } from "vitest";
import {
  addDaysUTC,
  formatDateTimeUTC,
  formatDateUTC,
  formatDelta,
  formatDuration,
  formatKm,
  formatPace,
  formatPoints,
  isoDateUTC,
} from "./format";

describe("format helpers", () => {
  it("formats durations as m:ss and h:mm:ss", () => {
    expect(formatDuration(0)).toBe("0:00");
    expect(formatDuration(1440)).toBe("24:00");
    expect(formatDuration(65)).toBe("1:05");
    expect(formatDuration(3600)).toBe("1:00:00");
    expect(formatDuration(3725)).toBe("1:02:05");
  });

  it("shows tenths only when seconds are fractional", () => {
    expect(formatDuration(1762.38)).toBe("29:22.4");
    expect(formatDuration(1440.5)).toBe("24:00.5");
    expect(formatDuration(59.96)).toBe("1:00");
    expect(formatDuration(3599.95)).toBe("1:00:00");
  });

  it("returns null for null so callers render Missing, never 0", () => {
    expect(formatDuration(null)).toBeNull();
    expect(formatDuration(undefined)).toBeNull();
    expect(formatPace(null)).toBeNull();
    expect(formatKm(null)).toBeNull();
    expect(formatPoints(null)).toBeNull();
    expect(formatDelta(null)).toBeNull();
    expect(formatDateUTC(null)).toBeNull();
  });

  it("formats pace, km, points and delta", () => {
    expect(formatPace(288)).toBe("4:48 /km");
    expect(formatPace(287.6)).toBe("4:48 /km");
    expect(formatKm(5000)).toBe("5.00 km");
    expect(formatKm(10012.4)).toBe("10.01 km");
    expect(formatPoints(816.3265)).toBe("816.33");
    expect(formatDelta(12.345)).toBe("+12.35");
    expect(formatDelta(-3.1)).toBe("−3.10");
    expect(formatDelta(0.001)).toBe("0.00");
  });

  it("labels dates in UTC regardless of local zone", () => {
    expect(formatDateUTC("2024-03-15T23:30:00Z")).toBe("15 Mar 2024 UTC");
    expect(formatDateTimeUTC("2024-03-15T07:05:00Z")).toBe("15 Mar 2024, 07:05 UTC");
    expect(isoDateUTC("2024-02-29T23:59:59Z")).toBe("2024-02-29");
    expect(addDaysUTC("2024-03-01", -1)).toBe("2024-02-29");
  });
});
