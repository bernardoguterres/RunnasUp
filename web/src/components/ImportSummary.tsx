import { useState } from "react";
import type { ImportOutcome, ImportPreview, ImportRecord, ImportRow } from "../api/types";
import { formatDateTimeUTC } from "../format";
import { Notice } from "./States";

export type Outcome = "success" | "issues" | "nothing-new" | "rejected";

export function importOutcome(r: ImportRecord): Outcome {
  if (r.status !== "completed") return "rejected";
  const added = r.inserted + r.corrected;
  if (added === 0) return "nothing-new";
  if (r.rejected > 0 || r.conflicts > 0 || r.warnings > 0) return "issues";
  return "success";
}

const OUTCOME_TEXT: Record<Outcome, { tone: "success" | "warning" | "info" | "danger"; title: string }> = {
  success: { tone: "success", title: "Import complete" },
  issues: { tone: "warning", title: "Imported with issues" },
  "nothing-new": { tone: "info", title: "No new activities" },
  rejected: { tone: "danger", title: "File rejected: nothing was stored" },
};

function Counts({ items }: { items: [string, number][] }) {
  return (
    <dl className="counts">
      {items.map(([label, n]) => (
        <div key={label} className="counts__item">
          <dt>{label}</dt>
          <dd className="num">{n}</dd>
        </div>
      ))}
    </dl>
  );
}

export function ImportSummary({ record }: { record: ImportRecord }) {
  const o = importOutcome(record);
  const t = OUTCOME_TEXT[o];
  const issues = record.rejected + record.conflicts;
  return (
    <div className="import-summary">
      <Notice tone={t.tone} title={t.title} role="status">
        <p>
          {record.filename} · {formatDateTimeUTC(record.imported_utc)} · import #{record.id}
        </p>
        {record.message ? <p>{record.message}</p> : null}
        {o === "nothing-new" && issues === 0 ? (
          <p>Every row was already stored (duplicates). Nothing changed.</p>
        ) : null}
        {o === "nothing-new" && issues > 0 ? (
          <p>No activity was added; {issues} rows need attention (see below).</p>
        ) : null}
        {o === "issues" ? (
          <p>
            Activities were added, but some rows were rejected, conflict with stored data, or had an
            optional value ignored. Review them below.
          </p>
        ) : null}
      </Notice>
      <Counts
        items={[
          ["Rows in file", record.rows_total],
          ["Inserted", record.inserted],
          ["Duplicates", record.duplicates],
          ["Conflicts", record.conflicts],
          ["Corrected", record.corrected],
          ["Rejected", record.rejected],
          ["Warnings", record.warnings],
        ]}
      />
    </div>
  );
}

export function PreviewSummary({ preview }: { preview: ImportPreview }) {
  return (
    <div className="import-summary">
      <Notice
        tone={preview.file_error ? "danger" : "info"}
        title={preview.file_error ? "This file would be rejected" : "Preview: nothing stored yet"}
        role="status"
      >
        <p>{preview.filename}</p>
        {preview.file_error ? <p>{preview.file_error}</p> : null}
      </Notice>
      {preview.identical_previous_import ? (
        <Notice tone="warning" title="This exact file was imported before">
          <p>
            Import #{preview.identical_previous_import.id} ({preview.identical_previous_import.filename}) on{" "}
            {formatDateTimeUTC(preview.identical_previous_import.imported_utc)}. Importing again will only
            report duplicates unless the data changed.
          </p>
        </Notice>
      ) : null}
      <Counts
        items={[
          ["Rows in file", preview.rows_total],
          ["Would insert", preview.would_insert],
          ["Duplicates", preview.duplicates],
          ["Conflicts", preview.conflicts],
          ["Would correct", preview.corrected],
          ["Rejected", preview.rejected],
          ["Warnings", preview.warnings],
        ]}
      />
    </div>
  );
}

type Chip = "attention" | ImportOutcome | "all";
const CHIPS: { key: Chip; label: string }[] = [
  { key: "attention", label: "Needs attention" },
  { key: "rejected", label: "Rejected" },
  { key: "conflict", label: "Conflict" },
  { key: "duplicate", label: "Duplicate" },
  { key: "corrected", label: "Corrected" },
  { key: "inserted", label: "Inserted" },
  { key: "all", label: "All" },
];

const needsAttention = (r: ImportRow) => r.outcome === "rejected" || r.outcome === "conflict" || r.warning;

export function ImportRowsTable({
  rows,
  caption = "Rows",
  chips = true,
}: {
  rows: ImportRow[];
  caption?: string;
  chips?: boolean;
}) {
  const [chip, setChip] = useState<Chip>(() => (rows.some(needsAttention) ? "attention" : "all"));
  const count = (k: Chip) =>
    k === "all" ? rows.length : k === "attention" ? rows.filter(needsAttention).length : rows.filter((r) => r.outcome === k).length;
  const shown = !chips
    ? rows
    : chip === "all"
      ? rows
      : chip === "attention"
        ? rows.filter(needsAttention)
        : rows.filter((r) => r.outcome === chip);
  return (
    <div>
      {chips ? (
        <div className="chips" role="group" aria-label="Filter rows by outcome">
          {CHIPS.map((c) => (
            <button
              key={c.key}
              type="button"
              className="chip"
              aria-pressed={chip === c.key}
              onClick={() => setChip(c.key)}
            >
              {c.label} <span className="num">({count(c.key)})</span>
            </button>
          ))}
        </div>
      ) : null}
      <div className="table-wrap" tabIndex={0} role="region" aria-label={caption}>
        <table className="table">
          <caption className="table__caption">
            {caption} ({shown.length} of {rows.length})
          </caption>
          <thead>
            <tr>
              <th scope="col" className="is-right">
                Line
              </th>
              <th scope="col">Activity ID</th>
              <th scope="col">Outcome</th>
              <th scope="col">Detail</th>
            </tr>
          </thead>
          <tbody>
            {shown.length === 0 ? (
              <tr>
                <td colSpan={4} className="table__empty">
                  No rows with this outcome.
                </td>
              </tr>
            ) : (
              shown.map((r, i) => (
                <tr key={`${r.line}-${i}`}>
                  <td className="is-right num">{r.line}</td>
                  <td className="num">{r.activity_id ?? <span className="muted">no ID</span>}</td>
                  <td>
                    <span className={`outcome outcome--${r.outcome}`}>{r.outcome}</span>
                  </td>
                  <td>{r.detail}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
