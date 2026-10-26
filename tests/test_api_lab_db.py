"""Ratings Lab over stored histories: read-only, explicit mapping, stored annotations respected, no writes.

The database is populated only through the existing importer and annotation endpoints, from a synthetic CSV
written here. Expected values come from (a) the hand-written source rows below, mapped to Lab records by this
test (not by runrank.lab_source), and (b) hand arithmetic with math.log; never from the adapter under test.
"""
import hashlib
import math
import sqlite3
from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

from runrank import api, lab_methods as L, store
from test_api import keys_match

HEADER = ("Activity ID,Activity Date,Activity Name,Activity Type,Elapsed Time,Distance,Elapsed Time,Moving Time,"
          "Distance,Elevation Gain,Average Heart Rate,Perceived Exertion\n")
# (id, start UTC, type, elapsed s, distance m, moving s or None, elevation m or None, hr or None)
ROWS = [
    ("9001", datetime(2026, 10, 1, 7, 0, 0), "Run", 2700, 10000.0, 2670, 50.0, 160),     # sets performance
    ("9002", datetime(2026, 10, 5, 7, 0, 0), "Run", 6300, 21097.5, None, None, None),    # no moving time; sets endurance
    ("9003", datetime(2026, 10, 1, 7, 0, 30), "Run", 2710, 10000.0, 2680, 50.0, 160),    # exact duplicate of 9001
    ("9004", datetime(2026, 10, 10, 18, 0, 0), "Run", 4500, 15000.0, 4450, 80.0, 150),
    ("9005", datetime(2026, 10, 10, 18, 0, 20), "Run", 4510, 15000.0, 4460, 80.0, 150),  # stored: not a duplicate
    ("9006", datetime(2026, 10, 12, 8, 0, 0), "Run", 840, 5000.0, 830, 10.0, 170),       # stored exclusion
    ("9007", datetime(2026, 10, 14, 8, 0, 0), "Run", 450, 1500.0, 440, None, None),      # out of range (< 3 km)
    ("9008", datetime(2026, 10, 15, 8, 0, 0), "Ride", 3600, 30000.0, 3500, 200.0, 130),  # unsupported type
    ("9009", datetime(2025, 1, 10, 8, 0, 0), "Run", 2400, 10000.0, 2390, 40.0, 165),     # older than 365 days
]
AS_OF = "2026-10-23"


def csv_text():
    out = HEADER
    for sid, st, typ, el, dm, mv, elev, hr in ROWS:
        shown = st.strftime("%b %d, %Y, %I:%M:%S %p").replace(" 0", " ")
        out += '%s,"%s",SYNTHETIC %s,%s,%d,%.2f,%d,%s,%.1f,%s,%s,\n' % (
            sid, shown, typ, typ, el, dm / 1000, el, "" if mv is None else mv, dm,
            "" if elev is None else elev, "" if hr is None else hr)
    return out.encode()


def direct_acts(keys, skip=("9006",)):
    """Hand mapping of ROWS to Lab records (metres, seconds, UTC), independent of runrank.lab_source."""
    effort = {}
    return [L.Act(keys[sid], st.replace(tzinfo=timezone.utc), typ, dm, float(el), None if mv is None else float(mv),
                  elev, effort.get(sid, "unknown"), hr)
            for sid, st, typ, el, dm, mv, elev, hr in ROWS if sid not in skip]


def dump(db):
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    try:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {t: con.execute("SELECT * FROM %s ORDER BY rowid" % t).fetchall() for t in tables}
    finally:
        con.close()


@pytest.fixture
def stored(tmp_path):
    db = tmp_path / "lab.sqlite"
    app = api.create_app(str(db), demo_mode=False, database="personal", allowed_hosts=("testserver",))
    with TestClient(app) as c:
        pid = c.post("/api/participants", json={"label": "Lab check (synthetic)", "data_kind": "synthetic"}).json()["id"]
        imp = c.post("/api/participants/%d/imports" % pid, files={"file": ("lab.csv", csv_text())}).json()
        assert imp["import"]["inserted"] == len(ROWS), imp
        for sid, body in (("9006", {"exclude": True, "exclude_note": "synthetic watch glitch"}),
                          ("9005", {"not_duplicate": True})):
            ann = {"exclude": False, "not_duplicate": False, "effort": "unknown", "exclude_note": None, **body}
            assert c.put("/api/participants/%d/activities/%s/annotation" % (pid, sid), json=ann).status_code == 200
        empty = c.post("/api/participants", json={"label": "Empty (synthetic)", "data_kind": "synthetic"}).json()["id"]
        yield c, db, pid, empty


def lab(c, pid, **q):
    r = c.get("/api/lab/db/runners/%d" % pid, params={"as_of": AS_OF, **q})
    assert r.status_code == 200, r.text
    return r.json()


def test_stored_history_matches_direct_and_hand_calculation(stored):
    c, db, pid, _ = stored
    r = lab(c, pid)
    keys_match(r, "LabRunner")
    keys_match(r["source"], "LabSourceUsed")
    keys_match(r["activities"][0], "LabActivity")
    keys_match(r["activities"][0]["provenance"], "LabProvenance")
    assert r["source"]["key"] == "database" and r["source"]["database"] == "personal"
    assert r["source"]["as_of_basis"] == "explicit date" and r["as_of_utc"] == "2026-10-23T23:59:59Z"
    assert r["runner"]["data_kind"] == "synthetic" and r["version"] == L.VERSION
    keys = {a["provenance"]["source_activity_id"]: a["key"] for a in r["activities"]}
    # direct calculation from the hand-mapped rows, with the stored annotations applied by hand
    t = datetime(2026, 10, 23, 23, 59, 59, tzinfo=timezone.utc)
    direct = L.evaluate("B", direct_acts(keys), t, {}, keep_separate=frozenset({keys["9005"]}))
    assert r["result"]["combined"] == direct.combined and r["result"]["components"] == direct.components
    # hand arithmetic: 9001 is exactly 10 km in 45:00 (T10 2700 s, 22 days old: no ageing);
    # 9002 is 21.0975 km at 4:59/km elapsed pace (running-pace factor 1, 18 days old)
    s = 3000 * math.log(7200 / 2700) / math.log(7200 / 1560)
    e = 3000 * math.log(21.0975) / math.log(250)
    assert r["result"]["components"]["speed"] == pytest.approx(s, abs=1e-6) == pytest.approx(1923.96, abs=0.01)
    assert r["result"]["components"]["endurance"] == pytest.approx(e, abs=1e-6) == pytest.approx(1656.71, abs=0.01)
    assert r["result"]["combined"] == pytest.approx(0.5 * s + 0.5 * e, abs=1e-6)
    sel = {x["component"]: x["activity"] for x in r["result"]["selected"]}
    assert sel == {"speed": keys["9001"], "endurance": keys["9002"]}
    # production method A in the Lab equals the stored production MMR for the same as-of date
    a = lab(c, pid, method="A")["result"]["components"]["speed"]
    prod = c.get("/api/mmr/participants/%d" % pid, params={"as_of": AS_OF}).json()["estimate"]
    assert a == pytest.approx(prod["mmr"], abs=1e-9) == pytest.approx(s, abs=1e-6)


def test_states_annotations_missing_fields_and_provenance(stored):
    c, _, pid, _ = stored
    r = lab(c, pid)
    by = {a["provenance"]["source_activity_id"]: a for a in r["activities"]}
    assert by["9003"]["state"] == "dropped" and by["9003"]["duplicate_of"] == by["9001"]["key"]
    assert by["9004"]["state"] != "dropped" and by["9005"]["state"] != "dropped"     # stored not_duplicate
    assert r["stored_keep_separate"] == [by["9005"]["key"]] and by["9005"]["key"] in r["keep_separate"]
    assert by["9006"]["state"] == "excluded (stored)"
    assert by["9006"]["reasons"] == ["excluded by a stored annotation: synthetic watch glitch"]
    assert by["9007"]["state"] == "unsupported" and any("3 km" in x for x in by["9007"]["reasons"])
    assert by["9008"]["state"] == "unsupported" and any("Ride" in x for x in by["9008"]["reasons"])
    assert by["9009"]["state"] == "outside window"
    assert by["9002"]["moving_s"] is None and by["9002"]["provenance"]["missing"] == ["moving time", "elevation",
                                                                                        "heart rate"]
    assert "continuity unknown: no moving time recorded" in by["9002"]["flags"]
    p = by["9001"]["provenance"]
    assert (p["source"], p["import_file"], p["stored_exclude"]) == ("strava_activities_csv", "lab.csv", False)
    assert by["9001"]["key"] == str(p["activity_id"]) and by["9001"]["distance_m"] == 10000.0
    assert "1 activity is excluded by a stored annotation and not used; change that on the activity page, not here." in r["coverage_notes"]


def test_temporary_overrides_change_only_the_response(stored):
    c, db, pid, _ = stored
    keys = {a["provenance"]["source_activity_id"]: a["key"] for a in lab(c, pid)["activities"]}
    before_tables, before_sha = dump(db), hashlib.sha256(db.read_bytes()).hexdigest()
    prod = c.get("/api/mmr/participants/%d" % pid, params={"as_of": AS_OF}).json()["estimate"]
    # exclude the speed setter in the Lab only: its duplicate 9003 is then no longer a duplicate and sets
    # performance (hand: exactly 10 km in 45:10, T10 2710 s)
    r = lab(c, pid, exclude=keys["9001"])
    assert r["result"]["components"]["speed"] == pytest.approx(3000 * math.log(7200 / 2710) / math.log(7200 / 1560),
                                                               abs=1e-6)
    assert {x["component"]: x["activity"] for x in r["result"]["selected"]}["speed"] == keys["9003"]
    assert r["excluded"] == [keys["9001"]]
    # excluding both copies: performance falls to 9002 (hand: 6300 × (10 / 21.0975)^1.06; 9004 gives 2927.6 s)
    r = lab(c, pid, exclude="%s,%s" % (keys["9001"], keys["9003"]))
    t10 = 6300 * (10000 / 21097.5) ** 1.06
    assert r["result"]["components"]["speed"] == pytest.approx(3000 * math.log(7200 / t10) / math.log(7200 / 1560),
                                                               abs=1e-6)
    lab(c, pid, keep_separate=keys["9003"], confirm=keys["9004"])
    lab(c, pid, method="C", aggregation="balanced")
    lab(c, pid, method="D", speed_weight="0.25")
    lab(c, pid, exclude_effort=keys["9001"])
    lab(c, pid, method="A", exclude=keys["9001"], keep_separate=keys["9003"])
    lab(c, pid, method="A", exclude_effort=keys["9004"])
    lab(c, pid, speed_weight="0.75", k_best="2", continuity="scalar", long_performance="bridged")
    assert c.get("/api/lab/db/runners/%d/activities/%s" % (pid, keys["9002"]), params={"method": "B"}).status_code == 200
    c.get("/api/lab/db/runners/%d" % pid)                        # default as-of: today
    c.get("/api/lab/db/runners")
    c.get("/api/lab/meta")
    # stored exclusions cannot be overridden from the Lab; unknown ids are rejected
    assert c.get("/api/lab/db/runners/%d" % pid, params={"exclude": keys["9006"]}).status_code == 400
    assert c.get("/api/lab/db/runners/%d" % pid, params={"exclude": "999999"}).status_code == 400
    assert c.get("/api/lab/db/runners/999").status_code == 404
    assert dump(db) == before_tables and hashlib.sha256(db.read_bytes()).hexdigest() == before_sha
    assert c.get("/api/mmr/participants/%d" % pid, params={"as_of": AS_OF}).json()["estimate"] == prod


def test_lab_request_path_never_uses_the_writing_connection(stored, monkeypatch):
    c, _, pid, _ = stored

    def refuse(*a, **k):
        raise AssertionError("store.connect called from a Lab route")
    monkeypatch.setattr(store, "connect", refuse)
    keys = [a["key"] for a in lab(c, pid)["activities"] if a["state"] != "excluded (stored)"]
    assert c.get("/api/lab/db/runners").status_code == 200
    assert c.get("/api/lab/meta").status_code == 200
    assert c.get("/api/lab/db/runners/%d/activities/%s" % (pid, keys[0])).status_code == 200


def test_default_as_of_is_today_and_old_or_empty_histories_are_explained(stored):
    c, _, pid, empty = stored
    r = c.get("/api/lab/db/runners/%d" % pid).json()
    today = datetime.now(timezone.utc).date().isoformat()
    assert r["source"]["as_of_basis"] == "today (default)" and r["source"]["as_of_date"] == today
    assert r["source"]["today"] == today
    old = lab(c, pid, as_of="2025-06-01")                 # only 9009 (2025-01-10 08:00) is on or before it
    f = 1 + 0.0005 * ((142 + 16 / 24 - 1 / 86400) - 30)  # 142 d 15:59:59 old: ageing factor 1.05633
    assert old["result"]["combined"] == pytest.approx(
        0.5 * 3000 * math.log(7200 / (2400 * f)) / math.log(7200 / 1560) +
        0.5 * 3000 * math.log(10 / f) / math.log(250), abs=1e-6)
    late = lab(c, pid, as_of="2026-01-20")                # 9009 is now 375 days old; everything else is later
    assert late["result"]["combined"] is None and late["result"]["components"] == {"speed": None, "endurance": None}
    assert any("older than 365 days" in n and "not low ability" in n for n in late["coverage_notes"])
    e = lab(c, empty)
    assert e["result"]["combined"] is None and e["activities"] == [] and e["latest_activity_utc"] is None
    assert e["coverage_notes"] == ["This runner has no stored activities: nothing to score."]
    runners = {x["label"]: x for x in c.get("/api/lab/db/runners").json()["runners"]}
    assert runners["Empty (synthetic)"]["activities"] == 0 and runners["Lab check (synthetic)"]["stored_excluded"] == 1


def test_missing_database_is_reported_and_never_created(tmp_path):
    db = tmp_path / "absent.sqlite"
    app = api.create_app(str(db), demo_mode=False, database="personal", allowed_hosts=("testserver",))
    with TestClient(app) as c:
        src = {s["key"]: s for s in c.get("/api/lab/meta").json()["sources"]}
        assert src["database"]["available"] is False and "does not exist" in src["database"]["reason"]
        assert c.get("/api/lab/db/runners").status_code == 409
        assert c.get("/api/lab/runners/beginner").json()["source"]["key"] == "synthetic"
    assert not db.exists()


def hand_speed(t10):
    return 3000 * math.log(7200 / t10) / math.log(7200 / 1560)


def test_recording_versus_effort_exclusion(stored):
    """9001/9003: one 10 km recorded twice. 9004 and 9005 are stored as separate (not duplicates). 9002 is separate."""
    c, _, pid, _ = stored
    r0 = lab(c, pid)
    keys = {a["provenance"]["source_activity_id"]: a["key"] for a in r0["activities"]}
    by = {a["provenance"]["source_activity_id"]: a for a in r0["activities"]}
    assert by["9001"]["duplicate_group"] == by["9003"]["duplicate_group"] == sorted([keys["9001"], keys["9003"]])
    assert by["9004"]["duplicate_group"] == [] and by["9002"]["duplicate_group"] == []   # stored not_duplicate pair
    assert r0["override_impact"]["active"] is False
    # recording: the other valid recording (9003, 45:10) becomes the scoring representative
    rec = lab(c, pid, exclude=keys["9001"])
    assert rec["override_impact"]["excluded_ids"] == [keys["9001"]]
    assert rec["result"]["components"]["speed"] == pytest.approx(hand_speed(2710), abs=1e-6)
    assert rec["override_impact"]["without_lab_overrides"]["components"]["speed"] == pytest.approx(hand_speed(2700))
    # effort: both recordings go; the separate 21.1 km (9002) now sets performance; 9004 is untouched
    eff = lab(c, pid, exclude_effort=keys["9001"])
    assert eff["excluded_efforts"] == [{"key": keys["9001"], "recordings": sorted([keys["9001"], keys["9003"]])}]
    assert eff["override_impact"]["excluded_ids"] == sorted([keys["9001"], keys["9003"]])
    assert eff["result"]["components"]["speed"] == pytest.approx(hand_speed(6300 * (10000 / 21097.5) ** 1.06), abs=1e-6)
    states = {a["provenance"]["source_activity_id"]: a["state"] for a in eff["activities"]}
    assert "9001" not in states and "9003" not in states and states["9004"] != "dropped"
    # effort exclusion of a separate activity removes only that activity
    one = lab(c, pid, exclude_effort=keys["9004"])
    assert one["override_impact"]["excluded_ids"] == [keys["9004"]]
    assert one["result"] == lab(c, pid, exclude=keys["9004"])["result"]
    # a stored exclusion cannot be an effort exclusion either
    assert c.get("/api/lab/db/runners/%d" % pid, params={"exclude_effort": keys["9006"], "as_of": AS_OF}).status_code == 400


def test_effort_exclusion_never_extends_to_ambiguous_overlaps(stored):
    c = stored[0]
    q = {"method": "B", "long_performance": "bridged"}
    r = c.get("/api/lab/runners/marathon", params=q).json()
    row = next(a for a in r["activities"] if a["key"] == "930265")
    assert row["overlap"] and "930235" in row["overlap"] and row["duplicate_group"] == []
    e = c.get("/api/lab/runners/marathon", params=dict(q, exclude_effort="930265")).json()
    assert e["override_impact"]["excluded_ids"] == ["930265"]
    assert any(a["key"] == "930235" for a in e["activities"])


def test_method_a_equals_production_including_duplicates_and_annotations(stored, tmp_path):
    c, db, pid, empty = stored
    for day in ("2025-01-11", "2025-06-01", "2026-01-20", "2026-10-02", "2026-10-11", AS_OF):
        a = c.get("/api/lab/db/runners/%d" % pid, params={"method": "A", "as_of": day}).json()
        prod = c.get("/api/mmr/participants/%d" % pid, params={"as_of": day}).json()["estimate"]
        assert a["result"]["combined"] == prod["mmr"], day
        setter = a["result"]["evidence"]["setter"]
        assert (None if setter is None else next(x["provenance"]["source_activity_id"] for x in a["activities"]
                                                 if x["key"] == setter)) == (prod["setter"] or {}).get("activity_id")
    r = lab(c, pid, method="A")
    by = {x["provenance"]["source_activity_id"]: x for x in r["activities"]}
    assert by["9003"]["state"] == "dropped" and by["9003"]["duplicate_of"] == by["9001"]["key"]
    assert by["9005"]["state"] == "counted"                       # stored not_duplicate respected
    assert "production Running MMR preprocessing" in r["comparator"]
    keys = {k: x["key"] for k, x in by.items()}
    # a Lab exclusion under A equals production after storing the same exclusion (in a copy of the database)
    lab_ex = lab(c, pid, method="A", exclude=keys["9001"])
    lab_sep = lab(c, pid, method="A", exclude=keys["9001"], keep_separate=keys["9003"])
    copy = tmp_path / "copy.sqlite"
    copy.write_bytes(db.read_bytes())
    with TestClient(api.create_app(str(copy), database="custom", allowed_hosts=("testserver",))) as c2:
        put = lambda sid, **b: c2.put("/api/participants/%d/activities/%s/annotation" % (pid, sid), json={
            "exclude": False, "not_duplicate": False, "effort": "unknown", "exclude_note": None, **b})
        put("9001", exclude=True)
        p1 = c2.get("/api/mmr/participants/%d" % pid, params={"as_of": AS_OF}).json()["estimate"]
        put("9003", not_duplicate=True)
        p2 = c2.get("/api/mmr/participants/%d" % pid, params={"as_of": AS_OF}).json()["estimate"]
    # production: 9003 stays a duplicate of the excluded 9001, so performance falls to 9002 ...
    assert lab_ex["result"]["combined"] == p1["mmr"] == pytest.approx(hand_speed(6300 * (10000 / 21097.5) ** 1.06))
    # ... unless 9003 is marked not a duplicate, when it counts (45:10)
    assert lab_sep["result"]["combined"] == p2["mmr"] == pytest.approx(hand_speed(2710))
    assert lab(c, empty, method="A")["result"]["combined"] is None


def test_method_a_equals_production_on_every_demo_history(tmp_path):
    with TestClient(api.create_app(str(tmp_path / "d.sqlite"), demo_mode=True, database="demo",
                                   allowed_hosts=("testserver",))) as c:
        assert c.post("/api/demo/histories").status_code == 200
        n = 0
        for r in c.get("/api/lab/db/runners").json()["runners"]:
            for day in ("2024-03-01", "2024-09-15", "2025-06-30", "2025-12-31", "2026-10-23"):
                a = c.get("/api/lab/db/runners/%d" % r["id"], params={"method": "A", "as_of": day}).json()
                prod = c.get("/api/mmr/participants/%d" % r["id"], params={"as_of": day}).json()["estimate"]
                assert a["result"]["combined"] == prod["mmr"] and a["result"]["evidence"]["coverage"] == prod["status"]
                n += 1
        assert n == 35
