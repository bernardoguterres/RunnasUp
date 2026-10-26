import { useRef, useEffect, useId, useState } from "react";
import { activityPath } from "../links";
import { Link, useLocation, useSearchParams } from "react-router";
import { api, csvUrl } from "../api/client";
import type { ActivityFilters } from "../api/client";
import type { ActivityRow, ActivitySort } from "../api/types";
import { Icon } from "../components/AppShell";
import { DataTable } from "../components/DataTable";
import type { Column } from "../components/DataTable";
import { DateRange } from "../components/DateRange";
import { Val } from "../components/Missing";
import { ParticipantGate } from "../components/ParticipantGate";
import { EmptyState, ErrorState, Loading } from "../components/States";
import { formatDateTimeUTC, formatDateUTC, formatDuration, formatKmNumber, formatPace } from "../format";
import { useApi } from "../hooks/useApi";
import { useAppState } from "../state/AppState";

export const PAGE_SIZE = 50;

const SORTS: { value: ActivitySort; label: string }[] = [
  { value: "start", label: "Date" },
  { value: "distance", label: "Distance" },
  { value: "elapsed", label: "Elapsed time" },
  { value: "pace", label: "Pace" },
  { value: "name", label: "Name" },
];
const SORT_VALUES = SORTS.map((s) => s.value);
const FILTER_KEYS = ["q", "from", "to", "min_km", "max_km", "type", "sort", "order"] as const;

/** Read the explorer filters from the URL; unknown values fall back to defaults. */
export function readFilters(sp: URLSearchParams): Required<Pick<ActivityFilters, "sort" | "order">> &
  ActivityFilters & { offset: number } {
  const sort = sp.get("sort") as ActivitySort | null;
  const order = sp.get("order");
  const offset = Number(sp.get("offset") ?? "0");
  return {
    q: sp.get("q") ?? "",
    from: sp.get("from") ?? "",
    to: sp.get("to") ?? "",
    min_km: sp.get("min_km") ?? "",
    max_km: sp.get("max_km") ?? "",
    type: sp.get("type") ?? "",
    sort: sort && SORT_VALUES.includes(sort) ? sort : "start",
    order: order === "asc" ? "asc" : "desc",
    offset: Number.isInteger(offset) && offset > 0 ? offset : 0,
  };
}

function columns(open: Set<string>, toggle: (id: string) => void): Column<ActivityRow>[] {
  return [
    {
      key: "name",
      header: "Activity",
      sortValue: (r) => r.name ?? "",
      render: (r) => (
        <span className="cell-stack">
          <ActivityLink row={r} />
          <span className="small muted">{r.type}</span>
        </span>
      ),
    },
    {
      key: "start",
      header: "Date (UTC)",
      sortValue: (r) => r.start_utc,
      render: (r) => <span className="nowrap num">{formatDateUTC(r.start_utc)?.replace(" UTC", "")}</span>,
    },
    {
      key: "distance",
      header: "Distance",
      align: "right",
      sortValue: (r) => r.distance_m,
      render: (r) => `${formatKmNumber(r.distance_m)} km`,
    },
    {
      key: "pace",
      header: "Elapsed pace",
      align: "right",
      sortValue: (r) => r.pace_s_per_km,
      render: (r) => `${formatPace(r.pace_s_per_km)} /km`,
    },
    {
      key: "elapsed",
      header: "Elapsed time",
      align: "right",
      sortValue: (r) => r.elapsed_s,
      render: (r) => formatDuration(r.elapsed_s),
    },
    {
      key: "details",
      header: <span className="visually-hidden">Details</span>,
      headerLabel: "Details",
      align: "right",
      render: (r) => (
        <button type="button" className="row-toggle" aria-expanded={open.has(r.id)} aria-controls={`act-${r.id}`}
          aria-label={`Details for ${r.name?.trim() || `activity ${r.id}`}`} onClick={() => toggle(r.id)}>
          <Icon name="chev" />
        </button>
      ),
    },
  ];
}

/** Expanded row: the optional fields, so they never widen every row. */
function Detail({ r }: { r: ActivityRow }) {
  const { participantId } = useAppState();
  return (
    <div className="stack stack--tight">
      <dl className="detail-grid">
        <div><dt>Date and time (UTC)</dt><dd>{formatDateTimeUTC(r.start_utc)}</dd></div>
        <div><dt>Moving time</dt><dd><Val value={formatDuration(r.moving_s)} /></dd></div>
        <div><dt>Moving pace</dt><dd><Val value={r.moving_pace_s_per_km === null ? null : `${formatPace(r.moving_pace_s_per_km)} /km`} /></dd></div>
        <div><dt>Avg heart rate</dt><dd><Val value={r.avg_hr === null ? null : `${Math.round(r.avg_hr)} bpm`} /></dd></div>
        <div><dt>Elevation gain</dt><dd><Val value={r.elevation_gain_m === null ? null : `${Math.round(r.elevation_gain_m)} m`} /></dd></div>
        <div><dt>Effort label</dt><dd>{r.effort}</dd></div>
      </dl>
      <p className="small">
        <Link to={activityPath(participantId, r.id)}>Open activity {r.id}</Link>
        <span className="muted"> · Running MMR effect, annotations and import history</span>
      </p>
    </div>
  );
}

function ActivityLink({ row }: { row: ActivityRow }) {
  const loc = useLocation();
  const { participantId } = useAppState();
  const name = row.name?.trim() ? row.name : `Untitled activity ${row.id}`;
  return (
    <Link
      to={activityPath(participantId, row.id)}
      state={{ fromExplorer: loc.search }}
      className="truncate"
      title={name}
    >
      {name}
    </Link>
  );
}

function ExplorerBody({ pid, label }: { pid: number; label: string }) {
  const [sp, setSp] = useSearchParams();
  const f = readFilters(sp);
  const [q, setQ] = useState(f.q ?? "");
  const ids = useId();

  // filters such as type and paging belong to one runner's list: reset them when the runner changes
  const prevPid = useRef(pid);
  useEffect(() => {
    if (prevPid.current !== pid) update({ type: "", offset: "" }, true);
    prevPid.current = pid;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pid]);

  // keep the search box in sync with back/forward navigation
  useEffect(() => {
    setQ(f.q ?? "");
  }, [f.q]);

  function update(patch: Partial<Record<(typeof FILTER_KEYS)[number] | "offset", string>>, replace = false) {
    const next = new URLSearchParams(sp);
    for (const [k, v] of Object.entries(patch)) {
      if (v === undefined || v === "" || (k === "offset" && v === "0"))
        next.delete(k);
      else next.set(k, v);
    }
    if (!("offset" in patch)) next.delete("offset");
    setSp(next, { replace });
  }

  // debounce typing into the URL
  useEffect(() => {
    if (q === (f.q ?? "")) return;
    const t = window.setTimeout(() => update({ q }, true), 300);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  const filters: ActivityFilters = {
    q: f.q,
    from: f.from,
    to: f.to,
    min_km: f.min_km,
    max_km: f.max_km,
    type: f.type,
    sort: f.sort,
    order: f.order,
  };
  const key = JSON.stringify(filters);
  const list = useApi(
    (s) => api.activities(pid, { ...filters, limit: PAGE_SIZE, offset: f.offset }, s),
    [pid, key, f.offset],
  );

  const hasFilters = FILTER_KEYS.some((k) => k !== "sort" && k !== "order" && sp.get(k));
  const advanced = (["from", "to", "min_km", "max_km"] as const).filter((k) => sp.get(k)).length;
  const [showFilters, setShowFilters] = useState(advanced > 0);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (id: string) =>
    setOpen((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const data = list.data;
  const total = data?.total ?? 0;
  const start = data && data.rows.length ? data.offset + 1 : 0;
  const end = data ? data.offset + data.rows.length : 0;

  return (
    <div className="page">
      <header className="page__header">
        <h1 className="page__title">Activities</h1>
        <p className="muted">Every stored activity for {label}. Open one to see how it informs Running MMR.</p>
      </header>

      <div className="toolbar" role="group" aria-label="Activity filters">
        <form
          role="search"
          className="field field--grow"
          onSubmit={(e) => {
            e.preventDefault();
            update({ q });
          }}
        >
          <label htmlFor={`${ids}-q`} className="field__label">
            Search name or ID
          </label>
          <input id={`${ids}-q`} type="search" value={q} onChange={(e) => setQ(e.target.value)} />
        </form>
        <div className="field">
          <label htmlFor={`${ids}-type`} className="field__label">
            Type
          </label>
          <select id={`${ids}-type`} value={f.type} onChange={(e) => update({ type: e.target.value })}>
            <option value="">All types</option>
            {(data?.types ?? (f.type ? [f.type] : [])).map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor={`${ids}-sort`} className="field__label">
            Sort by
          </label>
          <div className="inline-controls">
            <select id={`${ids}-sort`} value={f.sort} onChange={(e) => update({ sort: e.target.value })}>
              {SORTS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="btn"
              onClick={() => update({ order: f.order === "asc" ? "desc" : "asc" })}
              aria-label={`Order: ${f.order === "asc" ? "ascending" : "descending"}. Switch order`}
            >
              {f.order === "asc" ? "↑ Asc" : "↓ Desc"}
            </button>
          </div>
        </div>
        <button type="button" className="btn" aria-expanded={showFilters} aria-controls={`${ids}-more`}
          onClick={() => setShowFilters((o) => !o)}>
          Filters{advanced ? ` (${advanced})` : ""}
        </button>
        <div className="toolbar__end">
          <a className="btn" href={csvUrl.activities(pid, filters)} download>
            Download CSV
          </a>
        </div>
      </div>
      <section id={`${ids}-more`} className="filter-panel" aria-label="More filters" hidden={!showFilters}>
        <DateRange from={f.from ?? ""} to={f.to ?? ""} onChange={(from, to) => update({ from, to })} />
        <fieldset className="daterange">
          <legend className="field__label">Distance (km)</legend>
          <div className="daterange__inputs">
            <label className="field field--inline">
              <span>Min</span>
              <input
                type="number"
                inputMode="decimal"
                min={0}
                step="0.1"
                value={f.min_km}
                onChange={(e) => update({ min_km: e.target.value }, true)}
              />
            </label>
            <label className="field field--inline">
              <span>Max</span>
              <input
                type="number"
                inputMode="decimal"
                min={0}
                step="0.1"
                value={f.max_km}
                onChange={(e) => update({ max_km: e.target.value }, true)}
              />
            </label>
          </div>
        </fieldset>
        {hasFilters ? (
          <div className="field field--end">
            <button type="button" className="btn" onClick={() => setSp(new URLSearchParams())}>
              Clear filters
            </button>
          </div>
        ) : null}
      </section>

      <p className="result-count small muted" aria-live="polite">
        {data ? (
          <>
            <strong className="num">{data.rows.length}</strong> of <strong className="num">{total}</strong> activities
            {total > 0 ? ` (showing ${start}–${end})` : ""} · CSV uses these filters
          </>
        ) : list.loading ? (
          "Loading…"
        ) : null}
      </p>

      {list.error ? (
        <ErrorState error={list.error} onRetry={list.reload} title="Could not load activities" />
      ) : !data ? (
        <Loading label="Loading activities…" rows={6} />
      ) : data.rows.length === 0 ? (
        <EmptyState
          title={hasFilters ? "No activities match these filters" : "No activities yet"}
          action={
            hasFilters ? (
              <button type="button" className="btn btn--primary" onClick={() => setSp(new URLSearchParams())}>
                Clear filters
              </button>
            ) : (
              <Link className="btn btn--primary" to="/import">
                Import activities
              </Link>
            )
          }
        />
      ) : (
        <>
          <DataTable
            caption={`Activities for ${label}, sorted by ${SORTS.find((s) => s.value === f.sort)?.label} (${
              f.order === "asc" ? "ascending" : "descending"
            })`}
            captionHidden
            columns={columns(open, toggle)}
            rows={data.rows}
            rowKey={(r) => r.id}
            detail={(r) => (open.has(r.id) ? <Detail r={r} /> : null)}
            detailId={(r) => `act-${r.id}`}
            sort={{ key: f.sort, dir: f.order }}
            onSortChange={(s) => update({ sort: s.key, order: s.dir })}
          />
          <nav className="pager" aria-label="Pages">
            <button
              type="button"
              className="btn"
              disabled={data.offset === 0}
              onClick={() => update({ offset: String(Math.max(0, data.offset - PAGE_SIZE)) })}
            >
              ← Previous
            </button>
            <span className="muted num">
              Page {Math.floor(data.offset / PAGE_SIZE) + 1} of {Math.max(1, Math.ceil(total / PAGE_SIZE))}
            </span>
            <button
              type="button"
              className="btn"
              disabled={end >= total}
              onClick={() => update({ offset: String(data.offset + PAGE_SIZE) })}
            >
              Next →
            </button>
          </nav>
        </>
      )}
    </div>
  );
}

export function ExplorerPage() {
  return <ParticipantGate>{(pid, p) => <ExplorerBody pid={pid} label={p.label} />}</ParticipantGate>;
}
