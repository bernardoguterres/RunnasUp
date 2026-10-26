/**
 * Overview building blocks (Running MMR home). Display only: every value comes from /api/mmr/* and
 * /api/participants/{pid}/activities; nothing here computes a rating.
 */
import { useState } from "react";
import type { PointerEvent } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import type { MmrHistoryPoint, MmrOverview, MmrStatus } from "../api/types";
import { DataTable } from "../components/DataTable";
import { Val } from "../components/Missing";
import { ErrorState, Loading } from "../components/States";
import { formatDateTimeUTC, formatDateUTC, formatDuration, formatKm, formatPace } from "../format";
import { useApi } from "../hooks/useApi";
import { activityPath } from "../links";

const CONF: Record<MmrStatus, { text: string; glyph: string; cls: string }> = {
  high: { text: "High evidence coverage", glyph: "●", cls: "badge--success" },
  medium: { text: "Medium evidence coverage", glyph: "◑", cls: "badge--info" },
  low: { text: "Low evidence coverage", glyph: "◔", cls: "badge--warning" },
  "insufficient evidence": { text: "Insufficient evidence", glyph: "○", cls: "badge--neutral" },
};

export function CoverageBadge({ status }: { status: MmrStatus }) {
  const c = CONF[status];
  return (
    <span className={`badge ${c.cls}`}>
      <span aria-hidden="true" className="badge__glyph">
        {c.glyph}
      </span>
      {c.text}
    </span>
  );
}

export const fmtMmr = (v: number | null | undefined) => (v === null || v === undefined ? null : v.toFixed(0));
const big = (v: number) => Math.round(v).toLocaleString("en-GB");

type Range = "90d" | "1y" | "all";
const RANGES: { key: Range; label: string; days: number | null }[] = [
  { key: "90d", label: "90 days", days: 90 },
  { key: "1y", label: "1 year", days: 365 },
  { key: "all", label: "All", days: null },
];
const MONTH = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const iso = (t: number) => new Date(t).toISOString();

/**
 * Running MMR history as a step line (an estimate holds until the next point). The range control only
 * chooses which stored points are drawn; points after the selected as-of date are not shown.
 */
export function MmrHistoryChart({ points, end }: { points: MmrHistoryPoint[]; end: number }) {
  const [range, setRange] = useState<Range>("1y");
  const [hover, setHover] = useState<number | null>(null);
  const days = RANGES.find((r) => r.key === range)!.days;
  const upTo = points.filter((p) => Date.parse(p.at_utc) <= end);
  const t1 = upTo.length ? Date.parse(upTo[upTo.length - 1].at_utc) : end;
  const t0 = days === null ? (upTo.length ? Date.parse(upTo[0].at_utc) : end) : t1 - days * 86400000;
  // the estimate current at the window start, so the line begins at the left edge
  const before = upTo.filter((p) => Date.parse(p.at_utc) < t0);
  const shown = upTo.filter((p) => Date.parse(p.at_utc) >= t0);
  const pts = (before.length ? [{ ...before[before.length - 1], at_utc: iso(t0) }] : []).concat(shown);
  const vals = pts.filter((p) => p.mmr !== null).map((p) => p.mmr as number);
  const changes = shown.filter((p) => p.changed);
  const head = (
    <div className="card__head">
      <h2 id="hist-h" className="card__title">Rating history</h2>
      <div className="seg" role="group" aria-label="History range">
        {RANGES.map((r) => (
          <button key={r.key} type="button" className="seg__btn" aria-pressed={range === r.key} onClick={() => setRange(r.key)}>
            {r.label}
          </button>
        ))}
      </div>
    </div>
  );
  if (vals.length < 2) {
    return (
      <section className="card card--history" aria-labelledby="hist-h">
        {head}
        <p className="muted small">Not enough estimates in this range to draw a history.</p>
      </section>
    );
  }
  const W = 720, H = 260, L = 52, R = 14, T = 12, B = 28;
  const vmin = Math.min(...vals), vmax = Math.max(...vals);
  const step = [10, 25, 50, 100, 200, 250, 500].find((s) => (vmax - vmin) / s <= 4) ?? 1000;
  const lo = Math.floor((vmin - step / 4) / step) * step;
  const hi = Math.ceil((vmax + step / 4) / step) * step;
  const ticks: number[] = [];
  for (let v = lo; v <= hi; v += step) ticks.push(v);
  const x = (t: number) => L + ((t - t0) / Math.max(1, t1 - t0)) * (W - L - R);
  const y = (v: number) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  // step segments, broken where the estimate is missing (insufficient evidence)
  const segs: { d: string; x0: number }[] = [];
  let d = "";
  let x0 = 0;
  for (const p of pts) {
    const px = x(Date.parse(p.at_utc));
    if (p.mmr === null) {
      if (d) segs.push({ d: `${d}H${px.toFixed(1)}`, x0 });
      d = "";
      continue;
    }
    if (d) d += `H${px.toFixed(1)}V${y(p.mmr).toFixed(1)}`;
    else {
      d = `M${px.toFixed(1)},${y(p.mmr).toFixed(1)}`;
      x0 = px;
    }
  }
  if (d) segs.push({ d: `${d}H${x(t1).toFixed(1)}`, x0 });
  const months: number[] = [];
  const m0 = new Date(t0);
  for (let m = m0.getUTCMonth() + 1, yr = m0.getUTCFullYear(); ; m++) {
    const d = Date.UTC(yr + Math.floor(m / 12), m % 12, 1);
    if (d > t1) break;
    months.push(d);
  }
  const every = Math.max(1, Math.ceil(months.length / 8));
  const lastPt = [...pts].reverse().find((p) => p.mmr !== null)!;
  const hp = hover === null ? null : [...pts].reverse().find((p) => Date.parse(p.at_utc) <= hover) ?? null;
  function onMove(e: PointerEvent<SVGSVGElement>) {
    const box = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * W;
    setHover(px < L || px > W - R ? null : t0 + ((px - L) / (W - L - R)) * (t1 - t0));
  }
  return (
    <section className="card card--history" aria-labelledby="hist-h">
      {head}
      <figure className="chart chart--bare">
        <div className="chart__plot">
          <svg viewBox={`0 0 ${W} ${H}`} role="img" onPointerMove={onMove} onPointerLeave={() => setHover(null)}
            aria-label={`Running MMR from ${formatDateUTC(iso(t0))} to ${formatDateUTC(iso(t1))}: ${fmtMmr(vals[0])} at the start, ${fmtMmr(lastPt.mmr)} at the end, range ${fmtMmr(vmin)} to ${fmtMmr(vmax)}. "Show chart data" lists every change.`}>
            {ticks.map((v) => (
              <g key={v}>
                <line className="chart__grid" x1={L} x2={W - R} y1={y(v)} y2={y(v)} />
                <text className="chart__tick" x={L - 8} y={y(v) + 4} textAnchor="end">{v.toLocaleString("en-GB")}</text>
              </g>
            ))}
            {months.map((d, i) => (i % every ? null : (
              <text key={d} className="chart__tick" x={x(d)} y={H - 8} textAnchor="middle">
                {MONTH[new Date(d).getUTCMonth()]}{new Date(d).getUTCMonth() === 0 ? ` ${new Date(d).getUTCFullYear()}` : ""}
              </text>
            )))}
            {segs.map((s) => (
              <g key={s.d}>
                <path className="chart__area" d={`${s.d}V${y(lo).toFixed(1)}H${s.x0.toFixed(1)}Z`} />
                <path className="chart__line" d={s.d} />
              </g>
            ))}
            <circle className="chart__marker--current" cx={x(t1)} cy={y(lastPt.mmr as number)} r={4.5} />
            {hp && hp.mmr !== null && hover !== null ? (
              <g>
                <line className="chart__crosshair" x1={x(hover)} x2={x(hover)} y1={T} y2={H - B} />
                <circle className="chart__marker--current" cx={x(hover)} cy={y(hp.mmr)} r={4} />
              </g>
            ) : null}
          </svg>
          {hp && hover !== null ? (
            <div className="chart__tooltip" role="presentation"
              style={{ left: `${Math.min(68, Math.max(0, ((x(hover) - L) / (W - L - R)) * 100 - 12))}%` }}>
              {hp.mmr === null ? "Insufficient evidence" : `MMR ${fmtMmr(hp.mmr)}`} · since{" "}
              {formatDateUTC(Date.parse(hp.at_utc) < t0 ? iso(t0) : hp.at_utc)}
            </div>
          ) : null}
        </div>
        <figcaption className="small muted">Reconstructed from your current data; each step is a change in the estimate.</figcaption>
      </figure>
      <details className="disclosure">
        <summary>Show chart data ({changes.length} change{changes.length === 1 ? "" : "s"} in range)</summary>
        <DataTable
          caption="Running MMR changes in the chart range"
          captionHidden
          rows={changes}
          rowKey={(c) => c.at_utc}
          empty="No changes in this range."
          columns={[
            { key: "t", header: "When (UTC)", render: (c) => formatDateTimeUTC(c.at_utc) },
            { key: "m", header: "MMR", align: "right", render: (c) => <Val value={fmtMmr(c.mmr)} label="insufficient evidence" /> },
          ]}
        />
      </details>
    </section>
  );
}

/** The current production estimate: the first thing on the page. */
export function ScoreCard({ o }: { o: MmrOverview }) {
  const e = o.estimate;
  return (
    <section className="score-card" aria-labelledby="mmr-h">
      <h2 id="mmr-h" className="score-card__eyebrow">
        Running MMR <CoverageBadge status={e.status} />
      </h2>
      {e.mmr === null ? (
        <>
          <p className="score-card__value score-card__value--none">—</p>
          <p className="score-card__label">Insufficient evidence</p>
          <p className="score-card__note">
            No Run of 3–42.5 km in the last 365 days: missing evidence, not low ability.
          </p>
        </>
      ) : (
        <div className="score-card__main">
          <p className="score-card__value num">{big(e.mmr)}</p>
          <p className="score-card__label">Personal performance estimate</p>
        </div>
      )}
      <div className="score-card__foot">
        <p>
          <strong className="num">{e.supporting}</strong> supporting run{e.supporting === 1 ? "" : "s"}{" "}
          <span className="score-card__dim">within 3 % of the estimate</span>
        </p>
        <p className="score-card__dim">
          As of {formatDateUTC(e.as_of_utc)} · unvalidated estimate, not a race rating or percentile
        </p>
      </div>
    </section>
  );
}

export function SideStats({ o }: { o: MmrOverview }) {
  const e = o.estimate;
  const s = e.setter;
  const aged = s && e.setter_aged_t10_s !== null && s.t10_s !== null && e.setter_aged_t10_s > s.t10_s;
  return (
    <div className="stack">
      <section className="card" aria-labelledby="t10-h">
        <h2 id="t10-h" className="card__label">10 km-equivalent estimate</h2>
        <p className="stat-big num">{e.t10_display ?? "—"}</p>
        <p className="small muted">
          {e.t10_display === null ? "No informative run in the last 365 days."
            : aged ? `Best converted run: recorded ${formatDuration(s!.t10_s)}, counted ${formatDuration(e.setter_aged_t10_s)} after ageing.`
              : "From your best converted run; an estimate."}
        </p>
      </section>
      <section className="card" aria-labelledby="vol-h">
        <h2 id="vol-h" className="card__label">Training summary</h2>
        <dl className="stat-row">
          <div>
            <dt className="small muted">Distance · last 28 days</dt>
            <dd className="stat-mid num">{o.volume.km_last_28d}<span className="stat-unit"> km</span></dd>
          </div>
          <div>
            <dt className="small muted">Runs · last 28 days</dt>
            <dd className="stat-mid num">{o.volume.runs_last_28d}</dd>
          </div>
          <div>
            <dt className="small muted">Active weeks · last 12</dt>
            <dd className="stat-mid num">{o.volume.active_weeks_of_last_12} / 12</dd>
          </div>
        </dl>
        <p className="small muted">Volume does not change MMR: more or longer runs never add points.</p>
      </section>
    </div>
  );
}

export function BehindScore({ o }: { o: MmrOverview }) {
  const e = o.estimate;
  const s = e.setter;
  return (
    <section className="card" aria-labelledby="behind-h">
      <h2 id="behind-h" className="card__title">Behind your score</h2>
      {s ? (
        <div className="evidence">
          <p className="small muted">{s.activity_type} · {formatDateUTC(s.start_utc)}</p>
          <p className="stat-big num">{formatKm(s.distance_m)}</p>
          <p className="small">
            {formatDuration(s.elapsed_s)} elapsed · {formatPace((s.elapsed_s / s.distance_m) * 1000)} /km
            {s.t10_s !== null ? ` · 10 km-equivalent ${formatDuration(s.t10_s)}` : ""}
          </p>
          <p className="small">
            Sets your current estimate{e.best_evidence_age_days !== null ? `; ${Math.round(e.best_evidence_age_days)} days old` : ""}.
          </p>
          {s.flags.length ? (
            <ul className="small warning-list" aria-label="Flags on this activity">
              {s.flags.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          ) : null}
          <Link to={activityPath(o.participant.id, s.activity_id)}>Inspect activity {s.activity_id}</Link>
        </div>
      ) : (
        <p className="small muted">No activity sets an estimate at this date.</p>
      )}
      <p className="small muted">Evidence coverage describes the available evidence, not certainty.</p>
      <details className="disclosure">
        <summary>Calculation details</summary>
        <ul className="small">
          <li>Production method {o.version}, scale {o.scale_version}; as of {formatDateTimeUTC(e.as_of_utc)}.</li>
          <li>{e.informative_90d} / {e.informative_365d} informative runs in the last 90 / 365 days.</li>
          <li>Evidence coverage is a heuristic label, not a calibrated confidence interval: {e.upper_note}.</li>
          <li>Each Run of 3–42.5 km is converted to a 10 km-equivalent with Riegel's formula: an estimate.</li>
          <li>After 30 days evidence counts slightly slower (recency assumption); nothing older than 365 days is used.</li>
          <li>Effort labels are context only; elevation is not adjusted.</li>
          <li><Link to="/method">How ratings work</Link></li>
        </ul>
      </details>
    </section>
  );
}

export function RecentActivities({ pid, to }: { pid: number; to: string | undefined }) {
  const acts = useApi((s) => api.activities(pid, { sort: "start", order: "desc", limit: 5, to }, s), [pid, to]);
  return (
    <section className="card" aria-labelledby="recent-h">
      <div className="card__head">
        <h2 id="recent-h" className="card__title">Recent activities</h2>
        <Link to="/activities">View all activities →</Link>
      </div>
      {acts.error ? <ErrorState error={acts.error} onRetry={acts.reload} title="Could not load activities" /> : null}
      {!acts.data && !acts.error ? <Loading rows={2} /> : null}
      {acts.data ? (
        <DataTable
          caption="Recent activities"
          captionHidden
          rows={acts.data.rows}
          rowKey={(a) => a.id}
          empty="No activities stored."
          columns={[
            { key: "n", header: "Activity", render: (a) => <Link to={activityPath(pid, a.id)}>{a.name ?? `${a.type} ${a.id}`}</Link> },
            { key: "t", header: "Type", render: (a) => a.type },
            { key: "d", header: "Date (UTC)", render: (a) => formatDateUTC(a.start_utc) },
            { key: "k", header: "Distance", align: "right", render: (a) => formatKm(a.distance_m) },
            { key: "p", header: "Elapsed pace", align: "right", render: (a) => `${formatPace(a.pace_s_per_km)} /km` },
            { key: "e", header: "Elapsed", align: "right", render: (a) => formatDuration(a.elapsed_s) },
          ]}
        />
      ) : null}
    </section>
  );
}
