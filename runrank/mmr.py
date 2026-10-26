"""Running MMR: a personal ability estimate from one runner's own activity history (pure module).

Not Elo, and never coupled to race Elo (runrank.elo): no opponents, no win probabilities.
See docs/RATING_METHOD.md Part A for the meaning, equations and limitations.

Model (mmr-envelope-v2): because effort is unknown, no single run is read as maximal. Each informative
run is converted to a 10 km-equivalent (an ESTIMATE: the conversion can be wrong in either direction),
and the MMR estimate is the best such value, with older evidence degraded by a documented recency
assumption. Effort labels (easy / hard / race) are context only: they never change the score.
v1 (mmr-envelope-v1) let a later hard/race label cap older evidence at 3 % better than it; the user removed
that rule on 2026-10-22. Stored v1 calculations keep their own version string and parameters.
The evidence-coverage labels (high/medium/low) are heuristics, not calibrated statistical confidence.
"""
import math
from dataclasses import dataclass, field
from datetime import timedelta

ALGORITHM_VERSION = "mmr-envelope-v2"
SCALE_VERSION = "mmr-scale-v1"

PARAMS = {
    "sports": ["Run"],             # Trail Run (terrain) and Virtual Run (treadmill) are kept but not informative (P)
    "ref_m": 10000.0,              # ability is expressed as a 10 km-equivalent time
    "riegel_k": 1.06,              # (P) Riegel's exponent; one conversion, applied once
    "min_m": 3000.0,               # (P) supported conversion range; outside it runs are kept as
    "max_m": 42500.0,              #     distance-specific evidence only (no blind 100-mile extrapolation)
    "riegel_fit_max_s": 13800.0,   # 230 min: longer conversions are flagged (outside Riegel's fitted durations)
    "floor_t10_s": 1560.0,         # faster than 26:00 per 10 km-equivalent: implausible (GPS / wrong type)
    "grace_days": 30,              # (P) recency assumption: evidence keeps full value for 30 days,
    "aging_per_day": 0.0005,       # (P) then counts 0.05 % slower per day (1.5 % per 30 days)
    "max_age_days": 365,           # (P) older evidence is not used at all
    "declared_efforts": ["hard", "race"],   # context only (v2): may raise evidence coverage, never the score
    "support_tol": 0.03,           # (P) observations within 3 % of the estimate "support" it
    "hilly_m_per_km": 20.0,        # (P) display flag only; no elevation adjustment
    "scale": {"zero_t10_s": 7200.0, "top_t10_s": 1560.0, "top_points": 3000.0},
}
BANDS = [("3–7 km", 3000.0, 7000.0), ("7–15 km", 7000.0, 15000.0), ("15–30 km", 15000.0, 30000.0),
         ("30–42.5 km", 30000.0, 42500.0)]

INSUFFICIENT = "insufficient evidence"


def ten_k_equivalent_s(distance_m, elapsed_s, k=None):
    """Riegel: T10 = t × (10000 / d) ^ k."""
    k = PARAMS["riegel_k"] if k is None else k
    return elapsed_s * (PARAMS["ref_m"] / distance_m) ** k


def points(t10_s, scale=None):
    """Display scale (mmr-scale-v1): logarithmic in speed; 10 km in 2:00:00 = 0, in 26:00 = 3000.

    About 19.6 points per 1 % of speed. Absolute: independent of who else is imported.
    """
    s = scale or PARAMS["scale"]
    v = s["top_points"] * math.log(s["zero_t10_s"] / t10_s) / math.log(s["zero_t10_s"] / s["top_t10_s"])
    return max(0.0, v)


@dataclass(frozen=True)
class Obs:
    """One stored activity as seen by MMR (all activities, informative or not)."""
    key: str
    start_utc: object
    activity_type: str
    distance_m: float
    elapsed_s: float
    elevation_gain_m: float | None = None
    effort: str = "unknown"
    excluded: bool = False
    duplicate_of: str | None = None


@dataclass(frozen=True)
class Classified:
    obs: Obs
    informative: bool
    t10_s: float | None
    reasons: tuple
    flags: tuple

    @property
    def declared(self):
        return self.informative and self.obs.effort in PARAMS["declared_efforts"]



def duplicate_input(rows):
    """The input production gives its duplicate rule (activity_rules.possible_duplicates) for classify_history rows:
    ALL rows, so an excluded recording still marks its duplicates (they count only when not_duplicate)."""
    return ((r["key"], r["start_utc"], r["distance_m"], r["activity_type"], r["not_duplicate"]) for r in rows)


def classify_history(rows, dups, params=PARAMS):
    """Every activity of one runner classified: the production preprocessing (store.mmr_observations).

    rows: dicts with key, start_utc (UTC datetime), activity_type, distance_m, elapsed_s, elevation_gain_m,
    effort, excluded, not_duplicate. dups: {key: kept key}, activity_rules.possible_duplicates(duplicate_input(rows)).
    """
    return [classify(Obs(r["key"], r["start_utc"], r["activity_type"], r["distance_m"], r["elapsed_s"],
                         r["elevation_gain_m"], r["effort"], r["excluded"], dups.get(r["key"])), params)
            for r in sorted(rows, key=lambda r: (r["start_utc"], str(r["key"])))]


def classify(o, params=PARAMS):
    reasons, flags = [], []
    if o.activity_type not in params["sports"]:
        reasons.append("activity type %r is kept for exploration but not used (only %s)"
                       % (o.activity_type, ", ".join(params["sports"])))
    if o.distance_m < params["min_m"]:
        reasons.append("shorter than %g km: outside the supported conversion range" % (params["min_m"] / 1000))
    elif o.distance_m > params["max_m"]:
        reasons.append("longer than %g km: shown as distance-specific evidence, not converted"
                       % (params["max_m"] / 1000))
    t10 = None
    if not reasons:
        t10 = ten_k_equivalent_s(o.distance_m, o.elapsed_s, params["riegel_k"])
        if t10 < params["floor_t10_s"]:
            reasons.append("implausibly fast (10 km-equivalent under 26:00): check GPS or activity type")
            t10 = None
    if o.duplicate_of is not None:
        reasons.append("possible duplicate of activity %s" % o.duplicate_of)
    if o.excluded:
        reasons.append("excluded by annotation")
    if o.elapsed_s > params["riegel_fit_max_s"] and not reasons:
        flags.append("over 230 min: outside Riegel's fitted durations (likely understates)")
    if o.elevation_gain_m is not None and o.distance_m > 0 and \
            o.elevation_gain_m / (o.distance_m / 1000) >= params["hilly_m_per_km"]:
        flags.append("hilly (%.0f m/km climbing): not adjusted, probably understates ability"
                     % (o.elevation_gain_m / (o.distance_m / 1000)))
    if o.elevation_gain_m is None:
        flags.append("elevation not recorded")
    informative = not reasons
    if informative and o.effort in params["declared_efforts"]:
        flags.append("declared %s effort: context only; the label does not change the score" % o.effort)
    return Classified(o, informative, t10 if informative else None, tuple(reasons), tuple(flags))


@dataclass
class Estimate:
    as_of: object
    status: str                       # INSUFFICIENT or the evidence-coverage label (heuristic)
    t10_s: float | None = None
    mmr: float | None = None
    setter: Classified | None = None  # observation whose (aged) value is the estimate
    setter_aged_s: float | None = None
    cap: Classified | None = None     # declared effort whose cap binds, if any
    supporting: int = 0
    informative_window: int = 0
    informative_90d: int = 0
    best_age_days: float | None = None
    upper: str = ""
    window_keys: list = field(default_factory=list)


def aged(c, as_of, params=PARAMS):
    age = (as_of - c.obs.start_utc).total_seconds() / 86400.0
    return c.t10_s * (1.0 + params["aging_per_day"] * max(0.0, age - params["grace_days"]))


def estimate_at(classified, as_of, params=PARAMS):
    """Ability estimate from informative observations with as_of − 365 d < start ≤ as_of."""
    lo = as_of - timedelta(days=params["max_age_days"])
    win = sorted((c for c in classified if c.informative and lo < c.obs.start_utc <= as_of),
                 key=lambda c: (c.obs.start_utc, _key_order(c.obs.key)))
    if not win:
        return Estimate(as_of, INSUFFICIENT, upper="no informative run in the last 365 days")
    vals = [(aged(c, as_of, params), c) for c in win]
    est, setter = min(vals, key=lambda x: (x[0], x[1].obs.start_utc))   # labels play no part (v2)
    binding = None
    supporting = sum(1 for v, _ in vals if v <= est * (1.0 + params["support_tol"]))
    n90 = sum(1 for c in win if (as_of - c.obs.start_utc) <= timedelta(days=90))
    best_age = (as_of - setter.obs.start_utc).total_seconds() / 86400.0
    confirmed = any(c.declared and (as_of - c.obs.start_utc) <= timedelta(days=90)
                    and aged(c, as_of, params) <= est * (1.0 + params["support_tol"]) for c in win)
    if supporting >= 2 and best_age <= 180 and confirmed:
        status, upper = "high", "a recent declared hard effort agrees within 3 %"
    elif supporting >= 2 and best_age <= 180:
        status, upper = "medium", "no recent declared maximal effort confirms it; ability may be higher or the conversion may misjudge it"
    else:
        status = "low"
        upper = ("only one observation supports this level" if supporting < 2
                 else "the best evidence is more than 180 days old")
    return Estimate(as_of, status, est, points(est, params["scale"]), setter, aged(setter, as_of, params),
                    binding, supporting, len(win), n90, best_age, upper, [c.obs.key for c in win])


def _key_order(key):
    s = str(key)
    return (0, int(s), s) if s.isdigit() else (1, 0, s)


def explain(prev, cur, params=PARAMS):
    """Plain-language reasons for the change from Estimate prev to Estimate cur (same history)."""
    if cur.status == INSUFFICIENT:
        if prev is not None and prev.status != INSUFFICIENT:
            return ["No informative run remains in the last %d days: insufficient evidence (not a measured "
                    "decline)." % params["max_age_days"]]
        return ["No informative run yet: insufficient evidence."]
    s = cur.setter.obs
    if prev is None or prev.status == INSUFFICIENT:
        return ["First estimate: activity %s (%s km in %s) gives a 10 km-equivalent of %s." % (
            s.key, _km(s.distance_m), fmt(s.elapsed_s), fmt(cur.setter.t10_s))]
    out = []
    p = prev.setter.obs
    delta = cur.mmr - prev.mmr
    if s.key != p.key:
        if cur.setter.obs.start_utc > prev.as_of:
            out.append("New best evidence: activity %s (%s km in %s, 10 km-equivalent %s)." % (
                s.key, _km(s.distance_m), fmt(s.elapsed_s), fmt(cur.setter.t10_s)))
        elif p.key not in cur.window_keys:
            out.append("Activity %s is now older than %d days and no longer counts; the best remaining evidence "
                       "is %s." % (p.key, params["max_age_days"], s.key))
        else:
            out.append("Activity %s now gives the best aged value (older evidence aged past it)." % s.key)
    elif abs(delta) > 1e-9:
        out.append("Recency assumption: evidence from activity %s is %.0f days old, so it counts %.2f %% slower "
                   "than recorded." % (s.key, cur.best_age_days, 100 * (cur.setter_aged_s / cur.setter.t10_s - 1)))
    if not out and abs(delta) > 1e-9:
        out.append("The estimate changed by %+.1f points as evidence aged (recency assumption)." % delta)
    if not out:
        out.append("No change: no new evidence beats the current estimate.")
    if prev.status != cur.status:
        out.append("Evidence coverage: %s → %s (%s)." % (prev.status, cur.status, cur.upper))
    return out


def counterfactual(classified, target_key, params=PARAMS):
    """Effect of one activity: estimate at its start without it vs with it, and why."""
    c = next(x for x in classified if x.obs.key == target_key)
    t = c.obs.start_utc
    without = estimate_at([x for x in classified if x.obs.key != target_key], t, params)
    with_ = estimate_at(classified, t, params)
    if not c.informative:
        why = "Not informative (%s), so it cannot change MMR." % "; ".join(c.reasons)
    elif with_.mmr is not None and (without.mmr is None or with_.mmr > without.mmr + 1e-9):
        why = "It is better evidence than anything before it, so it raised the estimate."
    else:
        why = ("Evidence that does not beat the current estimate: an easier or slower run is not read as "
               "lower ability, so MMR did not change%s." % (
                   "; its '%s' label is context only and never changes the score" % c.obs.effort
                   if c.obs.effort in params["declared_efforts"] else ""))
    return c, without, with_, why


def history(classified, end, step_days=7, params=PARAMS):
    """Deterministic reconstruction: the estimate at every activity start and weekly in between, up to end."""
    starts = sorted({c.obs.start_utc for c in classified if c.obs.start_utc <= end})
    if not starts:
        return []
    instants = set(starts)
    t = starts[0]
    while t < end:
        instants.add(t)
        t += timedelta(days=step_days)
    instants.add(end)
    out, prev = [], None
    for t in sorted(instants):
        cur = estimate_at(classified, t, params)
        keys = [c.obs.key for c in classified if c.obs.start_utc == t]
        out.append({"at": t, "estimate": cur, "activities": sorted(keys, key=_key_order),
                    "explanation": explain(prev, cur, params), "changed": prev is None or
                    (prev.mmr is None) != (cur.mmr is None) or
                    (cur.mmr is not None and abs(cur.mmr - prev.mmr) > 1e-9) or prev.status != cur.status})
        prev = cur
    return out


def bands(classified, as_of, params=PARAMS):
    """Distance-specific evidence: best raw 10 km-equivalent per band, plus longer and shorter runs."""
    lo = as_of - timedelta(days=params["max_age_days"])
    recent = [c for c in classified if lo < c.obs.start_utc <= as_of]
    out = []
    for label, a, b in BANDS:
        cs = [c for c in recent if c.informative and a <= c.obs.distance_m < b + (1 if b == params["max_m"] else 0)]
        best = min(cs, key=lambda c: c.t10_s) if cs else None
        out.append({"label": label, "converted": True, "count": len(cs),
                    "best_key": best.obs.key if best else None, "best_t10_s": best.t10_s if best else None,
                    "best_pace_s_per_km": best.obs.elapsed_s / best.obs.distance_m * 1000 if best else None})
    for label, test in (("over 42.5 km (ultra; not converted)", lambda d: d > params["max_m"]),
                        ("under 3 km (not converted)", lambda d: d < params["min_m"])):
        cs = [c for c in recent if c.obs.activity_type in params["sports"] and test(c.obs.distance_m)
              and not c.obs.excluded and c.obs.duplicate_of is None]
        fast = min(cs, key=lambda c: c.obs.elapsed_s / c.obs.distance_m) if cs else None
        out.append({"label": label, "converted": False, "count": len(cs),
                    "best_key": fast.obs.key if fast else None, "best_t10_s": None,
                    "best_pace_s_per_km": fast.obs.elapsed_s / fast.obs.distance_m * 1000 if fast else None,
                    "longest_m": max(c.obs.distance_m for c in cs) if cs else None})
    return out


def fmt(seconds):
    t = int(round(seconds))
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return "%d:%02d:%02d" % (h, m, s) if h else "%d:%02d" % (m, s)


def _km(m):
    return ("%.2f" % (m / 1000)).rstrip("0").rstrip(".")
