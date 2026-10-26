"""Read-only adapter: stored runner histories -> Ratings Lab inputs (EXPERIMENTAL; never writes).

The Lab reads the application database through a SQLite URI with mode=ro plus PRAGMA query_only, never
through store.connect (which creates the schema and runs migrations). Nothing here imports, scores or stores:
rows become lab_methods.Act records and runrank.lab_methods computes everything.

Field mapping (stored column -> Act field), explicit so units stay visible:
  activities.id (integer)            -> key, as a string; source and source_activity_id kept as provenance
  start_utc 'YYYY-MM-DDTHH:MM:SSZ'   -> start, timezone-aware UTC datetime (store.parse_iso)
  activity_type (Strava's text)      -> type, unchanged ('Run', 'Trail Run', 'Ride', ...); lab_methods decides use
  distance_m (metres, > 0)           -> distance_m, metres
  elapsed_s (seconds, > 0)           -> elapsed_s, seconds
  moving_s (seconds or NULL)         -> moving_s, None when missing (never replaced by elapsed time)
  elevation_gain_m (metres or NULL)  -> gain_m, None when missing
  avg_hr (bpm or NULL)               -> hr, None when missing
  annotations.effort (or 'unknown')  -> effort (context only in every method)
  annotations.exclude = 1            -> left out of the Lab input and listed as a stored exclusion
  annotations.not_duplicate = 1      -> keep_separate: the Lab's duplicate rule never drops this activity
"""
import os
import sqlite3
from datetime import timedelta
from urllib.parse import quote

from . import lab_methods as L
from . import store


class Unavailable(Exception):
    """The database cannot be read (missing file, unreadable, older schema)."""


def connect_ro(path):
    """A read-only connection. Never creates the file: a missing database raises Unavailable."""
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise Unavailable("the database file does not exist yet (nothing has been imported into it)")
    try:
        con = sqlite3.connect("file:%s?mode=ro" % quote(path), uri=True)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only = ON")
        con.execute("SELECT 1 FROM activities LIMIT 1").fetchall()
    except sqlite3.Error as exc:
        raise Unavailable("the database could not be read: %s" % exc)
    return con


def _cols(con, table):
    return {r["name"] for r in con.execute("PRAGMA table_info(%s)" % table)}


def runners(con):
    """Every stored participant with activity counts; data_kind tells real from synthetic runners."""
    kind = "p.data_kind" if "data_kind" in _cols(con, "participants") else "'unlabelled'"
    rows = con.execute(
        "SELECT p.id, p.label, %s AS data_kind, COUNT(a.id) AS activities,"
        " SUM(CASE WHEN COALESCE(n.exclude, 0) = 1 THEN 1 ELSE 0 END) AS excluded,"
        " MIN(a.start_utc) AS first_utc, MAX(a.start_utc) AS last_utc"
        " FROM participants p LEFT JOIN activities a ON a.participant_id = p.id"
        " LEFT JOIN annotations n ON n.activity_id = a.id GROUP BY p.id ORDER BY p.label" % kind).fetchall()
    return [{"id": r["id"], "label": r["label"], "data_kind": r["data_kind"], "activities": r["activities"],
             "stored_excluded": r["excluded"] or 0, "first_utc": r["first_utc"], "last_utc": r["last_utc"]}
            for r in rows]


def runner(con, pid):
    return next((r for r in runners(con) if r["id"] == pid), None)


def history(con, pid):
    """(lab inputs, stored exclusions, keep_separate ids, provenance by key) for one participant."""
    gain = "a.elevation_gain_m" if "elevation_gain_m" in _cols(con, "activities") else "NULL"
    rows = con.execute(
        "SELECT a.id, a.source, a.source_activity_id, a.start_utc, a.activity_type, a.distance_m, a.elapsed_s,"
        " a.moving_s, a.avg_hr, %s AS elevation_gain_m, a.first_import_id, a.last_import_id,"
        " COALESCE(n.effort, 'unknown') AS effort, COALESCE(n.exclude, 0) AS exclude, n.exclude_note,"
        " COALESCE(n.not_duplicate, 0) AS not_duplicate, i.filename AS import_file, i.imported_utc"
        " FROM activities a LEFT JOIN annotations n ON n.activity_id = a.id"
        " LEFT JOIN imports i ON i.id = a.first_import_id"
        " WHERE a.participant_id = ? ORDER BY a.start_utc, a.id" % gain, (pid,)).fetchall()
    acts, stored_excluded, separate, prov = [], [], set(), {}
    for r in rows:
        key = str(r["id"])
        act = L.Act(key, store.parse_iso(r["start_utc"]), r["activity_type"], float(r["distance_m"]),
                    float(r["elapsed_s"]), None if r["moving_s"] is None else float(r["moving_s"]),
                    r["elevation_gain_m"], r["effort"], r["avg_hr"], r["source_activity_id"])
        prov[key] = {"activity_id": r["id"], "source": r["source"], "source_activity_id": r["source_activity_id"],
                     "import_file": r["import_file"], "imported_utc": r["imported_utc"],
                     "first_import_id": r["first_import_id"], "last_import_id": r["last_import_id"],
                     "stored_exclude": bool(r["exclude"]), "stored_exclude_note": r["exclude_note"],
                     "stored_not_duplicate": bool(r["not_duplicate"]),
                     "missing": [f for f, v in (("moving time", r["moving_s"]), ("elevation", r["elevation_gain_m"]),
                                                ("heart rate", r["avg_hr"])) if v is None]}
        if r["exclude"]:
            stored_excluded.append(act)
        else:
            acts.append(act)
            if r["not_duplicate"]:
                separate.add(key)
    return acts, stored_excluded, frozenset(separate), prov


def _count(k):
    """'1 activity is' / '3 activities are'."""
    return "1 activity is" if k == 1 else "%d activities are" % k


def coverage_notes(all_acts, lab_acts, stored_excluded, t):
    """Why a score may be absent at as-of t, stated from counts (missing evidence is never low ability)."""
    days = L.COMMON["window_days"]
    lo = t - timedelta(days=days)
    before = [a for a in lab_acts if a.start <= t]
    in_window = [a for a in before if a.start > lo]
    after = [a for a in lab_acts if a.start > t]
    notes = []
    if not all_acts:
        notes.append("This runner has no stored activities: nothing to score.")
    elif not lab_acts:
        notes.append("Every stored activity (%d) is excluded by a stored annotation: nothing to score." % len(all_acts))
    elif before and not in_window:
        notes.append("No current score: on or before the as-of date, %s older than %d days (latest %s). The Lab only "
                     "uses the last %d days, so this is missing recent evidence, not low ability."
                     % (_count(len(before)), days, max(a.start for a in before).strftime("%Y-%m-%d"), days))
    elif not before:
        notes.append("No activity on or before the as-of date: nothing to score yet.")
    if after:
        notes.append("%s after the as-of date: listed, not used." % _count(len(after)).rsplit(" ", 1)[0].capitalize())
    if stored_excluded and lab_acts:
        notes.append("%s excluded by a stored annotation and not used; change that on the activity page, not here."
                     % _count(len(stored_excluded)).capitalize())
    return notes
