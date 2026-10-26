"""Running MMR: hand-worked arithmetic, behavioural requirements, import pipeline, separation from race Elo.

Expected numbers are hand-derived (docs/RATING_METHOD.md Part A, §A9), computed independently with
math.log; they are not taken from runrank.mmr. All runners are SYNTHETIC.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest
from starlette.testclient import TestClient

from conftest import ROOT
from runrank import api, mmr, store
from test_api import keys_match

FIX = ROOT / "examples" / "synthetic" / "mmr"
T0 = datetime(2025, 1, 1, 7, tzinfo=timezone.utc)


def run(key, day, km, minutes, typ="Run", gain=None, effort="unknown", excluded=False, dup=None):
    return mmr.classify(mmr.Obs(str(key), T0 + timedelta(days=day), typ, km * 1000.0, minutes * 60.0, gain,
                                effort, excluded, dup))


def est(cs, day):
    return mmr.estimate_at(cs, T0 + timedelta(days=day))


# ---------------------------------------------------------------- arithmetic (hand values)

@pytest.mark.parametrize("t10,points", [(7200, 0.0), (4800, 795.344), (3600, 1359.650), (3000, 1717.284),
                                        (2700, 1923.955), (2400, 2154.994), (1800, 2719.299), (1560, 3000.0)])
def test_scale_anchor_values(t10, points):
    # points = 3000 × ln(7200 / t10) / ln(7200 / 1560), ln(4.6153846) = 1.5293952
    assert mmr.points(t10) == pytest.approx(points, abs=1e-3)


def test_scale_is_logarithmic_in_speed_and_clamped_at_zero():
    assert mmr.points(2700 / 1.01) - mmr.points(2700) == pytest.approx(19.518, abs=1e-3)   # 1 % faster
    assert mmr.points(9000) == 0.0


def test_riegel_conversion_hand_values():
    assert mmr.ten_k_equivalent_s(10000, 2700) == 2700
    assert mmr.ten_k_equivalent_s(5000, 1440) == pytest.approx(3002.301, abs=1e-3)       # 1440 × 2^1.06
    assert mmr.ten_k_equivalent_s(21097.5, 6120) == pytest.approx(2773.745, abs=1e-3)    # half in 1:42:00


def test_recency_aging_hand_value_and_labels_change_nothing():
    # 45:00 seen 130 days later: 2700 × (1 + 0.0005 × 100) = 2835 s -> 1828.250
    e = est([run(1, 0, 10, 45)], 130)
    assert e.t10_s == pytest.approx(2835.0) and e.mmr == pytest.approx(1828.250, abs=1e-3)
    # v2: three declared 47:00 efforts after a 45:00 no longer cap it (v1 gave 1898.404); 45:00 at day 21 = 1923.955
    cs = [run(1, 0, 10, 45)] + [run(k, 7 * (k - 1), 10, 47, effort="hard") for k in (2, 3, 4)]
    e = est(cs, 21)
    assert e.mmr == pytest.approx(1923.955, abs=1e-3) and e.cap is None and e.setter.obs.key == "1"


def test_easy_run_longer_slower_run_and_hilly_run_never_lower_mmr():
    base = [run(1, 0, 10, 45, gain=20)]
    ref = est(base, 7).mmr
    for extra in (run(2, 7, 10, 55), run(3, 7, 21.0975, 102), run(4, 7, 10, 47.5, gain=300)):
        assert est(base + [extra], 7).mmr == ref
    assert any(f.startswith("hilly") for f in run(4, 7, 10, 47.5, gain=300).flags)


def test_more_uploads_and_more_distance_add_nothing():
    base = [run(1, 0, 10, 45)]
    many = base + [run(100 + i, 1 + i * 0.2, 15, 90) for i in range(200)]
    assert est(many, 41).mmr == est(base, 41).mmr


def test_weaker_runs_never_lower_mmr_with_or_without_labels():
    base = [run(1, 0, 10, 45)]
    for label in ("unknown", "easy", "hard", "race"):
        weaker = [run(k, 7 * (k - 1), 10, 47, effort=label) for k in (2, 3, 4)]
        assert est(base + weaker, 21).mmr == est(base, 21).mmr


def test_changing_a_label_alone_never_changes_mmr():
    for minutes in (40, 45, 50):
        vals = {lab: est([run(1, 0, 10, 45), run(2, 7, 10, minutes, effort=lab)], 7).mmr
                for lab in ("unknown", "easy", "moderate", "hard", "race")}
        assert len(set(vals.values())) == 1, vals


def test_better_comparable_performance_raises_mmr():
    assert est([run(1, 0, 10, 45), run(2, 14, 10, 43)], 14).mmr > est([run(1, 0, 10, 45)], 14).mmr


def test_unsupported_and_invalid_activities_are_kept_but_not_informative():
    ultra = run(1, 0, 160.9344, 25 * 60)
    short = run(2, 0, 1.5, 6)
    trail = run(3, 0, 10, 50, typ="Trail Run")
    glitch = run(4, 0, 10, 20)
    dup = run(5, 0, 10, 45, dup="9")
    for c in (ultra, short, trail, glitch, dup):
        assert not c.informative and c.t10_s is None and c.reasons
    assert est([ultra], 1).status == mmr.INSUFFICIENT
    b = {x["label"]: x for x in mmr.bands([ultra], T0 + timedelta(days=1))}
    assert b["over 42.5 km (ultra; not converted)"]["count"] == 1


def test_inactivity_lowers_by_the_documented_assumption_then_becomes_insufficient():
    cs = [run(1, 0, 10, 45)]
    assert est(cs, 30).mmr == est(cs, 0).mmr                          # grace period
    assert est(cs, 200).mmr < est(cs, 30).mmr and est(cs, 200).status == "low"
    assert est(cs, 366).status == mmr.INSUFFICIENT and est(cs, 366).mmr is None
    expl = mmr.explain(est(cs, 30), est(cs, 200))
    assert "Recency assumption" in expl[0]


def test_counterfactual_explains_change_and_non_change():
    cs = [run(1, 0, 10, 45), run(2, 7, 10, 55), run(3, 14, 10, 43)]
    _, without, with_, why = mmr.counterfactual(cs, "2")
    assert without.mmr == with_.mmr and "not read as lower ability" in why
    _, without, with_, why = mmr.counterfactual(cs, "3")
    assert with_.mmr > without.mmr and "raised" in why


def test_history_is_deterministic_and_prefix_stable():
    cs = [run(1, 0, 10, 45), run(2, 50, 10, 46), run(3, 100, 10, 44)]
    end = T0 + timedelta(days=120)
    a, b = mmr.history(cs, end), mmr.history(cs, end)
    assert [(h["at"], h["estimate"].mmr) for h in a] == [(h["at"], h["estimate"].mmr) for h in b]
    late = cs + [run(4, 60, 10, 42)]
    old = {h["at"]: h["estimate"].mmr for h in a}
    for h in mmr.history(late, end):
        if h["at"] < T0 + timedelta(days=60) and h["at"] in old:
            assert h["estimate"].mmr == old[h["at"]]


# ---------------------------------------------------------------- full pipeline through the importer

ADD_RUN = ("Activity ID,Activity Date,Activity Name,Activity Type,Elapsed Time,Distance,Elapsed Time,Moving Time,"
           "Distance,Elevation Gain,Average Heart Rate,Perceived Exertion\n"
           "719001,\"Jan 5, 2026, 8:00:00 AM\",SYNTHETIC new 10 km,Run,2940,10.00,2940.0,2900,10000.0,40.0,,\n")


def load(con, key="recreational"):
    m = json.loads((FIX / "manifest.json").read_text())
    r = next(x for x in m["runners"] if x["key"] == key)
    pid = store.create_participant(con, r["label"], False, "synthetic")
    store.import_file(con, pid, r["file"], (FIX / r["file"]).read_bytes())
    return pid, r


def latest(con, pid):
    obs = store.mmr_observations(con, pid)
    return mmr.estimate_at(obs, max(c.obs.start_utc for c in obs)), obs


def test_full_history_import_then_add_a_run_then_reimport(con):
    pid, r = load(con)
    e0, obs = latest(con, pid)
    n = len(obs)
    assert e0.mmr is not None and n > 150 and sum(c.informative for c in obs) == n - 1   # one double recording
    store.import_file(con, pid, "add.csv", ADD_RUN.encode())
    e1, obs1 = latest(con, pid)
    assert len(obs1) == n + 1
    c, without, with_, why = mmr.counterfactual(obs1, "719001")
    assert with_.mmr > without.mmr and e1.setter.obs.key == "719001"                      # 49:00 beats aged evidence
    before = [tuple(x) for x in con.execute("SELECT id, source_activity_id, start_utc, activity_type, distance_m, elapsed_s FROM activities ORDER BY id")]
    store.import_file(con, pid, r["file"], (FIX / r["file"]).read_bytes())                # duplicate import
    store.import_file(con, pid, "add.csv", ADD_RUN.encode())
    e2, _ = latest(con, pid)
    assert e2.mmr == e1.mmr and [tuple(x) for x in con.execute("SELECT id, source_activity_id, start_utc, activity_type, distance_m, elapsed_s FROM activities ORDER BY id")] == before
    runs = con.execute("SELECT trigger, mmr, algorithm_version FROM mmr_runs WHERE participant_id = ? ORDER BY id",
                       (pid,)).fetchall()
    assert len(runs) == 4 and runs[0]["algorithm_version"] == "mmr-envelope-v2"
    assert runs[1]["mmr"] == pytest.approx(e1.mmr) and runs[3]["mmr"] == pytest.approx(e1.mmr)


def test_declared_annotation_recalculates_and_is_explained(con):
    pid, _ = load(con)
    store.import_file(con, pid, "add.csv", ADD_RUN.encode())
    e1, _ = latest(con, pid)
    aid = next(a["id"] for a in store.activities(con, pid) if a["source_activity_id"] == "719001")
    store.set_annotation(con, aid, True, "test", False, "unknown")            # excluding the best run
    e2, _ = latest(con, pid)
    assert e2.mmr < e1.mmr
    assert con.execute("SELECT trigger FROM mmr_runs ORDER BY id DESC").fetchone()[0].startswith("annotation")


def test_mmr_stays_uncoupled_after_race_elo_was_archived():
    """Race Elo and the legacy 5K score were archived on 2026-10-25: nothing live may import them, and mmr.py
    stays pure (standard library only)."""
    import ast
    for f in sorted((ROOT / "runrank").glob("*.py")):
        tree = ast.parse(f.read_text())
        names = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
        names |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert not names & {"elo", "races", "api_races", "rating", "rating_exp", "views", "demo"}, f.name
    for gone in ("elo", "races", "api_races", "rating", "rating_exp", "views", "demo"):
        assert not (ROOT / "runrank" / (gone + ".py")).exists()
    tree = ast.parse((ROOT / "runrank" / "mmr.py").read_text())
    modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    modules |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert modules == {"math", "dataclasses", "datetime"}            # standard library only
    assert all(n.level == 0 for n in ast.walk(tree) if isinstance(n, ast.ImportFrom))   # no project import


# ---------------------------------------------------------------- API

@pytest.fixture
def demo(tmp_path):
    app = api.create_app(str(tmp_path / "demo.sqlite"), demo_mode=True, database="demo", allowed_hosts=("testserver",))
    with TestClient(app) as c:
        assert c.post("/api/demo/histories").status_code == 200
        yield c


def test_mmr_api_contract_and_workflow(demo):
    keys_match(demo.get("/api/health").json(), "Health")
    people = {p["label"]: p["id"] for p in demo.get("/api/participants").json()}
    pid = people["Consistent recreational (synthetic)"]
    ov = demo.get("/api/mmr/participants/%d" % pid).json()
    keys_match(ov, "MmrOverview")
    keys_match(ov["estimate"], "MmrEstimate")
    keys_match(ov["estimate"]["setter"], "MmrObservation")
    keys_match(ov["quality"], "MmrQuality")
    keys_match(ov["recent_changes"][0], "MmrChange")
    keys_match(ov["snapshots"][0], "MmrSnapshot")
    assert ov["estimate"]["mmr"] is not None and ov["quality"]["informative"] == ov["quality"]["activities"] - 1
    h = demo.get("/api/mmr/participants/%d/history" % pid).json()
    keys_match(h, "MmrHistory")
    keys_match(h["points"][0], "MmrHistoryPoint")
    changed = [p for p in h["points"] if p["changed"]]
    ex = demo.get("/api/mmr/participants/%d/explain" % pid, params={"at": changed[2]["at_utc"]}).json()
    keys_match(ex, "MmrExplanation")
    aid = ov["estimate"]["setter"]["activity_id"]
    eff = demo.get("/api/mmr/participants/%d/activities/%s/effect" % (pid, aid)).json()
    keys_match(eff, "MmrEffect")
    obs = demo.get("/api/mmr/participants/%d/observations" % pid).json()
    keys_match(obs[0], "MmrObservation")
    cmp_ = demo.get("/api/mmr/comparison").json()
    keys_match(cmp_, "MmrComparison")
    keys_match(cmp_["rows"][0], "MmrComparisonRow")
    keys_match(demo.get("/api/mmr/method").json(), "MmrMethod")
    det = demo.get("/api/participants/%d/activities/%s" % (pid, aid)).json()
    keys_match(det["mmr"], "ActivityMmr")
    assert det["mmr"]["informative"] is True


def test_adding_a_runner_never_rescales_anyone(demo):
    before = {r["participant"]["id"]: r["estimate"]["mmr"] for r in demo.get("/api/mmr/comparison").json()["rows"]}
    p = demo.post("/api/participants", json={"label": "Late joiner (synthetic)", "data_kind": "synthetic"}).json()
    demo.post("/api/participants/%d/imports" % p["id"], files={"file": ("a.csv", ADD_RUN.replace("719001", "719777")
                                                                        .encode())})
    after = {r["participant"]["id"]: r["estimate"]["mmr"] for r in demo.get("/api/mmr/comparison").json()["rows"]}
    assert all(after[k] == v for k, v in before.items())


def test_demo_histories_are_demo_only_and_idempotent(demo, tmp_path):
    again = demo.post("/api/demo/histories").json()
    assert all("skipped" in m for m in again["messages"])
    app = api.create_app(str(tmp_path / "p.sqlite"), demo_mode=False, database="personal", allowed_hosts=("testserver",))
    with TestClient(app) as c:
        assert c.post("/api/demo/histories").json()["error"]["code"] == "demo_only"


def test_explanation_never_says_no_change_when_the_value_moved():
    """v1 review defect (cap aging); in v2 the same guarantee is checked for plain aging."""
    cs = [run(1, 0, 10, 45), run(2, 10, 10, 50, effort="race")]
    prev, cur = est(cs, 40), est(cs, 100)
    assert cur.cap is None and cur.mmr < prev.mmr
    text = " ".join(mmr.explain(prev, cur))
    assert "No change" not in text and "Recency assumption" in text
    deltas = mmr.history(cs, T0 + timedelta(days=200))
    for a, b in zip(deltas, deltas[1:]):
        if a["estimate"].mmr is not None and b["estimate"].mmr is not None and abs(b["estimate"].mmr - a["estimate"].mmr) > 1e-9:
            assert not any(x.startswith("No change") for x in b["explanation"])


def test_v2_label_change_keeps_score_and_v1_provenance(con):
    pid, _ = load(con)
    con.execute("INSERT INTO mmr_runs(participant_id, computed_utc, algorithm_version, scale_version, params_json,"
                " trigger, as_of_utc, status, mmr, t10_s, setter_activity_id, activities) VALUES (?, '2026-10-01T00:00:00Z',"
                " 'mmr-envelope-v1', 'mmr-scale-v1', '{\"declared_cap_tol\": 0.03}', 'earlier v1 calculation', NULL,"
                " 'low', 1700.0, NULL, NULL, 0)", (pid,))
    before, _ = latest(con, pid)
    aid = store.activities(con, pid)[5]["id"]
    store.set_annotation(con, aid, False, None, False, "race")             # a label change only
    after, _ = latest(con, pid)
    assert after.mmr == before.mmr
    rows = con.execute("SELECT algorithm_version, trigger, mmr FROM mmr_runs WHERE participant_id = ? ORDER BY id",
                       (pid,)).fetchall()
    assert ("mmr-envelope-v1", "earlier v1 calculation", 1700.0) in [tuple(r) for r in rows]   # provenance preserved
    assert rows[-1]["algorithm_version"] == "mmr-envelope-v2" and rows[-1]["trigger"].startswith("annotation")
