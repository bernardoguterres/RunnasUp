/**
 * Display formatting only. No rating arithmetic lives here.
 * Every function returns null for null/undefined input so callers can render
 * <Missing /> ("—", "not recorded") instead of a misleading 0.
 */

export const MISSING_TEXT = "—";
export const MISSING_LABEL = "not recorded";

type Num = number | null | undefined;

const pad2 = (n: number) => String(n).padStart(2, "0");

/** Seconds -> "m:ss" or "h:mm:ss"; tenths are shown when the value is fractional ("24:00.5"). */
export function formatDuration(seconds: Num): string | null {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return null;
  const negative = seconds < 0;
  const tenthsTotal = Math.round(Math.abs(seconds) * 10);
  const whole = Math.floor(tenthsTotal / 10);
  const tenths = tenthsTotal % 10;
  const h = Math.floor(whole / 3600);
  const m = Math.floor((whole % 3600) / 60);
  const s = whole % 60;
  const sec = tenths ? `${pad2(s)}.${tenths}` : pad2(s);
  const body = h > 0 ? `${h}:${pad2(m)}:${sec}` : `${m}:${sec}`;
  return negative ? `-${body}` : body;
}

/** Seconds per km -> "m:ss /km" (rounded to whole seconds). */
export function formatPace(secPerKm: Num): string | null {
  if (secPerKm === null || secPerKm === undefined || !Number.isFinite(secPerKm)) return null;
  return `${formatDuration(Math.round(secPerKm))} /km`;
}

/** Metres -> "5.00" (km, 2 decimals). */
export function formatKmNumber(metres: Num): string | null {
  if (metres === null || metres === undefined || !Number.isFinite(metres)) return null;
  return (metres / 1000).toFixed(2);
}

/** Metres -> "5.00 km". */
export function formatKm(metres: Num): string | null {
  const n = formatKmNumber(metres);
  return n === null ? null : `${n} km`;
}

/** Metres -> "5000 m" (whole metres, or one decimal when fractional). */
export function formatMetres(metres: Num): string | null {
  if (metres === null || metres === undefined || !Number.isFinite(metres)) return null;
  const rounded = Math.round(metres * 10) / 10;
  return `${Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1)} m`;
}

/** Points are already computed by the API; display with 2 decimals. */
export function formatPoints(points: Num): string | null {
  if (points === null || points === undefined || !Number.isFinite(points)) return null;
  return points.toFixed(2);
}

/** Signed delta "+12.34" / "−3.10" / "0.00". */
export function formatDelta(delta: Num): string | null {
  if (delta === null || delta === undefined || !Number.isFinite(delta)) return null;
  const abs = Math.abs(delta).toFixed(2);
  if (abs === "0.00") return "0.00";
  return delta > 0 ? `+${abs}` : `−${abs}`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function parse(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  // Date-only strings are treated as UTC days.
  const d = new Date(/^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T00:00:00Z` : iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "15 Mar 2024 UTC" */
export function formatDateUTC(iso: string | null | undefined): string | null {
  const d = parse(iso);
  if (!d) return null;
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()} UTC`;
}

/** "15 Mar 2024, 07:00 UTC" */
export function formatDateTimeUTC(iso: string | null | undefined): string | null {
  const d = parse(iso);
  if (!d) return null;
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}, ${pad2(
    d.getUTCHours(),
  )}:${pad2(d.getUTCMinutes())} UTC`;
}

/** ISO instant -> "YYYY-MM-DD" (UTC calendar date). */
export function isoDateUTC(iso: string | null | undefined): string | null {
  const d = parse(iso);
  if (!d) return null;
  return `${d.getUTCFullYear()}-${pad2(d.getUTCMonth() + 1)}-${pad2(d.getUTCDate())}`;
}

export function todayUTC(now: Date = new Date()): string {
  return isoDateUTC(now.toISOString()) as string;
}

/** Calendar arithmetic on "YYYY-MM-DD" in UTC (for period presets only). */
export function addDaysUTC(date: string, days: number): string {
  const d = parse(date) ?? new Date();
  d.setUTCDate(d.getUTCDate() + days);
  return isoDateUTC(d.toISOString()) as string;
}

export function isIsoDate(s: string | null | undefined): s is string {
  return !!s && /^\d{4}-\d{2}-\d{2}$/.test(s) && parse(s) !== null;
}

/**
 * Display name for a runner. Demo labels already end in "(synthetic)"; where the data kind is shown
 * separately (a badge, a group heading or an option suffix) the label's own suffix is dropped so the kind
 * appears once. The stored label is never changed.
 */
export function runnerName(label: string, kind?: string | null): string {
  return kind === "synthetic" ? label.replace(/\s*\(synthetic\)\s*$/i, "") || label : label;
}

/** Text for a runner <option>: the name, plus the data kind once for synthetic runners. */
export function runnerOption(label: string, kind?: string | null): string {
  return kind === "synthetic" ? `${runnerName(label, kind)} · synthetic` : label;
}
