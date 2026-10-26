#!/usr/bin/env python3
"""User journeys M (Running MMR), L (Ratings Lab over stored histories) and A, B, D-F (runners, import, annotation,
export, restart) at the API layer the React UI calls (SYNTHETIC data, disposable DB). Journey C (legacy 5K
comparison) was archived with the legacy score on 2026-10-25.

In-process Starlette TestClient: exercises routing, validation, storage and
calculation exactly as the UI's requests would, but NOT the browser, the
React components, or the network socket. Expected values are hand-worked
or recomputed here from the fixture CSV text.
Run: .venv/bin/python -I tools/journeys.py   -> docs/evidence/journeys_api.txt
"""
import csv
import io
import math
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from starlette.testclient import TestClient  # noqa: E402

from runrank import api, store  # noqa: E402

RESULTS = []
FIX = ROOT / "examples" / "synthetic"


def check(journey, item, ok, detail=""):
    RESULTS.append((journey, item, ok, detail))
    print("%s [%s] %s %s" % (journey, "VERIFIED" if ok else "FAILED", item, detail))


def client(db, demo=True):
    return TestClient(api.create_app(db, demo_mode=demo, database="demo" if demo else "custom",
                                     allowed_hosts=("testserver",)))


ADD = ("Activity ID,Activity Date,Activity Name,Activity Type,Elapsed Time,Distance,Elapsed Time,Moving Time,"
       "Distance,Elevation Gain,Average Heart Rate,Perceived Exertion\n"
       "%s,\"%s\",SYNTHETIC %s,Run,%d,%.2f,%d.0,%d,%.1f,20.0,,\n")


def mmr_journey(work):
    """M: upload a whole history -> data quality -> MMR -> history -> add runs -> explain; race Elo independent."""
    db = str(work / "mmr.sqlite")
    c = client(db, demo=False)
    pid = c.post("/api/participants", json={"label": "History (synthetic)", "data_kind": "synthetic"}).json()["id"]
    src = FIX / "mmr" / "recreational.csv"
    imp = c.post("/api/participants/%d/imports" % pid, files={"file": ("recreational.csv", src.read_bytes())}).json()
    rows = list(csv.reader(io.StringIO(src.read_text())))[1:]
    check("M", "whole history imported: every CSV row stored", imp["import"]["inserted"] == len(rows),
          "%d rows" % len(rows))
    ov = c.get("/api/mmr/participants/%d?as_of=2025-12-31" % pid).json()
    q = ov["quality"]
    check("M", "data quality: all activities kept; the double recording is the only non-informative one",
          q["activities"] == len(rows) and q["informative"] == len(rows) - 1
          and q["not_informative"][0]["reason"].startswith("possible duplicate"))
    e0 = ov["estimate"]
    check("M", "MMR calculated with evidence and an evidence-coverage label", e0["mmr"] is not None and e0["status"] in
          ("low", "medium", "high") and e0["setter"] is not None, "%.1f, %s" % (e0["mmr"], e0["status"]))
    h = c.get("/api/mmr/participants/%d/history?as_of=2025-12-31" % pid).json()
    check("M", "history reconstructed, labelled as reconstruction", h["reconstructed"] and len(h["points"]) > 100)
    # add an easy run: no change, explained
    c.post("/api/participants/%d/imports" % pid, files={"file": ("easy.csv", (ADD % (
        "719101", "Jan 3, 2026, 8:00:00 AM", "easy 8 km", 3300, 8.0, 3300, 3270, 8000.0)).encode())})
    eff = c.get("/api/mmr/participants/%d/activities/719101/effect" % pid).json()
    check("M", "added easy run: MMR unchanged and the reason is given", eff["delta"] == 0 and
          "not read as lower ability" in eff["explanation"])
    # add a strong run: increase, explained
    c.post("/api/participants/%d/imports" % pid, files={"file": ("fast.csv", (ADD % (
        "719102", "Jan 10, 2026, 8:00:00 AM", "fast 10 km", 2880, 10.0, 2880, 2860, 10000.0)).encode())})
    eff = c.get("/api/mmr/participants/%d/activities/719102/effect" % pid).json()
    t10 = 2880.0          # 10 km in 48:00 is its own 10 km-equivalent
    check("M", "added 10 km in 48:00: MMR rises to 3000 x ln(7200/2880)/ln(7200/1560) = 1797.36",
          eff["delta"] > 0 and abs(eff["with"]["mmr"] - 1797.36) < 0.01 and eff["with"]["t10_s"] == t10,
          eff["explanation"])
    at = eff["activity"]["start_utc"]
    ex = c.get("/api/mmr/participants/%d/explain" % pid, params={"at": at}).json()
    check("M", "change at that instant is explained", any("New best evidence: activity 719102" in x
                                                           for x in ex["explanation"]))
    # persistence and deterministic reconstruction across a restart
    hist1 = c.get("/api/mmr/participants/%d/history?as_of=2026-01-31" % pid).json()
    c.close()
    c2 = client(db, demo=False)
    hist2 = c2.get("/api/mmr/participants/%d/history?as_of=2026-01-31" % pid).json()
    snaps = c2.get("/api/mmr/participants/%d?as_of=2026-01-31" % pid).json()["snapshots"]
    check("M", "after restart: identical reconstructed history; one stored calculation per import",
          hist1 == hist2 and len(snaps) == 3)
    c2.close()


def lab_journey(work):
    """L: the Lab page's full request path over a stored history (synthetic CSV through the importer)."""
    import hashlib
    sys.path.insert(0, str(ROOT / "tests"))
    from test_api_lab_db import AS_OF, csv_text, dump
    db = str(pathlib.Path(work) / "lab.sqlite")
    c = client(db, demo=False)
    pid = c.post("/api/participants", json={"label": "Lab journey (synthetic)", "data_kind": "synthetic"}).json()["id"]
    imp = c.post("/api/participants/%d/imports" % pid, files={"file": ("lab.csv", csv_text())}).json()
    for sid, body in (("9006", {"exclude": True, "exclude_note": "synthetic watch glitch"}), ("9005", {"not_duplicate": True})):
        c.put("/api/participants/%d/activities/%s/annotation" % (pid, sid),
              json={"exclude": False, "not_duplicate": False, "effort": "unknown", "exclude_note": None, **body})
    check("L", "synthetic CSV imported through the existing importer", imp["import"]["inserted"] == 9)
    tables, sha = dump(db), hashlib.sha256(pathlib.Path(db).read_bytes()).hexdigest()
    prod = c.get("/api/mmr/participants/%d" % pid, params={"as_of": AS_OF}).json()["estimate"]
    # what the browser requests when the Lab page opens, then selects the database source and works with it
    shell = [c.get("/api/health").status_code, c.get("/api/participants").status_code, c.get("/").status_code]
    meta = c.get("/api/lab/meta").json()
    syn = c.get("/api/lab/runners/beginner").json()
    check("L", "page opens on the synthetic source; database offered, not selected",
          syn["source"]["key"] == "synthetic" and [x["key"] for x in meta["sources"]] == ["synthetic", "database"]
          and shell == [200, 200, 200])
    runners = c.get("/api/lab/db/runners").json()["runners"]
    r = c.get("/api/lab/db/runners/%d" % pid).json()
    check("L", "stored runner selectable; default as-of is today, shown with its basis",
          runners[0]["data_kind"] == "synthetic" and r["source"]["as_of_basis"] == "today (default)",
          "as of %s" % r["source"]["as_of_date"])
    r = c.get("/api/lab/db/runners/%d" % pid, params={"as_of": AS_OF}).json()
    hand = 0.5 * 3000 * math.log(7200 / 2700) / math.log(7200 / 1560) + 0.5 * 3000 * math.log(21.0975) / math.log(250)
    check("L", "B combined = 0.5 x 3000 ln(7200/2700)/ln(7200/1560) + 0.5 x 3000 ln(21.0975)/ln(250) = %.2f" % hand,
          abs(r["result"]["combined"] - hand) < 1e-6, "%.2f" % r["result"]["combined"])
    states = sorted({a["state"] for a in r["activities"]})
    check("L", "stored exclusion, duplicate, unsupported and outside-window states shown with reasons",
          {"excluded (stored)", "dropped", "unsupported", "outside window"} <= set(states), ", ".join(states))
    a_lab = c.get("/api/lab/db/runners/%d" % pid, params={"method": "A", "as_of": AS_OF}).json()["result"]["combined"]
    check("L", "method A runs production preprocessing: equals the stored Running MMR", a_lab == prod["mmr"],
          "%.2f" % a_lab)
    key = r["activities"][-1]["key"]
    others = [a["key"] for a in r["activities"] if a["state"] not in ("excluded (stored)",)]
    for q in ({"exclude": others[0]}, {"keep_separate": others[1]}, {"confirm": others[2]},
              {"method": "C"}, {"method": "D"}, {"method": "A"}, {"speed_weight": "0.25", "as_of": "2026-01-20"},
              {"exclude_effort": others[0]}, {"method": "A", "exclude": others[0]},
              {"method": "A", "exclude_effort": others[1]}):
        c.get("/api/lab/db/runners/%d" % pid, params=q)
    c.get("/api/lab/db/runners/%d/activities/%s" % (pid, others[0]))
    c.get("/api/lab/db/runners/%d" % pid, params={"exclude": key})            # rejected: a stored exclusion
    same = dump(db) == tables
    check("L", "after the whole page request path (shell, Lab reads, overrides): every table unchanged",
          same and c.get("/api/mmr/participants/%d" % pid, params={"as_of": AS_OF}).json()["estimate"] == prod,
          "file bytes %s" % ("identical" if hashlib.sha256(pathlib.Path(db).read_bytes()).hexdigest() == sha
                             else "changed (health/participants open the app's normal connection)"))
    c.close()


def main():
    work = pathlib.Path(tempfile.mkdtemp(prefix="runrank-journeys-"))
    db = str(work / "demo.sqlite")
    c = client(db)

    # A. first launch -> add two synthetic runners and import their files
    check("A", "empty database lists no runners", c.get("/api/participants").json() == [])
    for label, fixture in (("Demo Runner A (synthetic)", "runner_a_activities.csv"),
                           ("Demo Runner B (synthetic)", "runner_b_export.zip")):
        rid = c.post("/api/participants", json={"label": label, "data_kind": "synthetic", "consent": False}).json()["id"]
        c.post("/api/participants/%d/imports" % rid, files={"file": (fixture, (FIX / fixture).read_bytes())})
    people = c.get("/api/participants").json()
    check("A", "2 runners, 8 + 3 activities, synthetic",
          [(p["label"], p["activity_count"], p["data_kind"]) for p in people] ==
          [("Demo Runner A (synthetic)", 8, "synthetic"), ("Demo Runner B (synthetic)", 3, "synthetic")])
    a = people[0]["id"]

    # cross-runner identity: the demo file's activity IDs already belong to demo runner A
    cid = c.post("/api/participants", json={"label": "Other (synthetic)", "data_kind": "synthetic",
                                            "consent": False}).json()["id"]
    col = c.post("/api/participants/%d/imports" % cid, files={"file": (
        "a.csv", (FIX / "runner_a_activities.csv").read_bytes(), "text/csv")}).json()
    check("A", "same activity IDs under another runner are rejected as identity collisions (8), none stored",
          col["import"]["inserted"] == 0 and sum("identity collision" in x["detail"] for x in col["rows"]) == 8)

    # B. import -> inspect accepted/rejected -> inspect an activity (fresh database, like a new user)
    cb = client(str(work / "fresh.sqlite"), demo=False)
    c, c_demo = cb, c
    pid = c.post("/api/participants", json={"label": "Imported (synthetic)", "data_kind": "synthetic",
                                            "consent": False}).json()["id"]
    data = (FIX / "runner_a_activities.csv").read_bytes()
    pv = c.post("/api/participants/%d/imports/preview" % pid, files={"file": ("a.csv", data, "text/csv")}).json()
    check("B", "preview: 12 rows, 8 would be inserted, 4 rejected, nothing stored",
          (pv["rows_total"], pv["would_insert"], pv["rejected"]) == (12, 8, 4)
          and c.get("/api/participants/%d/activities" % pid).json()["total"] == 0)
    r = c.post("/api/participants/%d/imports" % pid, files={"file": ("a.csv", data, "text/csv")}).json()
    rejected = [x for x in r["rows"] if x["outcome"] == "rejected"]
    check("B", "import: 8 inserted, 4 rejected, each with a reason",
          (r["import"]["inserted"], len(rejected)) == (8, 4) and all(x["detail"] for x in rejected),
          " | ".join(x["detail"] for x in rejected))
    d = c.get("/api/participants/%d/activities/1003" % pid).json()
    src = list(csv.reader(io.StringIO(data.decode())))
    hdr = src[0]
    srow = next(x for x in src[1:] if x[0] == "1003")
    metres = float(srow[[i for i, n in enumerate(hdr) if n == "Distance"][1]])
    elapsed = float(srow[hdr.index("Elapsed Time")])
    check("B", "activity 1003: stored distance/elapsed equal source CSV; HR and RPE null (not 0)",
          (d["activity"]["distance_m"], d["activity"]["elapsed_s"]) == (metres, elapsed)
          and d["activity"]["avg_hr"] is None and d["activity"]["perceived_exertion"] is None)

    c.close()
    c = c_demo
    # D. annotation -> recalculation -> reload
    url = "/api/participants/%d/activities/1001/annotation" % a
    c.put(url, json={"exclude": True, "exclude_note": "SYNTHETIC", "not_duplicate": False, "effort": "unknown"})
    c.put(url, json={"exclude": True, "exclude_note": "SYNTHETIC", "not_duplicate": False, "effort": "unknown"})
    d = c.get("/api/participants/%d/activities/1001" % a).json()
    check("D", "exclude 1001 saved once (2 field changes); Running MMR no longer uses it",
          len(d["annotation_log"]) == 2 and d["mmr"]["informative"] is False
          and d["mmr"]["reasons"] == ["excluded by annotation"])
    snaps = c.get("/api/mmr/participants/%d" % a).json()["snapshots"]
    check("D", "the annotation recorded a new Running MMR calculation",
          any(s_["trigger"].startswith("annotation on activity") for s_ in snaps))

    # E. export filtered -> reconcile
    j = c.get("/api/participants/%d/activities?type=Run&sort=distance&order=desc" % a).json()["rows"]
    x = list(csv.DictReader(io.StringIO(c.get("/api/participants/%d/activities.csv?type=Run&sort=distance&order=desc"
                                                % a).text)))
    check("E", "CSV (type Run, distance desc) equals the JSON rows exactly",
          [(r["id"], float(r["distance_m"]), float(r["elapsed_s"])) for r in x] ==
          [(r["id"], r["distance_m"], r["elapsed_s"]) for r in j] and len(x) == 6)

    # F. restart -> persisted, consistent
    c.close()
    c2 = client(db)
    check("F", "new app instance on the same file: the annotation persisted",
          c2.get("/api/participants/%d/activities/1001" % a).json()["annotation"]["exclude"] is True)

    # failure preservation
    con = store.connect(db)
    before = con.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    real = store._import_row
    calls = {"n": 0}

    def flaky(*args):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("simulated crash")
        return real(*args)
    store._import_row = flaky
    try:
        pid2 = c2.post("/api/participants", json={"label": "Crash (synthetic)", "data_kind": "synthetic",
                                                   "consent": False}).json()["id"]
        res = c2.post("/api/participants/%d/imports" % pid2,
                      files={"file": ("b.csv", (FIX / "edge_tie_a.csv").read_bytes(), "text/csv")}).json()
    finally:
        store._import_row = real
    after = con.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    check("fail", "crash mid-import: status failed, no activity rows added",
          res["import"]["status"] == "failed" and after == before and res["import"]["inserted"] == 0)
    con.close()
    c2.close()

    mmr_journey(work)
    lab_journey(work)

    ok = all(r[2] for r in RESULTS)
    lines = ["SYNTHETIC data; in-process API journeys (not a browser, not the React UI).", ""]
    lines += ["%-5s %-9s %s %s" % (j_, "VERIFIED" if k else "FAILED", i, ("| " + d) if d else "")
              for j_, i, k, d in RESULTS]
    (ROOT / "docs" / "evidence" / "journeys_api.txt").write_text("\n".join(lines) + "\n")
    shutil.rmtree(work)
    print("\n%d checks, %d failed" % (len(RESULTS), sum(not r[2] for r in RESULTS)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
