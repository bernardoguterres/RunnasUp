"""SYNTHETIC activity histories for the Ratings Lab. Generator only: no rating logic lives here.

Every runner and activity is invented. Records are plain dicts (key, start, type, distance_m, elapsed_s,
moving_s, gain_m, effort, hr) so the rating methods (runrank/lab_methods.py) stay independent of how
data is produced. Generation is deterministic for a given seed.

Generator assumptions (NOT evidence about real runners): each runner has an invented 10 km time and a
personal distance exponent; easy runs are 1.15-1.35 x race pace, tempo 1.05-1.10, races 0.99-1.01;
ordinary runs carry 0-3 % stopped time; ultras carry aid-station stops.
"""
import random
from datetime import datetime, timedelta, timezone

T0 = datetime(2025, 1, 1, 7, tzinfo=timezone.utc)


def at(day, hours=0.0):
    return T0 + timedelta(days=day, hours=hours)


def act(key, day, km, elapsed, moving=None, typ="Run", effort="unknown", hour=0.0, gain=None, hr=None):
    return {"key": str(key), "start": at(day, hour), "type": typ, "distance_m": km * 1000.0, "elapsed_s": float(elapsed),
            "moving_s": None if moving is None else float(moving), "gain_m": gain, "effort": effort, "hr": hr}


def _race_time(t10, km, k):
    return t10 * (km / 10.0) ** k


# ---------------------------------------------------------------- required test cases 1-14 (hand-designed)

def base_5k():
    """Longest demonstrated run 5 km (four runs, 25:00-27:00)."""
    return [act(1, 0, 5, 1500, 1490), act(2, 7, 5, 1560, 1550), act(3, 14, 5, 1620, 1610), act(4, 21, 5, 1500, 1495)]


EIGHT_S = 2760.0    # 8 km in 46:00 (5:45/km)


def cases():
    """{id: (description, history, key of the examined activity or None, as-of day)}"""
    c = {}
    c["01"] = ("longest run 5 km, then a continuous 8 km at a slower pace (5:45/km)",
               base_5k() + [act(5, 28, 8, EIGHT_S, EIGHT_S - 20)], "5", 28)
    for lab in ("easy", "hard", "unknown"):
        c["02" + lab[0]] = ("the identical 8 km labelled %s" % lab,
                            base_5k() + [act(5, 28, 8, EIGHT_S, EIGHT_S - 20, effort=lab)], "5", 28)
    c["03"] = ("the same 8 km later, faster (38:40)",
               base_5k() + [act(5, 28, 8, EIGHT_S, EIGHT_S - 20), act(6, 35, 8, 2320, 2310)], "6", 35)
    c["04"] = ("12 km with 41 min stopped (moving 1:09:00, elapsed 1:50:00)",
               base_5k() + [act(5, 28, 12, 6600, 4140)], "5", 28)
    c["05"] = ("slow continuous 21 km at 7:30/km (moving = elapsed - 1 min)",
               base_5k() + [act(5, 28, 21.0975, 21.0975 * 450, 21.0975 * 450 - 60)], "5", 28)
    c["06"] = ("fast 5 km specialist (5 km races 17:30, nothing over 10 km)", runner("speed", 1), None, 364)
    c["07"] = ("marathon specialist", runner("marathon", 1), None, 364)
    c["08"] = ("ultra specialist with 100 km and 100 mile races", runner("ultra", 1), None, 364)
    c["09"] = ("improving beginner (5 km longest, then 8 km, then more)", runner("beginner", 1), None, 364)
    c["10"] = ("established runner doing only easy training after a strong 10 km",
               [act(1, 0, 10, 2700, 2690)] + [act(10 + i, 2 + i * 2, 8, 8 * 340, 8 * 340 - 15) for i in range(40)],
               None, 82)
    c["11"] = ("returning after 200 days of inactivity", [act(1, 0, 10, 2700, 2690), act(2, 20, 15, 4500, 4480)] +
               [act(10 + i, 240 + i * 3, 8, 8 * 360, 8 * 360 - 20) for i in range(10)], None, 270)
    c["12d"] = ("exact duplicate upload of the 8 km", base_5k() + [act(5, 28, 8, EIGHT_S, EIGHT_S - 20),
                                                                  act(6, 28, 8, EIGHT_S, EIGHT_S - 20)], "6", 28)
    c["12o"] = ("overlapping second recording (watch + phone, starts 3 min later)",
                base_5k() + [act(5, 28, 8, EIGHT_S, EIGHT_S - 20), act(6, 28, 7.6, EIGHT_S - 180, EIGHT_S - 200,
                                                                         hour=0.05)], "6", 28)
    c["12s"] = ("one 10 km session uploaded as two 5 km parts (2 min apart)",
                base_5k() + [act(5, 28, 5, 1650, 1640), act(6, 28, 5, 1650, 1640, hour=1650 / 3600 + 120 / 3600)],
                "6", 28)
    c["13"] = ("a single implausibly fast observation (10 km in 20:00)",
               base_5k() + [act(5, 28, 10, 1200, 1195)], "5", 28)
    c["14"] = ("60 repeated ordinary 5 km runs with distance noise (sd 2 %)", noisy_repeats(1), None, 200)
    # exp2 evidence handling: overlaps (same and different type), stops, missing moving time
    race10 = act(20, 28, 10, 2400, 2395)                                    # 10 km race 40:00 at 07:00
    c["15a"] = ("same-type probable duplicate: watch 8 km (moving time) and phone 8.3 km starting 1 min later "
                "without moving time", base_5k() + [act(5, 28, 8, EIGHT_S, EIGHT_S - 20),
                                                   act(6, 28, 8.3, EIGHT_S - 40, None, hour=1 / 60)], "6", 28)
    c["15b"] = ("same-type ambiguous overlap: 10 km race and a 6 km crop of it with the same start",
                base_5k() + [race10, act(21, 28, 6, 1380, 1375)], "21", 28)
    c["15c"] = ("different-type overlap: a 3 h Walk started 1 h before the 10 km race",
                base_5k() + [race10, act(22, 28, 5, 10800, 9000, typ="Walk", hour=-1)], "22", 28)
    c["15d"] = ("watch left running: a 12 km Run with 72 h elapsed (1 h moving) overlapping later runs",
                base_5k() + [act(23, 27, 12, 72 * 3600, 3600), race10], "23", 28)
    for share in (0.049, 0.050, 0.051, 0.149, 0.150, 0.151, 0.549, 0.550, 0.551):
        el = 26 * 3600.0
        c["16-%04.1f" % (100 * share)] = ("100 mile in 26:00:00 with %.1f %% stopped" % (100 * share),
                                          base_5k() + [act(30, 28, 160.9344, el, el * (1 - share), typ="Trail Run")],
                                          "30", 28)
    c["17a"] = ("100 km ultra, 8 % aid-station stops", base_5k() + [act(31, 28, 100, 11 * 3600, 11 * 3600 * 0.92,
                                                                         typ="Trail Run")], "31", 28)
    c["17b"] = ("24 h race: 160 km with 20 % rest", base_5k() + [act(32, 28, 160, 24 * 3600, 24 * 3600 * 0.80,
                                                                        typ="Trail Run")], "32", 28)
    c["17c"] = ("the same 24 h race without moving time", base_5k() + [act(32, 28, 160, 24 * 3600, None,
                                                                              typ="Trail Run")], "32", 28)
    return c


def noisy_repeats(seed, n=60):
    rng = random.Random(seed)
    return [act(i, i * 3, 5 * (1 + rng.gauss(0, 0.02)), 1560, 1545) for i in range(n)]


# ---------------------------------------------------------------- held-out scenarios (reserved until after selection)

def held_out():
    h = {}
    h["H1"] = ("every run recorded 3 % long by GPS", [dict(a, distance_m=a["distance_m"] * 1.03) for a in base_5k()]
               + [act(5, 28, 8.24, EIGHT_S, EIGHT_S - 20)], base_5k() + [act(5, 28, 8, EIGHT_S, EIGHT_S - 20)], 28)
    h["H2"] = ("downhill point-to-point 10 km, 4 % assisted, no descent recorded",
               [act(1, 0, 10, 2700, 2690), act(2, 10, 10, 2592, 2585)], [act(1, 0, 10, 2700, 2690)], 10)
    h["H3"] = ("fast 3 km segment saved separately from a 10 km tempo",
               [act(1, 0, 10, 2800, 2790), act(2, 0.01, 3, 720, 718)], [act(1, 0, 10, 2800, 2790)], 1)
    h["H4"] = ("slow continuous jogger: 15 km at 9:45/km", [act(1, 0, 5, 2700, 2690), act(2, 14, 15, 15 * 585,
                                                                                       15 * 585 - 30)],
               [act(1, 0, 5, 2700, 2690)], 14)
    h["H5"] = ("treadmill-only runner (Virtual Run)", [act(i, i * 4, 10, 3000, 3000, typ="Virtual Run")
                                                      for i in range(10)], [], 40)
    h["H6"] = ("100 mile ultra with 20 % aid-station stops", runner_ultra_long_stops(), runner("ultra", 1), 364)
    h["H7"] = ("same history uploaded shuffled and twice", None, None, 364)
    return h


# ---------------------------------------------------------------- fictional runners for the Lab

RUNNERS = {
    # key: (label, true 10 km (s) start->end, personal exponent, runs/week, km range, race plan)
    "beginner": ("Beginner: 5 km longest, then 8 km", (3600, 3200), 1.08, 3, (3, 5), []),
    "speed": ("Fast short-distance specialist", (2190, 2190), 1.10, 5, (4, 10), [(40, 5), (100, 5), (180, 5),
                                                                               (260, 5), (330, 10)]),
    "steady": ("Steady recreational runner", (3000, 3000), 1.06, 3.5, (6, 12), [(150, 10), (300, 10)]),
    "marathon": ("Marathon specialist", (2460, 2460), 1.03, 5, (10, 32), [(90, 21.0975), (200, 42.195),
                                                                        (320, 42.195)]),
    "ultra": ("Ultra specialist", (2820, 2820), 1.02, 4, (12, 38), [(110, 50), (200, 100), (300, 160.9344)]),
    "improving": ("Improving runner", (3600, 2880), 1.06, 4, (5, 12), [(m * 30 + 20, 5 if m % 2 else 10)
                                                                     for m in range(12)]),
    "easy": ("Runner with many easy activities", (2700, 2700), 1.06, 6, (6, 12), []),
}


def runner(key, seed=1):
    """Deterministic synthetic history for one fictional runner (one year from 2025-01-01)."""
    label, (t_start, t_end), k, per_week, (dmin, dmax), races = RUNNERS[key]
    rng = random.Random(_seed(key, seed))
    out, n, day = [], 0, 0.0
    base = 900000 + list(RUNNERS).index(key) * 10000
    while True:
        day += rng.expovariate(per_week / 7.0)
        if day >= 365:
            break
        if key == "beginner":
            km = round(rng.uniform(3, 5), 2) if day < 70 else round(rng.uniform(4, 8), 2)
            if 70 <= day < 72 and not any(r["distance_m"] >= 7999 for r in out):
                km = 8.0
        else:
            km = round(rng.uniform(dmin, dmax), 2)
        factor = rng.uniform(1.15, 1.35) if (key == "easy" or rng.random() < 0.8) else rng.uniform(1.05, 1.10)
        out.append(_mk(base + n, day, km, factor, key, rng, t_start, t_end, k, None))
        n += 1
    for rday, km in races:
        out.append(_mk(base + n, rday + 0.1, km, rng.uniform(0.99, 1.01), key, rng, t_start, t_end, k, "race"))
        n += 1
    return sorted(out, key=lambda a: a["start"])


def _seed(key, seed):
    return sum(ord(ch) * (i + 1) for i, ch in enumerate(key)) * 1000 + seed


def _mk(aid, day, km, factor, key, rng, t_start, t_end, k, effort):
    t10 = t_start + (t_end - t_start) * min(1.0, day / 365.0)
    elapsed = _race_time(t10, km, k) * factor
    if key == "ultra" and km > 45:
        elapsed *= 1.0 + 0.0012 * (km - 45)          # generator assumption: extra slowdown in long ultras
        stopped = rng.uniform(0.05, 0.10) if km < 150 else rng.uniform(0.08, 0.12)
    else:
        stopped = rng.uniform(0.0, 0.03)
    typ = "Trail Run" if key == "ultra" and (km > 45 or rng.random() < 0.3) else "Run"
    gain = round(km * (rng.uniform(20, 45) if typ == "Trail Run" else rng.uniform(0, 10)))
    hr = None if rng.random() < 0.25 else int(rng.uniform(130, 178))
    return act(aid, day, km, round(elapsed), round(elapsed * (1 - stopped)), typ, effort or "unknown", 0.0, gain, hr)


def runner_ultra_long_stops():
    """H6: the ultra runner, but the 100 mile race carries 20 % stopped time."""
    out = runner("ultra", 1)
    for a in out:
        if a["distance_m"] > 150000:
            a["moving_s"] = a["elapsed_s"] * 0.80
    return out


# ---------------------------------------------------------------- exp3: long-distance improvement (matched)

LONG_MATCHED = {"20 km": (20.0, 2 * 3600 + 10 * 60), "marathon": (42.195, 4 * 3600 + 10 * 60),
                "50 km": (50.0, 5 * 3600 + 30 * 60), "100 km": (100.0, 12 * 3600)}


def long_matched(name, faster=0.95, repeats=0):
    """Only performances at one long distance: four runs at time T (monthly), then the same distance at
    faster × T. Same type, stop share (2 %), elevation and effort label throughout; `repeats` more copies of the
    improved run follow weekly (to check that repetition earns nothing)."""
    km, t = LONG_MATCHED[name]
    runs = [act("%s-%d" % (name, i), i * 30, km, t, t * 0.98) for i in range(4)]
    better = [act("%s-new" % name, 120, km, t * faster, t * faster * 0.98)]
    better += [act("%s-rep%d" % (name, i), 127 + 7 * i, km, t * faster, t * faster * 0.98) for i in range(repeats)]
    return runs, runs + better
