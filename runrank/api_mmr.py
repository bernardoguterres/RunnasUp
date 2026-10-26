"""Running MMR routes (primary rating). Contract: web/src/api/types.ts; method: docs/RATING_METHOD.md Part A.

Every value comes from runrank.mmr over runrank.store.mmr_observations (all stored activities of one
runner). Nothing here reads race tables or race Elo, and race Elo never reads these values.
"""
import json
import pathlib
from datetime import datetime, timedelta, timezone

from starlette.responses import JSONResponse
from starlette.routing import Route

from . import activity_rules, mmr, store

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "examples" / "synthetic" / "mmr"

MEANING = [
    "Running MMR estimates your current running ability from your own activities. No opponents or races needed.",
    "Ability is expressed as a 10 km-equivalent time (Riegel conversion, k = 1.06), using Run activities of 3 to "
    "42.5 km only. Longer and shorter runs are kept and shown as distance-specific evidence.",
    "Effort is usually unknown, so no single run is read as your maximum and an easier run never lowers MMR. The "
    "estimate is your best converted evidence in the last 365 days; the conversion is itself an estimate.",
    "Older evidence counts gradually slower (a documented recency assumption: 1.5 % per 30 days after 30 days).",
    "Effort labels (easy, hard, race) are context only: changing a label never changes MMR (mmr-envelope-v2; the "
    "v1 rule that let a hard/race label lower older evidence was removed on 2026-10-22). A recent hard or race "
    "label that agrees with the estimate can raise the evidence-coverage label from medium to high.",
    "Points: 3000 × ln(7200 s / T10) / ln(7200 / 1560). 10 km in 2:00:00 = 0, 1:00:00 ≈ 1360, 50:00 ≈ 1717, "
    "40:00 ≈ 2155, 30:00 ≈ 2719, 26:00 = 3000. A fixed mapping (about 20 points per 1 % of speed), never rescaled "
    "by who else is imported; not a population ranking, not a validated ability scale, not Elo win probabilities.",
]
LIMITATIONS = [
    "A runner who never runs hard is usually under-estimated; evidence coverage (a heuristic label) shows how "
    "thin the evidence is. Noisy GPS distance, downhill courses and short fast segments can over-estimate.",
    "Runs over 42.5 km (ultras) and under 3 km do not contribute to MMR at all; they are shown as distance "
    "evidence only.",
    "Riegel's single exponent fits some runners better than others; endurance types convert optimistically "
    "from long runs and speed types from short ones.",
    "No elevation adjustment: summary ascent does not describe the route. Hilly runs are flagged; net-downhill "
    "courses cannot be detected and may overstate.",
    "Heart rate and perceived exertion are displayed only. GPS errors move the estimate about one-for-one.",
    "The recency rate, grace period and 365-day window are assumptions, not measured detraining.",
    "Not validated against real race results; the points scale is a convention.",
]


def routes(db, demo_mode, ApiError, read_date, end_of_day, get_participant, participant_shape):
    def pid_of(request):
        try:
            return int(request.path_params["pid"])
        except (KeyError, ValueError):
            raise ApiError(400, "bad_request", "runner id must be an integer", "pid")

    def obs_of(con, pid):
        return store.mmr_observations(con, pid)

    def default_as_of(obs):
        """Demo: the latest activity; otherwise now (UTC)."""
        now = datetime.now(timezone.utc).replace(microsecond=0)
        if demo_mode and obs:
            return max(c.obs.start_utc for c in obs)
        return now

    def as_of_of(q, obs):
        day = read_date(q, "as_of")
        return end_of_day(day) if day else default_as_of(obs)

    def cshape(c):
        o = c.obs
        return {"activity_id": o.key, "start_utc": store.iso(o.start_utc), "activity_type": o.activity_type,
                "distance_m": o.distance_m, "elapsed_s": o.elapsed_s, "elevation_gain_m": o.elevation_gain_m,
                "effort": o.effort, "informative": c.informative, "t10_s": c.t10_s,
                "points": mmr.points(c.t10_s) if c.t10_s is not None else None,
                "reasons": list(c.reasons), "flags": list(c.flags)}

    def eshape(e):
        return {"as_of_utc": store.iso(e.as_of), "status": e.status, "mmr": e.mmr, "t10_s": e.t10_s,
                "t10_display": mmr.fmt(e.t10_s) if e.t10_s is not None else None,
                "setter": cshape(e.setter) if e.setter else None, "setter_aged_t10_s": e.setter_aged_s,
                "cap": cshape(e.cap) if e.cap else None, "supporting": e.supporting,
                "informative_365d": e.informative_window, "informative_90d": e.informative_90d,
                "best_evidence_age_days": e.best_age_days, "upper_note": e.upper}

    def quality(con, pid, obs):
        acts = store.activities(con, pid)
        n = len(acts)
        types = {}
        for a in acts:
            types[a["activity_type"]] = types.get(a["activity_type"], 0) + 1
        rej = con.execute("SELECT COALESCE(SUM(rejected), 0), COALESCE(SUM(rows_total), 0) FROM imports WHERE "
                          "participant_id = ? AND status = 'completed'", (pid,)).fetchone()
        missing = lambda f: sum(1 for a in acts if a[f] is None)
        reasons = {}
        for c in obs:
            if not c.informative:
                k = c.reasons[0].split(":")[0]
                reasons[k] = reasons.get(k, 0) + 1
        return {"activities": n, "informative": sum(c.informative for c in obs),
                "first_utc": acts[0]["start_utc"] if acts else None, "last_utc": acts[-1]["start_utc"] if acts else None,
                "by_type": [{"type": k, "count": v} for k, v in sorted(types.items(), key=lambda x: -x[1])],
                "not_informative": [{"reason": k, "count": v} for k, v in sorted(reasons.items(), key=lambda x: -x[1])],
                "missing": {"heart_rate": missing("avg_hr"), "elevation": missing("elevation_gain_m"),
                            "moving_time": missing("moving_s"), "perceived_exertion": missing("perceived_exertion")},
                "declared_efforts": sum(1 for c in obs if c.obs.effort in mmr.PARAMS["declared_efforts"]),
                "hilly": sum(1 for c in obs if any(f.startswith("hilly") for f in c.flags)),
                "rows_imported": rej[1], "rows_rejected": rej[0]}

    async def overview(request):
        pid = pid_of(request)
        with db() as con:
            p = get_participant(con, pid)
            obs = obs_of(con, pid)
            as_of = as_of_of(request.query_params, obs)
            e = mmr.estimate_at(obs, as_of)
            hist = [h for h in mmr.history(obs, as_of) if h["changed"]]
            snaps = [dict(r) for r in con.execute(
                "SELECT computed_utc, trigger, as_of_utc, status, mmr, t10_s, setter_activity_id, activities, "
                "algorithm_version, scale_version FROM mmr_runs WHERE participant_id = ? ORDER BY id DESC LIMIT 20",
                (pid,))]
            return JSONResponse({
                "participant": participant_shape(con, p), "version": mmr.ALGORITHM_VERSION,
                "scale_version": mmr.SCALE_VERSION, "estimate": eshape(e), "quality": quality(con, pid, obs),
                "bands": mmr.bands(obs, as_of),
                "volume": activity_rules.training_volume([(c.obs.start_utc, c.obs.distance_m) for c in obs
                                                      if c.obs.activity_type == "Run"], as_of),
                "recent_changes": [{"at_utc": store.iso(h["at"]), "mmr": h["estimate"].mmr,
                                    "status": h["estimate"].status, "activities": h["activities"],
                                    "explanation": h["explanation"]} for h in hist[-8:]][::-1],
                "snapshots": snaps})

    async def history(request):
        pid = pid_of(request)
        with db() as con:
            get_participant(con, pid)
            obs = obs_of(con, pid)
            as_of = as_of_of(request.query_params, obs)
            return JSONResponse({"version": mmr.ALGORITHM_VERSION, "scale_version": mmr.SCALE_VERSION,
                                 "reconstructed": True, "points": [
                {"at_utc": store.iso(h["at"]), "mmr": h["estimate"].mmr, "t10_s": h["estimate"].t10_s,
                 "status": h["estimate"].status, "setter_activity_id": h["estimate"].setter.obs.key
                 if h["estimate"].setter else None, "activities": h["activities"], "changed": h["changed"],
                 "explanation": h["explanation"]} for h in mmr.history(obs, as_of)]})

    async def observations(request):
        pid = pid_of(request)
        with db() as con:
            get_participant(con, pid)
            return JSONResponse([cshape(c) for c in obs_of(con, pid)][::-1])

    async def effect(request):
        pid = pid_of(request)
        aid = request.path_params["aid"]
        with db() as con:
            get_participant(con, pid)
            obs = obs_of(con, pid)
            if aid not in {c.obs.key for c in obs}:
                raise ApiError(404, "not_found", "no activity %s for this runner" % aid)
            c, without, with_, why = mmr.counterfactual(obs, aid)
            delta = None if with_.mmr is None or without.mmr is None else with_.mmr - without.mmr
            return JSONResponse({"activity": cshape(c), "without": eshape(without), "with": eshape(with_),
                                 "delta": delta, "explanation": why})

    async def explain(request):
        pid = pid_of(request)
        q = request.query_params
        with db() as con:
            get_participant(con, pid)
            obs = obs_of(con, pid)
            try:
                at = store.parse_iso(q.get("at", ""))
            except ValueError:
                raise ApiError(400, "bad_request", "at must be an instant YYYY-MM-DDTHH:MM:SSZ", "at")
            hist = mmr.history(obs, at)
            idx = next((i for i, h in enumerate(hist) if h["at"] == at), None)
            if idx is None:
                raise ApiError(404, "not_found", "no history point at that instant")
            prev = hist[idx - 1]["estimate"] if idx else None
            cur = hist[idx]["estimate"]
            return JSONResponse({"at_utc": store.iso(at), "before": eshape(prev) if prev else None,
                                 "after": eshape(cur), "delta": None if prev is None or prev.mmr is None or
                                 cur.mmr is None else cur.mmr - prev.mmr,
                                 "activities": hist[idx]["activities"], "explanation": hist[idx]["explanation"]})

    async def comparison(request):
        q = request.query_params
        day = read_date(q, "as_of")
        with db() as con:
            rows = []
            for p in store.participants(con):
                obs = obs_of(con, p["id"])
                as_of = end_of_day(day) if day else default_as_of(obs)
                e = mmr.estimate_at(obs, as_of)
                rows.append({"participant": {"id": p["id"], "label": p["label"], "data_kind": p["data_kind"]},
                             "estimate": eshape(e), "rank": None})
            order = {"real": 0, "synthetic": 1, "unlabelled": 2}
            rows.sort(key=lambda r: (order[r["participant"]["data_kind"]], r["estimate"]["mmr"] is None,
                                     -(r["estimate"]["mmr"] or 0), r["participant"]["label"]))
            for kind in order:
                rank, prev = 0, None
                ranked = [r for r in rows if r["participant"]["data_kind"] == kind
                          and r["estimate"]["status"] in ("medium", "high")]
                for i, r in enumerate(ranked, start=1):
                    if prev is None or r["estimate"]["mmr"] != prev:
                        rank = i
                    r["rank"], prev = rank, r["estimate"]["mmr"]
            return JSONResponse({"version": mmr.ALGORITHM_VERSION, "scale_version": mmr.SCALE_VERSION,
                                 "as_of": day.isoformat() if day else None,
                                 "ranking_rule": "ranked only with medium or high evidence coverage, within the same data "
                                                 "kind; absolute scale, so adding runners never changes anyone's MMR",
                                 "rows": rows})

    async def method(request):
        return JSONResponse({"version": mmr.ALGORITHM_VERSION, "scale_version": mmr.SCALE_VERSION,
                             "params": mmr.PARAMS, "meaning": MEANING, "limitations": LIMITATIONS,
                             "scale_examples": [{"t10_s": t, "t10_display": mmr.fmt(t), "mmr": mmr.points(t)}
                                                for t in (7200, 4800, 3600, 3000, 2400, 1800, 1560)]})

    async def demo_histories(request):
        if not demo_mode:
            raise ApiError(409, "demo_only", "synthetic histories can only be loaded into the separate demo "
                                             "database: start the app with ./run.sh demo")
        manifest = json.loads((FIXTURES / "manifest.json").read_text())
        msgs = []
        with db() as con:
            for r in manifest["runners"]:
                if con.execute("SELECT 1 FROM participants WHERE label = ?", (r["label"],)).fetchone():
                    msgs.append("%s already exists; skipped." % r["label"])
                    continue
                pid = store.create_participant(con, r["label"], False, "synthetic")
                store.import_file(con, pid, r["file"], (FIXTURES / r["file"]).read_bytes())
                ids = {a["source_activity_id"]: a["id"] for a in store.activities(con, pid)}
                for sid in r["declared_race_ids"]:     # synthetic declared race efforts (manifest)
                    store.set_annotation(con, ids[sid], False, None, False, "race")
                msgs.append("%s: %d activities, %d declared race efforts." % (
                    r["label"], len(ids), len(r["declared_race_ids"])))
        return JSONResponse({"messages": msgs})

    return [
        Route("/api/mmr/method", method),
        Route("/api/mmr/comparison", comparison),
        Route("/api/mmr/participants/{pid}", overview),
        Route("/api/mmr/participants/{pid}/history", history),
        Route("/api/mmr/participants/{pid}/observations", observations),
        Route("/api/mmr/participants/{pid}/explain", explain),
        Route("/api/mmr/participants/{pid}/activities/{aid}/effect", effect),
        Route("/api/demo/histories", demo_histories, methods=["POST"]),
    ]
