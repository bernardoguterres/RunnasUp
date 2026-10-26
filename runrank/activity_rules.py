"""Rating-independent rules for stored activities (pure; no I/O).

Moved unchanged from the archived legacy 5K modules (runrank.rating, runrank.rating_exp) on 2026-10-25, because
Running MMR, the Ratings Lab and the MMR overview use them: the possible-duplicate rule and the training-volume
summary. Neither is a rating formula.
"""
from datetime import timedelta

DUP_MAX_START_GAP_S = 120    # possible-duplicate rule
DUP_MAX_DIST_FRAC = 0.02


def possible_duplicates(activities):
    """activities: iterable of (key, start_utc, distance_m, activity_type, not_duplicate).

    Two same-type activities starting within 120 s with distances within 2 % are
    treated as one effort recorded twice. The earliest start (then the smaller
    key) is kept; chains (B copies A, C copies B) collapse onto the kept one.
    Returns {flagged_key: kept_key}. An activity annotated not_duplicate is
    never flagged.
    """
    acts = sorted(activities, key=lambda a: (a[1], _key_order(a[0])))
    flagged = {}
    max_gap = timedelta(seconds=DUP_MAX_START_GAP_S)
    for i, (key, start, dist, typ, not_dup) in enumerate(acts):
        if not_dup:
            continue
        j = i                     # only earlier activities within the start gap can match
        while j > 0 and start - acts[j - 1][1] <= max_gap:
            j -= 1
        for kkey, kstart, kdist, ktyp, _ in acts[j:i]:
            if ktyp != typ:
                continue
            gap = (start - kstart).total_seconds()
            if gap <= DUP_MAX_START_GAP_S and abs(dist - kdist) <= DUP_MAX_DIST_FRAC * max(dist, kdist):
                flagged[key] = flagged.get(kkey, kkey)
                break
    return flagged


def _key_order(key):
    s = str(key)
    return (0, int(s), s) if s.isdigit() else (1, 0, s)


def training_volume(runs, as_of, days=28, weeks=12):
    """SEPARATE from any score. runs: iterable of (start_utc, distance_m) for activity type Run.

    Returns distance and count in the last `days`, and how many of the last
    `weeks` 7-day blocks contain at least one run. Units: km, runs, weeks.
    """
    runs = [(s, d) for s, d in runs if s <= as_of]
    recent = [d for s, d in runs if as_of - timedelta(days=days) < s]
    active = sum(1 for w in range(weeks)
                 if any(as_of - timedelta(days=7 * (w + 1)) < s <= as_of - timedelta(days=7 * w)
                        for s, _ in runs))
    return {"km_last_%dd" % days: round(sum(recent) / 1000, 2), "runs_last_%dd" % days: len(recent),
            "active_weeks_of_last_%d" % weeks: active}
