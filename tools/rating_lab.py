"""Ratings Lab experiment: the single reproducible entry point (SYNTHETIC data only).

    .venv/bin/python -I tools/rating_lab.py
      -> docs/evidence/rating_lab.txt and docs/evidence/rating_lab/*.svg

Methods: runrank/lab_methods.py (A-D). Data: runrank/lab_synthetic.py (generator, kept separate).
The evaluation specification (SPEC) is written below before any result is computed. Held-out scenarios
are evaluated only after the finalists are selected. Nothing is tuned to make cases pass.
"""
import hashlib
import io
import json
import math
import pathlib
import random
import re
import sys
from datetime import timedelta
from itertools import product

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from runrank import lab_methods as L  # noqa: E402
from runrank import lab_synthetic as S  # noqa: E402
from runrank import lab_compare as LC  # noqa: E402
from runrank import mmr  # noqa: E402

OUT = ROOT / "docs" / "evidence" / "rating_lab.txt"
PLOTS = ROOT / "docs" / "evidence" / "rating_lab"
EPS = 1e-6

# ---------------------------------------------------------------- predeclared evaluation specification
SPEC = {
    "mandatory_invariants": {
        "I1": "the identical activity gives identical scores whether labelled easy, hard or unknown (case 02)",
        "I2": "upload order does not change the reconstructed results (shuffled uploads, every runner)",
        "I3": "an exact duplicate or overlapping second recording changes nothing (cases 12d, 12o)",
        "I4": "repeating an identical observation cannot raise any component without bound (50 repeats)",
        "I5": "an easy run never lowers any component at its own time (case 10)",
        "I6": "missing moving time, heart rate or effort never yields a higher score than present data (case 01)",
        "I7": "no numerical coupling to race Elo (the lab modules import no race module)",
        "I8": "a runner's score depends only on their own history (no cohort normalisation)",
        "I9": "a single implausibly fast observation is kept, and carries a visible warning; the user can exclude it "
              "(case 13; revised 2026-10-22, exp5, user direction: never exclude a valid "
              "activity only because its converted score beats an anchor; earlier versions required 'raises nothing')",
        "I10": "no stopped-time cliff: 4.9/5.1 %, 14.9/15.1 % and 54.9/55.1 % stopped change endurance by < 5 points "
               "(case 16; added 2026-10-22 at the user's direction, exp2)",
        "I11": "an overlapping Walk, watch-left-running or other activity never lowers a genuine run's components "
               "(cases 15c, 15d; exp2)",
    },
    "desired": {
        "D1": "5 km longest -> continuous 8 km raises endurance evidence (case 01)",
        "D2": "the same distance faster raises speed (case 03)",
        "D3": "a long run with 41 min stopped keeps its recorded distance as completion evidence, is labelled 'with "
              "stops', and does not raise speed (case 04; revision 3, 2026-10-22, user direction: preserve observed "
              "facts and flag uncertainty; exp2 expected partial credit)",
        "D4": "a slow continuous 21 km raises endurance and does not lower speed (case 05)",
        "D5": "fast 5 km specialist and ultra specialist get recognisably different profiles (cases 06, 08)",
        "D6": "the improving beginner's combined score rises over the year (case 09)",
        "D7": "returning after 200 days: lower than before the gap, with no single-step drop over 150 points (case 11)",
        "D8": "60 noisy ordinary runs drift up by at most 39 points (about 2 % speed) after the first five, "
              "for each of seeds 1-5 (case 14)",
        "D9": "a run beyond 100 km is represented in the profile (case 08)",
    },
    "trade_offs": [
        "speed vs endurance weight (75/25, 50/50, 25/75): which runners gain or lose",
        "specialist (max) vs balanced (mean of demonstrated) aggregation of distance categories",
        "responsiveness (best single session, k = 1) vs robustness (second-best session, k = 2)",
        "sequential smoothing (bounded steps) vs immediate recognition of new capacity",
    ],
    "not_supported_by_data": [
        "whether a summary activity was uninterrupted running (moving time is a device estimate)",
        "running vs walking (only a pace anchor; slow runners and fast walkers overlap)",
        "terrain difficulty (total ascent does not describe a route; no correction is made)",
        "true maximal effort (labels are self-reported and are not used for points)",
        "any physiological ground truth: the generator's 'true' times are assumptions, not measurements",
    ],
    # exp4, written before the boundary results were computed (2026-10-22)
    "boundary_properties": {
        "BP1": "continuity: at a fixed pace, moving 0.01 km anywhere in 3-160.9 km changes performance by < 1 point",
        "BP2": "faster is better: at a fixed distance, 1 % less elapsed time always raises performance",
        "BP3": "same pace, longer distance never scores lower (no penalty for running further at the same pace)",
        "BP4": "consistent rule: the same distance, time and type (Run or Trail Run) is scored by one rule at every "
               "distance; Run and Trail Run are eligible on both sides of 42.5 km",
        "BP5": "unchanged where it was right: for Runs of 3-42.5 km the value equals the production 10 km-equivalent",
        "BP6": "defined for plausible paces across 3-160.9 km; below 3 km missing (not zero)",
    },
    "boundary_held_out": ["H8 kinks at anchor distances 50, 100, 160.9 km (continuity)",
                          "H9 a 1 % GPS distance error just below vs just above 42.5 km",
                          "H10 beyond the last anchor: 250-300 km",
                          "H11 the fastest plausible pace at 3 km (floor behaviour)",
                          "H12 a 30 km Trail Run vs the same as Run"],
    "selection_rule": "reject a method that fails any mandatory invariant at its default parameters; rank the "
                      "rest by desired behaviours passed (default parameters, then share of grid passing); keep at "
                      "most two; ties go to the method with fewer parameters",
    "grid_seeds": [1, 2, 3, 4, 5],
}


def acts_of(dicts):
    return [L.Act.of(d) for d in dicts]


def at(day):
    return S.at(day)


def comps(method, acts, day, params):
    r = L.evaluate(method, acts, at(day) if not hasattr(day, "tzinfo") else day, params)
    return r


def same(a, b):
    if set(a) != set(b):
        return False
    return all((a[k] is None and b[k] is None) or (a[k] is not None and b[k] is not None and abs(a[k] - b[k]) < EPS)
               for k in a)


def sp(comps):
    """The speed-like component: 'performance' in B's bridged mode, otherwise 'speed'."""
    return comps.get("performance", comps.get("speed"))


def endurance_like(method):
    return method in ("B", "D")


# ---------------------------------------------------------------- invariant and behaviour checks

def check_invariants(method, params, cases):
    res = {}
    c01 = cases["01"]
    labels = [comps(method, acts_of(cases[k][1]), cases[k][3], params).components for k in ("02e", "02h", "02u")]
    res["I1"] = same(labels[0], labels[1]) and same(labels[1], labels[2])
    ok = True
    for key in ("beginner", "ultra", "improving"):
        a = acts_of(S.runner(key, 1))
        shuffled = a[:]
        random.Random(7).shuffle(shuffled)
        t = max(x.start for x in a)
        ok &= same(L.evaluate(method, a, t, params).components, L.evaluate(method, shuffled, t, params).components)
    res["I2"] = ok
    ok = True
    for k in ("12d", "12o"):
        desc, hist, key, day = cases[k]
        a = acts_of(hist)
        ok &= same(L.evaluate(method, [x for x in a if x.key != key], at(day), params).components,
                   L.evaluate(method, a, at(day), params).components)
    res["I3"] = ok
    base = acts_of(S.base_5k())
    strong = S.act(99, 30, 8, 2520, 2510)                        # an 8 km stronger than anything before
    once = base + acts_of([strong])
    many = once + acts_of([dict(strong, key="r%d" % i, start=at(31 + i)) for i in range(50)])
    a1, a50 = L.evaluate(method, once, at(30), params).components, L.evaluate(method, many, at(81), params).components
    # bound: the repeated observation's own single-session value (k = 1); repeats may reach it, never exceed it
    ceil_method = method if method in ("B", "C") else "B"
    ceil_params = dict(params, k_best=1) if method in ("B", "C") else L.DEFAULTS["B"]
    ceiling = L.evaluate(ceil_method, once, at(30), ceil_params).components
    res["I4"] = all(v is None or v <= max(a1.get(k) or 0, ceiling.get(k) or 0) + 1.0 for k, v in a50.items())
    desc, hist, _, day = cases["10"]
    a = acts_of(hist)
    ok = True
    for x in a[1:]:
        ex = L.explain_activity(method, [y for y in a if y.start <= x.start], x.key, params)
        ok &= all(v is None or v >= -EPS for v in ex["deltas"].values())
    res["I5"] = ok
    ok = True
    stop_heavy = S.base_5k() + [S.act(5, 28, 20, 10289, 10289 * 0.58)]        # 42 % stopped (review finding)
    for hist in (c01[1], stop_heavy):
        full = acts_of(hist)
        stripped = [L.Act(x.key, x.start, x.type, x.distance_m, x.elapsed_s, None, None, "unknown", None) for x in full]
        r_full = L.evaluate(method, full, at(28), params).components
        r_str = L.evaluate(method, stripped, at(28), params).components
        ok &= all(r_str[k] is None or (r_full[k] is not None and r_str[k] <= r_full[k] + EPS) for k in r_full)
    res["I6"] = ok
    src = (ROOT / "runrank" / "lab_methods.py").read_text() + (ROOT / "runrank" / "lab_synthetic.py").read_text()
    res["I7"] = not re.search(r"^from \. import .*\b(elo|races)\b|^import .*\b(elo|races)\b", src, re.M)
    # no hidden cohort state: a runner's result is the same before and after evaluating every other runner
    a = acts_of(S.runner("steady", 1))
    t = max(x.start for x in a)
    first = L.evaluate(method, a, t, params).components
    for other in S.RUNNERS:
        L.evaluate(method, acts_of(S.runner(other, 1)), t, params)
    res["I8"] = same(first, L.evaluate(method, a, t, params).components)
    ok = True
    for lo, hi in (("16-04.9", "16-05.1"), ("16-14.9", "16-15.1"), ("16-54.9", "16-55.1")):
        e = [L.evaluate(method, acts_of(cases[k][1]), at(28), params).components for k in (lo, hi)]
        for comp in e[0]:
            if e[0][comp] is not None and e[1][comp] is not None:
                ok &= abs(e[0][comp] - e[1][comp]) < 5
    res["I10"] = ok
    ok = True
    for k in ("15c", "15d"):
        desc, hist, key, day = cases[k]
        a = acts_of(hist)
        clean = L.evaluate(method, [x for x in a if x.key != key], at(28), params).components
        junk = L.evaluate(method, a, at(28), params).components
        ok &= all(clean[c] is None or (junk[c] is not None and junk[c] >= clean[c] - EPS) for c in clean)
    res["I11"] = ok
    desc, hist, key, day = cases["13"]
    a = acts_of(hist)
    if method == "A":                          # production comparator keeps its own exclusion floor
        res["I9"] = same(L.evaluate(method, [x for x in a if x.key != key], at(day), params).components,
                         L.evaluate(method, a, at(day), params).components)
    else:                                      # kept (not dropped or invalid) and visibly warned
        pr = next(x for x in L.prepare(a, params) if x.act.key == key)
        res["I9"] = (pr.dropped is None and pr.invalid is None
                     and any("exceptional" in f or "suspicious" in f for f in pr.flags))
    return res


def check_desired(method, params, cases):
    res = {}

    def delta(case_id, comp):
        desc, hist, key, day = cases[case_id]
        ex = L.explain_activity(method, acts_of(hist), key, params)
        bc, ac = ex["before"].components, ex["after"].components
        b, a = (sp(bc), sp(ac)) if comp == "speed" else (bc.get(comp), ac.get(comp))
        return None if a is None or b is None else a - b

    res["D1"] = endurance_like(method) and (delta("01", "endurance") or 0) > EPS
    res["D2"] = (delta("03", "speed") or 0) > EPS if method != "C" else (delta("03", "short") or 0) > EPS
    if endurance_like(method):
        d4e = delta("04", "endurance")
        ex4 = L.explain_activity(method, acts_of(cases["04"][1]), "5", params)
        res["D3"] = (d4e is not None and d4e > EPS and (delta("04", "speed") or 0) <= EPS
                     and any("with stops" in r for r in ex4["reasons"]))
        res["D4"] = (delta("05", "endurance") or 0) > EPS and (delta("05", "speed") or 0) >= -EPS
    else:
        res["D3"] = method == "C"           # C has no endurance credit at all, so nothing is wrongly credited
        res["D4"] = False
    spd_ = L.evaluate(method, acts_of(cases["06"][1]), at(364), params).components
    ul = L.evaluate(method, acts_of(cases["08"][1]), at(364), params).components
    if endurance_like(method):
        res["D5"] = sp(spd_) > sp(ul) and ul["endurance"] > spd_["endurance"]
    elif method == "C":
        res["D5"] = spd_["ultra"] is None and ul["ultra"] is not None and (spd_["short"] or 0) > (ul["short"] or 0)
    else:
        res["D5"] = False
    beg = acts_of(cases["09"][1])
    c60, c364 = L.evaluate(method, beg, at(60), params).combined, L.evaluate(method, beg, at(364), params).combined
    res["D6"] = c60 is not None and c364 is not None and c364 > c60
    hist = L.history(method, acts_of(cases["11"][1]), at(270), params)
    pre = [h["combined"] for h in hist if h["at"] <= at(25) and h["combined"] is not None]
    post = [h["combined"] for h in hist if h["at"] >= at(260) and h["combined"] is not None]
    steps = [b["combined"] - a["combined"] for a, b in zip(hist, hist[1:])
             if a["combined"] is not None and b["combined"] is not None]
    res["D7"] = bool(pre and post) and post[-1] < pre[-1] and min(steps, default=0) > -150
    drift_ok = True
    for seed in SPEC["grid_seeds"]:
        a = acts_of(S.noisy_repeats(seed))
        first = L.evaluate(method, a[:5], a[4].start, params).components
        last = L.evaluate(method, a, a[-1].start, params).components
        fv, lv = (sp(first), sp(last)) if method != "C" else (first["short"], last["short"])
        drift_ok &= fv is not None and lv is not None and lv - fv <= 39
    res["D8"] = drift_ok
    if endurance_like(method):
        res["D9"] = ul["endurance"] is not None and ul["endurance"] >= L.endurance_points(100.0) - EPS
    elif method == "C":
        res["D9"] = ul["ultra"] is not None
    else:
        res["D9"] = False
    return res


def grid(method):
    space = L.PARAM_SPACE[method]
    keys = sorted(space)
    for values in product(*(space[k] for k in keys)):
        yield dict(zip(keys, values))


# ---------------------------------------------------------------- plots (static SVG; table views alongside)

COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"]
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def svg(w, h, body, title):
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" font-family="system-ui, sans-serif" '
            'font-size="12" role="img" aria-label="%s"><rect width="100%%" height="100%%" fill="#fcfcfb"/>'
            '<text x="16" y="22" font-size="14" font-weight="600" fill="%s">%s</text>%s</svg>\n'
            % (w, h, title, INK, title, body))


def scatter(points, title, xl, yl):
    W, H, L0, R0, T0, B0 = 720, 460, 64, 160, 40, 48
    xs, ys = [p[1] for p in points], [p[2] for p in points]
    x0, x1 = min(xs) - 100, max(xs) + 100
    y0, y1 = min(ys) - 100, max(ys) + 100
    X = lambda v: L0 + (v - x0) / (x1 - x0) * (W - L0 - R0)
    Y = lambda v: T0 + (1 - (v - y0) / (y1 - y0)) * (H - T0 - B0)
    b = ""
    for v in range(int(y0 // 250 + 1) * 250, int(y1), 250):
        b += '<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="%s"/><text x="%d" y="%.1f" text-anchor="end" fill="%s">%d</text>' % (
            L0, W - R0, Y(v), Y(v), GRID, L0 - 6, Y(v) + 4, MUTED, v)
    for v in range(int(x0 // 250 + 1) * 250, int(x1), 250):
        b += '<text x="%.1f" y="%d" text-anchor="middle" fill="%s">%d</text>' % (X(v), H - B0 + 18, MUTED, v)
    b += '<text x="%d" y="%d" text-anchor="middle" fill="%s">%s</text>' % ((L0 + W - R0) / 2, H - 10, MUTED, xl)
    b += '<text x="16" y="%d" fill="%s" transform="rotate(-90 16 %d)" text-anchor="middle">%s</text>' % (
        (T0 + H - B0) / 2, MUTED, (T0 + H - B0) / 2, yl)
    for i, (label, x, y) in enumerate(points):
        b += ('<g><title>%s: %s %.0f, %s %.0f</title><circle cx="%.1f" cy="%.1f" r="6" fill="%s" stroke="#fcfcfb" '
              'stroke-width="2"/><text x="%.1f" y="%.1f" fill="%s">%s</text></g>') % (
            label, xl, x, yl, y, X(x), Y(y), COLORS[i % 7], X(x) + 10, Y(y) + 4, INK, label)
    return svg(W, H, b, title)


def lines(series, xs_labels, title, yl):
    W, H, L0, R0, T0, B0 = 720, 420, 64, 190, 40, 48
    allv = [v for _, vs in series for v in vs if v is not None]
    y0, y1 = min(allv) - 50, max(allv) + 50
    n = len(xs_labels)
    X = lambda i: L0 + i / max(1, n - 1) * (W - L0 - R0)
    Y = lambda v: T0 + (1 - (v - y0) / (y1 - y0)) * (H - T0 - B0)
    b = ""
    for v in range(int(y0 // 100 + 1) * 100, int(y1), 100):
        b += '<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="%s"/><text x="%d" y="%.1f" text-anchor="end" fill="%s">%d</text>' % (
            L0, W - R0, Y(v), Y(v), GRID, L0 - 6, Y(v) + 4, MUTED, v)
    for i, lab in enumerate(xs_labels):
        b += '<text x="%.1f" y="%d" text-anchor="middle" fill="%s">%s</text>' % (X(i), H - B0 + 18, MUTED, lab)
    b += '<text x="16" y="%d" fill="%s" transform="rotate(-90 16 %d)" text-anchor="middle">%s</text>' % (
        (T0 + H - B0) / 2, MUTED, (T0 + H - B0) / 2, yl)
    for si, (label, vs) in enumerate(series):
        pts = [(X(i), Y(v)) for i, v in enumerate(vs) if v is not None]
        b += '<polyline fill="none" stroke="%s" stroke-width="2" points="%s"/>' % (
            COLORS[si % 7], " ".join("%.1f,%.1f" % p for p in pts))
        for (x, y), v in zip(pts, [v for v in vs if v is not None]):
            b += '<circle cx="%.1f" cy="%.1f" r="4" fill="%s" stroke="#fcfcfb" stroke-width="2"><title>%s: %.0f</title></circle>' % (
                x, y, COLORS[si % 7], label, v)
        if pts:
            b += '<text x="%.1f" y="%.1f" fill="%s">%s</text>' % (pts[-1][0] + 10, pts[-1][1] + 4, INK, label)
    return svg(W, H, b, title)


# ---------------------------------------------------------------- report

def fmt(v, nd=0):
    return "-" if v is None else ("%.*f" % (nd, v))


def main():
    buf = io.StringIO()
    w = lambda s="": buf.write(s + "\n")
    frozen = {"A": {"version": mmr.ALGORITHM_VERSION, "scale": mmr.SCALE_VERSION, "params": mmr.PARAMS},
              "lab": {"version": L.VERSION, "common": L.COMMON, "anchors": L.TOP_ANCHORS,
                      "param_space": L.PARAM_SPACE, "defaults": L.DEFAULTS}}
    digest = hashlib.sha256(json.dumps(frozen, sort_keys=True, default=str).encode()).hexdigest()[:16]
    w("RunnasUP Ratings Lab experiment (%s). SYNTHETIC data only; nothing here is a population standard." % L.VERSION)
    w("Frozen methods and parameters: sha256 %s (A = %s unchanged; B-D defaults %s)" % (
        digest, mmr.ALGORITHM_VERSION, json.dumps(L.DEFAULTS)))
    w("\n== 0. Evaluation specification (written before results) ==")
    for sec in ("mandatory_invariants", "desired"):
        w("  %s:" % sec)
        for k, v in SPEC[sec].items():
            w("    %s %s" % (k, v))
    for sec in ("trade_offs", "not_supported_by_data"):
        w("  %s:" % sec)
        for v in SPEC[sec]:
            w("    - %s" % v)
    w("  selection rule: %s" % SPEC["selection_rule"])

    cases = S.cases()
    w("\n== 1. Mandatory invariants and desired behaviour (default parameters) ==")
    inv, des = {}, {}
    for m in "ABCD":
        inv[m] = check_invariants(m, L.DEFAULTS[m], cases)
        des[m] = check_desired(m, L.DEFAULTS[m], cases)
    keys_i, keys_d = list(SPEC["mandatory_invariants"]), list(SPEC["desired"])
    w("   method " + " ".join("%3s" % k for k in keys_i) + " | " + " ".join("%3s" % k for k in keys_d) + " | desired")
    for m in "ABCD":
        w("   %-6s " % m + " ".join("%3s" % ("ok" if inv[m][k] else "NO") for k in keys_i) + " | " +
          " ".join("%3s" % ("ok" if des[m][k] else "no") for k in keys_d) + " | %d/9" % sum(des[m].values()))

    w("\n== 2. Predeclared parameter grid (share of combinations passing) ==")
    grid_score = {"A": (1.0, sum(des["A"].values()) / 9)}
    for m in "BCD":
        combos = list(grid(m))
        n_inv = n_des = 0
        worst = {}
        for p in combos:
            i = check_invariants(m, p, cases)
            d = check_desired(m, p, cases)
            n_inv += all(i.values())
            n_des += sum(d.values())
            for k, v in d.items():
                worst.setdefault(k, 0)
                worst[k] += v
        grid_score[m] = (n_inv / len(combos), n_des / (9 * len(combos)))
        w("   %s: %d combinations; all invariants hold in %d; desired behaviours passed %.0f %% overall; per "
          "behaviour: %s" % (m, len(combos), n_inv, 100 * n_des / (9 * len(combos)),
                             " ".join("%s %d/%d" % (k, worst[k], len(combos)) for k in keys_d)))

    w("\n== 3. Selection (rule above) ==")
    survivors = [m for m in "ABCD" if all(inv[m].values())]
    rejected = {m: [k for k, v in inv[m].items() if not v] for m in "ABCD" if m not in survivors}
    for m, ks in rejected.items():
        w("   REJECTED %s: fails %s" % (m, ", ".join("%s (%s)" % (k, SPEC["mandatory_invariants"][k]) for k in ks)))
    nparams = {m: len(L.PARAM_SPACE[m]) for m in "ABCD"}
    ranked = sorted(survivors, key=lambda m: (-sum(des[m].values()), -grid_score[m][1], nparams[m]))
    finalists = ranked[:2]
    for m in ranked:
        w("   %s: desired %d/9 at defaults, %.0f %% across its grid%s" % (
            m, sum(des[m].values()), 100 * grid_score[m][1], "  <- FINALIST" if m in finalists else ""))

    w("\n== 4. Fictional runners: components and combined scores (seed 1, as of 2025-12-31) ==")
    runners = list(S.RUNNERS)
    table = {}
    for key in runners:
        a = acts_of(S.runner(key, 1))
        t = at(364)
        row = {m: L.evaluate(m, a, t, L.DEFAULTS[m]) for m in "ABCD"}
        for wt in (0.75, 0.5, 0.25):
            row["B%d" % (wt * 100)] = L.evaluate("B", a, t, dict(L.DEFAULTS["B"], speed_weight=wt))
            row["D%d" % (wt * 100)] = L.evaluate("D", a, t, dict(L.DEFAULTS["D"], speed_weight=wt))
        row["Cbal"] = L.evaluate("C", a, t, dict(L.DEFAULTS["C"], aggregation="balanced"))
        table[key] = (a, row)
    w("   %-34s %6s | %6s %6s %6s %6s %6s | %6s %6s %6s %6s %6s %6s | %6s %6s %6s" % (
        "runner (activities; longest km)", "A", "B:S", "B:E", "B75", "B50", "B25", "C:sho", "C:mid", "C:mar", "C:ult",
        "Cspec", "Cbal", "D75", "D50", "D25"))
    for key in runners:
        a, r = table[key]
        cc = r["C"].components
        w("   %-34s %6s | %6s %6s %6s %6s %6s | %6s %6s %6s %6s %6s %6s | %6s %6s %6s" % (
            "%s (%d; %.1f)" % (S.RUNNERS[key][0][:22], len(a), max(x.distance_m for x in a) / 1000),
            fmt(r["A"].combined), fmt(r["B"].components["speed"]), fmt(r["B"].components["endurance"]),
            fmt(r["B75"].combined), fmt(r["B50"].combined), fmt(r["B25"].combined),
            fmt(cc["short"]), fmt(cc["middle"]), fmt(cc["marathon"]), fmt(cc["ultra"]),
            fmt(r["C"].combined), fmt(r["Cbal"].combined),
            fmt(r["D75"].combined), fmt(r["D50"].combined), fmt(r["D25"].combined)))
    for m in ("B", "D"):
        for wt in (75, 50, 25):
            order = sorted(runners, key=lambda k: -(table[k][1]["%s%d" % (m, wt)].combined or -1))
            w("   order %s %d/%d: %s" % (m, wt, 100 - wt, " > ".join(order)))
    for agg, k in (("specialist", "C"), ("balanced", "Cbal")):
        order = sorted(runners, key=lambda r: -(table[r][1][k].combined or -1))
        w("   order C %s: %s" % (agg, " > ".join(order)))

    w("\n== 5. Before/after for the matched cases (default parameters) ==")
    for cid in ("01", "02e", "02h", "02u", "03", "04", "05", "12d", "12o", "12s", "13", "15a", "15b", "15c", "15d",
                "16-04.9", "16-05.0", "16-05.1", "16-14.9", "16-15.0", "16-15.1", "16-54.9", "16-55.0", "16-55.1",
                "17a", "17b", "17c"):
        desc, hist, key, day = cases[cid]
        a = acts_of(hist)
        w("   %s %s" % (cid, desc))
        for m in "ABCD":
            ex = L.explain_activity(m, a, key, L.DEFAULTS[m])
            b, c = ex["before"].components, ex["after"].components
            w("      %s %s -> %s" % (m, " ".join("%s %s" % (k[:3], fmt(b[k])) for k in b),
                                     " ".join("%s %s" % (k[:3], fmt(c[k])) for k in c)))

    w("\n== 6. Sensitivity ==")
    w("   activity count (combined, default params; 25 / 50 / 100 % of the year's activities, every 4th/2nd/all):")
    for key in ("beginner", "speed", "ultra", "easy"):
        a = acts_of(S.runner(key, 1))
        races = [x for x in a if x.effort == "race"]
        sub = lambda n: sorted(set([x for i, x in enumerate(a) if i % n == 0] + races), key=lambda x: x.start)
        w("     %-10s " % key + "  ".join("%s %s/%s/%s" % (m, *(fmt(L.evaluate(m, s, at(364), L.DEFAULTS[m]).combined)
                                                            for s in (sub(4), sub(2), a))) for m in "ABCD"))
    w("   noise (case 14: 60 identical 5 km runs, distance sd 2 %; speed-like component after 5 vs 60 runs):")
    for m in "ABCD":
        drifts = []
        for seed in SPEC["grid_seeds"]:
            x = acts_of(S.noisy_repeats(seed))
            k = "speed" if m != "C" else "short"
            f = L.evaluate(m, x[:5], x[4].start, L.DEFAULTS[m]).components[k]
            l_ = L.evaluate(m, x, x[-1].start, L.DEFAULTS[m]).components[k]
            drifts.append(l_ - f)
        w("     %s drift per seed: %s" % (m, " ".join("%+.1f" % v for v in drifts)))
    w("   missing data (case 01 with moving time, HR and effort removed; combined):")
    full = acts_of(cases["01"][1])
    stripped = [L.Act(x.key, x.start, x.type, x.distance_m, x.elapsed_s, None, None, "unknown", None) for x in full]
    w("     " + "  ".join("%s %s -> %s" % (m, fmt(L.evaluate(m, full, at(28), L.DEFAULTS[m]).combined),
                                          fmt(L.evaluate(m, stripped, at(28), L.DEFAULTS[m]).combined)) for m in "ABCD"))
    w("   improvement and weaker evidence (improving runner; easy-only runner after a strong 10 km, case 10):")
    imp = acts_of(S.runner("improving", 1))
    w("     improving, combined at day 60/180/364: " + "  ".join(
        "%s %s" % (m, "/".join(fmt(L.evaluate(m, imp, at(dd), L.DEFAULTS[m]).combined) for dd in (60, 180, 364)))
        for m in "ABCD"))
    c10 = acts_of(cases["10"][1])
    w("     easy-only, combined at day 1/40/82: " + "  ".join(
        "%s %s" % (m, "/".join(fmt(L.evaluate(m, c10, at(dd), L.DEFAULTS[m]).combined) for dd in (1, 40, 82)))
        for m in "ABCD"))
    w("   initialisation (D only; beginner, combined day 30/120/364): first %s, anchor %s" % (
        "/".join(fmt(L.evaluate("D", acts_of(cases["09"][1]), at(dd), L.DEFAULTS["D"]).combined) for dd in (30, 120, 364)),
        "/".join(fmt(L.evaluate("D", acts_of(cases["09"][1]), at(dd), dict(L.DEFAULTS["D"], init="anchor")).combined)
                 for dd in (30, 120, 364))))
    w("   observation order: uploads shuffled give identical results for every method (I2).")
    spd = acts_of(S.runner("speed", 1))
    best10 = min(x.t10 for x in L.prepare(spd) if x.t10 is not None and x.act.start > at(300))
    glitch = acts_of([S.act("gl", 340, 10, best10 * 0.97, best10 * 0.97 - 10)])
    w("   outlier (one 10 km 3 % faster than the speed specialist's best recent evidence, e.g. a GPS short-read): "
      + "  ".join("%s %+.1f" % (m, (L.evaluate(m, spd + glitch, at(364), L.DEFAULTS[m]).combined or 0) -
                                (L.evaluate(m, spd, at(364), L.DEFAULTS[m]).combined or 0)) for m in "ABCD")
      + "   (B with k_best=2: %+.1f)" % ((L.evaluate("B", spd + glitch, at(364), dict(L.DEFAULTS["B"], k_best=2)).combined
                                        or 0) - (L.evaluate("B", spd, at(364), dict(L.DEFAULTS["B"], k_best=2)).combined
                                                 or 0)))
    w("   balanced aggregation and breadth: marathon specialist adds one slow 6 km jog (new short category for "
      "nobody, but the ultra runner gains a short category):")
    ul = acts_of(S.runner("ultra", 1))
    jog = acts_of([S.act("jog", 360, 6, 6 * 420, 6 * 420 - 10)])
    for agg in ("specialist", "balanced"):
        p = dict(L.DEFAULTS["C"], aggregation=agg)
        w("     ultra runner C %s: %s -> %s" % (agg, fmt(L.evaluate("C", ul, at(364), p).combined),
                                               fmt(L.evaluate("C", ul + jog, at(364), p).combined)))
    w("   withheld effort labels (speed specialist's races relabelled unknown): " + "  ".join(
        "%s %+.1f" % (m, (L.evaluate(m, [L.Act(x.key, x.start, x.type, x.distance_m, x.elapsed_s, x.moving_s,
                                               x.gain_m, "unknown", x.hr) for x in acts_of(S.runner("speed", 1))],
                                     at(364), L.DEFAULTS[m]).combined or 0) -
                      (L.evaluate(m, acts_of(S.runner("speed", 1)), at(364), L.DEFAULTS[m]).combined or 0))
        for m in "ABCD"))

    w("\n== 7. Held-out scenarios (evaluated only after selection; finalists %s) ==" % ", ".join(finalists))
    ho = S.held_out()
    for hid, (desc, with_, without, day) in ho.items():
        if hid == "H7":
            a = acts_of(S.runner("marathon", 1))
            mixed = a[::-1] + a[: len(a) // 3]
            w("   %s %s: " % (hid, desc) + "  ".join(
                "%s identical=%s" % (m, same(L.evaluate(m, a, at(364), L.DEFAULTS[m]).components,
                                             L.evaluate(m, mixed, at(364), L.DEFAULTS[m]).components)) for m in finalists))
            continue
        t = at(day)
        row = []
        for m in finalists:
            r1 = L.evaluate(m, acts_of(with_), t, L.DEFAULTS[m])
            r0 = L.evaluate(m, acts_of(without), t, L.DEFAULTS[m]) if without else None
            row.append("%s %s%s" % (m, " ".join("%s %s" % (k[:3], fmt(v)) for k, v in r1.components.items()),
                                    "" if r0 is None else " (reference %s)" % " ".join(
                                        "%s %s" % (k[:3], fmt(v)) for k, v in r0.components.items())))
        w("   %s %s:\n      %s" % (hid, desc, "\n      ".join(row)))

    w("\n== 8. What method B rewards (defaults; deltas in points) ==")
    w("   scale slopes: 1 %% faster = %+.2f speed points; 1 %% longer = %+.2f endurance points" % (
        3000 * math.log(1.01) / math.log(7200 / 1560), 3000 * math.log(1.01) / math.log(250)))
    w("   %-62s %8s %8s | %8s %8s %8s" % ("change", "speed", "endur.", "75/25", "50/50", "25/75"))
    for r in LC.improvements():
        w("   %-62s %+8.1f %+8.1f | %+8.1f %+8.1f %+8.1f" % (r["label"], r["dS"], r["dE"], r["d75"], r["d50"], r["d25"]))

    w("\n== 9. Long-distance improvement (matched: only performances at one distance; same type, stops, label) ==")
    w("   %-9s %-5s %18s %18s %20s %16s" % ("distance", "cfg", "performance", "endurance", "combined 50/50",
                                          "+5 repeats"))
    for name in S.LONG_MATCHED:
        before, after = S.long_matched(name)
        _, rep_ = S.long_matched(name, repeats=5)
        for cfg, pp in (("B", {}), ("B+LP", {"long_performance": "anchor"})):
            b = L.evaluate("B", acts_of(before), at(120), pp)
            a = L.evaluate("B", acts_of(after), at(120), pp)
            r5 = L.evaluate("B", acts_of(rep_), at(155), pp)
            perf = lambda r: max([v for k, v in r.components.items() if k != "endurance" and v is not None],
                                 default=None)
            w("   %-9s %-5s %8s -> %-7s %8s -> %-7s %9s -> %-8s %8s" % (
                name, cfg, fmt(perf(b), 1), fmt(perf(a), 1), fmt(b.components["endurance"], 1),
                fmt(a.components["endurance"], 1), fmt(b.combined, 1), fmt(a.combined, 1), fmt(r5.combined, 1)))
    w("   boundary at 42.5 km (same 5:55/km elapsed pace): " + "  ".join(
        "%.1f km: %s" % (km, " ".join("%s %s" % (k[:4], fmt(v, 1)) for k, v in L.evaluate(
            "B", acts_of([S.act(1, 0, km, km * 355, km * 350)]), at(0), {"long_performance": "anchor"}).components.items()))
        for km in (42.4, 42.5, 42.6)))

    w("\n== 10. Credible new bests, a suspicious outlier and explicit exclusion (B defaults) ==")
    spd = acts_of(S.runner("speed", 1))
    base_c = L.evaluate("B", spd, at(364)).combined
    best10 = min(x.t10 for x in L.prepare(spd) if x.t10 is not None and x.act.start > at(300))
    for label, extra in (("credible: 10 km 3 % faster than best recent evidence", S.act("ok", 340, 10, best10 * 0.97,
                                                                                         best10 * 0.97 - 10)),
                         ("suspicious: 'Run' 40 km in 2:00:00 (a ride?)", S.act("ride", 340, 40, 7200, 7150))):
        r = L.evaluate("B", spd + acts_of([extra]), at(364))
        sel = next(x for x in r.evidence["selected"] if x["component"] == "speed")
        w("   %-56s combined %+7.1f; speed set by %s (%s); pending: %s" % (
            label, r.combined - base_c, sel["activity"], "provisional" if sel["provisional"] else "corroborated",
            [x["activity"] for x in r.evidence["pending"]] or "none"))
        excl = [x for x in spd + acts_of([extra]) if x.key != extra["key"]]
        w("   %-56s combined %+7.1f (exclusion removes it; in production: the activity's Exclude annotation)" % (
            "   ... excluded", L.evaluate("B", excl, at(364)).combined - base_c))

    w("\n== 11. Missing moving time (credit function; full-range invariant; label vs scalar) ==")
    import itertools
    worst = {}
    for mode in ("label", "scalar"):
        cc = dict(L.COMMON, continuity=mode)
        n = viol = 0
        for km, pace, st in itertools.product((1.5, 5, 21.1, 42.2, 100, 160.9), (240, 330, 450, 560, 640, 900),
                                              (0.0, 0.03, 0.05, 0.1, 0.2, 0.4, 0.6, 0.8, 0.95, 0.99)):
            mv = km * pace
            known = L.Prep(L.Act("k", at(0), "Run", km * 1000, mv / (1 - st), mv))
            miss = L.Prep(L.Act("m", at(0), "Run", km * 1000, mv / (1 - st), None))
            L._endurance(known, cc)
            L._endurance(miss, cc)
            n += 1
            viol += (miss.endurance_km or 0) > (known.endurance_km or 0) + 1e-9
            worst[mode] = max(worst.get(mode, 0), (known.endurance_km or 0) - (miss.endurance_km or 0))
        w("   %-6s %d grid points (distance x moving pace x stopped share up to 99 %%): missing > known in %d" % (
            mode, n, viol))
    for cid in ("04", "15d", "17b", "17c"):
        desc, hist, key, day = cases[cid]
        row = []
        for mode in ("label", "scalar"):
            pr = next(x for x in L.prepare(acts_of(hist), {"continuity": mode}) if x.act.key == key)
            row.append("%s: %s km credited" % (mode, fmt(pr.endurance_km, 2)))
        w("   %-4s %-62s %s" % (cid, desc[:62], "; ".join(row)))

    w("\n== 12. Performance across 3-160.9 km: expected properties (written first) and dense scan ==")
    for k, v in SPEC["boundary_properties"].items():
        w("   %s %s" % (k, v))
    modes = (("off", "speed only (Riegel, Run 3-42.5 km)"), ("anchor", "exp3: max(speed, anchor-curve LP > 42.5 km)"),
             ("bridged", "exp4: one rule, bridged at 42.5 km"))

    def perf_value(mode, km, secs, typ="Run"):
        a = [L.Act("x", at(0), typ, km * 1000.0, secs, secs * 0.99)]
        r = L.evaluate("B", a, at(0), {"long_performance": mode})
        vals = [v for k, v in r.components.items() if k != "endurance" and v is not None]
        return max(vals) if vals else None

    kms = [round(3 + 0.05 * i, 2) for i in range(int((160.9 - 3) / 0.05) + 1)]
    for mode, desc in modes:
        res = {}
        for pace in (240, 300, 360, 450):
            vals = [perf_value(mode, km, km * pace) for km in kms]
            jumps = [abs(b - a) for a, b in zip(vals, vals[1:]) if a is not None and b is not None]
            gaps = sum(1 for a, b in zip(vals, vals[1:]) if (a is None) != (b is None))
            drops = [b - a for a, b in zip(vals, vals[1:]) if a is not None and b is not None and b < a - 1e-9]
            res[pace] = (max(jumps) if jumps else 0, gaps, min(drops) if drops else 0.0,
                         sum(v is None for v in vals))
        bp2 = all((perf_value(mode, km, km * 360 * 0.99) or 0) > (perf_value(mode, km, km * 360) or 0)
                  for km in (3, 10, 21.1, 42.4, 42.5, 42.6, 50, 100, 160.9))
        trail = [(perf_value(mode, km, km * 360, "Trail Run"), perf_value(mode, km, km * 360)) for km in (30, 60)]
        same_rule = all((a is None) == (b is None) and (a is None or abs(a - b) < 1e-9) for a, b in trail)
        w("   %-8s %s" % (mode, desc))
        for pace, (jmax, gaps, worst_drop, missing) in res.items():
            w("      pace %s/km: largest 0.05 km step %6.2f points; value appears/disappears %d times; worst drop with "
              "distance %+.2f; missing at %d of %d distances" % (mmr.fmt(pace), jmax, gaps, worst_drop, missing,
                                                                  len(kms)))
        w("      BP2 faster always higher: %s; BP4 Trail Run scored like Run at 30/60 km: %s" % (bp2, same_rule))
    w("   at the boundary (5:55/km): " + "  ".join(
        "%s %s" % (m, " ".join("%.1f km %s" % (km, fmt(perf_value(m, km, km * 355), 1)) for km in (42.4, 42.5, 42.6)))
        for m, _ in modes))
    w("   BP5 bridged equals production for Runs of 3-42.5 km: %s" % all(
        abs(perf_value("bridged", km, km * pace) - mmr.points(mmr.ten_k_equivalent_s(km * 1000, km * pace))) < 1e-9
        for km in (3, 5, 10, 21.1, 30, 42.5) for pace in (240, 300, 450)))
    w("\n   held-out boundary cases (evaluated after choosing 'bridged'):")
    for km in (49.9, 50.0, 50.1, 99.9, 100.0, 100.1, 160.8, 160.9344, 161.0):
        w("      H8 %6.1f km at 6:30/km: bridged %s" % (km, fmt(perf_value("bridged", km, km * 390), 2)))
    for km in (42.0, 43.0):
        a, b = perf_value("bridged", km, km * 330), perf_value("bridged", km * 1.01, km * 330)
        w("      H9 %4.1f km in %s, recorded 1 %% long: %s -> %s (%+.1f)" % (km, mmr.fmt(km * 330), fmt(a, 1), fmt(b, 1),
                                                                         b - a))
    for km in (200, 250, 300):
        w("      H10 %3d km at 8:00/km: bridged %s" % (km, fmt(perf_value("bridged", km, km * 480), 1)))
    w("      H11 3 km at 2:36/km (just above the 26:00 floor) %s; at 2:30/km %s" % (
        fmt(perf_value("bridged", 3, 3 * 156), 1), fmt(perf_value("bridged", 3, 3 * 150), 1)))
    w("      H12 30 km at 6:00/km, Trail Run vs Run: %s vs %s (terrain not adjusted)" % (
        fmt(perf_value("bridged", 30, 30 * 360, "Trail Run"), 1), fmt(perf_value("bridged", 30, 30 * 360), 1)))

    w("\n== 13. Credibility audit (exp4 policy; B defaults) ==")
    w("   states: dropped = duplicate recording; excluded = physical-floor implausible; held = segment inside a longer")
    w("   same-type recording (counts for nothing until confirmed separate); flagged = counted with a review note")
    easy = [S.act(i, i * 3, 8, 8 * 360, 8 * 355) for i in range(20)]
    imp = [S.act(i, i * 7, 10, 3300, 3290) for i in range(6)]
    old = [S.act(1, 0, 10, 2400, 2390)] + [S.act(i, 300 + i * 5, 10, 3000, 2990) for i in range(2, 8)]
    base5 = [S.act(i, i * 5, 10, 3000, 2990) for i in range(5)]
    audit = [
        ("first-ever activity (10 km 45:00)", [S.act(1, 0, 10, 2700, 2690)], 0, ()),
        ("first genuine race after easy-only history", easy + [S.act(99, 62, 10, 2700, 2690)], 62, ()),
        ("genuine improvement > 10 % (55:00 -> 47:00)", imp + [S.act(99, 45, 10, 2820, 2810)], 45, ()),
        ("returning runner: old 40:00, recent 50:00, now 45:00", old + [S.act(99, 340, 10, 2700, 2690)], 340, ()),
        ("one ride saved as Run (40 km in 2:00:00)", base5 + [S.act(9, 30, 40, 7200, 7150)], 30, ()),
        ("... and a second similar ride", base5 + [S.act(9, 30, 40, 7200, 7150), S.act(10, 37, 40, 7250, 7200)], 37,
         ()),
        ("genuine race + 6 km crop of it (same start)", S.base_5k() + [S.act(20, 28, 10, 2700, 2695),
                                                                       S.act(21, 28, 6, 1560, 1555)], 28, ()),
        ("... the crop confirmed as separate by the user", S.base_5k() + [S.act(20, 28, 10, 2700, 2695),
                                                                          S.act(21, 28, 6, 1560, 1555)], 28, ("21",)),
    ]
    for label, hist, day, conf in audit:
        r = L.evaluate("B", acts_of(hist), at(day), confirmed=set(conf))
        sel = {x["component"]: x["activity"] for x in r.evidence["selected"]}
        w("   %-52s S %6s E %6s set by %s | held %s | flagged %s" % (
            label, fmt(r.components["speed"], 1), fmt(r.components["endurance"], 1), sel,
            [x["activity"] for x in r.evidence["pending"]] or "-", sorted(r.evidence["flags"]) or "-"))
    hist = S.runner("speed", 1)
    r0 = L.evaluate("B", acts_of(hist), at(364))
    variants = {"backwards": hist[::-1], "4 interleaved batches": [x for k in range(4) for x in hist[k::4]]}
    w("   import order: " + "; ".join("%s identical (components, held, flags): %s" % (
        k, (lambda r: r.components == r0.components and r.evidence["pending"] == r0.evidence["pending"]
            and r.evidence["flags"] == r0.evidence["flags"])(L.evaluate("B", acts_of(v), at(364))))
        for k, v in variants.items()))

    w("\n== 14. What B rewards: matched examples (bridged performance, label continuity) ==")
    w("   %-78s %17s %17s | %7s %7s %7s" % ("change", "performance", "endurance", "75/25", "50/50", "25/75"))
    for r in LC.matched_rewards():
        w("   %-78s %7.1f -> %7.1f %7.1f -> %7.1f | %+7.1f %+7.1f %+7.1f  [%s]" % (
            r["label"], r["P_before"], r["P_after"], r["E_before"], r["E_after"], r["d75"], r["d50"], r["d25"],
            r["continuity_after"]))

    PLOTS.mkdir(parents=True, exist_ok=True)
    pts = [(S.RUNNERS[k][0].split(":")[0].replace("Fast short-distance specialist", "Speed specialist")
            .replace("Runner with many easy activities", "Many easy runs"),
            table[k][1]["B"].components["speed"], table[k][1]["B"].components["endurance"]) for k in runners]
    (PLOTS / "b_speed_vs_endurance.svg").write_text(scatter(
        pts, "Method B: speed vs endurance component (synthetic runners)", "speed points", "endurance points"))
    for m in ("B", "D"):
        series = [(p[0], [table[k][1]["%s%d" % (m, wt)].combined for wt in (75, 50, 25)])
                  for p, k in zip(pts, runners)]
        (PLOTS / ("%s_weights.svg" % m.lower())).write_text(lines(
            series, ["75/25", "50/50", "25/75"], "Method %s: combined score by speed/endurance weight" % m,
            "combined points"))
    series = []
    for p, k in zip(pts, runners):
        a = table[k][0]
        series.append((p[0], [L.evaluate(finalists[0], a, at(dd), L.DEFAULTS[finalists[0]]).combined
                              for dd in range(30, 365, 30)]))
    (PLOTS / "finalist_history.svg").write_text(lines(
        series, [str(i) for i in range(1, 13)], "Method %s: combined score at each month end (2025)" % finalists[0],
        "combined points"))
    w("\n   plots: %s" % ", ".join(sorted(x.name for x in PLOTS.glob("*.svg"))))
    w("   (every plotted value is also in the tables above)")
    OUT.write_text(buf.getvalue())
    sys.stdout.write(buf.getvalue())
    return 0


if __name__ == "__main__":
    sys.exit(main())
