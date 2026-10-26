import { useEffect, useId, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router";
import { api, ApiError } from "../api/client";
import type { ActivityDetail, Effort } from "../api/types";
import { KindBadge } from "../components/Badges";
import { Val } from "../components/Missing";
import { ParticipantGate } from "../components/ParticipantGate";
import { EmptyState, ErrorState, Loading, Notice } from "../components/States";
import {
  formatDateTimeUTC,
  formatDuration,
  formatKm,
  formatMetres,
  formatPace,
} from "../format";
import { useApi } from "../hooks/useApi";
import { useAppState } from "../state/AppState";
import { MmrActivityPanel } from "./Mmr";

const EFFORTS: Effort[] = ["unknown", "easy", "moderate", "hard", "race"];

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="kv__row">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function AnnotationForm({
  pid,
  detail,
  onSaved,
}: {
  pid: number;
  detail: ActivityDetail;
  onSaved: (d: ActivityDetail) => void;
}) {
  const a = detail.annotation;
  const [exclude, setExclude] = useState(a.exclude);
  const [note, setNote] = useState(a.exclude_note ?? "");
  const [notDup, setNotDup] = useState(a.not_duplicate);
  const [effort, setEffort] = useState<Effort>(a.effort);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const id = useId();

  useEffect(() => {
    setExclude(a.exclude);
    setNote(a.exclude_note ?? "");
    setNotDup(a.not_duplicate);
    setEffort(a.effort);
  }, [a.exclude, a.exclude_note, a.not_duplicate, a.effort]);

  const dirty =
    exclude !== a.exclude || (note || null) !== (a.exclude_note || null) || notDup !== a.not_duplicate || effort !== a.effort;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(null);
    try {
      const d = await api.putAnnotation(pid, detail.activity.id, {
        exclude,
        exclude_note: note.trim() ? note.trim() : null,
        not_duplicate: notDup,
        effort,
      });
      onSaved(d);
      setSaved(d.annotation.updated_utc ? formatDateTimeUTC(d.annotation.updated_utc) : "now");
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("unknown", String(err), 0));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="form" onSubmit={submit} aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`} className="section-title">
        Annotation
      </h2>
      <p className="muted small">Saving recalculates Running MMR for this runner.</p>
      <label className="check">
        <input type="checkbox" checked={exclude} onChange={(e) => setExclude(e.target.checked)} />
        Exclude this activity from Running MMR
      </label>
      <div className="field">
        <label htmlFor={`${id}-note`} className="field__label">
          Reason for excluding (optional)
        </label>
        <input
          id={`${id}-note`}
          type="text"
          value={note}
          maxLength={500}
          onChange={(e) => setNote(e.target.value)}
          disabled={!exclude}
        />
      </div>
      <label className="check">
        <input type="checkbox" checked={notDup} onChange={(e) => setNotDup(e.target.checked)} />
        Not a duplicate (keep it even if it looks like a copy of another activity)
      </label>
      <div className="field">
        <label htmlFor={`${id}-effort`} className="field__label">
          Effort
        </label>
        <select id={`${id}-effort`} value={effort} onChange={(e) => setEffort(e.target.value as Effort)}>
          {EFFORTS.map((x) => (
            <option key={x} value={x}>
              {x}
            </option>
          ))}
        </select>
        <p className="field__hint">Explanatory only: effort never changes the score.</p>
      </div>
      {error ? <ErrorState error={error} title="Could not save the annotation" /> : null}
      {saved && !dirty ? (
        <Notice tone="success" title="Annotation saved" role="status">
          <p>Saved {saved}. The values on this page were refreshed from the server.</p>
        </Notice>
      ) : null}
      <div className="actions">
        <button type="submit" className="btn btn--primary" disabled={saving || !dirty}>
          {saving ? "Saving…" : "Save annotation"}
        </button>
      </div>
    </form>
  );
}

function BackLink() {
  const loc = useLocation();
  const navigate = useNavigate();
  const from = (loc.state as { fromExplorer?: string } | null)?.fromExplorer;
  if (typeof from === "string") {
    return (
      <Link to={`/activities${from}`} className="back-link">
        ← Back to activities
      </Link>
    );
  }
  if (loc.key !== "default") {
    return (
      <button type="button" className="link-button back-link" onClick={() => navigate(-1)}>
        ← Back
      </button>
    );
  }
  return (
    <Link to="/activities" className="back-link">
      ← All activities
    </Link>
  );
}

function DetailBody({ pid, activityId }: { pid: number; activityId: string }) {
  const res = useApi((s) => api.activity(pid, activityId, s), [pid, activityId]);
  const [override, setOverride] = useState<ActivityDetail | null>(null);
  useEffect(() => setOverride(null), [pid, activityId]);
  const d = override ?? res.data;

  if (res.error) {
    if (res.error.code === "not_found") {
      return (
        <div className="page">
          <BackLink />
          <EmptyState
            title="Activity not found for this runner"
            action={
              <Link className="btn btn--primary" to="/activities">
                Open the activity list
              </Link>
            }
          >
            <p>
              Activity {activityId} is not stored for the selected runner. If you switched runners, pick the
              runner it belongs to.
            </p>
          </EmptyState>
        </div>
      );
    }
    return <ErrorState error={res.error} onRetry={res.reload} title="Could not load the activity" />;
  }
  if (!d) return <Loading label="Loading activity…" />;
  const a = d.activity;
  const name = a.name?.trim() ? a.name : `Untitled activity ${a.id}`;

  return (
    <div className="page">
      <BackLink />
      <header className="page__header">
        <div className="page__title-row">
          <h1 className="page__title truncate" title={name}>
            {name}
          </h1>
          <KindBadge kind={d.participant.data_kind} />
        </div>
        <p className="muted">
          {d.participant.label} · {a.type} · {formatDateTimeUTC(a.start_utc)}
        </p>
      </header>

      <Notice tone="info">
        <p>
          No map, route, splits or heart-rate trace: only summary fields were imported from the export.
        </p>
      </Notice>

      <div className="grid-2">
        <section className="panel" aria-labelledby="rec-h">
          <h2 id="rec-h" className="panel__title">
            Recorded <span className="muted small">(from the export)</span>
          </h2>
          <dl className="kv">
            <Row label="Name">{a.name?.trim() ? a.name : <Val value={null} />}</Row>
            <Row label="Type">{a.type}</Row>
            <Row label="Start">{formatDateTimeUTC(a.start_utc)}</Row>
            <Row label="Distance">
              <span className="num">
                {formatMetres(a.distance_m)} ({formatKm(a.distance_m)})
              </span>
            </Row>
            <Row label="Elapsed time">
              <span className="num">{formatDuration(a.elapsed_s)}</span>
            </Row>
            <Row label="Moving time">
              <Val value={formatDuration(a.moving_s)} />
            </Row>
            <Row label="Average heart rate">
              <Val value={a.avg_hr === null ? null : `${Math.round(a.avg_hr)} bpm`} />
              <div className="small muted">Average only; no HR trace imported.</div>
            </Row>
            <Row label="Perceived exertion">
              <Val value={a.perceived_exertion} />
            </Row>
            <Row label="Elevation gain">
              <Val value={formatMetres(a.elevation_gain_m)} />
            </Row>
            <Row label="Activity ID">
              <span className="num">{a.id}</span>
            </Row>
          </dl>
        </section>
        <section className="panel" aria-labelledby="der-h">
          <h2 id="der-h" className="panel__title">
            Derived <span className="muted small">(calculated by RunnasUP)</span>
          </h2>
          <dl className="kv">
            <Row label="Pace from elapsed time">
              <span className="num">{formatPace(a.pace_s_per_km)}</span>
            </Row>
            <Row label="Pace from moving time">
              <Val value={formatPace(a.moving_pace_s_per_km)} />
              <div className="small muted">Display only; never used by the score.</div>
            </Row>
          </dl>
        </section>
      </div>

      <MmrActivityPanel pid={pid} aid={activityId} />

      <section className="section" aria-labelledby="prov-h">
        <h2 id="prov-h" className="section-title">
          Provenance
        </h2>
        <dl className="kv">
          <Row label="Source">{a.source}</Row>
          <Row label="First imported">
            {a.first_import_file} · {formatDateTimeUTC(a.first_imported_utc)} (import #{a.first_import_id})
          </Row>
          <Row label="Last import that touched it">import #{a.last_import_id}</Row>
        </dl>
      </section>

      <div className="grid-2">
        <section className="section">
          <AnnotationForm pid={pid} detail={d} onSaved={setOverride} />
        </section>
        <section className="section" aria-labelledby="alog-h">
          <h2 id="alog-h" className="section-title">
            Annotation history
          </h2>
          {d.annotation_log.length === 0 ? (
            <p className="muted">No changes yet.</p>
          ) : (
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Annotation history">
              <table className="table">
                <caption className="visually-hidden">Annotation history</caption>
                <thead>
                  <tr>
                    <th scope="col">Changed (UTC)</th>
                    <th scope="col">Field</th>
                    <th scope="col">Old</th>
                    <th scope="col">New</th>
                  </tr>
                </thead>
                <tbody>
                  {d.annotation_log.map((c, i) => (
                    <tr key={i}>
                      <td>{formatDateTimeUTC(c.changed_utc)}</td>
                      <td>{c.field}</td>
                      <td>
                        <Val value={c.old_value} label="empty" />
                      </td>
                      <td>
                        <Val value={c.new_value} label="empty" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

export function ActivityDetailPage() {
  const { activityId = "" } = useParams();
  const { participantId, participants, setParticipantId } = useAppState();
  const [search, setSearch] = useSearchParams();
  const location = useLocation();
  const linked = Number(search.get("runner"));
  // A link carries its runner (?runner=<id>). Apply it once, then drop it from the URL so the
  // runner selector stays free to change while this page is open.
  useEffect(() => {
    if (!linked || !participants) return;
    if (linked !== participantId && participants.some((x) => x.id === linked)) setParticipantId(linked);
    const next = new URLSearchParams(search);
    next.delete("runner");
    setSearch(next, { replace: true, state: location.state });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linked, participants]);
  return (
    <ParticipantGate>{(pid) => <DetailBody pid={pid} activityId={activityId} />}</ParticipantGate>
  );
}
