/**
 * Running MMR (primary rating). Every number comes from /api/mmr/* (runrank/mmr.py); nothing is computed here.
 */
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api, ApiError } from "../api/client";
import type { MmrBand, MmrComparisonRow } from "../api/types";
import { Icon } from "../components/AppShell";
import { BehindScore, CoverageBadge, fmtMmr, MmrHistoryChart, RecentActivities, ScoreCard, SideStats } from "./OverviewParts";
import { DataTable } from "../components/DataTable";
import { Metric } from "../components/Metric";
import { Val } from "../components/Missing";
import { EmptyState, ErrorState, Loading, Notice } from "../components/States";
import { activityPath } from "../links";
import { formatDateTimeUTC, formatDateUTC, formatDelta, formatDuration, formatKm, formatPace, isIsoDate, isoDateUTC, runnerName } from "../format";
import { useApi } from "../hooks/useApi";
import { useAppState } from "../state/AppState";

export { CoverageBadge, fmtMmr } from "./OverviewParts";

/** Ultras and very short runs are kept but do not feed MMR: say so wherever MMR is shown. */
function NotConvertedNotice({ bands }: { bands: MmrBand[] }) {
  const long = bands.find((b) => !b.converted && b.label.startsWith("over"));
  const short = bands.find((b) => !b.converted && b.label.startsWith("under"));
  if (!long?.count && !short?.count) return null;
  return (
    <Notice tone="warning" title="Some runs do not contribute to Running MMR" role="status">
      <p className="small">
        {long?.count ? (
          <>
            <strong>{long.count}</strong> run{long.count === 1 ? "" : "s"} over 42.5 km (ultra
            {long.longest_m ? `; longest ${formatKm(long.longest_m)}` : ""}){" "}
          </>
        ) : null}
        {long?.count && short?.count ? "and " : ""}
        {short?.count ? (
          <>
            <strong>{short.count}</strong> run{short.count === 1 ? "" : "s"} under 3 km{" "}
          </>
        ) : null}
        in the last 365 days are kept but do <strong>not</strong> change your MMR: the 10 km conversion is not valid
        that far from 10 km, so ultra ability is not represented in this number. See{" "}
        <Link to="/activities?min_km=42.5">activities over 42.5 km</Link>.
      </p>
    </Notice>
  );
}

function GetStartedMmr() {
  const { health, reloadParticipants } = useAppState();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  async function load() {
    setBusy(true);
    setErr(null);
    try {
      await api.loadDemoHistories();
      reloadParticipants();
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError("unknown", String(e), 0));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page">
      <h1 className="page__title">Overview</h1>
      <EmptyState
        title="Upload a running history to get a Running MMR"
        action={
          <div className="actions">
            <Link className="btn btn--primary" to="/import">
              Import a Strava export
            </Link>
            {health?.demo_mode ? (
              <button type="button" className="btn" onClick={load} disabled={busy}>
                {busy ? "Loading…" : "Load synthetic histories"}
              </button>
            ) : null}
          </div>
        }
      >
        <p>Your whole history is enough: no races or opponents are needed. Everything stays on this computer.</p>
      </EmptyState>
      {err ? <ErrorState error={err} title="Could not load the synthetic histories" /> : null}
    </div>
  );
}

export function MmrOverviewPage() {
  const { participants, participantId } = useAppState();
  const [asOf, setAsOf] = useState("");
  const pid = participantId;
  const ov = useApi(pid === null ? null : (s) => api.mmr(pid, isIsoDate(asOf) ? asOf : undefined, s), [pid, asOf]);
  const hist = useApi(pid === null ? null : (s) => api.mmrHistory(pid, s), [pid]);
  if (participants && (participants.length === 0 || participants.every((p) => p.activity_count === 0))) return <GetStartedMmr />;
  if (pid === null || (!ov.data && !ov.error)) return <Loading label="Loading Running MMR…" />;
  if (ov.error) return <ErrorState error={ov.error} onRetry={ov.reload} title="Could not load Running MMR" />;
  const o = ov.data!;
  const q = o.quality;
  return (
    <div className="page page--overview">
      <header className="page-head">
        <div className="page-head__text">
          <h1 className="page-head__title">Your running, in perspective</h1>
          <p className="muted">Your current estimate, backed by your own activities.</p>
        </div>
        <div className="page-head__actions">
          <div className="field field--date">
            <label htmlFor="mmr-asof" className="field__label">As of (UTC)</label>
            <input id="mmr-asof" type="date" value={asOf || (isoDateUTC(o.estimate.as_of_utc) ?? "")}
              onChange={(e) => setAsOf(e.target.value)} />
          </div>
          <Link className="btn btn--primary btn--lg" to="/import">
            <Icon name="upload" /> Import history
          </Link>
        </div>
      </header>

      <div className="overview-hero">
        <ScoreCard o={o} />
        <SideStats o={o} />
      </div>
      <NotConvertedNotice bands={o.bands} />

      <div className="overview-row">
        {hist.data ? <MmrHistoryChart points={hist.data.points} end={Date.parse(o.estimate.as_of_utc)} />
          : hist.error ? <ErrorState error={hist.error} onRetry={hist.reload} title="Could not load the history" />
            : <section className="card card--history"><Loading rows={3} label="Loading history…" /></section>}
        <BehindScore o={o} />
      </div>

      <section className="card" aria-labelledby="traj-h">
        <h2 id="traj-h" className="card__title">Recent MMR changes</h2>
        <DataTable
          caption="Recent MMR changes"
          captionHidden
          rows={o.recent_changes}
          rowKey={(c) => c.at_utc}
          empty="No changes yet."
          columns={[
            { key: "t", header: "When (UTC)", render: (c) => formatDateTimeUTC(c.at_utc) },
            { key: "m", header: "MMR", align: "right", render: (c) => <Val value={fmtMmr(c.mmr)} label="insufficient evidence" /> },
            { key: "c", header: "Evidence coverage", render: (c) => <CoverageBadge status={c.status} /> },
            { key: "e", header: "Why", render: (c) => c.explanation.join(" ") },
            {
              key: "x",
              header: "Explain",
              render: (c) => <Link to={`/mmr/explain?runner=${o.participant.id}&at=${encodeURIComponent(c.at_utc)}`}>Explain</Link>,
            },
          ]}
        />
      </section>

      <div className="overview-row overview-row--even">
        <section className="card" aria-labelledby="bands-h">
          <h2 id="bands-h" className="card__title">
            Evidence by distance <span className="card__period">last 365 days</span>
          </h2>
          <DataTable
            caption="Evidence by distance"
            captionHidden
            rows={o.bands}
            rowKey={(b) => b.label}
            columns={[
              { key: "l", header: "Distance", render: (b) => b.label },
              { key: "n", header: "Runs", align: "right", render: (b) => b.count },
              {
                key: "best",
                header: "Best 10 km-equivalent",
                align: "right",
                render: (b) => (b.converted ? <Val value={formatDuration(b.best_t10_s)} label="none" /> : <span className="muted">not converted</span>),
              },
              { key: "pace", header: "Best pace", align: "right", render: (b) => <Val value={formatPace(b.best_pace_s_per_km)} label="none" /> },
            ]}
          />
        </section>
        <section className="card" aria-labelledby="dq-h">
          <h2 id="dq-h" className="card__title">Data quality</h2>
          <p className="small">
            {q.activities} activities stored ({q.first_utc ? `${formatDateUTC(q.first_utc)} – ${formatDateUTC(q.last_utc)}` : "none"}
            ); <strong>{q.informative}</strong> informative for MMR. Import rows rejected: {q.rows_rejected} of {q.rows_imported}.
          </p>
          <p className="small">{q.by_type.map((t) => `${t.type}: ${t.count}`).join(" · ")}</p>
          <details className="disclosure">
            <summary>Unused activities and missing fields</summary>
            {q.not_informative.length ? (
              <ul className="small">
                {q.not_informative.map((r) => (
                  <li key={r.reason}>
                    {r.reason}: {r.count}
                  </li>
                ))}
              </ul>
            ) : null}
            <p className="small muted">
              Missing: heart rate {q.missing.heart_rate}, elevation {q.missing.elevation}, moving time {q.missing.moving_time}
              , perceived exertion {q.missing.perceived_exertion} (none of these are needed). Hilly runs flagged: {q.hilly}.
              Declared hard or race efforts: {q.declared_efforts}.
            </p>
          </details>
        </section>
      </div>

      <RecentActivities pid={o.participant.id} to={isIsoDate(asOf) ? asOf : undefined} />

      <details className="card disclosure">
        <summary>What the app showed after each import or annotation ({o.snapshots.length})</summary>
        <DataTable
          caption="Stored MMR calculations"
          captionHidden
          rows={o.snapshots}
          rowKey={(s) => `${s.computed_utc}-${s.trigger}`}
          empty="No stored calculation yet."
          columns={[
            { key: "t", header: "Computed (UTC)", render: (s) => formatDateTimeUTC(s.computed_utc) },
            { key: "g", header: "Trigger", render: (s) => s.trigger },
            { key: "m", header: "MMR at latest activity", align: "right", render: (s) => <Val value={fmtMmr(s.mmr)} label="insufficient evidence" /> },
            { key: "n", header: "Activities", align: "right", render: (s) => s.activities },
            { key: "v", header: "Version", render: (s) => s.algorithm_version },
          ]}
        />
      </details>
    </div>
  );
}

export function MmrComparePage() {
  const [asOf, setAsOf] = useState("");
  const cmp = useApi((s) => api.mmrComparison(isIsoDate(asOf) ? asOf : undefined, s), [asOf]);
  const groups: { kind: MmrComparisonRow["participant"]["data_kind"]; title: string }[] = [
    { kind: "real", title: "Real runners" },
    { kind: "synthetic", title: "Synthetic demo runners" },
    { kind: "unlabelled", title: "Runners with no recorded data kind" },
  ];
  return (
    <div className="page">
      <header className="page-head">
        <div className="page-head__text">
        <h1 className="page__title">Compare Running MMR</h1>
        <p className="muted">Each runner's own estimate on one absolute scale; real and synthetic runners separately.</p>
        <details className="disclosure">
          <summary>How this comparison works</summary>
          <p className="small">
            Each runner's MMR comes only from their own history on an absolute scale, so adding a runner never changes
            anyone else's number. Ranked only with medium or high evidence coverage (a heuristic label, not calibrated
            confidence). A difference of about 20 points is about 1 % of speed, not a win probability.
          </p>
        </details>
        </div>
        <div className="page-head__actions">
          <div className="field">
            <label htmlFor="mmr-cmp-asof" className="field__label">As of (UTC)</label>
            <input id="mmr-cmp-asof" type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)}
              aria-describedby="mmr-cmp-asof-hint" />
            <span id="mmr-cmp-asof-hint" className="field__hint">Empty: each runner's latest data in the demo, otherwise today</span>
          </div>
        </div>
      </header>
      {cmp.error ? <ErrorState error={cmp.error} onRetry={cmp.reload} /> : null}
      {!cmp.data && !cmp.error ? <Loading /> : null}
      {cmp.data && cmp.data.rows.length === 0 ? <EmptyState title="No runners yet" /> : null}
      {cmp.data
        ? groups.map(({ kind, title }) => {
            const rows = cmp.data!.rows.filter((r) => r.participant.data_kind === kind);
            if (!rows.length) return null;
            return (
              <section key={kind} className="section" aria-labelledby={`mc-${kind}`}>
                <h2 id={`mc-${kind}`} className="section-title">
                  {title}
                </h2>
                <DataTable<MmrComparisonRow>
                  caption={`${title}: Running MMR`}
                  captionHidden
                  rows={rows}
                  rowKey={(r) => r.participant.id}
                  columns={[
                    { key: "r", header: "Rank", align: "right", render: (r) => r.rank ?? <span className="small muted">unranked</span> },
                    {
                      key: "p",
                      header: "Runner",
                      // the group heading states the data kind once; groups never mix kinds
                      render: (r) => runnerName(r.participant.label, r.participant.data_kind),
                    },
                    { key: "m", header: "Running MMR", align: "right", sortValue: (r) => r.estimate.mmr, render: (r) => <Val value={fmtMmr(r.estimate.mmr)} label="insufficient evidence" /> },
                    { key: "t", header: "10 km-equivalent", align: "right", render: (r) => <Val value={r.estimate.t10_display} label="—" /> },
                    { key: "c", header: "Evidence coverage", render: (r) => <CoverageBadge status={r.estimate.status} /> },
                    { key: "s", header: "Supporting runs", align: "right", render: (r) => r.estimate.supporting },
                    { key: "a", header: "As of (UTC)", render: (r) => formatDateUTC(r.estimate.as_of_utc) },
                  ]}
                />
              </section>
            );
          })
        : null}
    </div>
  );
}

export function MmrExplainPage() {
  const [sp] = useSearchParams();
  const { participantId } = useAppState();
  const pid = Number(sp.get("runner") ?? participantId);
  const at = sp.get("at") ?? "";
  const ex = useApi(at && Number.isInteger(pid) ? (s) => api.mmrExplain(pid, at, s) : null, [pid, at]);
  if (!at) return <EmptyState title="Pick a change to explain">Open a runner's Running MMR page and choose Explain on a change.</EmptyState>;
  if (ex.error) return <ErrorState error={ex.error} onRetry={ex.reload} title="Could not explain this change" />;
  if (!ex.data) return <Loading />;
  const e = ex.data;
  return (
    <div className="page">
      <p className="back-link">
        <Link to="/">← Running MMR</Link>
      </p>
      <h1 className="page__title">MMR change at {formatDateTimeUTC(e.at_utc)}</h1>
      <dl className="metrics">
        <Metric label="Before" value={<Val value={fmtMmr(e.before?.mmr)} label="no estimate" />} />
        <Metric label="Change" value={<Val value={formatDelta(e.delta)} label="—" />} />
        <Metric label="After" value={<Val value={fmtMmr(e.after.mmr)} label="insufficient evidence" />} hint={<CoverageBadge status={e.after.status} />} />
      </dl>
      <ul>
        {e.explanation.map((x) => (
          <li key={x}>{x}</li>
        ))}
      </ul>
      {e.activities.length ? (
        <p className="small">
          Activities at this instant:{" "}
          {e.activities.map((a) => (
            <Link key={a} to={activityPath(pid, a)} className="nowrap">
              {a}{" "}
            </Link>
          ))}
        </p>
      ) : (
        <p className="small muted">No activity at this instant: a weekly reconstruction point (aging of older evidence).</p>
      )}
    </div>
  );
}

/** Activity detail: what this activity means for Running MMR. */
export function MmrActivityPanel({ pid, aid }: { pid: number; aid: string }) {
  const eff = useApi((s) => api.mmrEffect(pid, aid, s), [pid, aid]);
  if (eff.error) return <ErrorState error={eff.error} onRetry={eff.reload} title="Could not load the MMR effect" />;
  if (!eff.data) return <Loading rows={1} />;
  const e = eff.data;
  return (
    <section className="panel" aria-labelledby="mmr-eff-h">
      <h2 id="mmr-eff-h" className="panel__title">
        Running MMR
      </h2>
      <p>
        {e.activity.informative ? (
          <>
            Informative: 10 km-equivalent <strong>{formatDuration(e.activity.t10_s)}</strong> (on its own: {fmtMmr(e.activity.points)}{" "}
            points).
          </>
        ) : (
          <>Not informative: {e.activity.reasons.join("; ")}.</>
        )}
      </p>
      <p>
        At its start: MMR {fmtMmr(e.without.mmr) ?? "insufficient evidence"} without it → {fmtMmr(e.with.mmr) ?? "insufficient evidence"} with it
        {e.delta !== null ? ` (${formatDelta(e.delta)})` : ""}. {e.explanation}
      </p>
      {e.activity.flags.length ? (
        <ul className="small muted">
          {e.activity.flags.map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
