"""Write SYNTHETIC API responses for the frontend tests (web/src/test/fixtures/{mmr,lab}.json).

Responses come from the real API (in-process, disposable databases filled with the synthetic histories), so the
component tests use the actual contract rather than hand-written mocks. Re-run after changing runrank/api_mmr.py
or runrank/api_lab.py:
    .venv/bin/python -I tools/export_fixtures.py
"""
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from starlette.testclient import TestClient  # noqa: E402

from runrank import api  # noqa: E402

OUT_MMR = ROOT / "web" / "src" / "test" / "fixtures" / "mmr.json"
OUT_LAB = ROOT / "web" / "src" / "test" / "fixtures" / "lab.json"


def main():
    with tempfile.TemporaryDirectory() as d:
        app = api.create_app(str(pathlib.Path(d) / "demo.sqlite"), demo_mode=True, database="demo",
                             allowed_hosts=("testserver",))
        with TestClient(app) as c:
            c.post("/api/demo/histories")
            people = c.get("/api/participants").json()
            pid = next(p["id"] for p in people if p["label"].startswith("Improving"))
            ov = c.get("/api/mmr/participants/%d" % pid).json()
            aid = ov["estimate"]["setter"]["activity_id"]
            easy = next(o["activity_id"] for o in c.get("/api/mmr/participants/%d/observations" % pid).json()
                        if o["informative"] and o["effort"] == "unknown")
            fm = {
                "participants": people, "overview": ov,
                "history": c.get("/api/mmr/participants/%d/history" % pid).json(),
                "explain": c.get("/api/mmr/participants/%d/explain" % pid,
                                 params={"at": ov["recent_changes"][0]["at_utc"]}).json(),
                "effect_best": c.get("/api/mmr/participants/%d/activities/%s/effect" % (pid, aid)).json(),
                "effect_easy": c.get("/api/mmr/participants/%d/activities/%s/effect" % (pid, easy)).json(),
                "comparison": c.get("/api/mmr/comparison").json(),
                "insufficient": c.get("/api/mmr/participants/%d" % pid, params={"as_of": "2024-06-01"}).json(),
                "method": c.get("/api/mmr/method").json(),
                "overview_ultra": c.get("/api/mmr/participants/%d" % next(
                    p["id"] for p in people if p["label"].startswith("Ultra"))).json(),
            }
    OUT_MMR.write_text(json.dumps(fm, indent=1, sort_keys=True) + "\n")
    print("wrote", OUT_MMR.relative_to(ROOT), "(synthetic)")
    sys.path.insert(0, str(ROOT / "tests"))
    from test_api_lab_db import AS_OF, csv_text  # noqa: E402  (the synthetic CSV the stored-history test imports)
    with tempfile.TemporaryDirectory() as d:
        app = api.create_app(str(pathlib.Path(d) / "x.sqlite"), demo_mode=False, database="personal",
                             allowed_hosts=("testserver",))
        with TestClient(app) as c:
            # stored histories: a disposable database filled through the importer and annotation endpoints
            pid = c.post("/api/participants", json={"label": "Lab check (synthetic)", "data_kind": "synthetic"}).json()["id"]
            c.post("/api/participants/%d/imports" % pid, files={"file": ("lab.csv", csv_text())})
            for sid, body in (("9006", {"exclude": True, "exclude_note": "synthetic watch glitch"}),
                              ("9005", {"not_duplicate": True})):
                c.put("/api/participants/%d/activities/%s/annotation" % (pid, sid),
                      json={"exclude": False, "not_duplicate": False, "effort": "unknown", "exclude_note": None, **body})
            c.post("/api/participants", json={"label": "Empty (synthetic)", "data_kind": "synthetic"})
            dbr = c.get("/api/lab/db/runners/%d" % pid, params={"method": "B", "as_of": AS_OF}).json()
            long_ = next(a["key"] for a in dbr["activities"] if a["distance_m"] == 21097.5)
            k9001 = next(a["key"] for a in dbr["activities"] if (a["provenance"] or {}).get("source_activity_id") == "9001")
            stored = {"db_runners": c.get("/api/lab/db/runners").json(), "db_runner": dbr,
                      "db_runner_old": c.get("/api/lab/db/runners/%d" % pid,
                                             params={"method": "B", "as_of": "2026-01-20"}).json(),
                      "db_explain": c.get("/api/lab/db/runners/%d/activities/%s" % (pid, long_),
                                          params={"method": "B", "as_of": AS_OF}).json(),
                      "db_runner_recording": c.get("/api/lab/db/runners/%d" % pid, params={
                          "method": "B", "as_of": AS_OF, "exclude": k9001}).json(),
                      "db_runner_effort": c.get("/api/lab/db/runners/%d" % pid, params={
                          "method": "B", "as_of": AS_OF, "exclude_effort": k9001}).json()}
            rb = c.get("/api/lab/runners/beginner", params={"method": "B"}).json()
            eight = next(a["key"] for a in rb["activities"] if a["distance_m"] == 8000)
            fl = {"meta": c.get("/api/lab/meta").json(), "runner_B": rb,
                  "runner_C": c.get("/api/lab/runners/beginner", params={"method": "C"}).json(),
                  "explain_8k": c.get("/api/lab/runners/beginner/activities/%s" % eight,
                                      params={"method": "B"}).json(),
                  "compare": c.get("/api/lab/compare").json(),
                  "marathon_bridged": c.get("/api/lab/runners/marathon",
                                            params={"method": "B", "long_performance": "bridged"}).json(),
                  "marathon_excluded": c.get("/api/lab/runners/marathon", params={
                      "method": "B", "long_performance": "bridged", "exclude": "930265"}).json(), **stored}
    OUT_LAB.write_text(json.dumps(fl, indent=1, sort_keys=True) + "\n")
    print("wrote", OUT_LAB.relative_to(ROOT), "(synthetic)")


if __name__ == "__main__":
    main()
