"""EXPERIMENTAL rating methods for the Ratings Lab (docs/RATING_METHOD.md §A15). Pure; never stored.

Not used by the application's production Running MMR (runrank/mmr.py) or by race Elo. Inputs are plain
activity records; the synthetic generator lives separately in runrank/lab_synthetic.py.

Methods (fixed scales only; nothing is normalised against the imported cohort):
  A  CURRENT PRODUCTION method, called live (runrank.mmr; mmr-envelope-v2 since 2026-10-22: no effort cap) - comparator
  B  two-component profile: speed S (10 km-equivalent) and endurance E (longest credited distance completion)
  C  performance-by-distance profile: short / middle / marathon / ultra category scores
  D  sequential update of S and E: bounded, upward-only steps plus a time decay

Scales:
  speed points  S = 3000 × ln(7200 / T10) / ln(7200 / 1560)          (mmr-scale-v1; 10 km eq 2:00:00 = 0, 26:00 = 3000)
  endurance pts E = 3000 × ln(D_km) / ln(250)                          (1 km = 0, 250 km = 3000; synthetic anchors)
  category pts  P = 3000 × ln(v / 5 km/h) / ln(v_top(d) / 5 km/h)      (5 km/h = 0; v_top = synthetic anchor curve)

Endurance credit of one activity (exp3): credited km = recorded distance × running-pace factor [× continuity]
  running-pace factor f = clamp((1.1 L − pace) / (0.2 L), 0, 1), L = walking anchor 10:00/km × (km / 10)^0.10,
      pace = moving pace (elapsed pace when moving time is missing: never more favourable)
  continuity "label" (default): stops are shown, not subtracted; recorded distance is a fact
  continuity "scalar" (exp2): × max(0.5, 1 − (stopped − 5 %)), missing moving time -> 0.5
Long-distance performance (B option, exp3): activities over 42.5 km are scored against the synthetic anchor
  curve at their own distance (no conversion to 10 km); performance = max(speed, long-distance performance).
"""
import math
from dataclasses import dataclass, field, replace
from datetime import timedelta

from . import activity_rules, mmr

VERSION = "ratings-lab-exp5"

# ---------------------------------------------------------------- shared, predeclared parameters

COMMON = {
    "speed_types": ["Run"],
    "endurance_types": ["Run", "Trail Run"],    # ultras are often recorded as Trail Run (terrain flagged, not adjusted)
    "split_gap_s": 600,                         # next activity within 10 min of the previous end = same session
    "dup_start_s": 120,                         # exact duplicate: starts within 120 s ...
    "dup_frac": 0.02,                           # ... distance and elapsed time within 2 %, same type
    "probable_overlap": 0.80,                   # probable duplicate recording: same type, >= 80 % of BOTH durations
    "probable_dist_frac": 0.10,                 # overlap, distances within 10 %
    "walk_ref_pace_s": 600.0,                   # synthetic walking anchor: 10:00/km at 10 km ...
    "walk_dist_exp": 0.10,                      # ... relaxed by (d / 10 km)^0.10 for longer distances
    "pace_band": 0.10,                          # running-pace factor falls from 1 to 0 across anchor ±10 %
    "continuity_grace": 0.05,                   # up to 5 % stopped (lights, auto-pause) counts as continuous
    "continuity_floor": 0.50,                   # scalar mode only: completed distance keeps at least this share
    "continuity": "label",                      # "label": stops shown, recorded distance kept; "scalar": exp2 factor
    "segment_tol_s": 60,                        # an activity inside a longer same-type recording (±60 s) = segment
    "e_top_km": 250.0,
    "support_tol": mmr.PARAMS["support_tol"],   # corroboration: another independent session within 3 %
    "review_faster": 0.10,                      # flag for review: > 10 % better than the runner's next-best session
    "aging_per_day": mmr.PARAMS["aging_per_day"],
    "grace_days": mmr.PARAMS["grace_days"],
    "window_days": mmr.PARAMS["max_age_days"],
}

# SYNTHETIC ASSUMPTION, not an established elite reference: rounded times written from memory of roughly elite
# performances, never checked against a source. Used by C (all categories) and by B's bridged rule above 42.5 km.
CURVE_RANGE_KM = (5.0, 250.0)       # the curve is defined only between its first and last anchor (no clamping)
PERFORMANCE_RANGE_KM = (3.0, 250.0)  # B's ONE supported range, for performance AND endurance (exp5): Riegel
#                                      3-42.5 km, curve-bridged 42.5-250 km; activities outside are kept, not scored
TOP_ANCHORS = [(5.0, 12.5 * 60), (10.0, 26 * 60), (21.0975, 57 * 60), (42.195, 121 * 60), (50.0, 160 * 60),
               (100.0, 365 * 60), (160.9344, 660 * 60), (250.0, 1260 * 60)]           # (km, seconds)
CATEGORIES = [("short", 3.0, 12.0), ("middle", 12.0, 30.0), ("marathon", 30.0, 45.0), ("ultra", 45.0, 10000.0)]

PARAM_SPACE = {
    "A": {},
    "B": {"speed_weight": [0.75, 0.5, 0.25], "k_best": [1, 2], "walk_ref_pace_s": [570.0, 600.0, 630.0],
          "continuity": ["label", "scalar"], "long_performance": ["off", "anchor", "bridged"]},
    "C": {"aggregation": ["specialist", "balanced"], "k_best": [1, 2]},
    "D": {"speed_weight": [0.75, 0.5, 0.25], "alpha": [0.3, 0.6], "step_max": [50.0, 150.0],
          "init": ["first", "anchor"]},
}
DEFAULTS = {"A": {}, "B": {"speed_weight": 0.5, "k_best": 1, "walk_ref_pace_s": 600.0, "continuity": "label",
                         "long_performance": "off"},
            "C": {"aggregation": "specialist", "k_best": 1},
            "D": {"speed_weight": 0.5, "alpha": 0.3, "step_max": 50.0, "init": "first"}}
NAMES = {"A": "A: current production method (live; mmr-envelope-v2, labels are context only)", "B": "B: speed + endurance profile",
         "C": "C: performance-by-distance profile", "D": "D: sequential speed + endurance update"}


def check_params(method, params):
    if method not in PARAM_SPACE:
        raise ValueError("unknown method %r" % method)
    out = dict(DEFAULTS[method])
    for k, v in (params or {}).items():
        if k not in PARAM_SPACE[method]:
            raise ValueError("parameter %r is not predeclared for method %s" % (k, method))
        if v not in PARAM_SPACE[method][k]:
            raise ValueError("%s must be one of %s" % (k, PARAM_SPACE[method][k]))
        out[k] = v
    return out


# ---------------------------------------------------------------- activity records and preprocessing

@dataclass(frozen=True)
class Act:
    key: str
    start: object
    type: str
    distance_m: float
    elapsed_s: float
    moving_s: float | None = None
    gain_m: float | None = None
    effort: str = "unknown"
    hr: float | None = None
    source_id: str | None = None      # the stored source_activity_id (method A orders and dedupes by it)

    @staticmethod
    def of(d):
        if getattr(d["start"], "tzinfo", None) is None:
            raise ValueError("activity %s: start must be a timezone-aware UTC datetime" % d.get("key"))
        return Act(str(d["key"]), d["start"], d["type"], float(d["distance_m"]), float(d["elapsed_s"]),
                   d.get("moving_s"), d.get("gain_m"), d.get("effort", "unknown"), d.get("hr"), d.get("source_id"))


@dataclass
class Prep:
    act: Act
    dropped: str | None = None        # exact / probable duplicate recording (original kept in the list)
    overlap: str | None = None        # ambiguous overlap note (both activities kept and counted)
    session: int = 0
    t10: float | None = None
    speed_reason: str = ""
    endurance_km: float | None = None  # CREDITED km (distance × continuity × running-pace factor)
    endurance_reason: str = ""
    continuity: str = ""              # continuous / with stops / unknown (label, separate from distance)
    category: str | None = None
    cat_points: float | None = None
    cat_reason: str = ""
    segment_of: str | None = None     # lies inside a longer, plausible same-type recording (possible crop)
    long_points: float | None = None  # performance at its own distance (> 42.5 km only; anchor curve)
    bridged_t10: float | None = None  # exp4: one continuous performance rule for every distance >= 3 km
    invalid: str | None = None        # exp5: structurally invalid record (kept, never scored)
    duplicate_of: str | None = None   # the record scored instead of this one
    duplicate_kind: str | None = None  # "exact" | "probable"
    flags: list = field(default_factory=list)


def walk_limit(km, c):
    return c["walk_ref_pace_s"] * (km / 10.0) ** c["walk_dist_exp"]


def t_top(km):
    """Synthetic anchor top time (s) at a distance: km / v_top(km); None outside the curve's range."""
    v = v_top(km)
    return None if v is None else km / v * 3600.0


def bridged_t10(distance_m, elapsed_s):
    """None outside PERFORMANCE_RANGE_KM (no extrapolation, no clamping)."""
    km_ = distance_m / 1000.0
    if not PERFORMANCE_RANGE_KM[0] <= km_ <= PERFORMANCE_RANGE_KM[1]:
        return None
    return _bridged_t10(distance_m, elapsed_s)


def _bridged_t10(distance_m, elapsed_s):
    """exp4 performance rule. Up to 42.5 km: the production 10 km-equivalent (Riegel k = 1.06). Beyond: the time is
    first mapped to a 42.5 km time with the anchor curve's own slowdown, t × t_top(42.5) / t_top(d), then converted
    the same way. Both pieces give the same value at 42.5 km, so the rule is continuous in distance."""
    km = distance_m / 1000.0
    cut = mmr.PARAMS["max_m"] / 1000.0
    if km > cut:
        elapsed_s, distance_m = elapsed_s * t_top(cut) / t_top(km), mmr.PARAMS["max_m"]
    return mmr.ten_k_equivalent_s(distance_m, elapsed_s)


def v_top(km):
    """Synthetic anchor top speed (km/h): log-linear interpolation in ln(distance) between anchors.
    Returns None outside CURVE_RANGE_KM: the curve is never extrapolated or clamped."""
    if not CURVE_RANGE_KM[0] <= km <= CURVE_RANGE_KM[1]:
        return None
    pts = [(math.log(k), k / (s / 3600.0)) for k, s in TOP_ANCHORS]
    x = math.log(km)
    for (x0, v0), (x1, v1) in zip(pts, pts[1:]):
        if x <= x1:
            return v0 + (v1 - v0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def _interval(a):
    return a.start, a.start + timedelta(seconds=a.elapsed_s)


def _overlap_s(a, b):
    (s1, e1), (s2, e2) = _interval(a), _interval(b)
    return max(0.0, (min(e1, e2) - max(s1, s2)).total_seconds())


def _classify_pair(a, b, c):
    """'exact' | 'probable' | 'ambiguous' | None (separate sessions) for two activities, a starting first."""
    ov = _overlap_s(a, b)
    same_type = a.type == b.type
    near = abs((b.start - a.start).total_seconds()) <= c["dup_start_s"]
    rel = lambda x, y: abs(x - y) <= c["dup_frac"] * max(x, y)
    if same_type and near and rel(a.distance_m, b.distance_m) and rel(a.elapsed_s, b.elapsed_s):
        return "exact"
    if ov <= 0:
        return None
    if (same_type and ov >= c["probable_overlap"] * a.elapsed_s and ov >= c["probable_overlap"] * b.elapsed_s
            and abs(a.distance_m - b.distance_m) <= c["probable_dist_frac"] * max(a.distance_m, b.distance_m)):
        return "probable"
    return "ambiguous"


def _segment(inner, outer, c):
    """inner lies within outer (±tolerance), same type, shorter, and outer is itself plausible running."""
    (s1, e1), (s2, e2) = _interval(inner), _interval(outer)
    tol = timedelta(seconds=c["segment_tol_s"])
    if inner.type != outer.type or inner.distance_m >= outer.distance_m or s1 < s2 - tol or e1 > e2 + tol:
        return False
    return outer.elapsed_s / (outer.distance_m / 1000.0) <= walk_limit(outer.distance_m / 1000.0, c)


def _completeness(a):
    """Preferred copy of a duplicate group: has moving time, then earlier start, then smaller id (not longest)."""
    return (0 if a.moving_s else 1, a.start, mmr._key_order(a.key))


def _structural(a):
    """(problem or None, activity to use). Structurally invalid records are kept but never scored; a moving time that
    contradicts the elapsed time is ignored (flagged), the rest of the record is still used."""
    ok = lambda v: isinstance(v, (int, float)) and math.isfinite(v)
    if not ok(a.distance_m) or a.distance_m <= 0:
        return "structurally invalid: distance must be a positive number", a
    if not ok(a.elapsed_s) or a.elapsed_s <= 0:
        return "structurally invalid: elapsed time must be a positive number", a
    if a.moving_s is not None and (not ok(a.moving_s) or a.moving_s <= 0 or a.moving_s > a.elapsed_s):
        return "moving", replace(a, moving_s=None)
    return None, a


def prepare(acts, params=None, keep_separate=frozenset()):
    """Chronological, upload-order independent preprocessing shared by B, C and D.

    Exact and probable duplicate recordings collapse to one preferred copy (the others stay listed as dropped).
    Any other time overlap is AMBIGUOUS: both activities are kept and judged on their own merits, flagged for
    review, and put in the same session so they can never corroborate each other.
    """
    c = dict(COMMON, **{k: v for k, v in (params or {}).items() if k in COMMON})
    acts = sorted(acts, key=lambda a: (a.start, mmr._key_order(a.key)))
    seen, unique = set(), []
    for a in acts:                      # the same activity id uploaded twice is one activity
        if a.key not in seen:
            seen.add(a.key)
            unique.append(a)
    checked = [_structural(a) for a in unique]
    acts = [a for prob, a in checked if prob is None or prob == "moving"]
    invalid = [Prep(a, invalid=prob) for prob, a in checked if prob not in (None, "moving")]
    moving_ignored = {a.key for prob, a in checked if prob == "moving"}
    preps = [Prep(a) for a in acts]
    for p_ in preps:
        if p_.act.key in moving_ignored:
            p_.flags.append("moving time contradicts the elapsed time (non-positive or longer): ignored; "
                            "continuity unknown")
    parent = list(range(len(acts)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    kinds = {}
    for i, a in enumerate(acts):
        a_end = _interval(a)[1]
        for j in range(i + 1, len(acts)):
            b = acts[j]
            if b.start > a_end + timedelta(seconds=c["dup_start_s"]):
                break
            k = _classify_pair(a, b, c)
            if k in ("exact", "probable") and (a.key in keep_separate or b.key in keep_separate):
                for x_, y_ in ((i, b), (j, a)):
                    preps[x_].flags.append("%s duplicate of %s, kept separate by the user's review (raw import "
                                           "unchanged)" % (k, y_.key))
                k = "ambiguous"
            if k in ("exact", "probable"):
                parent[find(j)] = find(i)
                kinds[(i, j)] = k
            elif k == "ambiguous":
                preps[i].overlap = (preps[i].overlap or "") + ("ambiguous overlap with %s; " % b.key)
                preps[j].overlap = (preps[j].overlap or "") + ("ambiguous overlap with %s; " % a.key)
                for inner, outer in ((a, b), (b, a)):
                    if _segment(inner, outer, c):
                        preps[acts.index(inner)].segment_of = outer.key
    groups = {}
    for i in range(len(acts)):
        groups.setdefault(find(i), []).append(i)
    for members in groups.values():
        if len(members) < 2:
            continue
        keep = min(members, key=lambda i: _completeness(acts[i]))
        for i in members:
            if i != keep:
                kind = kinds.get((min(i, keep), max(i, keep)), "probable")
                why = ("it has moving time and this one does not" if acts[keep].moving_s and not acts[i].moving_s
                       else "it starts first" if acts[keep].start < acts[i].start else "it has the smaller id")
                preps[i].dropped = ("%s duplicate recording of %s: %s is scored because %s. Kept in the import; "
                                    "reversible with 'keep separate'" % (kind, acts[keep].key, acts[keep].key, why))
                preps[i].duplicate_of, preps[i].duplicate_kind = acts[keep].key, kind
    session, last_end = 0, None
    for p in preps:
        if p.dropped is not None:
            continue
        a = p.act
        if last_end is None or (a.start - last_end).total_seconds() > c["split_gap_s"]:
            session += 1
        p.session = session
        last_end = max(last_end, _interval(a)[1]) if last_end else _interval(a)[1]
        if p.overlap:
            p.overlap = p.overlap.strip("; ") + ": both kept and judged separately; same session"
            p.flags.append("review: %s" % p.overlap)
        _speed(p, c)
        _endurance(p, c)
        _category(p)
        if p.segment_of:
            p.flags.append("review: lies inside the longer recording %s (possible crop or segment)" % p.segment_of)
        if a.type in c["endurance_types"] and a.distance_m >= mmr.PARAMS["min_m"]:
            bt = bridged_t10(a.distance_m, a.elapsed_s)
            if bt is None:
                p.flags.append("outside the supported performance range %g-%g km: kept, no performance score"
                               % PERFORMANCE_RANGE_KM)
            else:
                p.bridged_t10 = bt
                if bt < mmr.PARAMS["floor_t10_s"]:
                    p.flags.append(EXCEPTIONAL)
        p.flags = list(dict.fromkeys(p.flags))           # each warning once
        if p.category == "ultra" or (p.cat_points is not None and a.distance_m > mmr.PARAMS["max_m"]):
            p.long_points = p.cat_points
    return sorted(preps + invalid, key=lambda x: (x.act.start, mmr._key_order(x.act.key)))


EXCEPTIONAL = ("exceptional modelled score: the converted 10 km-equivalent is faster than the 26:00 reference "
               "anchor (score above 3000). The conversion or the recording may be wrong; counted, review suggested")
SUSPICIOUS_PACE = ("suspicious recorded measurement: average pace faster than 2:30/km (24 km/h), possibly not running "
                   "(GPS, vehicle or bike); counted, review suggested")


def _speed(p, c):
    """Lab speed eligibility: production's type and distance rules, but a converted value beyond the reference anchor
    is kept and flagged instead of excluded (exp5). Production mmr.classify is unchanged."""
    a = p.act
    km = a.distance_m / 1000.0
    if a.type not in mmr.PARAMS["sports"]:
        p.speed_reason = "activity type %r is not used for speed (only Run)" % a.type
        return
    if not mmr.PARAMS["min_m"] <= a.distance_m <= mmr.PARAMS["max_m"]:
        p.speed_reason = "outside the 3-42.5 km speed range (kept; see performance and endurance)"
        return
    p.t10 = mmr.ten_k_equivalent_s(a.distance_m, a.elapsed_s)
    p.speed_reason = "10 km-equivalent %s (Riegel k 1.06, elapsed time)" % mmr.fmt(p.t10)
    if p.t10 < mmr.PARAMS["floor_t10_s"]:
        p.flags.append(EXCEPTIONAL)
    if a.elapsed_s / km < 150.0 and SUSPICIOUS_PACE not in p.flags:
        p.flags.append(SUSPICIOUS_PACE)


def _endurance(p, c):
    """Distance completion, continuity and running pace are judged separately and combined smoothly."""
    a = p.act
    km = a.distance_m / 1000.0
    if a.type not in c["endurance_types"]:
        p.endurance_reason = "type %s not used for endurance" % a.type
        return
    if not PERFORMANCE_RANGE_KM[0] <= km <= PERFORMANCE_RANGE_KM[1]:
        p.endurance_reason = ("outside the supported range %g-%g km: kept, no endurance score (never clamped)"
                              % PERFORMANCE_RANGE_KM)
        return
    has_moving = a.moving_s is not None and 0 < a.moving_s <= a.elapsed_s
    stopped = max(0.0, 1.0 - a.moving_s / a.elapsed_s) if has_moving else None
    scalar = c["continuity"] == "scalar"
    if stopped is None:
        cont = c["continuity_floor"] if scalar else 1.0
        p.continuity = "unknown (no moving time)" + (": continuity credit %.2f (the floor)" % cont if scalar else
                                                     ": recorded distance kept, continuity unverified")
        p.flags.append("continuity unknown: no moving time recorded")
    elif stopped <= c["continuity_grace"]:
        cont = 1.0
        p.continuity = "continuous (%.1f %% stopped)" % (100 * stopped)
    else:
        cont = max(c["continuity_floor"], 1.0 - (stopped - c["continuity_grace"])) if scalar else 1.0
        p.continuity = "with stops (%.1f %% stopped)%s" % (100 * stopped, ": continuity credit %.2f" % cont
                                                            if scalar else "")
        if stopped > 0.5:
            p.flags.append("review: elapsed time is more than twice the moving time (watch left running?)")
    pace = (a.moving_s if has_moving else a.elapsed_s) / km
    if pace < 150.0 and SUSPICIOUS_PACE not in p.flags:
        p.flags.append(SUSPICIOUS_PACE)          # kept and credited; no longer excluded (exp5)
    lim = walk_limit(km, c)
    f = min(1.0, max(0.0, ((1 + c["pace_band"]) * lim - pace) / (2 * c["pace_band"] * lim)))
    credited = km * cont * f
    pace_kind = "moving" if has_moving else "elapsed"
    if credited <= 0:
        p.endurance_reason = ("%s pace %s/km is at or beyond walking pace (anchor %s/km): no running-endurance "
                              "credit" % (pace_kind, mmr.fmt(pace), mmr.fmt(lim)))
        return
    p.endurance_km = credited
    p.endurance_reason = "%s km recorded%s × running pace %.2f (%s pace %s/km, anchor %s/km) = %s km" % (
        mmr._km(a.distance_m), " × continuity %.2f" % cont if scalar else "", f, pace_kind, mmr.fmt(pace),
        mmr.fmt(lim), mmr._km(credited * 1000))
    if f < 1.0:
        p.flags.append("review: pace close to walking (running-pace factor %.2f)" % f)


def _category(p):
    a = p.act
    km = a.distance_m / 1000.0
    cat = next((name for name, lo, hi in CATEGORIES if lo <= km < hi), None)
    if cat is None:
        p.cat_reason = "shorter than 3 km"
        return
    if a.type not in (["Run", "Trail Run"] if cat == "ultra" else ["Run"]):
        p.cat_reason = "type %s not used in the %s category" % (a.type, cat)
        return
    v = km / (a.elapsed_s / 3600.0)
    top = v_top(km)
    if top is None and CATEGORIES[0][1] <= km < CURVE_RANGE_KM[0]:
        # Method C's own, explicit rule (its behaviour in exp1-4): the short category starts at 3 km, below the curve's
        # first anchor, so 3-5 km runs are scored against the 5 km anchor speed. Only C uses this; B never does.
        top = v_top(CURVE_RANGE_KM[0])
        p.flags.append("method C: below the curve's first anchor (5 km), the 5 km anchor speed is used for this run")
    if top is None:
        p.cat_reason = "outside the anchor curve's range %g-%g km: kept, no category score" % CURVE_RANGE_KM
        return
    if v > top:
        p.flags.append("exceptional modelled score: faster than the synthetic anchor curve at %s km (category score "
                       "above 3000); counted, review suggested" % mmr._km(a.distance_m))
    p.category = cat
    p.cat_points = max(0.0, 3000.0 * math.log(v / 5.0) / math.log(top / 5.0))
    p.cat_reason = "%s: %.2f km/h vs anchor %.2f km/h at %s km" % (cat, v, top, mmr._km(a.distance_m))


# ---------------------------------------------------------------- scales

def speed_points(t10):
    return None if t10 is None else mmr.points(t10)


def endurance_points(km, c=COMMON):
    if km is None:
        return None
    return 3000.0 * math.log(km) / math.log(c["e_top_km"])      # km within 3-250: no clamping needed


def _age_factor(start, t, c=COMMON):
    age = (t - start).total_seconds() / 86400.0
    return 1.0 + c["aging_per_day"] * max(0.0, age - c["grace_days"])


def _window(preps, t, c=COMMON):
    lo = t - timedelta(days=c["window_days"])
    return [p for p in preps if p.dropped is None and lo < p.act.start <= t]


def _kth(values, k):
    """k-th best (largest) value; None (missing evidence) when fewer than k sessions exist.

    No fallback to the best: falling back would let a weaker second session LOWER the component.
    """
    v = sorted(values, reverse=True)
    return (v[k - 1], len(v)) if len(v) >= k else (None, len(v))


def _per_session_best(items):
    best = {}
    for sess, val, p in items:
        if sess not in best or val > best[sess][0]:
            best[sess] = (val, p)
    return list(best.values())


# ---------------------------------------------------------------- results

@dataclass
class Result:
    method: str
    combined: float | None
    components: dict
    evidence: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)


def evaluate(method, acts, t, params=None, preps=None, confirmed=frozenset(), keep_separate=frozenset(),
             excluded=frozenset()):
    """excluded: method A only. A receives excluded activities in `acts` and flags them, as production does
    (an excluded recording still marks its duplicates); methods B-D receive inputs with exclusions removed."""
    p = check_params(method, params)
    if method == "A":
        return _a(acts, t, frozenset(excluded), frozenset(keep_separate))
    preps = preps if preps is not None else prepare(acts, p, frozenset(keep_separate))
    if method == "B":
        return _b(preps, t, p, frozenset(confirmed))
    return {"C": _c, "D": _d}[method](preps, t, p)


def production_classified(acts, excluded=frozenset(), keep_separate=frozenset()):
    """{Lab key: production Classified} via mmr.classify_history, production's own preprocessing.

    One row per id (as the importer stores); the production key is the stored source id when known."""
    first = {}
    for a in sorted(acts, key=lambda a: (a.start, mmr._key_order(a.source_id or a.key))):
        first.setdefault(a.key, a)
    lab_key = {(a.source_id or a.key): a.key for a in first.values()}
    rows = [{"key": a.source_id or a.key, "start_utc": a.start, "activity_type": a.type, "distance_m": a.distance_m,
             "elapsed_s": a.elapsed_s, "elevation_gain_m": a.gain_m, "effort": a.effort, "excluded": a.key in excluded,
             "not_duplicate": a.key in keep_separate} for a in first.values()]
    out = mmr.classify_history(rows, activity_rules.possible_duplicates(mmr.duplicate_input(rows)))
    return {lab_key[c.obs.key]: c for c in out}, lab_key


def _a(acts, t, excluded=frozenset(), keep_separate=frozenset()):
    cls, lab_key = production_classified(acts, excluded, keep_separate)
    e = mmr.estimate_at(list(cls.values()), t)
    rows = {k: {"informative": c.informative, "reasons": list(c.reasons), "flags": list(c.flags),
                "duplicate_of": lab_key.get(c.obs.duplicate_of) if c.obs.duplicate_of else None}
            for k, c in cls.items()}
    return Result("A", e.mmr, {"speed": e.mmr},
                  {"coverage": e.status, "setter": lab_key[e.setter.obs.key] if e.setter else None,
                   "cap": None, "production_rows": rows})


def _evidence_states(items, c, confirmed):
    """exp4 credibility policy for performance candidates [(points, prep)], judged in time order.

    excluded (elsewhere): duplicate recordings, physical-floor implausibility -> never counted
    held:    a segment inside a longer, plausible same-type recording (two recordings claim the same time) ->
             counts for NOTHING until the user confirms it is a separate activity
    flagged: counted at once, but labelled for review: more than 10 % faster (recorded time) than the runner's best
             earlier recorded evidence in the 365 days before it. A large improvement is NOT treated as invalid
    Returns (counted [(points, prep)], held [(points, prep, reasons)], flags {key: [reasons]}).
    """
    counted, held, flags = [], [], {}
    earlier = []                                          # (start, recorded T10, session) of counted evidence
    for v, x in sorted(items, key=lambda it: (it[1].act.start, mmr._key_order(it[1].act.key))):
        if x.segment_of and x.act.key not in confirmed:
            held.append((v, x, ["inside the longer recording %s (possible crop or segment); confirm it is a "
                                "separate activity to count it" % x.segment_of]))
            continue
        lo = x.act.start - timedelta(days=c["window_days"])
        prior = [t10 for st, t10, sess in earlier if lo < st < x.act.start and sess != x.session]
        if prior and x.t10 < min(prior) * (1 - c["review_faster"]):
            flags.setdefault(x.act.key, []).append(
                "large improvement: more than 10 % faster (recorded) than this runner's best earlier evidence; "
                "counted, review suggested")
        if x.act.key in confirmed:
            flags.setdefault(x.act.key, []).append("confirmed by the user (not independent validation)")
        counted.append((v, x))
        earlier.append((x.act.start, x.t10, x.session))
    return counted, held, flags


def _b(preps, t, p, confirmed=frozenset()):
    c = dict(COMMON, **{k: v for k, v in p.items() if k in COMMON})
    win = _window(preps, t)
    bridged = p.get("long_performance") == "bridged"
    if bridged:                      # one continuous performance function for every distance from 3 km
        raw = [(speed_points(x.bridged_t10 * _age_factor(x.act.start, t)), x) for x in win if x.bridged_t10]
    else:
        raw = [(speed_points(x.t10 * _age_factor(x.act.start, t)), x) for x in win if x.t10 is not None]
    # states are judged per activity BEFORE choosing each session's best, so a held crop can never hide (stand in
    # for) a genuine activity in the same session
    counted, held_items, flags = _evidence_states(
        [(v, _with_t10(x, bridged)) for v, x in raw], c, confirmed)
    s_items = _per_session_best([(x.session, v, x) for v, x in counted])
    for x in win:                                          # record every confirmation, not only speed candidates
        if x.act.key in confirmed and "confirmed by the user (not independent validation)" not in flags.get(
                x.act.key, []):
            flags.setdefault(x.act.key, []).append("confirmed by the user (not independent validation)")
    held = {x.act.key for _, x, _ in held_items}          # a held activity counts for no component
    e_items = _per_session_best([(x.session, endurance_points(x.endurance_km / _age_factor(x.act.start, t)), x)
                                 for x in win if x.endurance_km is not None and x.act.key not in held])
    s, ns = _kth([v for v, _ in s_items], p["k_best"])
    e, ne = _kth([v for v, _ in e_items], p["k_best"])
    lp, lp_items = None, []
    if p.get("long_performance") == "anchor":
        lp_items = _per_session_best([(x.session, x.long_points / _age_factor(x.act.start, t), x)
                                      for x in win if x.long_points is not None and x.act.key not in held])
        lp, _ = _kth([v for v, _ in lp_items], p["k_best"])
    perf = max([v for v in (s, lp) if v is not None], default=None)
    comb = None if perf is None or e is None else p["speed_weight"] * perf + (1 - p["speed_weight"]) * e
    first = "performance" if bridged else "speed"
    selected = [_selected(first, s, s_items, c, t, flags), _selected("endurance", e, e_items, c, t, flags)]
    if lp is not None:
        selected.append(_selected("long_performance", lp, lp_items, c, t, flags))
    notes = []
    if ns < p["k_best"]:
        notes.append("%s needs %d independent sessions (has %d): missing evidence" % (first, p["k_best"], ns))
    if ne < p["k_best"]:
        notes.append("endurance needs %d independent sessions (has %d): missing evidence" % (p["k_best"], ne))
    if perf is None or e is None:
        notes.append("combined score needs performance and endurance evidence: %s missing (missing evidence, not "
                     "low ability)" % ("performance" if perf is None else "endurance"))
    if lp is not None:
        notes.append("performance = max(speed %s, long-distance performance %.0f): each activity's time counts in "
                     "only one of them" % ("-" if s is None else "%.0f" % s, lp))
    if any(x and x["provisional"] for x in selected):
        notes.append("provisional: at least one component rests on a single uncorroborated session (corroboration "
                     "by another session is not validation)")
    for v, x, why in held_items:
        notes.append("held, counted for no component: activity %s: %s" % (x.act.key, "; ".join(why)))
    comps = {first: s, "endurance": e}
    if p.get("long_performance") == "anchor":
        comps["long_performance"] = lp
    s_set = next((x.act.key for v, x in s_items if v == s), None)
    e_set = next((x.act.key for v, x in e_items if v == e), None)
    return Result("B", comb, comps,
                  {"speed_sessions": ns, "endurance_sessions": ne, "speed_setter": s_set, "endurance_setter": e_set,
                   "endurance_km": None if e is None else math.exp(e / 3000.0 * math.log(COMMON["e_top_km"])),
                   "selected": [x for x in selected if x],
                   "pending": [{"activity": x.act.key, "value": v, "reasons": why} for v, x, why in held_items],
                   "flags": flags}, notes)


def _with_t10(x, bridged):
    """For the bridged mode the credibility comparison uses the bridged 10 km-equivalent."""
    if not bridged or x.t10 == x.bridged_t10:
        return x
    y = Prep(**{f: getattr(x, f) for f in x.__dataclass_fields__})
    y.t10 = x.bridged_t10
    return y


def _selected(component, value, items, c, t, flags=None):
    """The evidence behind one component: activity, date, value, corroboration and data-quality concerns."""
    if value is None:
        return None
    setter = next(x for v, x in items if v == value)
    others = sorted((v for v, x in items if x.session != setter.session), reverse=True)
    if component in ("speed", "performance"):
        t_set = 7200.0 / math.exp(value / 3000.0 * math.log(7200.0 / 1560.0))
        support = [7200.0 / math.exp(v / 3000.0 * math.log(7200.0 / 1560.0)) for v in others]
        corroborated = bool(support) and support[0] <= t_set * (1 + c["support_tol"])
        detail = "10 km-equivalent %s (aged)" % mmr.fmt(t_set)
        unusual = False                   # exp4: large-improvement review flags come from _evidence_states
    elif component == "long_performance":
        corroborated = bool(others) and others[0] >= value - 3000.0 * math.log(1 + c["support_tol"]) / math.log(
            v_top(setter.act.distance_m / 1000.0) / 5.0)
        detail = "%s km in %s at its own distance (anchor curve, no 10 km conversion)" % (
            mmr._km(setter.act.distance_m), mmr.fmt(setter.act.elapsed_s))
        unusual = False
    else:
        km_set = math.exp(value / 3000.0 * math.log(c["e_top_km"]))
        support = [math.exp(v / 3000.0 * math.log(c["e_top_km"])) for v in others]
        corroborated = bool(support) and support[0] >= km_set * (1 - c["support_tol"])
        detail = "%s km credited (aged); %s" % (mmr._km(km_set * 1000), setter.continuity)
        unusual = False
    concerns = list(setter.flags) + list((flags or {}).get(setter.act.key, []))
    if not corroborated:
        concerns.append("uncorroborated: no other independent session within 3 %")
    if unusual:
        concerns.append("review: unusually fast")
    if setter.overlap:
        concerns.append("provisional: set by an activity in an ambiguous overlap (e.g. a crop of a longer recording)")
    return {"component": component, "value": value, "activity": setter.act.key, "date": setter.act.start,
            "detail": detail, "provisional": (not corroborated) or bool(setter.overlap), "concerns": concerns}


def _c(preps, t, p):
    win = _window(preps, t)
    cats = {}
    setters = {}
    for name, _, _ in CATEGORIES:
        items = _per_session_best([(x.session, x.cat_points / _age_factor(x.act.start, t), x)
                                   for x in win if x.category == name])
        v, n = _kth([val for val, _ in items], p["k_best"])
        cats[name] = v
        setters[name] = next((x.act.key for val, x in items if val == v), None) if v is not None else None
    shown = [v for v in cats.values() if v is not None]
    if not shown:
        comb = None
    elif p["aggregation"] == "specialist":
        comb = max(shown)
    else:
        comb = sum(shown) / len(shown)
    notes = ["%d of 4 categories demonstrated; missing categories are not scored as zero" % len(shown)]
    return Result("C", comb, cats, {"setters": setters, "categories_demonstrated": len(shown)}, notes)


def _d(preps, t, p):
    """Sequential: S and E move up toward new evidence by at most step_max per session, never down from an
    observation; they decay only with time since the last raising evidence (recency assumption)."""
    seq = sorted((x for x in preps if x.dropped is None and x.act.start <= t), key=lambda x: x.act.start)
    state = {"speed": None, "endurance": None}
    raised = {"speed": None, "endurance": None}
    anchor = {"speed": 1000.0, "endurance": 0.0}
    sessions = {}
    for x in seq:
        sessions.setdefault(x.session, []).append(x)
    for sid in sorted(sessions):
        group = sessions[sid]
        when = group[0].act.start
        ys = {"speed": max((speed_points(x.t10) for x in group if x.t10 is not None), default=None),
              "endurance": max((endurance_points(x.endurance_km) for x in group if x.endurance_km is not None),
                               default=None)}
        for comp, y in ys.items():
            if y is None:
                continue                                  # no evidence for this component: nothing changes
            if state[comp] is None:
                if p["init"] == "first":
                    state[comp], raised[comp] = y, when
                    continue
                state[comp], raised[comp] = anchor[comp], when
            cur = _decayed(state[comp], raised[comp], when, comp)
            if y > cur:                                   # upward only, bounded per session
                state[comp], raised[comp] = cur + min(p["alpha"] * (y - cur), p["step_max"]), when
    s = _decayed(state["speed"], raised["speed"], t, "speed")
    e = _decayed(state["endurance"], raised["endurance"], t, "endurance")
    lo = t - timedelta(days=COMMON["window_days"])
    if raised["speed"] is not None and raised["speed"] <= lo and not any(
            x.t10 is not None and lo < x.act.start <= t for x in seq):
        s = None
    if raised["endurance"] is not None and raised["endurance"] <= lo and not any(
            x.endurance_km is not None and lo < x.act.start <= t for x in seq):
        e = None
    comb = None if s is None or e is None else p["speed_weight"] * s + (1 - p["speed_weight"]) * e
    return Result("D", comb, {"speed": s, "endurance": e}, {"sessions": len(sessions)},
                  ["lowered only by time since the last raising evidence; no single observation lowers an estimate"])


def _decayed(value, since, t, comp):
    if value is None or since is None:
        return value
    f = _age_factor(since, t)
    if comp == "speed":                    # decay applied to the underlying 10 km-equivalent time
        t10 = 7200.0 / math.exp(value / 3000.0 * math.log(7200.0 / 1560.0))
        return mmr.points(t10 * f)
    km = math.exp(value / 3000.0 * math.log(COMMON["e_top_km"]))
    return endurance_points(km / f)


# ---------------------------------------------------------------- history and explanations

def history(method, acts, end, params=None, step_days=14, confirmed=frozenset(), keep_separate=frozenset(),
            excluded=frozenset()):
    preps = prepare(acts, params, frozenset(keep_separate)) if method != "A" else None
    starts = sorted({a.start for a in acts if a.start <= end and a.key not in excluded})
    if not starts:
        return []
    instants = set(starts)
    t = starts[0]
    while t < end:
        instants.add(t)
        t += timedelta(days=step_days)
    instants.add(end)
    out = []
    for t in sorted(instants):
        r = evaluate(method, acts, t, params, preps, confirmed, keep_separate, excluded)
        out.append({"at": t, "combined": r.combined, "components": r.components,
                    "activities": [a.key for a in acts if a.start == t]})
    return out


def explain_activity(method, acts, key, params=None, confirmed=frozenset(), keep_separate=frozenset(),
                     excluded=frozenset()):
    """Components at the activity's start without vs with it, and the rule outcome for that activity.

    Method A's "without" excludes the recording the way production would (it stays in the duplicate rule)."""
    a = next(x for x in acts if x.key == key)
    others = acts if method == "A" else [x for x in acts if x.key != key]
    before = evaluate(method, others, a.start, params, confirmed=confirmed, keep_separate=keep_separate,
                      excluded=frozenset(excluded) | ({key} if method == "A" else set()))
    after = evaluate(method, acts, a.start, params, confirmed=confirmed, keep_separate=keep_separate,
                     excluded=excluded)
    reasons = []
    if method == "A":
        c = production_classified(acts, excluded, keep_separate)[0][key]
        reasons.append("Production classification: %s." % ("informative" if c.informative else
                                                             "not used: " + "; ".join(c.reasons)))
    else:
        pr = next(x for x in prepare(acts, params, frozenset(keep_separate)) if x.act.key == key)
        if pr.invalid:
            reasons.append("Not used: %s (the record is kept)." % pr.invalid)
        elif pr.dropped:
            reasons.append("Not used: %s." % pr.dropped)
        else:
            if method in ("B", "D"):
                reasons.append("Speed evidence: %s." % pr.speed_reason)
                reasons.append("Endurance evidence: %s." % (pr.endurance_reason or "none"))
                if pr.continuity:
                    reasons.append("Continuity: %s." % pr.continuity)
            if pr.overlap:
                reasons.append("Overlap: %s." % pr.overlap)
            if method == "C":
                reasons.append("Category evidence: %s." % (pr.cat_reason or "none"))
    reasons.append("Effort label '%s': the recorded distance and time are used unchanged%s." % (
        a.effort, "; no method in this lab changes points because of a label"))
    deltas = {}
    for k in set(before.components) | set(after.components):
        b, c = before.components.get(k), after.components.get(k)
        deltas[k] = None if b is None or c is None else c - b
        if b is None and c is not None:
            reasons.append("%s: first evidence (%.1f)." % (k, c))
        elif deltas[k] is not None and abs(deltas[k]) > 1e-9:
            reasons.append("%s: %+.1f." % (k, deltas[k]))
        elif b is not None:
            reasons.append("%s: unchanged (this activity does not beat the evidence already counted%s)." % (
                k, " under k-th best" if method in ("B", "C") and (params or {}).get("k_best", 1) > 1 else ""))
    return {"before": before, "after": after, "deltas": deltas, "reasons": reasons}
