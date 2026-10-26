/**
 * RunnasUP API contract (owned by the backend; see docs/API.md).
 * Frontend code must treat this file as read-only and never re-implement
 * rating formulas: every number below is computed by the Python API.
 *
 * Conventions
 * - Instants are ISO-8601 UTC strings: "2024-03-15T07:00:00Z".
 * - Query dates are UTC calendar dates "YYYY-MM-DD", inclusive.
 * - "as of D" means the end of that UTC day (23:59:59).
 * - Distances in metres, durations in seconds, pace in seconds per km.
 * - null means "not recorded / not applicable". It is never 0.
 */

export type DataKind = "real" | "synthetic" | "unlabelled";
export type Effort = "unknown" | "easy" | "moderate" | "hard" | "race";
export type ActivitySort = "start" | "distance" | "elapsed" | "pace" | "name";
export type SortOrder = "asc" | "desc";
export type ImportOutcome = "inserted" | "duplicate" | "conflict" | "corrected" | "rejected";
export type ImportStatus = "completed" | "file_rejected" | "failed";

/** Every non-2xx response has this body. `message` never contains activity data. */
export interface ApiErrorBody {
  error: {
    code:
      | "bad_request"
      | "not_found"
      | "conflict"
      | "duplicate_file"
      | "demo_only"
      | "payload_too_large"
      | "internal";
    message: string;
    field?: string;
    /** For code "duplicate_file": the earlier identical import. */
    previous_import?: ImportRecord;
  };
}

// ---------------------------------------------------------------- GET /api/health
export interface Health {
  ok: true;
  database: "personal" | "demo" | "custom";
  demo_mode: boolean;
  schema_version: string;
  /** Default "as of" date (YYYY-MM-DD): today in UTC, or in demo mode the date of the latest stored activity. */
  reference_date: string;
  /** Running MMR algorithm version. */
  mmr_version: string;
}

// ---------------------------------------------------------------- participants
/** GET /api/participants -> Participant[] ; POST /api/participants (CreateParticipant) -> 201 Participant */
export interface Participant {
  id: number;
  label: string;
  data_kind: DataKind;
  created_utc: string;
  activity_count: number;
  first_activity_utc: string | null;
  last_activity_utc: string | null;
  last_import_utc: string | null;
}

export interface CreateParticipant {
  label: string;
  data_kind: "real" | "synthetic";
  /** Must be true when data_kind is "real". */
  consent: boolean;
}

export interface RunnerRef {
  id: number;
  label: string;
  data_kind: DataKind;
}

// ---------------------------------------------------------------- activities
export interface ActivityRow {
  id: string; // Strava Activity ID
  start_utc: string;
  name: string | null;
  type: string;
  distance_m: number;
  elapsed_s: number;
  moving_s: number | null;
  pace_s_per_km: number; // from elapsed time
  moving_pace_s_per_km: number | null; // from moving time; display only
  avg_hr: number | null; // display only
  perceived_exertion: number | null; // display only
  elevation_gain_m: number | null; // display only
  effort: Effort; // annotation; display only
}

/**
 * GET /api/participants/{pid}/activities
 *   ?q&from&to&min_km&max_km&type&sort&order&limit(<=500, default 50)&offset
 * GET /api/participants/{pid}/activities.csv  (same filters, no paging) -> text/csv
 */
export interface ActivityList {
  participant_id: number;
  total: number; // matching rows before paging
  offset: number;
  limit: number;
  types: string[]; // all activity types stored for this participant
  rows: ActivityRow[];
}

export interface Annotation {
  exclude: boolean;
  exclude_note: string | null;
  not_duplicate: boolean;
  effort: Effort;
  updated_utc: string | null;
}

export interface AnnotationChange {
  changed_utc: string;
  field: string;
  old_value: string | null;
  new_value: string | null;
}

/** GET /api/participants/{pid}/activities/{id} ; PUT .../annotation (AnnotationUpdate) -> ActivityDetail */
export interface ActivityDetail {
  participant: Pick<Participant, "id" | "label" | "data_kind">;
  activity: ActivityRow & {
    source: string;
    first_import_id: number;
    first_imported_utc: string;
    first_import_file: string;
    last_import_id: number;
  };
  annotation: Annotation;
  annotation_log: AnnotationChange[];
  /** Running MMR view of this activity. */
  mmr: ActivityMmr;
}

export interface ActivityMmr {
  version: string;
  informative: boolean;
  reasons: string[];
  flags: string[];
  t10_s: number | null;
  points: number | null;
}

export interface AnnotationUpdate {
  exclude: boolean;
  exclude_note: string | null;
  not_duplicate: boolean;
  effort: Effort;
}

// ---------------------------------------------------------------- imports
export interface ImportRecord {
  id: number;
  participant_id: number;
  filename: string;
  imported_utc: string;
  status: ImportStatus;
  message: string | null;
  rows_total: number;
  inserted: number;
  duplicates: number;
  conflicts: number;
  corrected: number;
  rejected: number;
  warnings: number; // rows stored with an optional value ignored
}

export interface ImportRow {
  line: number;
  activity_id: string | null;
  outcome: ImportOutcome;
  detail: string;
  /** true when the row was stored but an optional value (HR, effort, moving time, elevation) was ignored */
  warning: boolean;
}

/** POST /api/participants/{pid}/imports/preview (multipart: file, apply_corrections=true|false) -> ImportPreview. Nothing is stored. */
export interface ImportPreview {
  filename: string;
  file_error: string | null; // whole file would be rejected
  rows_total: number;
  would_insert: number;
  duplicates: number;
  conflicts: number;
  corrected: number; // only non-zero when previewed with apply_corrections=true
  rejected: number;
  warnings: number;
  identical_previous_import: ImportRecord | null;
  rows: ImportRow[];
}

/**
 * POST /api/participants/{pid}/imports (multipart: file, apply_corrections=true|false, confirm_repeat=true|false)
 *   -> 201 ImportResult.
 * 409 duplicate_file when identical bytes were already imported for this participant and confirm_repeat != true.
 */
export interface ImportResult {
  import: ImportRecord;
  rows: ImportRow[];
}

/** GET /api/participants/{pid}/imports -> ImportRecord[] ; GET /api/imports/{id} -> ImportResult */

// ================================================================ Running MMR
// A personal ability estimate from one runner's own activities (runrank/mmr.py).

export type MmrStatus = "insufficient evidence" | "low" | "medium" | "high";

/** One stored activity as classified for MMR. */
export interface MmrObservation {
  activity_id: string;
  start_utc: string;
  activity_type: string;
  distance_m: number;
  elapsed_s: number;
  elevation_gain_m: number | null;
  effort: Effort;
  informative: boolean;
  /** 10 km-equivalent time (Riegel); null when not informative */
  t10_s: number | null;
  /** the MMR this single observation would give on its own (not aged) */
  points: number | null;
  reasons: string[];
  flags: string[];
}

export interface MmrEstimate {
  as_of_utc: string;
  status: MmrStatus;
  mmr: number | null;
  t10_s: number | null;
  t10_display: string | null;
  setter: MmrObservation | null;
  setter_aged_t10_s: number | null;
  /** declared effort whose 3 % cap binds, if any */
  cap: MmrObservation | null;
  supporting: number;
  informative_365d: number;
  informative_90d: number;
  best_evidence_age_days: number | null;
  upper_note: string;
}

export interface MmrBand {
  label: string;
  converted: boolean;
  count: number;
  best_key: string | null;
  best_t10_s: number | null;
  best_pace_s_per_km: number | null;
  longest_m?: number | null;
}

export interface MmrQuality {
  activities: number;
  informative: number;
  first_utc: string | null;
  last_utc: string | null;
  by_type: { type: string; count: number }[];
  not_informative: { reason: string; count: number }[];
  missing: { heart_rate: number; elevation: number; moving_time: number; perceived_exertion: number };
  declared_efforts: number;
  hilly: number;
  rows_imported: number;
  rows_rejected: number;
}

export interface MmrChange {
  at_utc: string;
  mmr: number | null;
  status: MmrStatus;
  activities: string[];
  explanation: string[];
}

export interface MmrSnapshot {
  computed_utc: string;
  trigger: string;
  as_of_utc: string | null;
  status: MmrStatus;
  mmr: number | null;
  t10_s: number | null;
  setter_activity_id: string | null;
  activities: number;
  algorithm_version: string;
  scale_version: string;
}

/** GET /api/mmr/participants/{pid}?as_of= (default: now; demo database: latest activity) */
export interface MmrOverview {
  participant: Participant;
  version: string;
  scale_version: string;
  estimate: MmrEstimate;
  quality: MmrQuality;
  bands: MmrBand[];
  /** training volume: shown separately, never part of MMR */
  volume: { km_last_28d: number; runs_last_28d: number; active_weeks_of_last_12: number };
  recent_changes: MmrChange[];
  /** what the app stored after each import or annotation (newest first) */
  snapshots: MmrSnapshot[];
}

export interface MmrHistoryPoint {
  at_utc: string;
  mmr: number | null;
  t10_s: number | null;
  status: MmrStatus;
  setter_activity_id: string | null;
  activities: string[];
  changed: boolean;
  explanation: string[];
}

/** GET /api/mmr/participants/{pid}/history : reconstructed from current data (activity starts + weekly) */
export interface MmrHistory {
  version: string;
  scale_version: string;
  reconstructed: true;
  points: MmrHistoryPoint[];
}

/** GET /api/mmr/participants/{pid}/activities/{aid}/effect : estimate at its start without vs with it */
export interface MmrEffect {
  activity: MmrObservation;
  without: MmrEstimate;
  with: MmrEstimate;
  delta: number | null;
  explanation: string;
}

/** GET /api/mmr/participants/{pid}/explain?at= */
export interface MmrExplanation {
  at_utc: string;
  before: MmrEstimate | null;
  after: MmrEstimate;
  delta: number | null;
  activities: string[];
  explanation: string[];
}

export interface MmrComparisonRow {
  participant: RunnerRef;
  estimate: MmrEstimate;
  rank: number | null;
}

/** GET /api/mmr/comparison?as_of= */
export interface MmrComparison {
  version: string;
  scale_version: string;
  as_of: string | null;
  ranking_rule: string;
  rows: MmrComparisonRow[];
}

/** GET /api/mmr/method */
export interface MmrMethod {
  version: string;
  scale_version: string;
  params: Record<string, unknown>;
  meaning: string[];
  limitations: string[];
  scale_examples: { t10_s: number; t10_display: string; mmr: number }[];
}

// ================================================================ Ratings Lab (EXPERIMENTAL; synthetic examples or stored histories, read-only)
// Computed per request by runrank/lab_methods.py; never stored; never touches personal MMR or race Elo.

export type LabMethod = "A" | "B" | "C" | "D";
export type LabParams = Record<string, number | string>;

/** GET /api/lab/meta */
export interface LabMeta {
  version: string;
  experimental: true;
  methods: { key: LabMethod; name: string; params: Record<string, (number | string)[]>; defaults: LabParams }[];
  runners: { key: string; label: string }[];
  /** the two data sources; "database" is the database this app was started with (never switched silently) */
  sources: LabSourceInfo[];
  scales: string[];
  /** method B's one supported range (performance and endurance); outside it activities are kept, not scored */
  supported_range_km: [number, number];
  /** the synthetic anchor curve's range (no extrapolation or clamping) */
  curve_range_km: [number, number];
  anchors: { km: number; time_s: number; provenance: string }[];
  generator: string;
}

export interface LabSourceInfo {
  key: "synthetic" | "database";
  label: string;
  /** database source only: "demo" | "personal" | "custom" (the database the app was started with) */
  database?: string | null;
  demo_mode?: boolean | null;
  available: boolean;
  /** why the source cannot be read (e.g. the database file does not exist yet) */
  reason: string | null;
}

/** where a Lab result's history came from and which as-of date it uses */
export interface LabSourceUsed {
  key: "synthetic" | "database";
  label: string;
  database: string | null;
  demo_mode: boolean | null;
  available: boolean;
  reason: string | null;
  /** "today (default)", "explicit date", or the synthetic fixed reference date */
  as_of_basis: string;
  as_of_date: string;
  /** database source only: the server's current UTC date */
  today: string | null;
}

/** a stored runner as read for the Lab (GET /api/lab/db/runners) */
export interface LabStoredRunner {
  id: number;
  label: string;
  data_kind: "real" | "synthetic" | "unlabelled";
  activities: number;
  stored_excluded: number;
  first_utc: string | null;
  last_utc: string | null;
}

/** GET /api/lab/db/runners (read-only connection) */
export interface LabStoredRunners {
  source: LabSourceInfo;
  runners: LabStoredRunner[];
}

/** stored provenance of an activity read from the database (null for synthetic examples) */
export interface LabProvenance {
  activity_id: number;
  source: string;
  source_activity_id: string | null;
  import_file: string | null;
  imported_utc: string | null;
  first_import_id: number;
  last_import_id: number;
  stored_exclude: boolean;
  stored_exclude_note: string | null;
  stored_not_duplicate: boolean;
  /** optional fields absent in the stored row: "moving time", "elevation", "heart rate" */
  missing: string[];
}

export interface LabExplanationSummary {
  components: { component: string; value: number; activity: string; date: string; detail: string; raises: string;
    lowers: string; provisional: boolean; warnings: string[] }[];
  weighting: string;
  unvalidated: string[];
}

export interface LabSelectedEvidence {
  component: string;
  value: number;
  activity: string;
  date: string;
  detail: string;
  /** true when uncorroborated by another independent session, or set by an ambiguous overlap */
  provisional: boolean;
  concerns: string[];
}

export interface LabResult {
  combined: number | null;
  /** speed/endurance (A: speed only; C: short/middle/marathon/ultra); null = missing evidence, never zero */
  components: Record<string, number | null>;
  evidence: Record<string, unknown>;
  notes: string[];
  /** method B only: the evidence behind each component */
  selected: LabSelectedEvidence[];
}

export interface LabActivity {
  key: string;
  start_utc: string;
  type: string;
  distance_m: number;
  elapsed_s: number;
  moving_s: number | null;
  effort: string;
  used_for: string[];
  dropped: string | null;
  duplicate_of: string | null;
  duplicate_kind: "exact" | "probable" | null;
  t10_s: number | null;
  /** endurance credit: distance × continuity × running-pace factor (km) */
  credited_km: number | null;
  continuity: string | null;
  overlap: string | null;
  flags: string[];
  /** exp4 evidence state: counted, flagged (counted, review suggested), held (counts for nothing), dropped;
   * unsupported (no component can use it: type or range), outside window (older than 365 days before as-of),
   * excluded (stored) (a stored annotation; not part of the Lab input) */
  state: "counted" | "flagged" | "held" | "dropped" | "invalid" | "after as-of" | "unsupported" | "outside window"
    | "excluded (stored)";
  /** why an unsupported or stored-excluded activity is not used */
  reasons: string[];
  /** recordings of the same effort under the selected method's duplicate rule (A: production's; B-D: exact or
   * probable duplicates); ambiguous overlaps are never grouped. Empty when the activity has no duplicate */
  duplicate_group: string[];
  provenance: LabProvenance | null;
}

/** GET /api/lab/runners/{key}?method=&<predeclared params> (synthetic) or
 * GET /api/lab/db/runners/{pid}?as_of=YYYY-MM-DD&method=&... (stored history, read-only; as_of defaults to today) */
export interface LabRunner {
  /** synthetic: { key, label, data_kind: "synthetic" }; stored: a LabStoredRunner */
  runner: { key?: string; id?: number; label: string; data_kind: string };
  method: LabMethod;
  params: LabParams;
  /** experimental method version (ratings-lab-exp…) */
  version: string;
  source: LabSourceUsed;
  /** why a score may be absent (no activities, all excluded, evidence older than the window, ...) */
  coverage_notes: string[];
  /** activity ids kept separate because of a stored "not a duplicate" annotation */
  stored_keep_separate: string[];
  latest_activity_utc: string | null;
  /** recordings excluded in the Lab for this request only (never stored); another recording of the effort may count */
  excluded: string[];
  /** effort-level Lab exclusions: the chosen recording and every identified duplicate recording of it */
  excluded_efforts: { key: string; recordings: string[] }[];
  /** the result without any Lab override (stored annotations still applied) vs with them */
  override_impact: {
    active: boolean;
    without_lab_overrides: { combined: number | null; components: Record<string, number | null> };
    with: { combined: number | null; components: Record<string, number | null> };
    /** every activity id removed by Lab exclusions (recordings and efforts) */
    excluded_ids: string[];
  };
  /** method A only: what the comparator runs and how Lab exclusions are applied */
  comparator: string | null;
  /** activity ids the user confirmed as separate genuine activities (Lab only; not independent validation) */
  confirmed: string[];
  /** activity ids whose duplicate decision the user reversed (Lab only; the input is unchanged) */
  keep_separate: string[];
  /** method B only: how this score is determined */
  explanation: LabExplanationSummary | null;
  as_of_utc: string;
  result: LabResult;
  history: { at_utc: string; combined: number | null; components: Record<string, number | null> }[];
  activities: LabActivity[];
}

/** GET /api/lab/runners/{key}/activities/{aid}?method=&params : components without vs with this activity */
export interface LabExplanation {
  activity: { key: string; start_utc: string; type: string; distance_m: number; elapsed_s: number;
    moving_s: number | null; effort: string; pace: string };
  method: LabMethod;
  params: LabParams;
  before: LabResult;
  after: LabResult;
  deltas: Record<string, number | null>;
  reasons: string[];
}

export interface LabCell {
  config: string;
  method: LabMethod;
  params: LabParams;
  combined: number | null;
  components: Record<string, number | null>;
}

/** GET /api/lab/compare */
export interface LabCompare {
  version: string;
  as_of_utc: string;
  rows: { runner: string; label: string; activities: number; longest_km: number; races: number; cells: LabCell[] }[];
  tradeoffs: {
    endurance_weight: { runner: string; label: string; B: number; D: number }[];
    breadth: { probe: string; specialist: (number | null)[]; balanced: (number | null)[] };
    outlier: { probe: string; effects: { config: string; delta: number }[] };
    gaming: {
      more_uploads: { config: string; delta: number }[];
      more_uploads_probe: string;
      withheld_labels: { config: string; delta_speed_races: number; delta_hard_8km: number }[];
      withheld_probe: string;
    };
  };
  improvements: { label: string; dS: number; dE: number; S_after: number; E_after: number; d75: number; d50: number;
    d25: number }[];
  matched: { label: string; P_before: number; P_after: number; E_before: number; E_after: number;
    continuity_after: string; d75: number; d50: number; d25: number }[];
}
