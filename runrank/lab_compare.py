"""Ratings Lab comparisons and trade-off probes for the API (SYNTHETIC runners only; never stored).

Every number comes from runrank.lab_methods applied to runrank.lab_synthetic histories. The trade-off
probes are fixed perturbations whose effect is computed, not described after the fact.
"""
from . import lab_methods as L
from . import lab_synthetic as S

LAB_RUNNERS = ["beginner", "speed", "steady", "marathon", "ultra", "improving", "easy"]
CONFIGS = [("A", {}), ("B", {"speed_weight": 0.75}), ("B", {"speed_weight": 0.5}), ("B", {"speed_weight": 0.25}),
           ("C", {"aggregation": "specialist"}), ("C", {"aggregation": "balanced"}),
           ("D", {"speed_weight": 0.75}), ("D", {"speed_weight": 0.5}), ("D", {"speed_weight": 0.25})]
AS_OF_DAY = 364


def acts(key, seed=1):
    return [L.Act.of(d) for d in S.runner(key, seed)]


def config_label(method, params):
    p = L.check_params(method, params)
    k = " (second-best session)" if p.get("k_best", 1) == 2 else ""
    if method in ("B", "D"):
        return "%s %d/%d%s" % (method, round(p["speed_weight"] * 100), round((1 - p["speed_weight"]) * 100), k)
    if method == "C":
        return "C %s%s" % (p["aggregation"], k)
    return "A current"


def table():
    t = S.at(AS_OF_DAY)
    rows = []
    for key in LAB_RUNNERS:
        a = acts(key)
        cells = []
        for m, p in CONFIGS:
            r = L.evaluate(m, a, t, p)
            cells.append({"config": config_label(m, p), "method": m, "params": L.check_params(m, p),
                          "combined": r.combined, "components": r.components})
        rows.append({"runner": key, "label": S.RUNNERS[key][0], "activities": len(a),
                     "longest_km": max(x.distance_m for x in a) / 1000.0,
                     "races": sum(1 for x in a if x.effort == "race"), "cells": cells})
    return rows


def _combined(m, a, p, t):
    return L.evaluate(m, a, t, p).combined


def tradeoffs():
    t = S.at(AS_OF_DAY)
    out = {}
    # 1. who benefits from more endurance weight: combined at 25/75 minus 75/25
    out["endurance_weight"] = [
        {"runner": k, "label": S.RUNNERS[k][0],
         "B": _combined("B", acts(k), {"speed_weight": 0.25}, t) - _combined("B", acts(k), {"speed_weight": 0.75}, t),
         "D": _combined("D", acts(k), {"speed_weight": 0.25}, t) - _combined("D", acts(k), {"speed_weight": 0.75}, t)}
        for k in LAB_RUNNERS]
    # 2. does balanced aggregation reward more categories? add one slow 6 km jog to the ultra runner
    ul = acts("ultra")
    jog = [L.Act.of(S.act("jog", AS_OF_DAY - 4, 6, 6 * 420, 6 * 420 - 10))]
    out["breadth"] = {"probe": "ultra runner adds one slow 6 km jog (a new 'short' category)",
                      "specialist": [_combined("C", ul, {"aggregation": "specialist"}, t),
                                     _combined("C", ul + jog, {"aggregation": "specialist"}, t)],
                      "balanced": [_combined("C", ul, {"aggregation": "balanced"}, t),
                                   _combined("C", ul + jog, {"aggregation": "balanced"}, t)]}
    # 3. outlier: one 10 km 3 % faster than the speed specialist's best recent evidence
    spd = acts("speed")
    best = min(x.t10 for x in L.prepare(spd) if x.t10 is not None and x.act.start > S.at(300))
    glitch = [L.Act.of(S.act("glitch", 340, 10, best * 0.97, best * 0.97 - 10))]
    out["outlier"] = {"probe": "speed specialist gains one 10 km 3 % faster than their best recent evidence",
                      "effects": [{"config": config_label(m, p), "delta": _combined(m, spd + glitch, p, t) -
                                   _combined(m, spd, p, t)} for m, p in
                                  [("A", {}), ("B", {}), ("B", {"k_best": 2}), ("C", {}), ("C", {"k_best": 2}),
                                   ("D", {})]]}
    # 4. more uploads / withheld labels
    beg = acts("beginner")
    extra = [L.Act.of(S.act("x%d" % i, 300 + i * 0.5, 5, 1950, 1940)) for i in range(60)]
    unl = [L.Act(x.key, x.start, x.type, x.distance_m, x.elapsed_s, x.moving_s, x.gain_m, "unknown", x.hr)
           for x in acts("speed")]
    hard8 = S.base_5k() + [S.act(5, 28, 8, S.EIGHT_S, S.EIGHT_S - 20, effort="hard")]
    unk8 = S.base_5k() + [S.act(5, 28, 8, S.EIGHT_S, S.EIGHT_S - 20)]
    out["gaming"] = {
        "more_uploads": [{"config": config_label(m, {}), "delta": _combined(m, beg + extra, {}, t) -
                          _combined(m, beg, {}, t)} for m in "ABCD"],
        "more_uploads_probe": "beginner uploads 60 extra ordinary 5 km runs",
        "withheld_labels": [{"config": config_label(m, {}),
                             "delta_speed_races": _combined(m, unl, {}, t) - _combined(m, spd, {}, t),
                             "delta_hard_8km": _combined(m, [L.Act.of(x) for x in unk8], {}, S.at(28)) -
                             _combined(m, [L.Act.of(x) for x in hard8], {}, S.at(28))} for m in "ABCD"],
        "withheld_probe": "score with labels removed minus score with honest labels (speed specialist's races; the "
                          "5 km -> 8 km run labelled hard)"}
    return out


def improvements():
    """Concrete changes and what method B rewards: component and combined deltas at 75/25, 50/50, 25/75.

    Each row: (label, history before, history after, evaluation day). Deltas come from lab_methods only.
    """
    def base5(t5):
        return [S.act(i, i * 5, 5, t5 + 30 * (i % 2), t5 + 30 * (i % 2) - 10) for i in range(1, 5)]
    long20 = base5(1500) + [S.act(10, 25, 20, 20 * 360, 20 * 360 - 30)]
    rows = [
        ("5 km best improves from 25:00 to 23:00", base5(1500), base5(1500) + [S.act(20, 30, 5, 1380, 1375)], 30),
        ("longest run 5 km -> 8 km (46:00, 5:45/km)", base5(1500), base5(1500) + [S.act(20, 30, 8, 2760, 2740)], 30),
        ("longest run 20 km -> 30 km (6:20/km)", long20, long20 + [S.act(20, 30, 30, 30 * 380, 30 * 380 - 40)], 30),
        ("same 20 km completed faster (6:00 -> 5:30/km)", long20, long20 + [S.act(20, 30, 20, 20 * 330, 20 * 330 - 30)],
         30),
        ("fast short-distance specialist adds a slow 25 km (6:30/km)", S.runner("speed", 1),
         S.runner("speed", 1) + [S.act("long", AS_OF_DAY - 3, 25, 25 * 390, 25 * 390 - 60)], AS_OF_DAY),
        ("ultra specialist adds a short easy 6 km (6:30/km)", S.runner("ultra", 1),
         S.runner("ultra", 1) + [S.act("short", AS_OF_DAY - 3, 6, 6 * 390, 6 * 390 - 10)], AS_OF_DAY),
    ]
    out = []
    for label, before, after, day in rows:
        t = S.at(day)
        b, a = [L.Act.of(x) for x in before], [L.Act.of(x) for x in after]
        rb, ra = L.evaluate("B", b, t), L.evaluate("B", a, t)
        cell = {"label": label, "dS": ra.components["speed"] - rb.components["speed"],
                "dE": ra.components["endurance"] - rb.components["endurance"],
                "S_after": ra.components["speed"], "E_after": ra.components["endurance"]}
        for wt in (0.75, 0.5, 0.25):
            cell["d%d" % round(wt * 100)] = wt * cell["dS"] + (1 - wt) * cell["dE"]
        out.append(cell)
    return out


def matched_rewards():
    """exp4: what B (bridged performance, label continuity) rewards. Each pair differs in one recorded fact."""
    p = {"long_performance": "bridged"}
    a = lambda km, el, mv="same": [L.Act("x", S.at(0), "Run", km * 1000.0, el,
                                         None if mv is None else (el * 0.99 if mv == "same" else mv))]
    pairs = [
        ("same distance, faster time (10 km 50:00 -> 45:00)", a(10, 3000), a(10, 2700)),
        ("longer distance, same pace (10 km -> 21.1 km at 5:00/km)", a(10, 3000), a(21.0975, 21.0975 * 300)),
        ("longer distance, same elapsed time (10 km -> 12 km in 50:00)", a(10, 3000), a(12, 3000)),
        ("same distance and elapsed, moving 1:48:00 -> 1:35:00 (21.1 km in 1:50:00)", a(21.0975, 6600, 6480),
         a(21.0975, 6600, 5700)),
        ("same activity with moving time missing (21.1 km in 1:50:00)", a(21.0975, 6600, 6480), a(21.0975, 6600, None)),
    ]
    out = []
    for label, before, after in pairs:
        rb, ra = L.evaluate("B", before, S.at(0), p), L.evaluate("B", after, S.at(0), p)
        pre = next(x for x in L.prepare(after, p) if x.act.key == "x")
        row = {"label": label, "P_before": rb.components["performance"], "P_after": ra.components["performance"],
               "E_before": rb.components["endurance"], "E_after": ra.components["endurance"],
               "continuity_after": pre.continuity}
        for w in (0.75, 0.5, 0.25):
            row["d%d" % round(w * 100)] = (w * ra.components["performance"] + (1 - w) * ra.components["endurance"]) - \
                (w * rb.components["performance"] + (1 - w) * rb.components["endurance"])
        out.append(row)
    return out
