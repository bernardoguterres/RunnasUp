/**
 * Ratings Lab (EXPERIMENTAL). Two explicit data sources: built-in synthetic runners, or histories stored in the
 * database this app was started with (read-only on the server). Every number comes from /api/lab/*
 * (runrank/lab_methods.py). Nothing here is saved, and nothing changes personal Running MMR or race Elo.
 */
import { useState } from "react";
import { api } from "../api/client";
import type { LabActivity, LabCompare, LabMeta, LabMethod, LabParams, LabRunner, LabSourceInfo } from "../api/types";
import { DataTable } from "../components/DataTable";
import { Metric } from "../components/Metric";
import { ErrorState, Loading, Notice } from "../components/States";
import { formatDateUTC, formatDuration, formatKm, formatPace, runnerOption, runnerName } from "../format";
import { useApi } from "../hooks/useApi";

// validated categorical slots (dataviz reference palette, light): identity is also given by direct labels
const SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#6250d6"];
const f0 = (v: number | null | undefined) => (v === null || v === undefined ? "—" : v.toFixed(0));
const sign = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}`;

function HistoryChart({ data }: { data: LabRunner }) {
  const keys = ["combined", ...Object.keys(data.result.components)];
  const series = keys.map((k) => ({
    k,
    pts: data.history
      .map((h) => ({ t: Date.parse(h.at_utc), v: k === "combined" ? h.combined : h.components[k] }))
      .filter((p): p is { t: number; v: number } => p.v !== null && p.v !== undefined),
  })).filter((s) => s.pts.length > 1);
  if (!series.length) return null;
  const W = 760, H = 240, L = 56, R = 110, T = 12, B = 28;
  const all = series.flatMap((s) => s.pts.map((p) => p.v));
  const lo = Math.floor((Math.min(...all) - 40) / 100) * 100;
  const hi = Math.ceil((Math.max(...all) + 40) / 100) * 100;
  const t0 = Date.parse(data.history[0].at_utc);
  const t1 = Date.parse(data.history[data.history.length - 1].at_utc);
  const x = (t: number) => L + ((t - t0) / Math.max(1, t1 - t0)) * (W - L - R);
  const y = (v: number) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  return (
    <figure className="chart">
      <figcaption className="chart__title">Score history (fortnightly and at each activity)</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Lab score history; the current values are listed above">
        {[lo, (lo + hi) / 2, hi].map((v) => (
          <g key={v}>
            <line className="chart__grid" x1={L} x2={W - R} y1={y(v)} y2={y(v)} />
            <text className="chart__tick" x={L - 6} y={y(v) + 4} textAnchor="end">
              {Math.round(v)}
            </text>
          </g>
        ))}
        {series.map((s, i) => {
          const last = s.pts[s.pts.length - 1];
          return (
            <g key={s.k}>
              <polyline fill="none" stroke={SERIES[i % SERIES.length]} strokeWidth={2}
                points={s.pts.map((p) => `${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ")} />
              <text className="chart__tick" x={x(last.t) + 6} y={y(last.v) + 4}>
                {s.k} {Math.round(last.v)}
              </text>
            </g>
          );
        })}
        <text className="chart__tick" x={L} y={H - 6}>{formatDateUTC(data.history[0].at_utc)}</text>
        <text className="chart__tick" x={W - R} y={H - 6} textAnchor="end">{formatDateUTC(data.as_of_utc)}</text>
      </svg>
    </figure>
  );
}

/** which history the Lab reads: a built-in synthetic runner, or a runner stored in the app's database */
type Target = { source: "synthetic"; key: string } | { source: "database"; pid: number };

const fetchRunner = (t: Target, method: LabMethod, p: LabParams, s: AbortSignal) =>
  t.source === "synthetic" ? api.labRunner(t.key, method, p, s) : api.labDbRunner(t.pid, method, p, s);

const KIND: Record<string, string> = { real: "real data", synthetic: "synthetic", unlabelled: "unlabelled (kind not recorded)" };

function sourceText(src: LabSourceInfo) {
  if (src.key === "synthetic") return src.label;
  const db = src.demo_mode ? "the demo database (synthetic runners only)" : `the ${src.database} database`;
  return `${src.label}: ${db}`;
}

function Explain({ target, aid, method, params }: { target: Target; aid: string; method: LabMethod; params: LabParams }) {
  const ex = useApi(
    (s) => (target.source === "synthetic" ? api.labActivity(target.key, aid, method, params, s)
      : api.labDbActivity(target.pid, aid, method, params, s)),
    [JSON.stringify(target), aid, method, JSON.stringify(params)],
  );
  if (ex.error) return <ErrorState error={ex.error} onRetry={ex.reload} />;
  if (!ex.data) return <Loading rows={1} />;
  const e = ex.data;
  return (
    <section className="panel" aria-label="Why this activity changed the score or not">
      <h3 className="panel__title">
        Activity {e.activity.key}: {formatKm(e.activity.distance_m)} in {formatDuration(e.activity.elapsed_s)} ({e.activity.pace}/km),
        effort “{e.activity.effort}”
      </h3>
      <p className="small">
        At its start, without vs with this activity: combined {f0(e.before.combined)} → {f0(e.after.combined)}.{" "}
        {Object.entries(e.deltas).map(([k, v]) => `${k} ${f0(e.before.components[k])} → ${f0(e.after.components[k])} (${sign(v)})`).join("; ")}
      </p>
      <ul className="small">
        {e.reasons.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
    </section>
  );
}

/**
 * Readable names for the predeclared Lab parameters. Each explanation restates what runrank/lab_methods.py does
 * with the value (display text only; the request still sends the raw value).
 */
const PARAM_INFO: Record<string, { label: string; primary?: boolean; option: (v: number | string) => string; help: string }> = {
  speed_weight: {
    label: "Performance weight",
    primary: true,
    option: (v) => `${Math.round(Number(v) * 100)} % performance · ${Math.round((1 - Number(v)) * 100)} % endurance`,
    help: "Combined = weight × performance + (1 − weight) × endurance.",
  },
  aggregation: {
    label: "Combine categories",
    primary: true,
    option: (v) => (v === "specialist" ? "Best category" : "Mean of demonstrated categories"),
    help: "Best: the highest category score. Mean: the average of the categories with evidence; missing categories are not counted as zero.",
  },
  k_best: {
    label: "Evidence needed",
    option: (v) => (Number(v) === 1 ? "Best session" : "Second-best session"),
    help: "Each component uses the k-th best independent session. With the second-best, one outstanding session cannot set it alone, and fewer than two sessions leave it missing.",
  },
  walk_ref_pace_s: {
    label: "Walking reference pace",
    option: (v) => `${formatPace(Number(v))} /km`,
    help: "Endurance credit falls from full to none across this pace ±10 % (moving pace), relaxed slightly with distance (× (km / 10)^0.10).",
  },
  continuity: {
    label: "Stopped time",
    option: (v) => (v === "label" ? "Shown only; distance kept" : "Reduces endurance credit"),
    help: "Shown only: stops are reported and the recorded distance is kept. Reduces: above 5 % stopped, credited distance falls with the stopped share (floor 50 %); without moving time the floor applies.",
  },
  long_performance: {
    label: "Runs over 42.5 km",
    option: (v) => (v === "off" ? "Not scored for performance" : v === "anchor" ? "Separate long-distance score" : "Bridged into performance"),
    help: "Not scored: performance uses 3–42.5 km runs only. Separate: a long-distance score on the synthetic anchor curve. Bridged: up to 250 km converted continuously into performance via the anchor curve.",
  },
  alpha: {
    label: "Update rate",
    option: (v) => `${Math.round(Number(v) * 100)} % of the gap`,
    help: "Each session moves a component up by this share of the gap to the new evidence (never down from an observation).",
  },
  step_max: {
    label: "Largest step per session",
    option: (v) => `${Number(v)} points`,
    help: "Caps how far one session can raise a component.",
  },
  init: {
    label: "Starting value",
    option: (v) => (v === "first" ? "First evidence" : "Fixed start (speed 1000, endurance 0)"),
    help: "First evidence: a component starts at its first session's value. Fixed start: it starts at the anchor and moves up by the update rule.",
  },
};

function ParamField({ k, values, value, onChange }: {
  k: string; values: (number | string)[]; value: number | string; onChange: (v: number | string) => void;
}) {
  const info = PARAM_INFO[k] ?? { label: k, option: String, help: "" };
  return (
    <div className="field">
      <label htmlFor={`lab-${k}`} className="field__label">{info.label}</label>
      <select id={`lab-${k}`} value={String(value)} aria-describedby={info.help ? `lab-${k}-help` : undefined}
        onChange={(e) => onChange(values.find((v) => String(v) === e.target.value)!)}>
        {values.map((v) => (
          <option key={String(v)} value={String(v)}>{info.option(v)}</option>
        ))}
      </select>
      {info.help ? <span id={`lab-${k}-help`} className="field__hint">{info.help}</span> : null}
    </div>
  );
}

function Explore({ meta }: { meta: LabMeta }) {
  // the source never changes by itself: synthetic examples until the user picks the database
  const [source, setSource] = useState<"synthetic" | "database">("synthetic");
  const [runner, setRunner] = useState(meta.runners[0].key);
  const [pid, setPid] = useState<number | null>(null);
  const [asOf, setAsOf] = useState("");          // "" = the server's default (today, UTC) for stored histories
  const [method, setMethod] = useState<LabMethod>("B");
  const [params, setParams] = useState<Record<LabMethod, LabParams>>(
    Object.fromEntries(meta.methods.map((m) => [m.key, { ...m.defaults }])) as Record<LabMethod, LabParams>,
  );
  const [aid, setAid] = useState<string | null>(null);
  const [excluded, setExcluded] = useState<string[]>([]);       // recordings
  const [efforts, setEfforts] = useState<string[]>([]);         // a recording and its identified duplicates
  const [confirmed, setConfirmed] = useState<string[]>([]);
  const [separate, setSeparate] = useState<string[]>([]);
  const reset = () => { setAid(null); setExcluded([]); setEfforts([]); setConfirmed([]); setSeparate([]); };
  const dbInfo = meta.sources.find((x) => x.key === "database");
  const stored = useApi(source === "database" ? (s) => api.labDbRunners(s) : null, [source]);
  const storedRunners = stored.data?.runners ?? [];
  const pidNow = pid ?? storedRunners[0]?.id ?? null;
  const target: Target | null = source === "synthetic" ? { source, key: runner }
    : pidNow === null ? null : { source, pid: pidNow };
  const p: LabParams = { ...params[method], ...(excluded.length ? { exclude: excluded.join(",") } : {}),
    ...(efforts.length ? { exclude_effort: efforts.join(",") } : {}),
    ...(confirmed.length ? { confirm: confirmed.join(",") } : {}),
    ...(separate.length ? { keep_separate: separate.join(",") } : {}),
    ...(source === "database" && asOf ? { as_of: asOf } : {}) };
  const r = useApi(target ? (s) => fetchRunner(target, method, p, s) : null,
    [JSON.stringify(target), method, JSON.stringify(p)]);
  const def = meta.methods.find((m) => m.key === method)!;
  const storedOf = (a: LabActivity) => a.state === "excluded (stored)";
  return (
    <>
      <fieldset className="panel" aria-describedby="lab-source-help">
        <legend className="field__label">Data source</legend>
        {meta.sources.map((x) => (
          <label key={x.key} className="small" style={{ display: "block" }}>
            <input type="radio" name="lab-source" value={x.key} checked={source === x.key} disabled={!x.available}
              onChange={() => { setSource(x.key); reset(); }} />{" "}
            {sourceText(x)}{!x.available && x.reason ? <span className="muted"> (unavailable: {x.reason})</span> : null}
          </label>
        ))}
        <p id="lab-source-help" className="small muted">
          The database is the one this app was started with ({dbInfo?.demo_mode ? "./run.sh demo" : "./run.sh"});
          the Lab never switches between the demo and personal databases. Stored histories are read through a
          read-only connection; Lab exclusions, confirmations and parameters are never saved.
        </p>
      </fieldset>
      {source === "database" && stored.error ? <ErrorState error={stored.error} onRetry={stored.reload} /> : null}
      {source === "database" && stored.data && !storedRunners.length ? (
        <Notice tone="info" title="No stored runners">
          <p>This database has no runners yet. Add a runner and import an export on the Import page first.</p>
        </Notice>
      ) : null}
      <section className="filterbar" aria-label="Lab controls">
        {source === "synthetic" ? (
          <div className="field">
            <label htmlFor="lab-runner" className="field__label">Fictional runner</label>
            <select id="lab-runner" value={runner} onChange={(e) => { setRunner(e.target.value); reset(); }}>
              {meta.runners.map((x) => (
                <option key={x.key} value={x.key}>{x.label}</option>
              ))}
            </select>
          </div>
        ) : (
          <>
            <div className="field">
              <label htmlFor="lab-stored" className="field__label">Stored runner</label>
              <select id="lab-stored" value={pidNow ?? ""} disabled={!storedRunners.length}
                onChange={(e) => { setPid(Number(e.target.value)); reset(); }}>
                {storedRunners.map((x) => (
                  <option key={x.id} value={x.id}>{runnerOption(x.label, x.data_kind)}, {x.activities} activities</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="lab-asof" className="field__label">As of (UTC date)</label>
              <input id="lab-asof" type="date" value={asOf || r.data?.source.as_of_date || ""}
                onChange={(e) => { setAsOf(e.target.value); setAid(null); }} />
            </div>
          </>
        )}
        <div className="field">
          <label htmlFor="lab-method" className="field__label">Method</label>
          <select id="lab-method" value={method} onChange={(e) => setMethod(e.target.value as LabMethod)}>
            {meta.methods.map((m) => (
              <option key={m.key} value={m.key}>{m.name}</option>
            ))}
          </select>
        </div>
        {Object.entries(def.params).filter(([k]) => PARAM_INFO[k]?.primary).map(([k, values]) => (
          <ParamField key={k} k={k} values={values} value={p[k]}
            onChange={(v) => setParams((cur) => ({ ...cur, [method]: { ...cur[method], [k]: v } }))} />
        ))}
      </section>
      {Object.keys(def.params).some((k) => !PARAM_INFO[k]?.primary) ? (
        <details className="disclosure lab-advanced">
          <summary>Advanced settings ({def.name.split(":")[0]})</summary>
          <div className="param-grid">
            {Object.entries(def.params).filter(([k]) => !PARAM_INFO[k]?.primary).map(([k, values]) => (
              <ParamField key={k} k={k} values={values} value={p[k]}
                onChange={(v) => setParams((cur) => ({ ...cur, [method]: { ...cur[method], [k]: v } }))} />
            ))}
          </div>
        </details>
      ) : null}
      {r.data ? (
        <section className="panel" aria-label="Active source" role="status">
          <p className="small">
            <strong>Active source:</strong> {sourceText(r.data.source)}. Runner: <strong>{runnerName(r.data.runner.label, r.data.runner.data_kind)}</strong>{" "}
            ({KIND[r.data.runner.data_kind] ?? r.data.runner.data_kind}).
          </p>
          <p className="small">
            <strong>As of {r.data.source.as_of_date}</strong> ({r.data.source.as_of_basis}
            {r.data.source.today && r.data.source.as_of_date !== r.data.source.today ? `; today is ${r.data.source.today}` : ""}).{" "}
            {source === "database" ? (
              <>
                {asOf ? <button type="button" className="link-button" onClick={() => { setAsOf(""); setAid(null); }}>Use today</button> : null}
                {r.data.latest_activity_utc && r.data.latest_activity_utc.slice(0, 10) !== r.data.source.as_of_date ? (
                  <>
                    {asOf ? " · " : ""}
                    <button type="button" className="link-button"
                      onClick={() => { setAsOf(r.data!.latest_activity_utc!.slice(0, 10)); setAid(null); }}>
                      Use the latest activity date ({r.data.latest_activity_utc.slice(0, 10)})
                    </button>
                  </>
                ) : null}
              </>
            ) : null}
          </p>
          <p className="small muted">
            Method {r.data.method} ({def.name}) · {r.data.version} · settings:{" "}
            {Object.entries(r.data.params).map(([k, v]) => `${PARAM_INFO[k]?.label ?? k}: ${PARAM_INFO[k]?.option(v) ?? String(v)}`).join("; ") || "none"}{" "}
            <span className="nowrap">({Object.entries(r.data.params).map(([k, v]) => `${k}=${String(v)}`).join(", ") || "no parameters"})</span>
          </p>
        </section>
      ) : null}
      {r.data?.coverage_notes.length ? (
        <Notice tone="info" title="Why a score may be missing">
          <ul className="small">
            {r.data.coverage_notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </Notice>
      ) : null}
      {r.error ? <ErrorState error={r.error} onRetry={r.reload} /> : null}
      {!r.data && !r.error ? <Loading label="Calculating…" /> : null}
      {r.data ? (
        <>
          <dl className="metrics">
            <Metric label="Combined (experimental)" value={f0(r.data.result.combined)} hint={method === "A" ? "the app's current Running MMR" : "fixed-scale points; weights are product choices"} />
            {Object.entries(r.data.result.components).map(([k, v]) => {
              const why = r.data!.explanation?.components.find((c) => c.component === k);
              const hint = v === null ? "missing evidence (not zero)" : why?.warnings.length ? (
                <span className="warning-text" role="note" aria-label={`Warning for ${k}`}>
                  ⚠ set by flagged activity {why.activity}: {why.warnings[0]}
                </span>
              ) : why?.provisional ? "provisional: not yet corroborated" : undefined;
              return <Metric key={k} label={k} value={f0(v)} hint={hint} />;
            })}
          </dl>
          {r.data.explanation ? (
            <section className="panel" aria-labelledby="lab-why-h">
              <h2 id="lab-why-h" className="panel__title">How this score is determined</h2>
              <ul className="small">
                {r.data.explanation.components.map((c) => (
                  <li key={c.component}>
                    <strong>{c.component} {f0(c.value)}</strong>: set by activity{" "}
                    <button type="button" className="link-button" onClick={() => setAid(c.activity)}>{c.activity}</button>{" "}
                    ({formatDateUTC(c.date)}; {c.detail}){c.provisional ? ", provisional" : ""}. Raised by {c.raises};
                    lowered {c.lowers}.
                    {c.warnings.length ? <span className="warning-text"> ⚠ {c.warnings.join(" ⚠ ")}</span> : null}
                  </li>
                ))}
              </ul>
              <p className="small">{r.data.explanation.weighting}</p>
              <details>
                <summary className="small">Unvalidated assumptions</summary>
                <ul className="small">
                  {r.data.explanation.unvalidated.map((u) => (
                    <li key={u}>{u}</li>
                  ))}
                </ul>
              </details>
            </section>
          ) : null}
          {r.data.result.notes.map((n) => (
            <p key={n} className="small muted">{n}</p>
          ))}
          {r.data.result.selected.length ? (
            <DataTable
              caption="Evidence behind each component"
              rows={r.data.result.selected}
              rowKey={(x) => x.component}
              columns={[
                { key: "c", header: "Component", render: (x) => x.component },
                { key: "v", header: "Points", align: "right", render: (x) => f0(x.value) },
                { key: "a", header: "Activity", render: (x) => (
                  <button type="button" className="link-button" onClick={() => setAid(x.activity)}>{x.activity}</button>
                ) },
                { key: "d", header: "Date (UTC)", render: (x) => formatDateUTC(x.date) },
                { key: "e", header: "Evidence", render: (x) => x.detail },
                { key: "p", header: "Status", render: (x) => (x.provisional ? <strong>provisional</strong> : "corroborated") },
                { key: "q", header: "Data-quality concerns", render: (x) => (x.concerns.length ? x.concerns.join("; ") : "none") },
              ]}
            />
          ) : null}
          <HistoryChart data={r.data} />
          {r.data.comparator ? <p className="small"><strong>Method A:</strong> {r.data.comparator}</p> : null}
          {r.data.override_impact.excluded_ids.length ? (
            <section className="panel" aria-label="Lab exclusions">
              <p className="small">
                Excluded in this Lab view only (not stored):{" "}
                {[...excluded.map((k) => `recording ${k}`),
                  ...r.data.excluded_efforts.map((e) => `effort of ${e.key} (recordings ${e.recordings.join(", ")})`)].join("; ")}
                . Removed activity ids: {r.data.override_impact.excluded_ids.join(", ")}.{" "}
                <button type="button" className="link-button" onClick={() => { setExcluded([]); setEfforts([]); }}>Include all again</button>
              </p>
              <p className="small">
                Score impact: combined {f0(r.data.override_impact.without_lab_overrides.combined)} →{" "}
                {f0(r.data.override_impact.with.combined)}
                {Object.keys(r.data.override_impact.with.components).map((k) =>
                  `; ${k} ${f0(r.data!.override_impact.without_lab_overrides.components[k])} → ${f0(r.data!.override_impact.with.components[k])}`).join("")}
                {" "}(without vs with all Lab overrides).
              </p>
            </section>
          ) : null}
          {aid && target && !r.data.override_impact.excluded_ids.includes(aid) && !r.data.activities.some((a) => a.key === aid && storedOf(a)) ? (
            <Explain target={target} aid={aid} method={method} params={p} />
          ) : null}
          <DataTable<LabActivity>
            caption={`Input history: ${r.data.runner.label} (${r.data.activities.length} ${source === "synthetic" ? "synthetic" : "stored"} activities, newest first)`}
            empty="No activities stored for this runner."
            rows={r.data.activities}
            rowKey={(a) => a.key}
            columns={[
              { key: "d", header: "Date (UTC)", render: (a) => formatDateUTC(a.start_utc) },
              { key: "t", header: "Type", render: (a) => a.type },
              { key: "km", header: "Distance", align: "right", sortValue: (a) => a.distance_m, render: (a) => formatKm(a.distance_m) },
              { key: "el", header: "Elapsed", align: "right", render: (a) => formatDuration(a.elapsed_s) },
              { key: "mv", header: "Moving", align: "right", render: (a) => formatDuration(a.moving_s) ?? "—" },
              { key: "p", header: "Pace (elapsed)", align: "right", render: (a) => formatPace(a.elapsed_s / a.distance_m * 1000) },
              { key: "e", header: "Effort label", render: (a) => a.effort },
              { key: "st", header: "State", render: (a) => (a.state === "held" ? (
                <>
                  <strong>held</strong>{" "}
                  <button type="button" className="link-button" onClick={() => setConfirmed((cur) => [...cur, a.key])}
                    aria-label={`Confirm activity ${a.key} is a separate activity`}>Confirm separate</button>
                </>
              ) : a.reasons.length ? (
                <>
                  <strong>{a.state}</strong>
                  <span className="small muted">: {a.reasons.join("; ")}</span>
                </>
              ) : a.state) },
              { key: "u", header: "Used as", render: (a) => (a.dropped ? (
                <span className="muted">
                  {a.dropped}{" "}
                  {a.duplicate_of ? (
                    <button type="button" className="link-button" onClick={() => setSeparate((cur) => [...cur, a.key])}
                      aria-label={`Keep activity ${a.key} separate`}>Keep separate</button>
                  ) : null}
                </span>
              ) : (
                <>
                  {a.used_for.join(", ") || <span className="muted">not used</span>}
                  {a.provenance?.stored_not_duplicate ? <span className="muted"> (stored: not a duplicate)</span> : null}
                </>
              )) },
              { key: "ck", header: "Endurance credit", align: "right", render: (a) => (a.credited_km === null ? "—" : `${a.credited_km.toFixed(2)} km`) },
              { key: "ct", header: "Continuity", render: (a) => a.continuity ?? "—" },
              { key: "fl", header: "Review flags", render: (a) => (a.flags.length ? a.flags.join("; ") : "") },
              ...(source === "database" ? [{ key: "pv", header: "Stored as", render: (a: LabActivity) => (a.provenance ? (
                <span className="small">
                  id {a.provenance.source_activity_id ?? "—"} · {a.provenance.import_file ?? "—"}
                  {a.provenance.missing.length ? <span className="muted"> · missing: {a.provenance.missing.join(", ")}</span> : null}
                </span>
              ) : "—") }] : []),
              { key: "x", header: "Why?", render: (a) => (storedOf(a) ? "" : (
                <button type="button" className="link-button" onClick={() => setAid(a.key)} aria-label={`Explain activity ${a.key}`}>Explain</button>
              )) },
              { key: "ex", header: "Exclude (Lab only)", render: (a) => (storedOf(a) ? <span className="muted">stored</span> : (
                <>
                  <button type="button" className="link-button" onClick={() => setExcluded((cur) => [...cur, a.key])}
                    aria-label={`Exclude activity ${a.key} in the Lab`}
                    title="Exclude this recording; another valid recording of the same effort may count">Recording</button>
                  {a.duplicate_group.length > 1 ? (
                    <>
                      {" · "}
                      <button type="button" className="link-button" onClick={() => setEfforts((cur) => [...cur, a.key])}
                        aria-label={`Exclude the effort of activity ${a.key} (recordings ${a.duplicate_group.join(", ")})`}
                        title="Exclude this effort: every identified duplicate recording of it">
                        Effort ({a.duplicate_group.join(", ")})
                      </button>
                    </>
                  ) : null}
                </>
              )) },
            ]}
          />
        </>
      ) : null}
    </>
  );
}

function Compare() {
  const c = useApi((s) => api.labCompare(s), []);
  if (c.error) return <ErrorState error={c.error} onRetry={c.reload} />;
  if (!c.data) return <Loading label="Calculating every runner under every method…" />;
  const d: LabCompare = c.data;
  const configs = d.rows[0].cells.map((x) => x.config);
  const t = d.tradeoffs;
  return (
    <>
      <DataTable
        caption={`Combined scores as of ${formatDateUTC(d.as_of_utc)} (synthetic runners; fixed scales)`}
        rows={d.rows}
        rowKey={(r) => r.runner}
        columns={[
          { key: "r", header: "Runner (activities · longest · races)", render: (r) => `${r.label} (${r.activities} · ${r.longest_km.toFixed(1)} km · ${r.races})` },
          ...configs.map((cfg, i) => ({
            key: cfg, header: cfg, align: "right" as const, sortValue: (r: LabCompare["rows"][number]) => r.cells[i].combined,
            render: (r: LabCompare["rows"][number]) => f0(r.cells[i].combined),
          })),
          { key: "comp", header: "B components (speed / endurance)", render: (r) => {
            const b = r.cells.find((x) => x.config === "B 50/50")!;
            return `${f0(b.components.speed)} / ${f0(b.components.endurance)}`;
          } },
        ]}
      />
      <DataTable
        caption="What method B rewards (default parameters; change in points)"
        rows={d.improvements}
        rowKey={(r) => r.label}
        columns={[
          { key: "l", header: "Change", render: (r) => r.label },
          { key: "s", header: "Speed", align: "right", render: (r) => sign(r.dS) },
          { key: "e", header: "Endurance", align: "right", render: (r) => sign(r.dE) },
          { key: "a", header: "75/25", align: "right", render: (r) => sign(r.d75) },
          { key: "b", header: "50/50", align: "right", render: (r) => sign(r.d50) },
          { key: "c", header: "25/75", align: "right", render: (r) => sign(r.d25) },
        ]}
      />
      <DataTable
        caption="Matched examples: what method B (bridged performance) rewards"
        rows={d.matched}
        rowKey={(r) => r.label}
        columns={[
          { key: "l", header: "Change", render: (r) => r.label },
          { key: "p", header: "Performance", align: "right", render: (r) => `${f0(r.P_before)} → ${f0(r.P_after)}` },
          { key: "e", header: "Endurance", align: "right", render: (r) => `${f0(r.E_before)} → ${f0(r.E_after)}` },
          { key: "a", header: "75/25", align: "right", render: (r) => sign(r.d75) },
          { key: "b", header: "50/50", align: "right", render: (r) => sign(r.d50) },
          { key: "c", header: "25/75", align: "right", render: (r) => sign(r.d25) },
          { key: "k", header: "Continuity", render: (r) => r.continuity_after },
        ]}
      />
      <p className="small muted">
        Distance enters twice: through performance normalisation (the same pace held for longer converts to a better
        10 km-equivalent) and through endurance. Moving time changes no number, only the continuity label.
      </p>
      <p className="small muted">
        Scale slopes: 1 % faster ≈ +19.5 speed points; 1 % longer ≈ +5.4 endurance points (log scales with different
        anchors). Equal weights therefore do not mean equal value: at 50/50, 1 % of speed is worth about 3.6 % of
        distance.
      </p>
      <section className="section" aria-labelledby="to-h">
        <h2 id="to-h" className="section-title">Trade-offs (computed probes, not commentary)</h2>
        <h3 className="subhead">Who benefits from more endurance weight? (combined at 25/75 minus 75/25)</h3>
        <ul className="small">
          {t.endurance_weight.map((x) => (
            <li key={x.runner}>{x.label}: B {sign(x.B)}, D {sign(x.D)}</li>
          ))}
        </ul>
        <h3 className="subhead">Does balanced aggregation reward having more categories?</h3>
        <p className="small">
          {t.breadth.probe}: specialist {f0(t.breadth.specialist[0])} → {f0(t.breadth.specialist[1])}; balanced{" "}
          {f0(t.breadth.balanced[0])} → {f0(t.breadth.balanced[1])}.
        </p>
        <h3 className="subhead">Does a method overreact to one outlier?</h3>
        <p className="small">
          {t.outlier.probe}: {t.outlier.effects.map((x) => `${x.config} ${sign(x.delta)}`).join("; ")}.
        </p>
        <h3 className="subhead">Can more uploads or withheld effort labels raise the score?</h3>
        <p className="small">
          {t.gaming.more_uploads_probe}: {t.gaming.more_uploads.map((x) => `${x.config} ${sign(x.delta)}`).join("; ")}.
        </p>
        <p className="small">
          {t.gaming.withheld_probe}: {t.gaming.withheld_labels.map((x) => `${x.config} ${sign(x.delta_speed_races)} / ${sign(x.delta_hard_8km)}`).join("; ")}.
        </p>
      </section>
    </>
  );
}

export function LabPage() {
  const meta = useApi((s) => api.labMeta(s), []);
  const [tab, setTab] = useState<"explore" | "compare">("explore");
  return (
    <div className="page">
      <header className="page__header">
        <h1 className="page__title">Ratings Lab (experimental)</h1>
        <p className="exp-note" role="status">
          <strong>Experimental · changes are not saved.</strong>{" "}
          <span className="muted">Nothing changes your stored activities, Running MMR or race Elo.</span>
        </p>
        <details className="disclosure">
          <summary>About these methods and their limitations</summary>
          <p className="small prose">
            Explore the built-in synthetic examples or the histories already stored in this app's database. Methods
            B–D are candidates under study and are not your Running MMR; method A runs the production calculation as
            a comparator. Scores use fixed synthetic anchors: they are not population standards and are not
            validated.
          </p>
        </details>
      </header>
      <div className="segmented" role="group" aria-label="Lab view">
        <button type="button" className="segmented__btn" aria-pressed={tab === "explore"} onClick={() => setTab("explore")}>Explore a runner</button>
        <button type="button" className="segmented__btn" aria-pressed={tab === "compare"} onClick={() => setTab("compare")}>Compare runners</button>
        <span className="small muted"> (comparison uses the synthetic examples only)</span>
      </div>
      {meta.error ? <ErrorState error={meta.error} onRetry={meta.reload} /> : null}
      {!meta.data && !meta.error ? <Loading /> : null}
      {meta.data && tab === "explore" ? <Explore meta={meta.data} /> : null}
      {meta.data && tab === "compare" ? <Compare /> : null}
      {meta.data ? (
        <details className="panel">
          <summary>Scales, generator assumptions</summary>
          <ul className="small">
            {meta.data.scales.map((s) => (
              <li key={s}>{s}</li>
            ))}
            <li>
              Supported range for method B: {meta.data.supported_range_km[0]}–{meta.data.supported_range_km[1]} km
              (performance and endurance). Activities outside it are kept and listed, but not scored; nothing is clamped.
              The anchor curve covers {meta.data.curve_range_km[0]}–{meta.data.curve_range_km[1]} km.
            </li>
            <li>
              Anchor curve (synthetic assumption, not an established elite reference):{" "}
              {meta.data.anchors.map((x) => `${x.km} km ${formatDuration(x.time_s)}`).join(", ")}.
            </li>
            <li>{meta.data.generator}</li>
          </ul>
        </details>
      ) : null}
    </div>
  );
}
