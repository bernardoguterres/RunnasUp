"""Running MMR controlled experiment (SYNTHETIC). Writes fixtures and docs/evidence/mmr_experiment.txt.

1. Hand-designed scenarios S1-S13. The expected direction of each is written BEFORE anything is
   computed (EXPECT below) and checked against two candidates:
     A  recency-weighted mean: mean 10 km-equivalent over the last 90 days, weight 0.5^(age/30 d)
     B  aged lower-bound envelope (runrank.mmr, mmr-envelope-v1)
2. Seven synthetic histories (fixed seed) written as Strava-style activities.csv files under
   examples/synthetic/mmr/, imported through the real importer into a disposable database.
   The output shows the trajectories, evidence coverage and change explanations.
3. Sensitivity of the provisional parameters, and the rank order of the seven runners.
5. Effort-cap challenge (counterexamples), and
6. a FROZEN-method robustness evaluation: new scenarios not used to choose the method, with the intended
   behaviour written first. The method is not tuned to make them pass.

    .venv/bin/python -I tools/mmr_experiment.py
Synthetic results show behaviour under the generator's assumptions, not validity for real runners.
"""
import io
import json
import math
import pathlib
import random
import sys
import tempfile
from dataclasses import replace
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from runrank import mmr, store  # noqa: E402

OUT = ROOT / "docs" / "evidence" / "mmr_experiment.txt"
FIX = ROOT / "examples" / "synthetic" / "mmr"
SEED = 20251022
T0 = datetime(2025, 1, 1, 7, 0, tzinfo=timezone.utc)


def d(days, hours=0):
    return T0 + timedelta(days=days, hours=hours)


def run(key, day, km, minutes, typ="Run", gain=None, effort="unknown", excluded=False, dup=None, hour=0):
    return mmr.Obs(str(key), d(day, hour), typ, km * 1000.0, minutes * 60.0, gain, effort, excluded, dup)


# ---------------------------------------------------------------- candidate A (comparison only)

def candidate_a(classified, as_of, params=mmr.PARAMS):
    win = [c for c in classified if c.informative and as_of - timedelta(days=90) < c.obs.start_utc <= as_of]
    if not win:
        return None
    w = [0.5 ** ((as_of - c.obs.start_utc).total_seconds() / 86400 / 30) for c in win]
    return mmr.points(sum(wi * c.t10_s for wi, c in zip(w, win)) / sum(w))


def candidate_b(classified, as_of, params=mmr.PARAMS):
    return mmr.estimate_at(classified, as_of, params).mmr


# ---------------------------------------------------------------- scenarios (expectations first)
# each: (id, description, base history, added history, expected direction for B, why)
# direction: "up", "down", "same", "insufficient", "first"; A is checked against the same expectation.
EXPECT = [
    ("S1", "easy run after a strong performance", [run(1, 0, 10, 45)], [run(2, 2, 10, 55)], "same",
     "an easy run is weaker evidence, not evidence of lower ability"),
    ("S2", "comparable improved performance", [run(1, 0, 10, 45)], [run(2, 14, 10, 43)], "up",
     "a faster comparable run is new evidence of higher ability"),
    ("S3a", "repeated comparable weaker runs, effort unknown", [run(1, 0, 10, 45)],
     [run(2, 7, 10, 47), run(3, 14, 10, 47), run(4, 21, 10, 47)], "same",
     "without effort labels, slower runs are treated cautiously (no decline)"),
    ("S3b", "repeated comparable weaker runs declared hard", [run(1, 0, 10, 45)],
     [run(2, 7, 10, 47, effort="hard"), run(3, 14, 10, 47, effort="hard"), run(4, 21, 10, 47, effort="hard")],
     "same", "v2 (user direction 2026-10-22): effort labels are context only; v1 expected 'down' (cap)"),
    ("S4", "longer but slower run (half marathon)", [run(1, 0, 10, 45)], [run(2, 7, 21.0975, 102)], "same",
     "1:42 for 21.1 km converts to 46:14, slower than 45:00: no change, no penalty"),
    ("S5", "hilly run slower than flat", [run(1, 0, 10, 45, gain=20)], [run(2, 7, 10, 47.5, gain=300)], "same",
     "hilly run flagged and unadjusted; it cannot lower the estimate"),
    ("S6", "missing or erroneous heart rate", [run(1, 0, 10, 45)], [run(2, 7, 10, 46)], "same",
     "heart rate is not an input; HR 300 or blank cannot change anything (also checked through the importer)"),
    ("S7", "100 easy uploads", [run(1, 0, 10, 45)], [run(100 + i, 1 + i * 0.2, 8, 50) for i in range(100)],
     "same", "more uploads or more distance never add points"),
    ("S8a", "duplicate recording of the best run", [run(1, 0, 10, 45)],
     [run(2, 0, 10.05, 45, hour=0.01, dup="1")], "same", "a second copy of the same effort adds nothing"),
    ("S8b", "split session: two 5 km halves vs the whole 10 km", [run(1, 0, 5, 24), run(2, 0, 5, 25, hour=0.5)],
     [run(3, 0, 10, 49, hour=1)], "up", "the whole 10 km in 49:00 (10 km-eq 49:00) beats either half (50:02)"),
    ("S9", "late import of an earlier strong run", [run(2, 30, 10, 47)], [run(1, 10, 10, 44)], "up",
     "evidence imported late still counts from its own date"),
    ("S10", "single implausible run (10 km in 20:00)", [run(1, 0, 10, 45)], [run(2, 7, 10, 20)], "same",
     "implausibly fast runs are rejected"),
    ("S11", "only a 100-mile ultra", [], [run(1, 0, 160.9344, 25 * 60)], "insufficient",
     "ultra distances are kept as evidence but not converted: no confident MMR"),
    ("S12", "inactivity after one strong run (evaluated 200 days later)", [run(1, 0, 10, 45)], [], "down",
     "documented recency assumption: aged evidence counts slower; evidence coverage low"),
    ("S13", "inactivity beyond 365 days", [run(1, 0, 10, 45)], [], "insufficient",
     "no evidence in the window: insufficient evidence, not a measured decline"),
]
EVAL_AT = {"S12": 200, "S13": 400}


def direction(before, after):
    if after is None:
        return "insufficient"
    if before is None:
        return "first"
    return "up" if after > before + 1e-9 else "down" if after < before - 1e-9 else "same"


def scenarios(w):
    w("\n== 1. Controlled scenarios (expected direction written before computing) ==")
    w("   id   expected      A (weighted mean)       B (envelope, chosen)    scenario")
    fails = {"A": [], "B": []}
    for sid, desc, base, added, exp, why in EXPECT:
        cb = [mmr.classify(o) for o in base]
        ca = [mmr.classify(o) for o in base + added]
        last_base = max([o.start_utc for o in base], default=None)
        t_end = max(o.start_utc for o in base + added) if sid not in EVAL_AT else d(EVAL_AT[sid])
        res = {}
        for name, f in (("A", candidate_a), ("B", candidate_b)):
            before = f(cb, last_base) if last_base else None
            after = f(ca, t_end)
            res[name] = (before, after, direction(before, after))
            if res[name][2] != exp:
                fails[name].append(sid)
        cell = lambda r: "%7s->%7s %-5s %s" % ("-" if r[0] is None else "%.1f" % r[0],
                                               "-" if r[1] is None else "%.1f" % r[1], r[2],
                                               "ok " if r[2] == exp else "FAIL")
        w("   %-4s %-12s  %s  %s  %s" % (sid, exp, cell(res["A"]), cell(res["B"]), desc))
        w("        why: %s" % why)
    w("\n   Candidate A fails: %s" % (", ".join(fails["A"]) or "none"))
    w("   Candidate B fails: %s" % (", ".join(fails["B"]) or "none"))
    return fails


# ---------------------------------------------------------------- synthetic histories

ARCHETYPES = [
    # key, label, true 10 km time start->end (min), personal exponent, runs/week, distances (km), races
    ("beginner", "Beginner", (70, 62), 1.08, 2.5, (3, 6), []),
    ("recreational", "Consistent recreational", (50, 50), 1.06, 3.5, (5, 12), [(120, 10), (300, 10)]),
    ("speed", "Fast short-distance", (34, 34), 1.10, 5, (4, 12), [(60, 5), (150, 5), (240, 5), (330, 10)]),
    ("endurance", "Endurance specialist", (40, 40), 1.03, 5, (8, 32), [(100, 21.0975), (290, 42.195)]),
    ("ultra", "Ultra specialist", (46, 46), 1.02, 4, (10, 35), [(130, 50), (220, 100), (300, 160.9344),
                                                               (180, 42.195)]),
    ("improving", "Improving runner", (55, 45), 1.06, 4, (5, 12), [(m * 30 + 20, 5 if m % 2 else 10)
                                                                    for m in range(12)]),
    ("returning", "Returning after inactivity", (42, 48), 1.06, 4, (6, 14), [(60, 10), (340, 10)]),
]
GAP = (120, 270)          # the returning runner does not run between these days


def true_t10(a, day):
    s, e = a[2]
    if a[0] == "returning":
        return (s if day < GAP[0] else e) * 60.0
    return (s + (e - s) * min(1.0, day / 365.0)) * 60.0


def generate(a, rng, id_base):
    key, label, _, k_ind, per_week, (dmin, dmax), races = a
    rows, n = [], 0
    race_days = {day: km for day, km in races}
    day = 0.0
    while day < 365:
        day += rng.expovariate(per_week / 7.0)
        if key == "returning" and GAP[0] <= day < GAP[1]:
            continue
        if day >= 365:
            break
        km = round(rng.uniform(dmin, dmax), 2)
        effort = rng.choices(["easy", "tempo"], [0.8, 0.2])[0]
        factor = rng.uniform(1.15, 1.35) if effort == "easy" else rng.uniform(1.05, 1.10)
        rows.append(_row(a, rng, id_base + n, day, km, factor, k_ind, None))
        n += 1
    for rday, km in races:
        rows.append(_row(a, rng, id_base + n, rday + 0.1, km, rng.uniform(0.995, 1.01), k_ind, "race"))
        n += 1
    return sorted(rows, key=lambda r: r["day"])


def _row(a, rng, aid, day, km, factor, k_ind, declared):
    hilly = rng.random() < 0.15
    gain = round(km * (rng.uniform(20, 40) if hilly else rng.uniform(0, 8)))
    t10 = true_t10(a, day)
    # generator assumption: about +0.25 % time per m/km of climbing (simulation only, never used by MMR)
    secs = t10 * (km * 1000 / 10000.0) ** k_ind * factor * (1 + 0.0025 * gain / km)
    hr = None if rng.random() < 0.2 else int(rng.uniform(130, 175))
    if rng.random() < 0.02:
        hr = 300                              # erroneous value: the importer stores it as missing
    return {"id": aid, "day": day, "km": km, "secs": round(secs), "gain": gain, "hr": hr, "declared": declared,
            "type": "Run"}


HEADER = ["Activity ID", "Activity Date", "Activity Name", "Activity Type", "Elapsed Time", "Distance",
          "Elapsed Time", "Moving Time", "Distance", "Elevation Gain", "Average Heart Rate", "Perceived Exertion"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def strava_date(dt):
    h = dt.hour % 12 or 12
    return "%s %d, %d, %d:%02d:%02d %s" % (MONTHS[dt.month - 1], dt.day, dt.year, h, dt.minute, dt.second,
                                          "AM" if dt.hour < 12 else "PM")


def write_csv(path, rows):
    import csv
    with open(path, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(HEADER)
        for r in rows:
            dt = (T0 + timedelta(days=r["day"])).replace(microsecond=0)
            name = "SYNTHETIC %s %.1f km" % ("Race" if r["declared"] else "Run", r["km"])
            wr.writerow([r["id"], strava_date(dt), name, r["type"], r["secs"], "%.2f" % r["km"], "%.1f" % r["secs"],
                         r["secs"] - 30, "%.1f" % (r["km"] * 1000), "%.1f" % r["gain"],
                         "" if r["hr"] is None else r["hr"], ""])


def make_fixtures():
    """Deterministic fixtures: same seed, same files."""
    FIX.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    manifest = {"_comment": "SYNTHETIC. Declared race efforts are applied as 'race' annotations by the demo "
                            "loader; Strava's CSV has no reliable effort label.", "runners": []}
    for i, a in enumerate(ARCHETYPES):
        rows = generate(a, rng, 700000 + i * 10000)
        if a[0] == "recreational":                        # a watch + phone double recording of one run
            r = dict(rows[10]); r["id"] = 709999; r["day"] = rows[10]["day"] + 0.0004
            rows.append(r); rows.sort(key=lambda x: x["day"])
        fname = "%s.csv" % a[0]
        write_csv(FIX / fname, rows)
        manifest["runners"].append({"key": a[0], "label": "%s (synthetic)" % a[1], "file": fname,
                                    "declared_race_ids": [str(r["id"]) for r in rows if r["declared"]]})
    (FIX / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return manifest


def load_histories(con, manifest):
    """Import every fixture through the real importer and apply the declared race annotations."""
    out = {}
    for r in manifest["runners"]:
        pid = store.create_participant(con, r["label"], False, "synthetic")
        store.import_file(con, pid, r["file"], (FIX / r["file"]).read_bytes())
        ids = {a["source_activity_id"]: a["id"] for a in store.activities(con, pid)}
        for sid in r["declared_race_ids"]:
            store.set_annotation(con, ids[sid], False, None, False, "race")
        out[r["key"]] = pid
    return out


def trajectories(w, con, pids, manifest):
    w("\n== 2. Synthetic histories (imported through the real importer) ==")
    w("   Generator assumptions (not evidence about real runners): true 10 km time per archetype; personal")
    w("   exponent; 80 % easy runs at 1.15-1.35 x race pace, 20 % tempo at 1.05-1.10, declared races at")
    w("   0.995-1.01; 15 % hilly runs (+0.25 % time per m/km climbing); 20 % missing HR, 2 % HR = 300.")
    labels = {r["key"]: r["label"] for r in manifest["runners"]}
    final = {}
    for a in ARCHETYPES:
        pid = pids[a[0]]
        obs = store.mmr_observations(con, pid)
        imp = con.execute("SELECT inserted, duplicates, rejected FROM imports WHERE participant_id = ?",
                          (pid,)).fetchone()
        inf = sum(c.informative for c in obs)
        w("\n-- %s: %d activities stored (%d rejected rows), %d informative; true 10 km %s -> %s" % (
            labels[a[0]], imp["inserted"], imp["rejected"], inf, mmr.fmt(true_t10(a, 0)), mmr.fmt(true_t10(a, 364))))
        not_inf = {}
        for c in obs:
            if not c.informative:
                k = c.reasons[0].split(":")[0].split(" (")[0]
                not_inf[k] = not_inf.get(k, 0) + 1
        if not_inf:
            w("   not informative: " + "; ".join("%s x%d" % (k, v) for k, v in sorted(not_inf.items())))
        w("   month-end   MMR    10k-eq   coverage    support  inf90d  set by")
        for m in range(1, 13):
            t = datetime(2025, m, 1, tzinfo=timezone.utc) + timedelta(days=32)
            t = t.replace(day=1) - timedelta(seconds=1)
            e = mmr.estimate_at(obs, t)
            w("   %s  %s  %8s  %-10s  %7s  %6d  %s" % (
                t.date(), "   -  " if e.mmr is None else "%6.1f" % e.mmr, "-" if e.t10_s is None else mmr.fmt(e.t10_s),
                e.status, e.supporting or "-", e.informative_90d,
                "" if e.setter is None else "%s %s km%s" % (e.setter.obs.key, mmr._km(e.setter.obs.distance_m),
                                                            " (capped by %s)" % e.cap.obs.key if e.cap else "")))
        changes = [h for h in mmr.history(obs, datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc)) if h["changed"]]
        w("   %d recorded changes; the first three and last two explained:" % len(changes))
        for h in changes[:3] + changes[-2:]:
            e = h["estimate"]
            w("     %s %s: %s" % (h["at"].date(), "-" if e.mmr is None else "%.1f" % e.mmr, " ".join(h["explanation"])))
        bands = mmr.bands(obs, datetime(2025, 12, 31, tzinfo=timezone.utc))
        w("   distance evidence: " + "; ".join(
            "%s n=%d%s" % (b["label"], b["count"], "" if b["best_key"] is None else
                           (" best %s" % mmr.fmt(b["best_t10_s"]) if b["converted"] else
                            " fastest %s/km" % mmr.fmt(b["best_pace_s_per_km"]))) for b in bands if b["count"]))
        final[a[0]] = mmr.estimate_at(obs, datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc))
    return final


def sensitivity(w, con, pids):
    w("\n== 3. Sensitivity (as of 2025-12-31; synthetic cohort) ==")
    t = datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    obs = {k: store.mmr_observations(con, pid) for k, pid in pids.items()}
    base = {k: mmr.estimate_at(o, t).mmr for k, o in obs.items()}
    order = lambda vals: [k for k, v in sorted(vals.items(), key=lambda x: -(x[1] or -1))]
    w("   baseline order: " + " > ".join("%s %.0f" % (k, base[k] or 0) for k in order(base)))
    variants = [("aging_per_day", v) for v in (0.0, 0.00025, 0.001)] + \
               [("grace_days", v) for v in (0, 60)] + \
               [("riegel_k", v) for v in (1.03, 1.10)]
    for name, v in variants:
        p = dict(mmr.PARAMS, **{name: v})
        vals = {}
        for k, o in obs.items():
            cs = [mmr.classify(c.obs, p) for c in o]
            vals[k] = mmr.estimate_at(cs, t, p).mmr
        swaps = sum(1 for i, a in enumerate(order(base)) for b in order(base)[i + 1:]
                    if (vals[a] or 0) < (vals[b] or 0))
        w("   %-16s = %-7g max |dMMR| %5.1f  pair order swaps %d  [%s]" % (
            name, v, max(abs((vals[k] or 0) - (base[k] or 0)) for k in vals), swaps,
            ", ".join("%s %+.0f" % (k, (vals[k] or 0) - (base[k] or 0)) for k in order(base))))


def coupling(w):
    import re
    w("\n== 4. Separation from race Elo ==")
    imports = lambda f: set(re.findall(r"^from \. import (.+)$|^import (\S+)", (ROOT / "runrank" / f).read_text(), re.M))
    names = lambda f: {n.strip() for pair in imports(f) for part in pair for n in part.split(",") if n.strip()}
    w("   runrank/mmr.py imports: %s" % (sorted(names("mmr.py")) or "nothing from runrank"))
    w("   race Elo (runrank/elo.py, races.py) was archived on 2026-10-25 (archive/); nothing in runrank imports it"
      " (asserted in tests/test_mmr.py)")


FROZEN = ("mmr-envelope-v2", "mmr-scale-v1", 0.0005, 30, 365, 1.06, 0.03, 3000.0, 42500.0)


def frozen_ok():
    p = mmr.PARAMS
    return (mmr.ALGORITHM_VERSION, mmr.SCALE_VERSION, p["aging_per_day"], p["grace_days"], p["max_age_days"],
            p["riegel_k"], p["support_tol"], p["min_m"], p["max_m"]) == FROZEN


def obs(key, day, km, secs, gain=None, effort="unknown", typ="Run"):
    return mmr.Obs(str(key), d(day), typ, km * 1000.0, float(secs), gain, effort)


def est(observations, day, params=mmr.PARAMS):
    return mmr.estimate_at([mmr.classify(o, params) for o in observations], d(day), params)


def cap_challenge(w):
    w("\n== 5. Effort-cap challenge (%s: the cap was removed in v2, so every label case should show no change) =="
      % mmr.ALGORITHM_VERSION)
    f = lambda e: "-" if e.mmr is None else "%.1f %s%s" % (e.mmr, e.status, " cap=%s" % e.cap.obs.key if e.cap else "")
    base = [obs(1, 0, 10, 2700), obs(2, 10, 10, 3120), obs(3, 20, 10, 3300)]
    lab = [base[0], obs(2, 10, 10, 3120, effort="hard"), base[2]]
    a, b = est(base, 20), est(lab, 20)
    w("   C1 same history, 52:00 run unlabelled vs honestly labelled hard: %s vs %s -> withholding the label "
      "gains %+.1f points" % (f(a), f(b), a.mmr - b.mmr))
    one = [obs(1, 0, 10, 2700), obs(2, 21, 10, 2820, effort="race")]
    three = [obs(1, 0, 10, 2700)] + [obs(k, 7 * (k - 1), 10, 2820, effort="race") for k in (2, 3, 4)]
    w("   C2 ONE declared 47:00 vs THREE declared 47:00: %s vs %s -> no difference; "
      "under v1 one declared effort sufficed to lower MMR" % (f(est(one, 21)), f(est(three, 21))))
    poor = [obs(1, 0, 10, 2700), obs(2, 10, 10, 3000, effort="race")]
    w("   C3 one poor declared race (50:00) after 45:00: %s; followed by a normal 46:00 run: %s; "
      "followed only by easy runs, day 120: %s" % (f(est(poor, 10)), f(est(poor + [obs(3, 20, 10, 2760)], 20)),
                                                 f(est(poor + [obs(3, 20, 10, 3300)], 120))))
    order = [obs(1, 0, 10, 2700), obs(2, 10, 10, 2760, effort="race"), obs(3, 20, 10, 2940, effort="race")]
    w("   C4 declared 46:00 then later declared 49:00: %s (v1: the later, weaker one set the cap); input order "
      "reversed: %s (identical: the start time decides, not import order)" % (f(est(order, 20)),
                                                                             f(est(order[::-1], 20))))
    w("   C5 annotation corrected later (49:00 label removed): %s -> the whole history is reconstructed"
      % f(est(order[:2] + [obs(3, 20, 10, 2940)], 20)))
    for label, items in (("hilly 199 vs 200 m gain on 10 km", [(199, 3000), (200, 3000)]),):
        vals = [est([obs(1, 0, 10, 2700, gain=0), obs(2, 7, 10, t, gain=g, effort="race")], 7) for g, t in items]
        w("   C6 %s, same declared 50:00: %s vs %s -> step of %.1f points" % (label, f(vals[0]), f(vals[1]),
                                                                           vals[1].mmr - vals[0].mmr))
    vals = [est([obs(1, 0, 10, 2700), obs(2, 7, 42.195, m * 60, effort="race")], 7) for m in (229.9, 230.1)]
    w("   C7 declared marathon 229.9 vs 230.1 min: %s vs %s -> step of %.1f points"
      % (f(vals[0]), f(vals[1]), vals[1].mmr - vals[0].mmr))
    w("   v2: no label can lower (or raise) MMR; v1 results for these cases are recorded in docs/RATING_METHOD.md §A12.")


TRUE10 = 2700.0          # robustness runners: true 10 km ability 45:00 unless stated


def robustness(w, params=mmr.PARAMS, quiet=False):
    """Frozen-method scenarios R1-R9. Intended behaviour is stated before computing; returns errors."""
    rng = random.Random(4242)
    true_pts = mmr.points(TRUE10)
    res = {}
    # R1 noisy GPS: 30 identical tempo-equivalent efforts (true 10 km race effort x 1.04), distance noise sd 2 %
    r1 = [obs(i, i * 3, 10 * (1 + rng.gauss(0, 0.02)), TRUE10 * 1.04) for i in range(30)]
    res["R1"] = ("noisy GPS distance (sd 2 %) on 30 identical efforts at 1.04 x race pace",
                 "estimate within 1 % (about 20 points) of the noise-free value", est(r1, 90, params),
                 mmr.points(TRUE10 * 1.04), 20)
    # R2 downhill point-to-point 10 km, assumed 4 % faster than flat ability, no gain recorded
    r2 = [obs(1, 0, 10, TRUE10), obs(2, 3, 10, TRUE10 * 1.02), obs(3, 7, 10, TRUE10 * 0.96, gain=0)]
    res["R2"] = ("downhill-assisted 10 km (4 % faster than ability; descent not recorded)",
                 "MMR not above flat ability", est(r2, 7, params), true_pts, 0)
    # R3 a fast 3 km segment saved separately by a speed-type runner (true exponent 1.10)
    seg = TRUE10 * 0.3 ** 1.10
    r3 = [obs(1, 0, 10, TRUE10 * 1.03), obs(2, 0.01, 3, seg)]
    res["R3"] = ("short fast 3 km segment saved separately (speed type, true k 1.10)",
                 "MMR not above true 10 km ability", est(r3, 1, params), true_pts, 0)
    # R4 endurance profiles: same true 10 km 45:00; A only half marathons (k 1.02), B only 5 km (k 1.12)
    ra = [obs(1, 0, 21.0975, TRUE10 * 2.10975 ** 1.02), obs(2, 30, 21.0975, TRUE10 * 2.10975 ** 1.02)]
    rb = [obs(1, 0, 5, TRUE10 * 0.5 ** 1.12), obs(2, 30, 5, TRUE10 * 0.5 ** 1.12)]
    res["R4a"] = ("endurance type (k 1.02), race-effort half marathons only", "within 2 % (about 39 points) of true",
                  est(ra, 30, params), true_pts, 39)
    res["R4b"] = ("speed type (k 1.12), race-effort 5 km only", "within 2 % (about 39 points) of true",
                  est(rb, 30, params), true_pts, 39)
    # R5 missing effort: two below-par races (3 % and 6 % slow) honestly labelled vs unlabelled
    hist = [obs(1, 0, 10, TRUE10), obs(2, 20, 10, TRUE10 * 1.06), obs(3, 40, 10, TRUE10 * 1.03)]
    labelled = [hist[0], obs(2, 20, 10, TRUE10 * 1.06, effort="race"), obs(3, 40, 10, TRUE10 * 1.03, effort="race")]
    e_un, e_lab = est(hist, 40, params), est(labelled, 40, params)
    res["R5"] = ("honest race labels on below-par races vs no labels", "labelling never costs more than 1 % "
                 "(about 20 points) vs withholding", e_lab, e_un.mmr, 20)
    # R6 long gap: 45:00 until day 100, nothing for 200 days, back at true 50:00 with easy runs only
    r6 = [obs(i, i * 5, 10, TRUE10 * (1.0 if i % 5 == 0 else 1.2)) for i in range(21)] + \
         [obs(100 + i, 300 + i * 3, 8, 3000 * (0.8 ** 1.06) * 1.2) for i in range(10)]
    res["R6"] = ("long gap (200 days), return at true 50:00 with easy running only",
                 "not more than 3 % (about 59 points) above the new true ability", est(r6, 330, params),
                 mmr.points(3000), 59)
    # R7 easy-only runner: all runs at 1.20-1.30 x race pace
    r7 = [obs(i, i * 3, 8, TRUE10 * 0.8 ** 1.06 * rng.uniform(1.2, 1.3)) for i in range(40)]
    res["R7"] = ("easy-only runner (1.20-1.30 x race pace), no labels",
                 "under-estimate allowed, but evidence coverage not 'high'", est(r7, 120, params), true_pts, None)
    # R8 threshold continuity: identical declared races at 199 vs 200 m gain
    e199 = est([obs(1, 0, 10, TRUE10, gain=0), obs(2, 7, 10, TRUE10 * 1.10, gain=199, effort="race")], 7, params)
    e200 = est([obs(1, 0, 10, TRUE10, gain=0), obs(2, 7, 10, TRUE10 * 1.10, gain=200, effort="race")], 7, params)
    res["R8"] = ("declared race at 19.9 vs 20.0 m/km climbing", "a 1 m change moves MMR by less than 5 points",
                 e200, e199.mmr, 5)
    out = []
    for k, (desc, intended, e, ref, tol) in res.items():
        if k == "R7":
            ok = e.status != "high"
            detail = "MMR %.1f vs true %.1f (%+.1f), coverage %s" % (e.mmr, ref, e.mmr - ref, e.status)
        elif k in ("R2", "R3"):
            ok = e.mmr <= ref + 1e-9
            detail = "MMR %.1f vs true %.1f (%+.1f)" % (e.mmr, ref, e.mmr - ref)
        else:
            ok = abs(e.mmr - ref) <= tol
            detail = "MMR %.1f vs reference %.1f (%+.1f)" % (e.mmr, ref, e.mmr - ref)
        out.append((k, ok, e.mmr - ref))
        if not quiet:
            w("   %-4s %s  %s" % (k, "PASS" if ok else "FAIL", desc))
            w("        intended: %s; %s" % (intended, detail))
    return out


def robustness_report(w):
    w("\n== 6. Frozen-method robustness (scenarios not used to choose the method) ==")
    w("   frozen parameters unchanged: %s" % frozen_ok())
    base = robustness(w)
    w("   %d PASS, %d FAIL" % (sum(o for _, o, _ in base), sum(not o for _, o, _ in base)))
    w("\n   Sensitivity of the deviations above (points vs reference; R7 vs true ability):")
    keys = [k for k, _, _ in base]
    w("   %-24s " % "variant" + " ".join("%7s" % k for k in keys))
    w("   %-24s " % "frozen" + " ".join("%+7.1f" % dv for _, _, dv in base))
    for name, vals in (("aging_per_day", (0.0, 0.001)), ("riegel_k", (1.03, 1.10))):
        for v in vals:
            p = dict(mmr.PARAMS, **{name: v})
            r = robustness(w, p, quiet=True)
            w("   %-24s " % ("%s=%g" % (name, v)) + " ".join("%+7.1f" % dv for _, _, dv in r))


def main():
    buf = io.StringIO()
    w = lambda s="": buf.write(s + "\n")
    w("RunnasUP Running MMR experiment (%s, %s). SYNTHETIC data only." % (mmr.ALGORITHM_VERSION, mmr.SCALE_VERSION))
    w("Scale: 10 km-equivalent 2:00:00 = 0, 26:00 = 3000 (log of speed; ~19.6 points per 1 %% speed).")
    fails = scenarios(w)
    manifest = make_fixtures()
    with tempfile.TemporaryDirectory() as tmp:
        con = store.connect(str(pathlib.Path(tmp) / "mmr.sqlite"))
        pids = load_histories(con, manifest)
        trajectories(w, con, pids, manifest)
        sensitivity(w, con, pids)
        con.close()
    coupling(w)
    cap_challenge(w)
    robustness_report(w)
    OUT.write_text(buf.getvalue())
    sys.stdout.write(buf.getvalue())
    return 1 if fails["B"] else 0


if __name__ == "__main__":
    sys.exit(main())
