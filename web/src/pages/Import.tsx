import { useEffect, useId, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router";
import { api, ApiError } from "../api/client";
import type { ImportPreview, ImportRecord, ImportResult, Participant } from "../api/types";
import { KindTag, RunnerOptions } from "../components/Badges";
import { DataTable } from "../components/DataTable";
import { ImportRowsTable, ImportSummary, PreviewSummary } from "../components/ImportSummary";
import { ErrorState, Loading, Notice } from "../components/States";
import { formatDateTimeUTC } from "../format";
import { useApi } from "../hooks/useApi";
import { Icon } from "../components/AppShell";
import { useAppState } from "../state/AppState";

const toApiError = (e: unknown) => (e instanceof ApiError ? e : new ApiError("unknown", String(e), 0));

function Guidance() {
  return (
    <details className="disclosure">
      <summary>Column requirements and what is read</summary>
      <ul className="small">
        <li>
          A Strava bulk export <strong>.zip</strong> (Settings → My Account → Download or delete your account →
          Request your archive), or the <strong>activities.csv</strong> inside it.
        </li>
        <li>
          Required columns: Activity ID, Activity Date, Activity Type, Elapsed Time, and both Distance columns
          (display units and metres).
        </li>
        <li>Optional: Moving Time, Average Heart Rate, Perceived Exertion, Elevation Gain.</li>
        <li>GPS files (.gpx, .fit, .tcx) in the export are ignored; only summary fields are read.</li>
        <li>Activity dates are assumed to be UTC.</li>
      </ul>
    </details>
  );
}

function AddRunner({ onCreated }: { onCreated: (p: Participant) => void }) {
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState("");
  const [kind, setKind] = useState<"real" | "synthetic">("real");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const id = useId();

  const valid = label.trim().length > 0 && (kind === "synthetic" || consent);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!valid) return;
    setBusy(true);
    setError(null);
    try {
      const p = await api.createParticipant({ label: label.trim(), data_kind: kind, consent: kind === "real" ? consent : false });
      setLabel("");
      setConsent(false);
      setOpen(false);
      onCreated(p);
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button type="button" className="btn btn--small" onClick={() => setOpen(true)} aria-expanded={false}>
        <span aria-hidden="true">+ </span>Add runner
      </button>
    );
  }
  return (
    <form className="form panel" onSubmit={submit} aria-labelledby={`${id}-h`}>
      <h3 id={`${id}-h`} className="panel__title">
        Add runner
      </h3>
      <div className="field">
        <label htmlFor={`${id}-label`} className="field__label">
          Name or label
        </label>
        <input id={`${id}-label`} type="text" value={label} maxLength={80} onChange={(e) => setLabel(e.target.value)} required />
      </div>
      <fieldset className="field">
        <legend className="field__label">Data kind</legend>
        <label className="check">
          <input type="radio" name={`${id}-kind`} checked={kind === "real"} onChange={() => setKind("real")} />
          Real (a person's own export)
        </label>
        <label className="check">
          <input type="radio" name={`${id}-kind`} checked={kind === "synthetic"} onChange={() => setKind("synthetic")} />
          Synthetic (made-up demo data)
        </label>
      </fieldset>
      {kind === "real" ? (
        <label className="check">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          This person agreed to have their exported running data analysed here (required for real data).
        </label>
      ) : null}
      {error ? <ErrorState error={error} title="Could not add the runner" /> : null}
      <div className="actions">
        <button type="submit" className="btn btn--primary" disabled={!valid || busy}>
          {busy ? "Adding…" : "Add runner"}
        </button>
        <button type="button" className="btn" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function PastImport({ id, onClose }: { id: number; onClose: () => void }) {
  const res = useApi((s) => api.importDetail(id, s), [id]);
  return (
    <section className="panel" aria-label={`Import ${id}`}>
      <div className="section__head">
        <h3 className="panel__title">Import #{id}</h3>
        <button type="button" className="btn btn--small" onClick={onClose}>
          Close
        </button>
      </div>
      {res.error ? (
        <ErrorState error={res.error} onRetry={res.reload} />
      ) : !res.data ? (
        <Loading />
      ) : (
        <>
          <ImportSummary record={res.data.import} />
          <ImportRowsTable rows={res.data.rows} caption={`Rows of import #${id}`} />
        </>
      )}
    </section>
  );
}

function History({ pid, nonce }: { pid: number; nonce: number }) {
  const list = useApi((s) => api.imports(pid, s), [pid, nonce]);
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => setOpen(null), [pid]);
  if (list.error) return <ErrorState error={list.error} onRetry={list.reload} title="Could not load import history" />;
  if (!list.data) return <Loading />;
  return (
    <>
      <DataTable<ImportRecord>
        caption="Import history for this runner"
        columns={[
          { key: "id", header: "#", align: "right", sortValue: (r) => r.id, render: (r) => r.id },
          {
            key: "when",
            header: "Imported (UTC)",
            sortValue: (r) => r.imported_utc,
            render: (r) => <span className="nowrap">{formatDateTimeUTC(r.imported_utc)}</span>,
          },
          { key: "file", header: "File", sortValue: (r) => r.filename, render: (r) => <span className="truncate" title={r.filename}>{r.filename}</span> },
          { key: "status", header: "Status", render: (r) => r.status.replace("_", " ") },
          { key: "rows", header: "Rows", align: "right", render: (r) => r.rows_total },
          { key: "ins", header: "Inserted", align: "right", render: (r) => r.inserted },
          { key: "dup", header: "Duplicates", align: "right", render: (r) => r.duplicates },
          { key: "con", header: "Conflicts", align: "right", render: (r) => r.conflicts },
          { key: "cor", header: "Corrected", align: "right", render: (r) => r.corrected },
          { key: "rej", header: "Rejected", align: "right", render: (r) => r.rejected },
          {
            key: "open",
            header: <span className="visually-hidden">Rows</span>,
            render: (r) => (
              <button type="button" className="btn btn--small" aria-pressed={open === r.id} onClick={() => setOpen(open === r.id ? null : r.id)}>
                {open === r.id ? "Hide rows" : "View rows"}
              </button>
            ),
          },
        ]}
        rows={list.data}
        rowKey={(r) => r.id}
        initialSort={{ key: "id", dir: "desc" }}
        empty="No imports yet for this runner."
      />
      {open !== null ? <PastImport id={open} onClose={() => setOpen(null)} /> : null}
    </>
  );
}

export function ImportPage() {
  const { participants, participant, participantId, setParticipantId, reloadParticipants, participantsError } =
    useAppState();
  const ids = useId();
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<ApiError | null>(null);
  const [applyCorrections, setApplyCorrections] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<ApiError | null>(null);
  const [duplicateOf, setDuplicateOf] = useState<ImportRecord | null>(null);
  const [confirmRepeat, setConfirmRepeat] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [doneFor, setDoneFor] = useState<File | null>(null);
  const [historyNonce, setHistoryNonce] = useState(0);
  const previewSeq = useRef(0);

  function reset() {
    previewSeq.current++;
    setFile(null);
    setPreview(null);
    setPreviewing(false);
    setPreviewError(null);
    setSubmitError(null);
    setDuplicateOf(null);
    setConfirmRepeat(false);
    setResult(null);
    setDoneFor(null);
    if (fileInput.current) fileInput.current.value = "";
  }

  // switching runner discards the chosen file and preview
  useEffect(() => {
    reset();
  }, [participantId]);

  async function choose(f: File | null, corrections = applyCorrections) {
    const seq = ++previewSeq.current;
    setFile(f);
    setPreview(null);
    setPreviewError(null);
    setSubmitError(null);
    setDuplicateOf(null);
    setConfirmRepeat(false);
    setResult(null);
    if (!f || participantId === null) return;
    setPreviewing(true);
    try {
      const p = await api.previewImport(participantId, f, corrections);
      if (seq === previewSeq.current) setPreview(p);
    } catch (e) {
      if (seq === previewSeq.current) setPreviewError(toApiError(e));
    } finally {
      if (seq === previewSeq.current) setPreviewing(false);
    }
  }

  async function submit() {
    if (!file || participantId === null) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const r = await api.importFile(participantId, file, {
        apply_corrections: applyCorrections,
        confirm_repeat: duplicateOf !== null && confirmRepeat,
      });
      setResult(r);
      setDoneFor(file);
      setDuplicateOf(null);
      setConfirmRepeat(false);
      setHistoryNonce((n) => n + 1);
      reloadParticipants();
    } catch (e) {
      const err = toApiError(e);
      if (err.code === "duplicate_file") {
        setDuplicateOf((err.previous_import as ImportRecord | undefined) ?? null);
        if (!err.previous_import) setSubmitError(err);
      } else {
        setSubmitError(err);
      }
    } finally {
      setSubmitting(false);
    }
  }

  const blockedByDuplicate = duplicateOf !== null && !confirmRepeat;
  const canImport =
    !!file &&
    !!preview &&
    !preview.file_error &&
    !previewing &&
    !submitting &&
    doneFor !== file &&
    !blockedByDuplicate;

  return (
    <div className="page page--form">
      <header className="page__header">
        <h1 className="page__title">Import activities</h1>
        <p className="muted">Preview first: nothing is stored until you press Import.</p>
      </header>

      <section className="section step" aria-labelledby="s1-h">
        <h2 id="s1-h" className="section-title">
          <span className="step__n">1</span> Runner
        </h2>
        {participantsError ? <ErrorState error={participantsError} onRetry={reloadParticipants} /> : null}
        {participants && participants.length > 0 ? (
          <div className="field">
            <label htmlFor={`${ids}-p`} className="field__label">
              Import into
            </label>
            <div className="inline-controls">
              <select id={`${ids}-p`} value={participantId ?? ""} onChange={(e) => setParticipantId(Number(e.target.value))}>
                <RunnerOptions participants={participants} />
              </select>
              {participant ? <KindTag kind={participant.data_kind} /> : null}
              <AddRunner
                onCreated={(p) => {
                  setParticipantId(p.id);
                  reloadParticipants();
                }}
              />
            </div>
          </div>
        ) : participants ? (
          <>
            <p>No runners yet. Add one to import into.</p>
            <AddRunner
              onCreated={(p) => {
                setParticipantId(p.id);
                reloadParticipants();
              }}
            />
          </>
        ) : (
          <Loading rows={1} />
        )}
      </section>

      <section className="section step" aria-labelledby="s2-h">
        <h2 id="s2-h" className="section-title">
          <span className="step__n">2</span> File
        </h2>
        <div className={`file-pick${participantId === null ? " file-pick--disabled" : ""}`}>
          {/* the native input stays focusable and operable; the box is its visible label */}
          <input
            id={`${ids}-file`}
            ref={fileInput}
            className="file-pick__input"
            type="file"
            accept=".csv,.zip"
            disabled={participantId === null}
            aria-describedby={`${ids}-file-hint`}
            onChange={(e) => choose(e.target.files?.[0] ?? null)}
          />
          <label htmlFor={`${ids}-file`} className="file-pick__box">
            <Icon name="upload" />
            <span className="file-pick__text">
              <strong>{file ? file.name : "Choose a file"}</strong>
              <span className="small muted">Strava export (.zip) or activities.csv</span>
            </span>
            <span className="btn btn--small" aria-hidden="true">{file ? "Change" : "Browse"}</span>
          </label>
          <p id={`${ids}-file-hint`} className="field__hint">
            {participantId === null ? "Add or choose a runner first. " : ""}Up to 50 MB · read on this computer, never
            uploaded.
          </p>
        </div>
        <Guidance />
        {previewing ? <Loading label="Checking the file…" rows={1} /> : null}
        {previewError ? <ErrorState error={previewError} title="Could not check this file" /> : null}
        {preview ? (
          <>
            <PreviewSummary preview={preview} />
            {preview.rows.some((r) => r.outcome === "rejected" || r.outcome === "conflict") || preview.warnings > 0 ? (
              <ImportRowsTable rows={preview.rows} caption="Rows in this file" />
            ) : null}
          </>
        ) : null}
      </section>

      <section className="section step" aria-labelledby="s3-h">
        <h2 id="s3-h" className="section-title">
          <span className="step__n">3</span> Import
        </h2>
        <label className="check">
          <input
            type="checkbox"
            checked={applyCorrections}
            onChange={(e) => {
              const v = e.target.checked;
              setApplyCorrections(v);
              if (file) void choose(file, v); // the preview must describe what Import will actually do
            }}
          />
          Apply corrections: replace stored values when a row has the same Activity ID but different values
          (otherwise it is reported as a conflict)
        </label>
        {duplicateOf ? (
          <Notice tone="warning" title="This exact file was already imported" role="alert">
            <p>
              Import #{duplicateOf.id}: {duplicateOf.filename}, {formatDateTimeUTC(duplicateOf.imported_utc)} (
              {duplicateOf.inserted} inserted, {duplicateOf.duplicates} duplicates).
            </p>
            <label className="check">
              <input type="checkbox" checked={confirmRepeat} onChange={(e) => setConfirmRepeat(e.target.checked)} />
              Import again anyway
            </label>
          </Notice>
        ) : null}
        {submitError ? <ErrorState error={submitError} title="Import failed" /> : null}
        <div className="actions">
          <button type="button" className="btn btn--primary" disabled={!canImport} onClick={submit}>
            {submitting ? "Importing…" : "Import"}
          </button>
          {doneFor && doneFor === file ? <span className="muted small">This file has been imported.</span> : null}
        </div>
      </section>

      {result ? (
        <section className="section" aria-labelledby="res-h">
          <h2 id="res-h" className="section-title">
            Result
          </h2>
          <ImportSummary record={result.import} />
          <ImportRowsTable rows={result.rows} caption="Rows" />
          <div className="actions">
            <Link className="btn btn--primary" to="/activities">
              View activities
            </Link>
            <Link className="btn" to="/">
              See Running MMR
            </Link>
            <button type="button" className="btn" onClick={reset}>
              Import another file
            </button>
          </div>
        </section>
      ) : null}

      {participantId !== null ? (
        <section className="section" aria-labelledby="hist-h">
          <h2 id="hist-h" className="section-title">
            Import history
          </h2>
          <History pid={participantId} nonce={historyNonce} />
        </section>
      ) : null}
    </div>
  );
}
