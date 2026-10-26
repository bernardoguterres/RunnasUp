"""Failure cases: whole-file rejection, collisions, rollback, annotations."""
import pytest

from conftest import fixture_bytes
from runrank import store, strava_csv


def table_counts(con):
    return {t: con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
            for t in ("activities", "import_rows", "eligibility", "corrections")}


@pytest.mark.parametrize("name, message", [
    ("bad_empty.csv", "file is empty"),
    ("bad_wrong_columns.csv", "missing column(s) Activity ID"),
    ("bad_single_distance.csv", "expected two 'Distance' columns"),
    ("bad_notes.txt", "unsupported file type"),
    ("bad_unsafe_paths.zip", "unsafe paths"),
])
def test_file_level_rejection_stores_nothing(con, name, message):
    pid = store.create_participant(con, "Synthetic Runner A", True)
    imp = store.import_file(con, pid, name, fixture_bytes(name))
    row = con.execute("SELECT status, message FROM imports WHERE id=?", (imp,)).fetchone()
    assert row["status"] == "file_rejected" and message in row["message"]
    assert table_counts(con) == {"activities": 0, "import_rows": 0, "eligibility": 0, "corrections": 0}


def test_identity_collision_between_participants(con, two_runners):
    a, b = two_runners
    imp = store.import_file(con, b, "runner_b_collision.csv", fixture_bytes("runner_b_collision.csv"))
    rows = {r["source_activity_id"]: r for r in store.import_rows(con, imp)}
    assert rows["1001"]["outcome"] == "rejected"
    assert "already stored for another participant" in rows["1001"]["detail"]
    assert "Synthetic Runner A" not in rows["1001"]["detail"]          # no cross-participant label leak
    assert rows["2004"]["outcome"] == "inserted"
    owner = con.execute("SELECT participant_id FROM activities WHERE source_activity_id='1001'").fetchone()
    assert owner[0] == a
    assert {r["source_activity_id"] for r in store.activities(con, b)} == {"2001", "2002", "2003", "2004"}


def test_failed_import_rolls_back(con, monkeypatch):
    pid = store.create_participant(con, "Synthetic Runner A", True)
    real = store._import_row
    calls = {"n": 0}

    def flaky(*args):
        calls["n"] += 1
        if calls["n"] == 5:
            raise RuntimeError("simulated crash mid-import")
        return real(*args)

    monkeypatch.setattr(store, "_import_row", flaky)
    imp = store.import_file(con, pid, "runner_a_activities.csv", fixture_bytes("runner_a_activities.csv"))
    row = con.execute("SELECT status, message FROM imports WHERE id=?", (imp,)).fetchone()
    assert row["status"] == "failed" and "rolled back" in row["message"]
    assert table_counts(con) == {"activities": 0, "import_rows": 0, "eligibility": 0, "corrections": 0}
    assert con.execute("SELECT COUNT(*) FROM imports").fetchone()[0] == 1
    monkeypatch.setattr(store, "_import_row", real)       # retry after the failure succeeds
    imp = store.import_file(con, pid, "runner_a_activities.csv", fixture_bytes("runner_a_activities.csv"))
    assert con.execute("SELECT inserted FROM imports WHERE id=?", (imp,)).fetchone()[0] == 8


def test_participant_rules(con):
    with pytest.raises(ValueError, match="consented"):
        store.create_participant(con, "X", False)
    store.create_participant(con, "X", True)
    with pytest.raises(ValueError, match="already exists"):
        store.create_participant(con, "X", True)


def test_annotations_exclude_restore_and_log(con, two_runners):
    a, _ = two_runners
    acts = {r["source_activity_id"]: r for r in store.activities(con, a)}

    def mmr_state():   # Running MMR classification of each stored activity
        return {c.obs.key: (c.informative, list(c.reasons)) for c in store.mmr_observations(con, a)}
    store.set_annotation(con, acts["1002"]["id"], True, "watch glitch", False, "hard")
    s = mmr_state()
    assert s["1002"] == (False, ["excluded by annotation"])
    assert store.activities(con, a)[1]["exclude_note"] == "watch glitch"
    # excluding the kept copy does not promote its duplicate: both record the same effort
    assert s["1007"] == (False, ["possible duplicate of activity 1002"])
    store.set_annotation(con, acts["1007"]["id"], False, None, True, "unknown")
    assert mmr_state()["1007"] == (True, [])
    store.set_annotation(con, acts["1002"]["id"], False, None, False, "hard")
    assert mmr_state()["1002"] == (True, [])
    fields = [(r["source_activity_id"], r["field"], r["new_value"]) for r in store.annotation_log(con, a)]
    assert ("1002", "exclude", "1") in fields and ("1002", "exclude", "0") in fields
    assert ("1002", "effort", "hard") in fields and ("1007", "not_duplicate", "1") in fields
    assert store.set_annotation(con, acts["1002"]["id"], False, None, False, "hard") is False
    with pytest.raises(ValueError):
        store.set_annotation(con, acts["1002"]["id"], False, None, False, "maximal")


def test_effort_annotation_does_not_change_score(con, two_runners):
    from runrank import mmr
    from conftest import utc
    a, _ = two_runners
    at = utc("2024-03-31 23:59:59")
    before = mmr.estimate_at(store.mmr_observations(con, a), at).mmr
    acts = {r["source_activity_id"]: r for r in store.activities(con, a)}
    for effort in ("easy", "hard", "race"):
        store.set_annotation(con, acts["1002"]["id"], False, None, False, effort)
        assert mmr.estimate_at(store.mmr_observations(con, a), at).mmr == before


def test_parser_units_and_optional_ranges():
    hdr = ("Activity ID,Activity Date,Activity Type,Elapsed Time,Distance,Elapsed Time,Moving Time,"
           "Distance,Average Heart Rate,Perceived Exertion\n")
    body = (hdr
            + '1,"Mar 1, 2024, 7:00:00 AM",Run,1500,3.11,1500.0,1490,5005.0,300,11\n'   # miles display
            + '2,"Mar 1, 2024, 7:00:00 PM",Run,1500,5.00,1501.5,abc,5000.0,,\n'          # elapsed disagree
            + '3,"Mar 2, 2024, 7:00:00 AM",Run,0,5.00,0,,5000.0,,\n')
    rows = strava_csv.parse_activities_csv(body.encode())
    r1, r2, r3 = rows
    assert r1.values["distance_m"] == 5005.0 and r1.values["avg_hr"] is None
    assert r1.values["perceived_exertion"] is None and len(r1.warnings) == 2
    assert r1.values["start_utc"].isoformat() == "2024-03-01T07:00:00+00:00"
    assert any("elapsed time columns disagree" in e for e in r2.errors)
    assert any("invalid elapsed time" in e for e in r3.errors)


def test_review_f1_duplicate_chain_collapses():
    # reviewer counterexample: A 07:00:00, B 07:01:40, C 07:03:20, 5000 m each
    from runrank import activity_rules
    from conftest import utc
    acts = [("A", utc("2024-03-01 07:00:00"), 5000.0, "Run", False),
            ("B", utc("2024-03-01 07:01:40"), 5000.0, "Run", False),
            ("C", utc("2024-03-01 07:03:20"), 5000.0, "Run", False)]
    assert activity_rules.possible_duplicates(acts) == {"B": "A", "C": "A"}


def test_review_f7_f9_parser_strictness():
    hdr = "Activity ID,Activity Date,Activity Type,Elapsed Time,Distance,Elapsed Time,Distance\n"
    body = (hdr + '1,"Mar 1, 2024, 7:00:00 AM",Run,1500,,1500,5000\n'
            + '2,"Mar 1, 2024, 8:00:00 AM",Run,1_500,5.00,1500,5000\n'
            + '3,"Mar 1, 2024, 9:00:00 AM",Run,1500,"5,000",1500,"5,000"\n')
    r1, r2, r3 = strava_csv.parse_activities_csv(body.encode())
    assert r1.values["distance_m"] == 5000 and any("display Distance blank" in w for w in r1.warnings)
    assert r2.values is None and any("not a plain number" in e for e in r2.errors)
    assert r3.values is None and any("not a plain number" in e for e in r3.errors)
