"""SQLite persistence: participants, imports, activities, annotations, Running MMR snapshots.

Every import is one transaction: either all of its rows are recorded or none.
Stored activity fields are the normalized CSV values; no GPS data is kept.
The legacy 5K score and race Elo were removed on 2026-10-25 (kept in a local backup, not in the repository). Their tables stay in the schema so
existing databases and their stored rows are untouched, but nothing writes them any more.
"""
import hashlib
import json
import os
import sqlite3
from datetime import datetime, time, timezone

from . import activity_rules, mmr, strava_csv

SCHEMA_VERSION = "5"
SOURCE = "strava_activities_csv"
DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "data", "runrank.sqlite")
EFFORTS = ("unknown", "easy", "moderate", "hard", "race")
CORRECTABLE = ("start_utc", "activity_type", "name", "distance_m", "elapsed_s",
               "moving_s", "avg_hr", "perceived_exertion")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS participants (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL UNIQUE,
    consent_confirmed_utc TEXT NOT NULL,
    created_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY,
    participant_id INTEGER NOT NULL REFERENCES participants(id),
    filename TEXT NOT NULL,
    file_sha256 TEXT NOT NULL,
    source_member TEXT,
    imported_utc TEXT NOT NULL,
    apply_corrections INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('completed', 'file_rejected', 'failed')),
    message TEXT,
    rows_total INTEGER NOT NULL DEFAULT 0,
    inserted INTEGER NOT NULL DEFAULT 0,
    duplicates INTEGER NOT NULL DEFAULT 0,
    conflicts INTEGER NOT NULL DEFAULT 0,
    corrected INTEGER NOT NULL DEFAULT 0,
    rejected INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY,
    participant_id INTEGER NOT NULL REFERENCES participants(id),
    source TEXT NOT NULL,
    source_activity_id TEXT NOT NULL,
    start_utc TEXT NOT NULL,
    activity_type TEXT NOT NULL,
    name TEXT,
    distance_m REAL NOT NULL CHECK (distance_m > 0),
    elapsed_s REAL NOT NULL CHECK (elapsed_s > 0),
    moving_s REAL,
    avg_hr REAL,
    perceived_exertion REAL,
    first_import_id INTEGER NOT NULL REFERENCES imports(id),
    last_import_id INTEGER NOT NULL REFERENCES imports(id),
    UNIQUE (source, source_activity_id)
);
CREATE TABLE IF NOT EXISTS import_rows (
    id INTEGER PRIMARY KEY,
    import_id INTEGER NOT NULL REFERENCES imports(id),
    line_no INTEGER NOT NULL,
    source_activity_id TEXT,
    outcome TEXT NOT NULL CHECK (outcome IN ('inserted', 'duplicate', 'conflict', 'corrected', 'rejected')),
    detail TEXT
);
CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY,
    activity_id INTEGER NOT NULL REFERENCES activities(id),
    import_id INTEGER NOT NULL REFERENCES imports(id),
    field TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT
);
CREATE TABLE IF NOT EXISTS annotations (
    activity_id INTEGER PRIMARY KEY REFERENCES activities(id),
    exclude INTEGER NOT NULL DEFAULT 0,
    exclude_note TEXT,
    not_duplicate INTEGER NOT NULL DEFAULT 0,
    effort TEXT NOT NULL DEFAULT 'unknown'
        CHECK (effort IN ('unknown', 'easy', 'moderate', 'hard', 'race')),
    updated_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS annotation_log (
    id INTEGER PRIMARY KEY,
    activity_id INTEGER NOT NULL REFERENCES activities(id),
    changed_utc TEXT NOT NULL,
    field TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT
);
CREATE TABLE IF NOT EXISTS calculations (
    id INTEGER PRIMARY KEY,
    participant_id INTEGER NOT NULL REFERENCES participants(id),
    algorithm_version TEXT NOT NULL,
    params_json TEXT NOT NULL,
    computed_utc TEXT NOT NULL,
    trigger TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eligibility (
    activity_id INTEGER PRIMARY KEY REFERENCES activities(id),
    calculation_id INTEGER NOT NULL REFERENCES calculations(id),
    eligible INTEGER NOT NULL,
    reasons_json TEXT NOT NULL,
    t5_s REAL
);
-- schema 4: race results and race Elo (runrank.races, runrank.elo); new tables only
CREATE TABLE IF NOT EXISTS races (
    id INTEGER PRIMARY KEY,
    race_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    start_utc TEXT NOT NULL,
    distance_m REAL NOT NULL CHECK (distance_m > 0),
    classification TEXT,
    elevation_gain_m REAL,
    order_by TEXT NOT NULL CHECK (order_by IN ('place', 'time')),
    data_kind TEXT NOT NULL CHECK (data_kind IN ('real', 'synthetic', 'unlabelled')),
    revision INTEGER NOT NULL DEFAULT 1,
    created_utc TEXT NOT NULL,
    updated_utc TEXT NOT NULL,
    created_source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS race_results (
    id INTEGER PRIMARY KEY,
    race_id INTEGER NOT NULL REFERENCES races(id),
    participant_id INTEGER NOT NULL REFERENCES participants(id),
    status TEXT NOT NULL CHECK (status IN ('FIN', 'DNF', 'DNS', 'DSQ')),
    finish_time_s REAL CHECK (finish_time_s IS NULL OR finish_time_s > 0),
    place INTEGER CHECK (place IS NULL OR place >= 1),
    UNIQUE (race_id, participant_id)
);
CREATE TABLE IF NOT EXISTS race_imports (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    file_sha256 TEXT NOT NULL,
    imported_utc TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('completed', 'file_rejected', 'failed')),
    message TEXT,
    apply_corrections INTEGER NOT NULL,
    races_total INTEGER NOT NULL DEFAULT 0,
    inserted INTEGER NOT NULL DEFAULT 0,
    duplicates INTEGER NOT NULL DEFAULT 0,
    conflicts INTEGER NOT NULL DEFAULT 0,
    corrected INTEGER NOT NULL DEFAULT 0,
    rejected INTEGER NOT NULL DEFAULT 0,
    details_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS race_revisions (
    id INTEGER PRIMARY KEY,
    race_id INTEGER NOT NULL REFERENCES races(id),
    revision INTEGER NOT NULL,
    changed_utc TEXT NOT NULL,
    source TEXT NOT NULL,
    reason TEXT,
    content_json TEXT NOT NULL,
    UNIQUE (race_id, revision)
);
-- schema 5: Running MMR snapshots (what the app showed after each recalculation); separate from race Elo
CREATE TABLE IF NOT EXISTS mmr_runs (
    id INTEGER PRIMARY KEY,
    participant_id INTEGER NOT NULL REFERENCES participants(id),
    computed_utc TEXT NOT NULL,
    algorithm_version TEXT NOT NULL,
    scale_version TEXT NOT NULL,
    params_json TEXT NOT NULL,
    trigger TEXT NOT NULL,
    as_of_utc TEXT,
    status TEXT NOT NULL,
    mmr REAL,
    t10_s REAL,
    setter_activity_id TEXT,
    activities INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS elo_runs (
    id INTEGER PRIMARY KEY,
    computed_utc TEXT NOT NULL,
    algorithm_version TEXT NOT NULL,
    params_json TEXT NOT NULL,
    trigger TEXT NOT NULL,
    races INTEGER NOT NULL,
    ratings_json TEXT NOT NULL
);
"""


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def db_file(path=None):
    """The database path connect() would open (explicit path, then RUNRANK_DB, then the default)."""
    return path or os.environ.get("RUNRANK_DB") or DEFAULT_DB


def connect(path=None):
    path = db_file(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    con = sqlite3.connect(path, isolation_level=None)   # explicit transactions below
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    cols = [r["name"] for r in con.execute("PRAGMA table_info(participants)")]
    if "data_kind" not in cols:   # schema 2: participants created before it stay 'unlabelled'
        con.execute("ALTER TABLE participants ADD COLUMN data_kind TEXT NOT NULL DEFAULT 'unlabelled'"
                    " CHECK (data_kind IN ('real', 'synthetic', 'unlabelled'))")
    # schema 3: optional display-only elevation, and a history snapshot per recalculation
    if "elevation_gain_m" not in [r["name"] for r in con.execute("PRAGMA table_info(activities)")]:
        con.execute("ALTER TABLE activities ADD COLUMN elevation_gain_m REAL")
    if "history_json" not in [r["name"] for r in con.execute("PRAGMA table_info(calculations)")]:
        con.execute("ALTER TABLE calculations ADD COLUMN history_json TEXT")
    con.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
    con.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (SCHEMA_VERSION,))
    return con


class _tx:
    def __init__(self, con):
        self.con = con

    def __enter__(self):
        self.con.execute("BEGIN IMMEDIATE")
        return self.con

    def __exit__(self, exc_type, exc, tb):
        self.con.execute("ROLLBACK" if exc_type else "COMMIT")
        return False


# ---------------------------------------------------------------- participants

def create_participant(con, label, consent_confirmed, data_kind="real"):
    """data_kind 'real' needs confirmed consent; 'synthetic' is demonstration data."""
    label = (label or "").strip()
    if not label:
        raise ValueError("participant label is required")
    if data_kind not in ("real", "synthetic"):
        raise ValueError("data kind must be 'real' or 'synthetic'")
    if data_kind == "real" and not consent_confirmed:
        raise ValueError("confirm the participant consented before adding their data")
    if con.execute("SELECT 1 FROM participants WHERE label = ?", (label,)).fetchone():
        raise ValueError("a participant called %r already exists" % label)
    ts = iso(now_utc())
    consent = ts if data_kind == "real" else "not applicable (synthetic)"
    with _tx(con):
        cur = con.execute("INSERT INTO participants(label, consent_confirmed_utc, created_utc, data_kind)"
                          " VALUES (?, ?, ?, ?)", (label, consent, ts, data_kind))
    return cur.lastrowid


def completed_import_of(con, participant_id, sha):
    """Most recent completed import of identical file bytes for this participant, if any."""
    return con.execute("SELECT * FROM imports WHERE participant_id = ? AND file_sha256 = ? AND"
                       " status = 'completed' ORDER BY id DESC LIMIT 1", (participant_id, sha)).fetchone()


def file_sha256(data):
    return hashlib.sha256(data or b"").hexdigest()


def participants(con):
    return con.execute("SELECT * FROM participants ORDER BY label").fetchall()


# ---------------------------------------------------------------- import

def _row_dict(values):
    d = dict(values)
    d["start_utc"] = iso(d["start_utc"])
    return d


def _same(a, b):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, float) or isinstance(b, float):
        return abs(float(a) - float(b)) <= 1e-6
    return a == b


def import_file(con, participant_id, filename, data, apply_corrections=False):
    """Import one uploaded file for one participant. Returns the imports row id.

    File-level problems record a 'file_rejected' import and store no rows.
    Any unexpected error rolls back every row and records a 'failed' import.
    """
    if not con.execute("SELECT 1 FROM participants WHERE id = ?", (participant_id,)).fetchone():
        raise ValueError("unknown participant id %r" % participant_id)
    sha = file_sha256(data)
    started = iso(now_utc())
    try:
        body, member = strava_csv.read_upload(filename, data)
        rows = strava_csv.parse_activities_csv(body)
    except strava_csv.FileRejected as exc:
        return _record_import(con, participant_id, filename, sha, None, started,
                              apply_corrections, "file_rejected", str(exc))
    except Exception as exc:  # unexpected reader error: report it, never crash the page or hide it
        return _record_import(con, participant_id, filename, sha, None, started, apply_corrections,
                              "failed", "file could not be read: %s: %s" % (type(exc).__name__, exc))
    try:
        with _tx(con):
            imp = con.execute(
                "INSERT INTO imports(participant_id, filename, file_sha256, source_member, imported_utc,"
                " apply_corrections, status, rows_total) VALUES (?, ?, ?, ?, ?, ?, 'completed', ?)",
                (participant_id, filename, sha, member, started, int(apply_corrections), len(rows))
            ).lastrowid
            counts = {"inserted": 0, "duplicates": 0, "conflicts": 0, "corrected": 0, "rejected": 0}
            seen_in_file = {}
            for row in rows:
                outcome, detail = _import_row(con, participant_id, imp, row, apply_corrections,
                                              seen_in_file)
                key = {"duplicate": "duplicates", "conflict": "conflicts"}.get(outcome, outcome)
                counts[key] += 1
                con.execute("INSERT INTO import_rows(import_id, line_no, source_activity_id, outcome, detail)"
                            " VALUES (?, ?, ?, ?, ?)",
                            (imp, row.line_no, row.source_activity_id, outcome, detail))
            con.execute("UPDATE imports SET inserted=?, duplicates=?, conflicts=?, corrected=?, rejected=?"
                        " WHERE id=?", (counts["inserted"], counts["duplicates"], counts["conflicts"],
                                        counts["corrected"], counts["rejected"], imp))
            _recompute(con, participant_id, "import %d" % imp)
        return imp
    except Exception as exc:  # rolled back above; leave an audit record
        return _record_import(con, participant_id, filename, sha, member, started,
                              apply_corrections, "failed",
                              "import failed and was rolled back: %s: %s" % (type(exc).__name__, exc))


class _Preview(Exception):
    """Raised inside the preview transaction so that everything is rolled back."""

    def __init__(self, result):
        super().__init__("preview")
        self.result = result


def preview_import(con, participant_id, filename, data, apply_corrections=False):
    """Dry run of import_file: the same per-row logic inside a transaction that is
    always rolled back. Returns a dict; nothing (not even an import record) is stored."""
    if not con.execute("SELECT 1 FROM participants WHERE id = ?", (participant_id,)).fetchone():
        raise ValueError("unknown participant id %r" % participant_id)
    base = {"filename": filename, "file_error": None, "rows_total": 0, "would_insert": 0, "duplicates": 0,
            "conflicts": 0, "corrected": 0, "rejected": 0, "warnings": 0, "rows": []}
    try:
        body, _member = strava_csv.read_upload(filename, data)
        rows = strava_csv.parse_activities_csv(body)
    except strava_csv.FileRejected as exc:
        return dict(base, file_error=str(exc))
    except Exception as exc:
        return dict(base, file_error="file could not be read: %s" % type(exc).__name__)
    try:
        with _tx(con):
            imp = con.execute(
                "INSERT INTO imports(participant_id, filename, file_sha256, imported_utc, apply_corrections,"
                " status, rows_total) VALUES (?, ?, ?, ?, ?, 'completed', ?)",
                (participant_id, filename, file_sha256(data), iso(now_utc()), int(apply_corrections), len(rows))
            ).lastrowid
            result = dict(base, rows_total=len(rows))
            seen = {}
            for row in rows:
                outcome, detail = _import_row(con, participant_id, imp, row, apply_corrections, seen)
                key = {"inserted": "would_insert", "duplicate": "duplicates", "conflict": "conflicts"}.get(
                    outcome, outcome)
                result[key] += 1
                result["warnings"] += "warnings:" in (detail or "")
                result["rows"].append({"line": row.line_no, "activity_id": row.source_activity_id,
                                       "outcome": outcome, "detail": detail})
            raise _Preview(result)
    except _Preview as done:
        return done.result


def _record_import(con, participant_id, filename, sha, member, started, apply_corrections, status, msg):
    with _tx(con):
        return con.execute(
            "INSERT INTO imports(participant_id, filename, file_sha256, source_member, imported_utc,"
            " apply_corrections, status, message) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (participant_id, filename, sha, member, started, int(apply_corrections), status, msg)
        ).lastrowid


def _import_row(con, pid, imp, row, apply_corrections, seen_in_file):
    if row.errors:
        return "rejected", "; ".join(row.errors)
    v = _row_dict(row.values)
    warn = ("; warnings: " + "; ".join(row.warnings)) if row.warnings else ""
    sid = v["source_activity_id"]
    if sid in seen_in_file:
        return "rejected", "Activity ID %s appears again in this file (first at line %d)" % (
            sid, seen_in_file[sid])
    seen_in_file[sid] = row.line_no
    existing = con.execute("SELECT a.*, p.label FROM activities a JOIN participants p"
                           " ON p.id = a.participant_id WHERE source = ? AND source_activity_id = ?",
                           (SOURCE, sid)).fetchone()
    if existing is None:
        con.execute(
            "INSERT INTO activities(participant_id, source, source_activity_id, start_utc, activity_type,"
            " name, distance_m, elapsed_s, moving_s, avg_hr, perceived_exertion, elevation_gain_m,"
            " first_import_id, last_import_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pid, SOURCE, sid, v["start_utc"], v["activity_type"], v["name"], v["distance_m"],
             v["elapsed_s"], v["moving_s"], v["avg_hr"], v["perceived_exertion"], v["elevation_gain_m"],
             imp, imp))
        return "inserted", ("new activity" + warn)
    if existing["participant_id"] != pid:
        return "rejected", ("identity collision: Activity ID %s is already stored for another participant;"
                            " not imported (check the file belongs to this runner)" % sid)
    diffs = [f for f in CORRECTABLE if not _same(existing[f], v[f])]
    if not diffs:
        con.execute("UPDATE activities SET last_import_id = ? WHERE id = ?", (imp, existing["id"]))
        # elevation (display only) was not imported before schema 3: fill it once, never overwrite
        if existing["elevation_gain_m"] is None and v["elevation_gain_m"] is not None:
            con.execute("UPDATE activities SET elevation_gain_m = ? WHERE id = ?",
                        (v["elevation_gain_m"], existing["id"]))
            return "duplicate", "identical to stored activity; missing elevation gain filled (display only)"
        return "duplicate", "identical to stored activity; nothing changed"
    change = ", ".join("%s: %r -> %r" % (f, existing[f], v[f]) for f in diffs)
    if not apply_corrections:
        return "conflict", "differs from stored activity (%s); stored version kept" % change
    for f in diffs:
        con.execute("INSERT INTO corrections(activity_id, import_id, field, old_value, new_value)"
                    " VALUES (?, ?, ?, ?, ?)", (existing["id"], imp, f, _txt(existing[f]), _txt(v[f])))
    sets = ", ".join("%s = ?" % f for f in diffs)
    con.execute("UPDATE activities SET %s, last_import_id = ? WHERE id = ?" % sets,
                [v[f] for f in diffs] + [imp, existing["id"]])
    return "corrected", "stored activity corrected (%s)" % change


def _txt(v):
    return None if v is None else str(v)


# ---------------------------------------------------------------- annotations

def set_annotation(con, activity_id, exclude, exclude_note, not_duplicate, effort):
    if effort not in EFFORTS:
        raise ValueError("effort must be one of %s" % ", ".join(EFFORTS))
    act = con.execute("SELECT participant_id FROM activities WHERE id = ?", (activity_id,)).fetchone()
    if act is None:
        raise ValueError("unknown activity %r" % activity_id)
    new = {"exclude": int(bool(exclude)), "exclude_note": (exclude_note or "").strip() or None,
           "not_duplicate": int(bool(not_duplicate)), "effort": effort}
    ts = iso(now_utc())
    with _tx(con):
        old = con.execute("SELECT * FROM annotations WHERE activity_id = ?", (activity_id,)).fetchone()
        old = dict(old) if old else {"exclude": 0, "exclude_note": None, "not_duplicate": 0,
                                     "effort": "unknown"}
        changed = [f for f in new if old[f] != new[f]]
        if not changed:
            return False
        for f in changed:
            con.execute("INSERT INTO annotation_log(activity_id, changed_utc, field, old_value, new_value)"
                        " VALUES (?, ?, ?, ?, ?)", (activity_id, ts, f, _txt(old[f]), _txt(new[f])))
        con.execute("INSERT INTO annotations(activity_id, exclude, exclude_note, not_duplicate, effort,"
                    " updated_utc) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(activity_id) DO UPDATE SET"
                    " exclude=excluded.exclude, exclude_note=excluded.exclude_note,"
                    " not_duplicate=excluded.not_duplicate, effort=excluded.effort,"
                    " updated_utc=excluded.updated_utc",
                    (activity_id, new["exclude"], new["exclude_note"], new["not_duplicate"],
                     new["effort"], ts))
        _recompute(con, act["participant_id"], "annotation on activity %d" % activity_id)
    return True


# ---------------------------------------------------------------- results

def _recompute(con, pid, trigger):
    """Record a Running MMR snapshot for one participant (inside the caller's transaction)."""
    _record_mmr(con, pid, trigger)


def mmr_observations(con, pid, acts=None, dups=None):
    """Every stored activity of one runner classified for Running MMR (same duplicate rule as import)."""
    if acts is None:
        acts = con.execute(
            "SELECT a.*, COALESCE(n.exclude, 0) AS exclude, COALESCE(n.not_duplicate, 0) AS not_duplicate"
            " FROM activities a LEFT JOIN annotations n ON n.activity_id = a.id WHERE a.participant_id = ?",
            (pid,)).fetchall()
    efforts = {r["activity_id"]: r["effort"] for r in con.execute(
        "SELECT n.activity_id, n.effort FROM annotations n JOIN activities a ON a.id = n.activity_id"
        " WHERE a.participant_id = ?", (pid,))}
    rows = [{"key": a["source_activity_id"], "start_utc": parse_iso(a["start_utc"]),
             "activity_type": a["activity_type"], "distance_m": a["distance_m"], "elapsed_s": a["elapsed_s"],
             "elevation_gain_m": a["elevation_gain_m"], "effort": efforts.get(a["id"], "unknown"),
             "excluded": bool(a["exclude"]), "not_duplicate": bool(a["not_duplicate"])} for a in acts]
    if dups is None:
        dups = activity_rules.possible_duplicates(mmr.duplicate_input(rows))
    return mmr.classify_history(rows, dups)


def _record_mmr(con, pid, trigger):
    obs = mmr_observations(con, pid)
    last = max((c.obs.start_utc for c in obs), default=None)
    est = mmr.estimate_at(obs, last) if last else None
    con.execute("INSERT INTO mmr_runs(participant_id, computed_utc, algorithm_version, scale_version, params_json,"
                " trigger, as_of_utc, status, mmr, t10_s, setter_activity_id, activities)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (pid, iso(now_utc()), mmr.ALGORITHM_VERSION, mmr.SCALE_VERSION,
                 json.dumps(mmr.PARAMS, sort_keys=True), trigger, iso(last) if last else None,
                 est.status if est else mmr.INSUFFICIENT, est.mmr if est else None, est.t10_s if est else None,
                 est.setter.obs.key if est and est.setter else None, len(obs)))


def activities(con, pid):
    return con.execute(
        "SELECT a.*, COALESCE(n.effort, 'unknown') AS effort, COALESCE(n.exclude, 0) AS exclude, n.exclude_note,"
        " COALESCE(n.not_duplicate, 0) AS not_duplicate, i.filename AS first_import_file,"
        " i.imported_utc AS first_imported_utc"
        " FROM activities a LEFT JOIN annotations n ON n.activity_id = a.id"
        " JOIN imports i ON i.id = a.first_import_id"
        " WHERE a.participant_id = ? ORDER BY a.start_utc, a.source_activity_id", (pid,)).fetchall()


def data_status(con, pid):
    p = con.execute("SELECT * FROM participants WHERE id = ?", (pid,)).fetchone()
    imp = con.execute("SELECT COUNT(*) AS n, MAX(imported_utc) AS last FROM imports WHERE participant_id = ?"
                      " AND status = 'completed'", (pid,)).fetchone()
    acts = con.execute("SELECT COUNT(*) AS n, MIN(start_utc) AS first, MAX(start_utc) AS last FROM activities"
                       " WHERE participant_id = ?", (pid,)).fetchone()
    return {"data_kind": p["data_kind"], "imports": imp["n"], "last_import_utc": imp["last"],
            "activities": acts["n"], "first_activity_utc": acts["first"], "last_activity_utc": acts["last"]}


def end_of_day_utc(d):
    return datetime.combine(d, time(23, 59, 59), tzinfo=timezone.utc)


def imports(con, pid):
    return con.execute("SELECT * FROM imports WHERE participant_id = ? ORDER BY id DESC", (pid,)).fetchall()


def import_rows(con, import_id):
    return con.execute("SELECT * FROM import_rows WHERE import_id = ? ORDER BY line_no",
                       (import_id,)).fetchall()


def annotation_log(con, pid):
    return con.execute("SELECT l.*, a.source_activity_id FROM annotation_log l JOIN activities a"
                       " ON a.id = l.activity_id WHERE a.participant_id = ? ORDER BY l.id", (pid,)).fetchall()
