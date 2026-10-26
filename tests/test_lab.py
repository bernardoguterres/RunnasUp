"""Ratings Lab (EXPERIMENTAL methods B-D, comparator A): hand values, invariants, isolation. SYNTHETIC data.

Hand values computed independently with math.log (docs/RATING_METHOD.md §A15):
  5 km in 25:00: T10 = 1500 × 2^1.06 = 3127.397 s -> speed 1635.705
  endurance points 3000 × ln(km) / ln(250): 5 km 874.463, 8 km 1129.832 (+255.369)
  D: 874.463 + min(0.3 × 255.369, 50) = 924.463
  C at 10 km: 45:00 = 13.333 km/h; anchor 26:00 -> 1923.955
"""
import random

import pytest
from starlette.testclient import TestClient

from runrank import api, lab_methods as L, lab_synthetic as S


def A(dicts):
    return [L.Act.of(d) for d in dicts]


CASES = S.cases()


def ev(method, case, params=None):
    desc, hist, key, day = CASES[case]
    return L.explain_activity(method, A(hist), key, params)


def test_hand_values_for_the_5_to_8_km_example():
    b = ev("B", "01")
    assert b["before"].components["speed"] == pytest.approx(1635.705, abs=1e-3)
    assert b["before"].components["endurance"] == pytest.approx(874.463, abs=1e-3)
    assert b["after"].components["endurance"] == pytest.approx(1129.832, abs=1e-3)
    assert b["after"].components["speed"] == b["before"].components["speed"]     # slower pace does not lower speed
    assert b["after"].combined == pytest.approx((1635.705 + 1129.832) / 2, abs=1e-3)
    d = ev("D", "01")
    assert d["after"].components["endurance"] == pytest.approx(924.463, abs=1e-3)
    c = ev("C", "01")
    assert c["after"].components == c["before"].components                     # C does not credit it (a finding)


def test_category_anchor_hand_value():
    assert L.v_top(10.0) == pytest.approx(10 / (26 / 60))
    r = L.evaluate("C", [L.Act("1", S.at(0), "Run", 10000.0, 2700.0, 2690.0)], S.at(0))
    assert r.components["short"] == pytest.approx(1923.955, abs=1e-3)


@pytest.mark.parametrize("method", ["B", "C", "D"])
def test_effort_label_never_changes_points(method):
    vals = [ev(method, c)["after"].components for c in ("02e", "02h", "02u")]
    assert vals[0] == vals[1] == vals[2]


def test_production_comparator_a_no_longer_changes_with_a_hard_label():
    """A is the live production method; since mmr-envelope-v2 a hard label changes nothing (v1 cost 159 points)."""
    assert ev("A", "02h")["after"].combined == ev("A", "02u")["after"].combined


@pytest.mark.parametrize("method", ["A", "B", "C", "D"])
def test_upload_order_and_repeated_ids_do_not_change_results(method):
    a = A(S.runner("marathon", 1))
    mixed = a[::-1] + a[: len(a) // 3]
    random.Random(3).shuffle(mixed)
    t = S.at(364)
    assert L.evaluate(method, a, t).components == L.evaluate(method, mixed, t).components


@pytest.mark.parametrize("method", ["B", "C", "D"])
def test_duplicates_overlaps_and_splits_add_nothing(method):
    for case in ("12d", "12o", "12s"):
        r = ev(method, case)
        assert r["after"].components == r["before"].components, case


def test_extreme_converted_score_is_kept_flagged_not_excluded():
    """exp5: case 13 (10 km in 20:00) used to be excluded for beating the 26:00 anchor; now it counts with warnings."""
    desc, hist, key, day = CASES["13"]
    r = L.evaluate("B", A(hist), S.at(day))
    sel = next(x for x in r.evidence["selected"] if x["component"] == "speed")
    assert sel["activity"] == key and r.components["speed"] > 3000
    assert any("exceptional modelled score" in w for w in sel["concerns"])
    assert any("suspicious recorded measurement" in w for w in sel["concerns"])


def test_missing_moving_time_is_stricter_never_an_advantage():
    with_mv = A(S.base_5k() + [S.act(5, 28, 8, 8 * 560, 8 * 556)])          # 9:20/km: passes with moving time
    no_mv = [L.Act(x.key, x.start, x.type, x.distance_m, x.elapsed_s, None) for x in with_mv]
    e1 = L.evaluate("B", with_mv, S.at(28)).components["endurance"]
    e0 = L.evaluate("B", no_mv, S.at(28)).components["endurance"]
    assert e0 is None or e0 <= e1          # missing moving time: no endurance credit (missing, never higher)


def test_k_best_two_never_lets_a_weaker_session_lower_a_component():
    p = dict(L.DEFAULTS["B"], k_best=2)
    one = A([S.act(1, 0, 10, 2700, 2690)])
    two = one + A([S.act(2, 2, 8, 8 * 340, 8 * 335)])
    assert L.evaluate("B", one, S.at(0), p).components["speed"] is None       # needs two sessions: missing evidence
    assert L.evaluate("B", two, S.at(2), p).components["speed"] is not None


def test_sequential_d_is_bounded_and_drifts_upward_under_noise():
    r = ev("D", "01")
    assert r["after"].components["endurance"] - r["before"].components["endurance"] <= 50 + 1e-9
    a = A(S.noisy_repeats(5))
    first = L.evaluate("D", a[:5], a[4].start).components["speed"]
    last = L.evaluate("D", a, a[-1].start).components["speed"]
    assert last - first > 39                    # the documented positive-only drift (D8 fails)


def test_parameters_must_be_predeclared():
    with pytest.raises(ValueError):
        L.check_params("B", {"speed_weight": 0.9})
    with pytest.raises(ValueError):
        L.check_params("B", {"nonsense": 1})


def test_lab_modules_do_not_touch_race_elo_or_the_database():
    import pathlib
    import re
    for f in ("lab_methods.py", "lab_synthetic.py"):
        src = (pathlib.Path(L.__file__).parent / f).read_text()
        imports = " ".join(re.findall(r"^(?:from|import) .*$", src, re.M))
        assert not re.search(r"\b(elo|races|store|sqlite3|api)\b", imports), (f, imports)


def test_missing_moving_time_never_raises_endurance_even_with_heavy_stops():
    """Review defect 1: a stop-heavy 20 km gained endurance when its moving time was removed."""
    with_mv = A(S.base_5k() + [S.act(5, 28, 20, 10289, 10289 * 0.58)])
    no_mv = [L.Act(x.key, x.start, x.type, x.distance_m, x.elapsed_s, None) for x in with_mv]
    zero_mv = [L.Act(x.key, x.start, x.type, x.distance_m, x.elapsed_s, 0.0) for x in with_mv]
    for m in ("B", "D"):
        e = L.evaluate(m, with_mv, S.at(28)).components["endurance"]
        for variant in (no_mv, zero_mv):
            v = L.evaluate(m, variant, S.at(28)).components["endurance"]
            assert v is None or v <= e


def test_naive_datetimes_are_rejected_clearly():
    """Review defect 10: mixing naive and aware datetimes crashed with a TypeError."""
    from datetime import datetime
    with pytest.raises(ValueError):
        L.Act.of({"key": "x", "start": datetime(2025, 1, 1), "type": "Run", "distance_m": 5000, "elapsed_s": 1500})


# ---------------------------------------------------------------- exp2 evidence handling (hand values: math.log)

def _e(case, day=28):
    desc, hist, key, _ = CASES[case]
    return L.evaluate("B", A(hist), S.at(day))


def test_overlap_classes():
    pr = {p.act.key: p for p in L.prepare(A(CASES["15a"][1]))}
    assert pr["6"].dropped.startswith("probable duplicate recording of 5") and pr["5"].dropped is None
    for case, junk in (("15c", "22"), ("15d", "23")):                     # different-type and watch left running
        a = A(CASES[case][1])
        clean = L.evaluate("B", [x for x in a if x.key != junk], S.at(28)).components
        with_junk = L.evaluate("B", a, S.at(28)).components
        assert with_junk["speed"] == clean["speed"] and with_junk["endurance"] >= clean["endurance"]
        pr = {p.act.key: p for p in L.prepare(a)}
        assert pr[junk].dropped is None and pr["20"].dropped is None and "ambiguous overlap" in pr["20"].overlap
    pr = {p.act.key: p for p in L.prepare(A(CASES["15d"][1]))}
    assert any("watch left running" in f for f in pr["23"].flags)


def test_single_session_evidence_is_provisional_until_corroborated():
    one = A([S.act(1, 0, 10, 2700, 2690), S.act(2, 3, 5, 1800, 1790)])
    sel = {x["component"]: x for x in L.evaluate("B", one, S.at(3)).evidence["selected"]}
    assert sel["speed"]["provisional"] and sel["endurance"]["provisional"]
    two = one + A([S.act(3, 6, 10, 2720, 2710)])
    sel = {x["component"]: x for x in L.evaluate("B", two, S.at(6)).evidence["selected"]}
    assert not sel["speed"]["provisional"] and not sel["endurance"]["provisional"]


# ---------------------------------------------------------------- exp3 (hand values: math.log)

SCALAR = {"continuity": "scalar"}


def _e(case, day=28, params=None):
    desc, hist, key, _ = CASES[case]
    return L.evaluate("B", A(hist), S.at(day), params)


def test_exp2_scalar_continuity_hand_values_are_preserved():
    # 12 km, 37.27 % stopped: 1 - (0.3727 - 0.05) = 0.6773 -> 8.127 km -> 1138.4
    assert _e("04", params=SCALAR).components["endurance"] == pytest.approx(1138.4, abs=0.1)
    # 100 mile: 14.9 % -> 0.901 -> 145.00 km -> 2704.04; 15.1 % -> 2702.83
    assert _e("16-14.9", params=SCALAR).components["endurance"] == pytest.approx(2704.04, abs=0.05)
    assert _e("16-15.1", params=SCALAR).components["endurance"] == pytest.approx(2702.83, abs=0.05)


def test_label_mode_keeps_recorded_distance_and_flags_stops():
    r = L.explain_activity("B", A(CASES["04"][1]), "5")
    assert r["after"].components["endurance"] == pytest.approx(1350.14, abs=0.01)     # 3000 ln 12 / ln 250
    assert any("with stops (37.3 % stopped)" in x for x in r["reasons"])
    vals = {k: _e(k).components["endurance"] for k in CASES if k.startswith("16-")}
    assert len({round(v, 9) for v in vals.values()}) == 1                            # stops never subtract


def test_missing_moving_time_never_increases_credit_across_the_valid_range():
    import itertools
    for mode in ("label", "scalar"):
        c = dict(L.COMMON, continuity=mode)
        for km, pace, stopped in itertools.product((1.5, 5, 21.1, 42.2, 100, 160.9), (240, 330, 450, 560, 640, 900),
                                                   (0.0, 0.03, 0.05, 0.1, 0.2, 0.4, 0.6, 0.8, 0.95, 0.99)):
            moving = km * pace
            elapsed = moving / (1 - stopped)
            known, missing = L.Prep(L.Act("k", S.at(0), "Run", km * 1000, elapsed, moving)), \
                L.Prep(L.Act("m", S.at(0), "Run", km * 1000, elapsed, None))
            L._endurance(known, c)
            L._endurance(missing, c)
            assert (missing.endurance_km or 0) <= (known.endurance_km or 0) + 1e-9, (mode, km, pace, stopped)


def test_long_distance_performance_recognises_faster_ultras_without_conversion():
    import math
    vt = 100 / (365 / 60)
    P = lambda v: 3000 * math.log(v / 5) / math.log(vt / 5)
    hist = [S.act(i, i * 30, 100, 11 * 3600, 11 * 3600 - 600, typ="Trail Run") for i in range(4)]
    faster = hist + [S.act(9, 130, 100, 11 * 3600 * 0.95, 11 * 3600 * 0.95 - 600, typ="Trail Run")]
    on = {"long_performance": "anchor"}
    b0 = L.evaluate("B", A(hist), S.at(90), on)                              # at the last run: no aging
    b1 = L.evaluate("B", A(faster), S.at(130), on)
    assert b0.components["long_performance"] == pytest.approx(P(100 / 11), abs=0.05)        # 1507.0
    assert b1.components["long_performance"] == pytest.approx(P(100 / (11 * 0.95)), abs=0.05)  # 1636.3
    assert L.evaluate("B", A(faster), S.at(130)).combined is None           # off: no performance evidence at all
    again = faster + [S.act(10, 140, 100, 11 * 3600 * 0.95, 11 * 3600 * 0.95 - 600, typ="Trail Run")]
    assert L.evaluate("B", A(again), S.at(140), on).components["long_performance"] == pytest.approx(
        b1.components["long_performance"], abs=0.5)                          # repeating it adds nothing (aging only)


# ---------------------------------------------------------------- exp4: evidence states and the bridged rule

def _sel(r, comp):
    return next(x for x in r.evidence["selected"] if x["component"] == comp)


def test_genuine_race_after_easy_only_counts_at_once_and_is_flagged():
    """exp3 defect: the first race after easy-only training was held, losing its speed AND its endurance."""
    easy = [S.act(i, i * 3, 8, 8 * 360, 8 * 355) for i in range(20)]
    r = L.evaluate("B", A(easy + [S.act(99, 62, 10, 2700, 2690)]), S.at(62))
    assert _sel(r, "speed")["activity"] == "99" and _sel(r, "endurance")["activity"] == "99"
    assert r.evidence["pending"] == [] and any("large improvement" in w for w in r.evidence["flags"]["99"])


def test_large_improvement_is_judged_on_recorded_times_not_aged_values():
    """exp3 defect: a 9 % recorded improvement was held because the older evidence had been aged first."""
    h = A([S.act(1, 0, 10, 3000, 2990), S.act(2, 100, 10, 2730, 2720)])         # 50:00 -> 45:30 (9 %)
    for day in (100, 200, 300):
        r = L.evaluate("B", h, S.at(day))
        assert "2" not in r.evidence["flags"] and r.evidence["pending"] == []
    h2 = A([S.act(1, 0, 10, 3000, 2990), S.act(2, 100, 10, 2640, 2630)])        # 12 %: flagged, still counted
    r = L.evaluate("B", h2, S.at(100))
    assert _sel(r, "speed")["activity"] == "2" and "2" in r.evidence["flags"]


def test_crop_is_held_genuine_race_counts_and_confirmation_is_labelled():
    race, crop = S.act(20, 28, 10, 2700, 2695), S.act(21, 28, 6, 1560, 1555)
    acts = A(S.base_5k() + [race, crop])
    r = L.evaluate("B", acts, S.at(28))
    assert [x["activity"] for x in r.evidence["pending"]] == ["21"]
    assert _sel(r, "speed")["activity"] == "20"
    rc = L.evaluate("B", acts, S.at(28), confirmed={"21"})
    assert rc.evidence["pending"] == [] and _sel(rc, "speed")["activity"] == "21"
    assert any("confirmed by the user (not independent validation)" in w for w in rc.evidence["flags"]["21"])


def test_mislabelled_rides_count_flagged_and_a_second_ride_does_not_validate():
    """Summary data cannot tell a ride from a run: the ride counts (flagged); exclusion is the user's tool."""
    base = [S.act(i, i * 5, 10, 3000, 2990) for i in range(5)]
    ride1, ride2 = S.act(9, 30, 40, 7200, 7150), S.act(10, 37, 40, 7250, 7200)
    r1 = L.evaluate("B", A(base + [ride1]), S.at(30))
    assert _sel(r1, "speed")["activity"] == "9" and any("large improvement" in w for w in r1.evidence["flags"]["9"])
    r2 = L.evaluate("B", A(base + [ride1, ride2]), S.at(37))
    assert not _sel(r2, "speed")["provisional"]                    # 'corroborated' by another ride: not validation
    excl = L.evaluate("B", A(base), S.at(37))
    assert excl.combined < r2.combined


def test_held_segment_counts_for_no_component():
    tempo, seg = S.act(1, 0, 10, 2800, 2790), S.act(2, 0.01, 3, 720, 718)
    r = L.evaluate("B", A([tempo, seg]), S.at(1))
    assert [x["activity"] for x in r.evidence["pending"]] == ["2"]
    assert _sel(r, "speed")["activity"] == "1" and _sel(r, "endurance")["activity"] == "1"


def test_bridged_rule_is_continuous_monotone_and_equal_to_production_up_to_42_5_km():
    import math
    from runrank import mmr
    def perf(km, secs, typ="Run"):
        r = L.evaluate("B", [L.Act("x", S.at(0), typ, km * 1000, secs, secs * 0.99)], S.at(0),
                       {"long_performance": "bridged"})
        return r.components["performance"]
    for pace in (300, 390, 450):
        vals = [perf(km / 100, km / 100 * pace) for km in range(300, 16091, 7)]
        assert all(b >= a - 1e-9 for a, b in zip(vals, vals[1:]))                         # no drop with distance
        assert max(b - a for a, b in zip(vals, vals[1:])) < 7 * 1.0                       # BP1: < 1 point per 0.01 km
    for km in (3, 10, 42.5):
        assert perf(km, km * 330) == pytest.approx(mmr.points(mmr.ten_k_equivalent_s(km * 1000, km * 330)), abs=1e-9)
    assert perf(42.5, 42.5 * 355) == pytest.approx(perf(42.5001, 42.5001 * 355), abs=0.01)  # the old 42.5 km step
    assert perf(60, 60 * 400, "Trail Run") == perf(60, 60 * 400)
    for km in (5, 42.6, 100):
        assert perf(km, km * 360 * 0.99) > perf(km, km * 360)                             # faster is better
    # hand value: 100 km in 11:00:00 -> 42.5 km-equivalent 39600 x t_top(42.5) / t_top(100)
    t_eq = 39600 * L.t_top(42.5) / L.t_top(100)
    assert perf(100, 39600) == pytest.approx(mmr.points(t_eq * (10 / 42.5) ** 1.06), abs=1e-9)


# ---------------------------------------------------------------- exp5: plausibility, range, evidence preservation

BR = {"long_performance": "bridged"}


def test_fast_short_run_and_fast_ultra_are_kept_and_flagged():
    import math
    from runrank import mmr
    r = L.evaluate("B", A(S.base_5k() + [S.act(9, 28, 3, 420, 418)]), S.at(28), BR)
    assert r.components["performance"] == pytest.approx(mmr.points(420 * (10 / 3) ** 1.06), abs=1e-9)   # 3070.6
    sel = next(x for x in r.evidence["selected"] if x["component"] == "performance")
    assert sel["activity"] == "9" and any("exceptional modelled score" in c for c in sel["concerns"])
    u = L.evaluate("B", A(S.base_5k() + [S.act(9, 28, 100, 21600, 21500, typ="Trail Run")]), S.at(28), BR)
    t_eq = 21600 * L.t_top(42.5) / L.t_top(100)
    assert u.components["performance"] == pytest.approx(mmr.points(t_eq * (10 / 42.5) ** 1.06), abs=1e-9)  # 2996.5
    assert any("faster than the synthetic anchor curve" in c for c in
               next(x for x in u.evidence["selected"] if x["component"] == "performance")["concerns"])


def test_one_supported_range_and_no_silent_clamping():
    assert L.v_top(4.9) is None and L.v_top(250.1) is None and L.v_top(100) is not None
    for km in (2.0, 300.0):
        a = A(S.base_5k() + [S.act(9, 28, km, km * 480, km * 470, typ="Trail Run")])
        pr = next(x for x in L.prepare(a) if x.act.key == "9")
        assert pr.endurance_km is None and pr.bridged_t10 is None and "outside the supported range" in pr.endurance_reason
        r = L.evaluate("B", a, S.at(28), BR)
        assert r.components["endurance"] == pytest.approx(874.46, abs=0.01)        # the 5 km evidence, not 3000


def test_invalid_and_contradictory_records_are_kept_not_scored():
    bad = dict(S.act(9, 28, 8, 2760, 2740), elapsed_s=0.0)
    pr = {x.act.key: x for x in L.prepare(A(S.base_5k() + [bad]))}
    assert "9" in pr and pr["9"].invalid.startswith("structurally invalid") and pr["9"].endurance_km is None
    mv = {x.act.key: x for x in L.prepare(A(S.base_5k() + [S.act(9, 28, 8, 2760, 3000)]))}
    assert mv["9"].act.moving_s is None and mv["9"].endurance_km == pytest.approx(8.0)
    assert any("moving time contradicts" in f for f in mv["9"].flags)


def test_probable_duplicate_is_explained_and_reversible_without_editing_input():
    hist = A(S.base_5k() + [S.act(5, 28, 8, 2760, 2740), S.act(6, 28, 8.3, 2720, None, hour=1 / 60)])
    before = list(hist)
    pr = {x.act.key: x for x in L.prepare(hist)}
    assert pr["6"].duplicate_of == "5" and pr["6"].duplicate_kind == "probable" and "has moving time" in pr["6"].dropped
    rev = {x.act.key: x for x in L.prepare(hist, keep_separate=frozenset({"6"}))}
    assert rev["6"].dropped is None and any("kept separate" in f for f in rev["6"].flags)
    assert hist == before                                                       # inputs untouched


def test_method_c_keeps_its_3_to_5_km_rule_while_the_shared_curve_does_not_clamp():
    """exp5 coupling defect: un-clamping the shared curve removed C's 3-5 km scores. C's explicit rule restores them;
    the curve itself (used by B) still returns nothing below 5 km."""
    assert L.v_top(4.0) is None
    r = L.evaluate("C", [L.Act("x", S.at(0), "Run", 4000.0, 1200.0, 1190.0)], S.at(0))   # 4 km in 20:00 = 12 km/h
    import math
    vt5 = 5 / (12.5 / 60)
    assert r.components["short"] == pytest.approx(3000 * math.log(12 / 5) / math.log(vt5 / 5), abs=1e-9)
