"""API contract and behaviour tests (Starlette TestClient, disposable databases).

Expected values are hand-worked from the fixture files, not values produced by the code under test. Response keys
are checked against web/src/api/types.ts so the contract cannot drift. Legacy 5K score and race Elo routes were
archived on 2026-10-25; test_archived_routes_are_gone checks they no longer answer.
"""
import csv
import io
import pathlib
import re

import pytest
from starlette.testclient import TestClient

from conftest import FIXTURES, ROOT
from runrank import api, store

TYPES = (ROOT / "web" / "src" / "api" / "types.ts").read_text()


def ts_fields(name):
    """Top-level field names of `export interface <name> { ... }` in types.ts."""
    start = TYPES.index("export interface %s " % name)
    i = TYPES.index("{", start) + 1
    depth, fields, line, line_depth = 1, set(), "", 1
    while depth:
        ch = TYPES[i]
        if ch == "\n":
            m = re.match(r"\s{2}(\w+)\??:", line) if line_depth == 1 else None
            if m:
                fields.add(m.group(1))
            line, line_depth = "", depth
        else:
            line += ch
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    return fields


def keys_match(obj, iface):
    assert set(obj) == ts_fields(iface), (iface, set(obj) ^ ts_fields(iface))


@pytest.fixture
def demo_client(tmp_path):
    app = api.create_app(str(tmp_path / "demo.sqlite"), demo_mode=True, database="demo",
                         allowed_hosts=("testserver",))
    with TestClient(app) as c:
        for label, fixture in ((A, "runner_a_activities.csv"), (B, "runner_b_export.zip")):
            pid = c.post("/api/participants", json={"label": label, "data_kind": "synthetic",
                                                    "consent": False}).json()["id"]
            r = c.post("/api/participants/%d/imports" % pid, files={"file": (fixture, (FIXTURES / fixture).read_bytes())})
            assert r.status_code == 201
        yield c


@pytest.fixture
def personal_client(tmp_path):
    app = api.create_app(str(tmp_path / "p.sqlite"), demo_mode=False, database="personal",
                         allowed_hosts=("testserver",))
    with TestClient(app) as c:
        yield c


def pid_of(c, label):
    return next(p["id"] for p in c.get("/api/participants").json() if p["label"] == label)


A, B = "Demo Runner A (synthetic)", "Demo Runner B (synthetic)"


def test_health_and_participant_contract(demo_client):
    h = demo_client.get("/api/health").json()
    keys_match(h, "Health")
    assert h["demo_mode"] and h["database"] == "demo" and h["mmr_version"] == "mmr-envelope-v2"
    people = demo_client.get("/api/participants").json()
    keys_match(people[0], "Participant")
    assert [p["label"] for p in people] == [A, B] and {p["data_kind"] for p in people} == {"synthetic"}
    assert [p["activity_count"] for p in people] == [8, 3]


def test_create_participant_validation(personal_client, demo_client):
    r = personal_client.post("/api/participants", json={"label": "R", "data_kind": "real", "consent": False})
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_request" and "consent" in r.json()["error"]["message"]
    r = personal_client.post("/api/participants", json={"label": "R", "data_kind": "real", "consent": True})
    assert r.status_code == 201 and r.json()["data_kind"] == "real"
    r = personal_client.post("/api/participants", json={"label": "R", "data_kind": "real", "consent": True})
    assert r.status_code == 400 and "already exists" in r.json()["error"]["message"]
    r = demo_client.post("/api/participants", json={"label": "X", "data_kind": "real", "consent": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "demo_only"
    assert personal_client.post("/api/participants", content=b"not json").status_code == 400


def test_activity_filters_sort_paging_and_missing_values(demo_client):
    pid = pid_of(demo_client, A)
    base = "/api/participants/%d/activities" % pid
    lst = demo_client.get(base).json()
    keys_match(lst, "ActivityList")
    assert lst["total"] == 8 and lst["types"] == ["Ride", "Run", "Virtual Run"]
    far = demo_client.get(base + "?sort=distance&order=desc&limit=2").json()
    assert [r["id"] for r in far["rows"]] == ["1004", "1005"]       # Ride 20 km, then the 10 km run
    km = demo_client.get(base + "?min_km=9&max_km=11").json()
    assert [r["id"] for r in km["rows"]] == ["1005"]
    q = demo_client.get(base + "?q=virtual").json()
    assert [r["id"] for r in q["rows"]] == ["1008"]
    page = demo_client.get(base + "?limit=3&offset=3&sort=start&order=asc").json()
    # ascending by start: 1001, 1002, 1007 (03-15 07:01), 1003, 1004, 1005, 1006, 1008 -> offset 3
    assert [r["id"] for r in page["rows"]] == ["1003", "1004", "1005"] and page["total"] == 8
    r1003 = next(r for r in lst["rows"] if r["id"] == "1003")
    assert r1003["avg_hr"] is None and r1003["perceived_exertion"] is None and r1003["elevation_gain_m"] is None
    assert r1003["pace_s_per_km"] == 360.0          # 1818 s / 5.05 km
    bad = demo_client.get(base + "?sort=points")
    assert bad.status_code == 400 and bad.json()["error"]["field"] == "sort"
    assert demo_client.get(base + "?from=2024-04-01&to=2024-03-01").status_code == 400


def test_csv_export_matches_json(demo_client):
    pid = pid_of(demo_client, A)
    j = demo_client.get("/api/participants/%d/activities?type=Run" % pid).json()["rows"]
    c = demo_client.get("/api/participants/%d/activities.csv?type=Run" % pid)
    assert c.headers["content-type"].startswith("text/csv") and "attachment" in c.headers["content-disposition"]
    assert 'filename="runnasup_activities_%d.csv"' % pid in c.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(c.text)))
    assert [(r["id"], float(r["distance_m"])) for r in rows] == [(x["id"], x["distance_m"]) for x in j]
    assert len(rows) == 6 and "points" not in rows[0] and "algorithm" not in rows[0]


def test_activity_detail_and_isolation(demo_client):
    a, b = pid_of(demo_client, A), pid_of(demo_client, B)
    d = demo_client.get("/api/participants/%d/activities/1005" % a).json()
    keys_match(d, "ActivityDetail")
    assert d["activity"]["distance_m"] == 10000.0 and d["mmr"]["version"] == "mmr-envelope-v2"
    assert d["mmr"]["informative"] is True and d["mmr"]["t10_s"] == 3000.0     # a 10 km run is its own equivalent
    assert demo_client.get("/api/participants/%d/activities/1005" % b).status_code == 404   # not B's activity


def test_annotation_persists_once_and_recalculates(demo_client):
    a = pid_of(demo_client, A)
    url = "/api/participants/%d/activities/1002/annotation" % a
    body = {"exclude": True, "exclude_note": "SYNTHETIC test", "not_duplicate": False, "effort": "hard"}
    d = demo_client.put(url, json=body).json()
    assert d["annotation"]["exclude"] is True and len(d["annotation_log"]) == 3      # exclude, note, effort
    assert demo_client.put(url, json=body).json()["annotation_log"] == d["annotation_log"]   # repeat: no new rows
    assert d["mmr"]["informative"] is False and any("exclu" in x for x in d["mmr"]["reasons"])
    for bad in ({**body, "effort": "maximal"}, {**body, "exclude": "yes"}, {**body, "exclude_note": "x" * 501}):
        r = demo_client.put(url, json=bad)
        assert r.status_code == 400 and r.json()["error"]["code"] == "bad_request"


def test_import_preview_import_and_server_side_repeat_guard(personal_client):
    pid = personal_client.post("/api/participants", json={"label": "R", "data_kind": "synthetic",
                                                          "consent": False}).json()["id"]
    data = (FIXTURES / "runner_a_activities.csv").read_bytes()
    files = {"file": ("runner_a_activities.csv", data, "text/csv")}
    pv = personal_client.post("/api/participants/%d/imports/preview" % pid, files=files).json()
    keys_match(pv, "ImportPreview")
    assert (pv["rows_total"], pv["would_insert"], pv["rejected"]) == (12, 8, 4)
    assert personal_client.get("/api/participants/%d/imports" % pid).json() == []          # preview stored nothing
    assert personal_client.get("/api/participants/%d/activities" % pid).json()["total"] == 0
    r = personal_client.post("/api/participants/%d/imports" % pid, files=files)
    assert r.status_code == 201
    keys_match(r.json()["import"], "ImportRecord")
    keys_match(r.json()["rows"][0], "ImportRow")
    assert (r.json()["import"]["inserted"], r.json()["import"]["rejected"]) == (8, 4)
    again = personal_client.post("/api/participants/%d/imports" % pid, files=files)
    assert again.status_code == 409 and again.json()["error"]["code"] == "duplicate_file"
    assert again.json()["error"]["previous_import"]["id"] == r.json()["import"]["id"]
    forced = personal_client.post("/api/participants/%d/imports" % pid, files=files, data={"confirm_repeat": "true"})
    assert forced.status_code == 201 and forced.json()["import"]["duplicates"] == 8
    assert personal_client.get("/api/participants/%d/activities" % pid).json()["total"] == 8   # no duplicates
    bad = personal_client.post("/api/participants/%d/imports" % pid,
                               files={"file": ("bad_empty.csv", b"", "text/csv")}).json()
    assert bad["import"]["status"] == "file_rejected" and "file is empty" in bad["import"]["message"]
    assert personal_client.post("/api/participants/%d/imports" % pid).status_code == 400   # no file field


def test_upload_limit_and_internal_error_shape(personal_client, monkeypatch):
    pid = personal_client.post("/api/participants", json={"label": "R", "data_kind": "synthetic",
                                                          "consent": False}).json()["id"]
    monkeypatch.setattr(api, "MAX_UPLOAD", 10)
    r = personal_client.post("/api/participants/%d/imports/preview" % pid,
                             files={"file": ("a.csv", b"x" * 100, "text/csv")})
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"

    def boom(*a, **k):
        raise RuntimeError("secret activity name in exception")
    monkeypatch.setattr(store, "activities", boom)
    quiet = TestClient(personal_client.app, raise_server_exceptions=False)
    r = quiet.get("/api/participants/%d/activities" % pid)
    assert r.status_code == 500 and r.json() == {"error": {"code": "internal", "message":
                                                           "unexpected server error; nothing was changed by a failed request"}}


def test_trusted_host_and_spa_fallback(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>RunnasUP</title>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    monkeypatch.setattr(api, "DIST", dist)
    app = api.create_app(str(tmp_path / "x.sqlite"), allowed_hosts=("testserver",))
    with TestClient(app) as c:
        assert "RunnasUP" in c.get("/activities/1001").text            # client route -> index.html
        assert c.get("/assets/app.js").text == "console.log(1)"
        assert c.get("/../../etc/passwd").status_code in (200, 404) and "root:" not in c.get("/../../etc/passwd").text
        assert c.get("/api/nope").json()["error"]["code"] == "not_found"
    with TestClient(api.create_app(str(tmp_path / "y.sqlite"))) as c:       # only localhost hosts allowed
        assert c.get("/api/health").status_code == 400


def _runner_with(client, label, fixture):
    pid = client.post("/api/participants", json={"label": label, "data_kind": "synthetic", "consent": False}).json()["id"]
    data = (FIXTURES / fixture).read_bytes()
    r = client.post("/api/participants/%d/imports" % pid, files={"file": (fixture, data, "text/csv")})
    assert r.status_code == 201
    return pid


def test_edge_unicode_and_long_names_roundtrip(personal_client):
    pid = _runner_with(personal_client, "Unicode", "edge_unicode_names.csv")
    base = "/api/participants/%d/activities" % pid
    assert [r["id"] for r in personal_client.get(base, params={"q": "SÃO paulo"}).json()["rows"]] == ["3001"]
    assert [r["id"] for r in personal_client.get(base, params={"q": "東京"}).json()["rows"]] == ["3002"]
    long = personal_client.get(base + "/3001").json()["activity"]["name"]
    assert long.startswith('Corrida matinal — São Paulo, "parque"') and len(long) > 150
    rows = list(csv.DictReader(io.StringIO(personal_client.get(base + ".csv").text)))
    assert {r["name"] for r in rows} >= {"東京マラソン練習 5km テンポ走", "Läufchen am Rhein; Ölweg (Ü-Strecke)"}
    r3003 = next(r for r in personal_client.get(base).json()["rows"] if r["id"] == "3003")
    assert r3003["moving_s"] is None and r3003["moving_pace_s_per_km"] is None and r3003["avg_hr"] is None


def test_empty_database_endpoints(personal_client):
    assert personal_client.get("/api/participants").json() == []
    assert personal_client.get("/api/participants/1/activities").status_code == 404
    assert personal_client.get("/api/mmr/comparison").status_code == 200


def test_archived_routes_are_gone(demo_client):
    a = pid_of(demo_client, A)
    for url in ("/api/participants/%d/overview" % a, "/api/participants/%d/history" % a,
                "/api/participants/%d/history.csv" % a, "/api/participants/%d/explain" % a,
                "/api/participants/%d/recalculations" % a, "/api/comparison", "/api/comparison.csv",
                "/api/comparison/pair?a=1&b=2", "/api/method", "/api/races", "/api/elo/ratings", "/api/elo/config"):
        r = demo_client.get(url)
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found", url
    assert demo_client.post("/api/demo/load").status_code in (404, 405)


# ---- critical-review regressions (reviewer findings; legacy-score ones archived)

def test_review_preview_honours_apply_corrections(personal_client):
    pid = personal_client.post("/api/participants", json={"label": "R", "data_kind": "synthetic",
                                                          "consent": False}).json()["id"]
    up = lambda f: {"file": (f, (FIXTURES / f).read_bytes(), "text/csv")}
    personal_client.post("/api/participants/%d/imports" % pid, files=up("runner_a_activities.csv"))
    off = personal_client.post("/api/participants/%d/imports/preview" % pid, files=up("runner_a_corrected.csv")).json()
    on = personal_client.post("/api/participants/%d/imports/preview" % pid, files=up("runner_a_corrected.csv"),
                              data={"apply_corrections": "true"}).json()
    assert (off["conflicts"], off["corrected"]) == (1, 0) and (on["conflicts"], on["corrected"]) == (0, 1)
    real = personal_client.post("/api/participants/%d/imports" % pid, files=up("runner_a_corrected.csv"),
                                data={"apply_corrections": "true"}).json()["import"]
    assert (real["conflicts"], real["corrected"]) == (on["conflicts"], on["corrected"])    # preview was truthful


def test_review_search_matches_activity_id_exactly(personal_client):
    pid = _runner_with(personal_client, "Unicode", "edge_unicode_names.csv")       # names do not contain IDs
    rows = personal_client.get("/api/participants/%d/activities" % pid, params={"q": "3002"}).json()["rows"]
    assert [r["id"] for r in rows] == ["3002"]


def test_review_demo_reference_date_is_latest_activity(demo_client, personal_client):
    assert demo_client.get("/api/health").json()["reference_date"] == "2024-03-30"   # B's 2003 is the latest
    from datetime import datetime, timezone
    assert personal_client.get("/api/health").json()["reference_date"] == datetime.now(timezone.utc).date().isoformat()


def test_review_csv_cells_cannot_start_formulas(personal_client):
    pid = personal_client.post("/api/participants", json={"label": "F", "data_kind": "synthetic",
                                                          "consent": False}).json()["id"]
    hdr = "Activity ID,Activity Date,Activity Type,Elapsed Time,Distance,Elapsed Time,Distance,Activity Name\n"
    body = hdr + '1,"Mar 1, 2024, 7:00:00 AM",Run,1500,5.00,1500,5000.0,"=HYPERLINK(""http://x"")"\n'
    personal_client.post("/api/participants/%d/imports" % pid, files={"file": ("f.csv", body.encode(), "text/csv")})
    rows = list(csv.DictReader(io.StringIO(personal_client.get("/api/participants/%d/activities.csv" % pid).text)))
    assert rows[0]["name"] == "'=HYPERLINK(\"http://x\")"
    j = personal_client.get("/api/participants/%d/activities/1" % pid).json()
    assert j["activity"]["name"] == '=HYPERLINK("http://x")'          # stored and shown unchanged in the app
