"""Ratings Lab routes (EXPERIMENTAL). Contract: web/src/api/types.ts.

Two data sources, chosen explicitly by the route: built-in synthetic runners (/api/lab/runners/...), which
never open the database, and histories stored in the database this app was started with
(/api/lab/db/runners/...), read only through runrank.lab_source.connect_ro (SQLite mode=ro, query_only).
Every result is recomputed by runrank.lab_methods per request; Lab overrides live only in the query string,
so no control can write into personal MMR, race Elo or annotation records.
"""
from contextlib import closing
from datetime import timedelta

from starlette.responses import JSONResponse
from starlette.routing import Route

from . import lab_compare as C
from . import lab_methods as L
from . import lab_source as DB
from . import lab_synthetic as S
from . import mmr

NUMERIC = {"speed_weight": float, "k_best": int, "walk_ref_pace_s": float, "stop_max": float, "alpha": float,
           "step_max": float}


SOURCES = {"synthetic": "Built-in synthetic examples",
           "database": "Histories in the currently selected application database"}


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def routes(ApiError, db_file=None, database="custom", demo_mode=False, date_param=None, today=None,
           end_of_day=None):
    def method_and_params(q):
        m = q.get("method", "B")
        if m not in L.PARAM_SPACE:
            raise ApiError(400, "bad_request", "method must be one of A, B, C, D", "method")
        params = {}
        for k in L.PARAM_SPACE[m]:
            if q.get(k) not in (None, ""):
                try:
                    params[k] = NUMERIC[k](q[k]) if k in NUMERIC else q[k]
                except ValueError:
                    raise ApiError(400, "bad_request", "%s must be a number" % k, k)
        try:
            return m, L.check_params(m, params)
        except ValueError as exc:
            raise ApiError(400, "bad_request", str(exc))

    def runner_of(request):
        key = request.path_params["key"]
        if key not in C.LAB_RUNNERS:
            raise ApiError(404, "not_found", "no synthetic runner %r" % key)
        return key

    def result(r):
        ev = dict(r.evidence)
        sel = ev.pop("selected", [])
        ev.pop("production_rows", None)
        return {"combined": r.combined, "components": r.components, "evidence": ev, "notes": r.notes,
                "selected": [dict(x, date=_iso(x["date"])) for x in sel]}

    def explanation(m, p, res):
        """One concise explanation of a B result, derived from its rules and its selected evidence."""
        if m != "B":
            return None
        rules = {
            "speed": ("a faster 10 km-equivalent on a 3-42.5 km Run", "only time: evidence ages after 30 days (0.05 %/day)"),
            "performance": ("a faster time at any distance (3-250 km; Riegel up to 42.5 km, then the synthetic "
                            "anchor-curve bridge)", "only time: evidence ages after 30 days (0.05 %/day)"),
            "endurance": ("a longer recorded distance in one activity (3-250 km), at running pace",
                          "only time: evidence ages after 30 days"),
            "long_performance": ("a faster time over 42.5 km (anchor curve)", "only time: evidence ages"),
        }
        comps = []
        for x in res.evidence.get("selected", []):
            raises, lowers = rules[x["component"]]
            warnings = [c for c in x["concerns"] if not c.startswith("uncorroborated")]
            comps.append({"component": x["component"], "value": x["value"], "activity": x["activity"],
                          "date": _iso(x["date"]), "detail": x["detail"], "raises": raises, "lowers": lowers,
                          "provisional": x["provisional"], "warnings": warnings})
        w = p["speed_weight"]
        return {"components": comps,
                "weighting": ("combined = %.2f × performance + %.2f × endurance. The two fixed scales have different "
                              "slopes (1 %% faster ≈ +19.5 performance points; 1 %% longer ≈ +5.4 endurance points), so "
                              "%d/%d is an experimental exchange rate, not a neutral split." % (
                                  w, 1 - w, round(w * 100), round((1 - w) * 100))),
                "unvalidated": [
                    "Riegel's exponent 1.06 for every runner (personal endurance profiles differ)",
                    "the anchor curve: rounded times written from memory, a synthetic assumption, not elite records",
                    "the 26:00 and 2:00:00 scale anchors and the 1-250 km endurance anchors",
                    "the recency rate (1.5 % per 30 days after 30 days) and the 365-day window",
                    "the walking anchor 10:00/km and the 10 % large-improvement flag",
                    "the speed/endurance weight",
                    "no real export has been evaluated; nothing here is validated on real runners"]}

    async def meta(request):
        return JSONResponse({
            "version": L.VERSION, "experimental": True,
            "methods": [{"key": m, "name": L.NAMES[m], "params": {k: v for k, v in L.PARAM_SPACE[m].items()},
                         "defaults": L.DEFAULTS[m]} for m in "ABCD"],
            "runners": [{"key": k, "label": S.RUNNERS[k][0]} for k in C.LAB_RUNNERS],
            "sources": [{"key": "synthetic", "label": SOURCES["synthetic"], "available": True, "reason": None},
                        source_info()],
            "scales": ["Speed: 3000 × ln(7200 / T10) / ln(7200 / 1560); 10 km-equivalent (Riegel k 1.06) 2:00:00 = 0, "
                       "26:00 = 3000 (the app's fixed mapping).",
                       "Endurance (demonstrated distance completion, not estimated capacity): 3000 × ln(credited km) / "
                       "ln(250); 1 km = 0, 250 km = 3000 (synthetic anchors). Credited km = distance × continuity "
                       "(1 up to 5 % stopped, then falling 1:1, floor 0.5; missing moving time = 0.5) × running pace "
                       "(1 to 0 across the walking anchor 10:00/km × (km / 10)^0.10 ± 10 %, moving pace).",
                       "Distance categories (C): 3000 × ln(v / 5 km/h) / ln(v_top(d) / 5 km/h) with synthetic "
                       "near-elite anchor speeds per distance (not population standards).",
                       "Combined (B, D): speed weight × S + (1 − speed weight) × E. The weights are product "
                       "choices, not validated."],
            "supported_range_km": list(L.PERFORMANCE_RANGE_KM), "curve_range_km": list(L.CURVE_RANGE_KM),
            "anchors": [{"km": k, "time_s": t_, "provenance": "synthetic assumption: rounded from memory of roughly "
                         "elite performances; unverified, not an established reference"} for k, t_ in L.TOP_ANCHORS],
            "generator": next(par for par in S.__doc__.split("\n\n") if par.startswith("Generator assumptions"))
            .replace("\n", " ")})

    def ids_param(q, a, name):
        ex = [k for k in (q.get(name) or "").split(",") if k]
        unknown = set(ex) - {x.key for x in a}
        if unknown:
            raise ApiError(400, "bad_request", "unknown activity id(s) in %s: %s" % (name, ", ".join(sorted(unknown))),
                           name)
        return ex

    def dup_groups(m, p, inputs, sep, stored_keys):
        """{key: sorted recordings of the same effort}, under the selected method's own duplicate rule.

        Only identified duplicates (A: production's rule; B-D: exact or probable duplicates). Ambiguous overlaps
        are never grouped. Groups have two or more recordings."""
        if m == "A":
            cls, lab_key = L.production_classified(inputs, stored_keys, sep)
            edges = {k: lab_key.get(c.obs.duplicate_of, c.obs.duplicate_of) for k, c in cls.items()
                     if c.obs.duplicate_of}
        else:
            edges = {x.act.key: x.duplicate_of for x in L.prepare(inputs, p, sep) if x.duplicate_of}
        root = {}

        def find(k):
            while root.get(k, k) != k:
                k = root[k]
            return k
        for k, v in edges.items():
            root[find(k)] = find(v)
        groups = {}
        for k in set(edges) | set(edges.values()):
            groups.setdefault(find(k), set()).add(k)
        return {k: sorted(g, key=lambda x: (len(x), x)) for g in groups.values() if len(g) > 1 for k in g}

    def ids_of(q, name):
        return [k for k in (q.get(name) or "").split(",") if k]

    def overrides(m, p, q, a, stored_excluded=(), base_sep=frozenset()):
        """Lab-only overrides from the query string: validated ids, never stored.

        exclude:        recordings; another valid recording of the same effort may then count (B-D), or stays a
                        duplicate as production would treat it (A).
        exclude_effort: a recording and every identified duplicate recording of the same effort."""
        stored_keys = frozenset(x.key for x in stored_excluded)
        known = {x.key for x in a}
        for name in ("exclude", "exclude_effort"):
            ids = set(ids_of(q, name))
            if ids & stored_keys:
                raise ApiError(400, "bad_request", "already excluded by a stored annotation: %s"
                               % ", ".join(sorted(ids & stored_keys)), name)
            if ids - known:
                raise ApiError(400, "bad_request", "unknown activity id(s) in %s: %s"
                               % (name, ", ".join(sorted(ids - known))), name)
        sep = frozenset(ids_param(q, a, "keep_separate")) | (base_sep & known)
        group_input = a + list(stored_excluded) if m == "A" else a
        groups = dup_groups(m, p, group_input, sep, stored_keys)
        rec = ids_of(q, "exclude")
        efforts = [{"key": k, "recordings": [r for r in groups.get(k, [k]) if r in known]}
                   for k in ids_of(q, "exclude_effort")]
        gone = set(rec).union(*[e["recordings"] for e in efforts])
        kept = [x for x in a if x.key not in gone]
        conf = frozenset(ids_param(q, kept, "confirm"))
        return {"recordings": rec, "efforts": efforts, "gone": frozenset(gone), "kept": kept, "confirmed": conf,
                "sep": sep, "groups": groups, "stored_keys": stored_keys}

    def evaluate(m, p, o, a, stored_excluded, t, lab=True):
        """One evaluation. A gets every stored row with exclusions flagged (production's preprocessing);
        B-D get the inputs with exclusions removed. lab=False: stored annotations only (no Lab overrides)."""
        sep = o["sep"] if lab else o["sep"] & set(o["base_sep"])
        if m == "A":
            ex = o["stored_keys"] | (o["gone"] if lab else frozenset())
            return L.evaluate("A", a + list(stored_excluded), t, p, keep_separate=sep, excluded=ex)
        return L.evaluate(m, o["kept"] if lab else a, t, p, confirmed=o["confirmed"] if lab else frozenset(),
                          keep_separate=sep)

    def activity_rows(m, a, t, p, res, o, prov=None):
        preps = {x.act.key: x for x in L.prepare(a, p, o["sep"])}
        held = {x["activity"] for x in res.evidence.get("pending", [])}
        flagged = res.evidence.get("flags", {})
        prod = res.evidence.get("production_rows", {})
        lo = t - timedelta(days=L.COMMON["window_days"])
        rows = []
        for x in sorted(a, key=lambda x: x.start, reverse=True):
            pr = preps[x.key]
            if m == "A":            # production's own classification
                c = prod[x.key]
                used = ["speed"] if c["informative"] else []
                dup, kind = c["duplicate_of"], "production" if c["duplicate_of"] else None
                dropped = next((r for r in c["reasons"] if r.startswith("possible duplicate")), None)
                flags, t10 = c["flags"], None
                reasons = [] if c["informative"] or dropped else c["reasons"]
            else:
                used = [u for u, ok in (("speed", pr.t10 is not None), ("endurance", pr.endurance_km is not None),
                                        ("category", pr.category is not None)) if ok]
                dup, kind, dropped = pr.duplicate_of, pr.duplicate_kind, pr.dropped or pr.invalid
                flags, t10 = pr.flags + flagged.get(x.key, []), pr.t10
                reasons = [r for r in (pr.speed_reason, pr.endurance_reason, pr.cat_reason) if r]
            state = ("after as-of" if x.start > t else "invalid" if m != "A" and pr.invalid else
                     "dropped" if dropped else "held" if x.key in held else "unsupported" if not used else
                     "outside window" if x.start <= lo else
                     "flagged" if m != "A" and (flagged.get(x.key) or pr.flags) else "counted")
            rows.append({"key": x.key, "start_utc": _iso(x.start), "type": x.type, "distance_m": x.distance_m,
                         "elapsed_s": x.elapsed_s, "moving_s": x.moving_s, "effort": x.effort, "used_for": used,
                         "dropped": dropped, "duplicate_of": dup, "duplicate_kind": kind, "t10_s": t10,
                         "credited_km": None if m == "A" else pr.endurance_km,
                         "continuity": None if m == "A" else (pr.continuity or None),
                         "overlap": None if m == "A" else pr.overlap, "flags": flags, "state": state,
                         "reasons": reasons if state == "unsupported" else [],
                         "duplicate_group": o["groups"].get(x.key, []),
                         "provenance": prov[x.key] if prov is not None else None})
        return rows

    def lite(r):
        return {"combined": r.combined, "components": r.components}

    def payload(m, p, q, all_acts, t, runner_info, stored_excluded=(), base_sep=frozenset(), prov=None):
        o = overrides(m, p, q, all_acts, stored_excluded, base_sep)
        o["base_sep"] = base_sep
        res = evaluate(m, p, o, all_acts, stored_excluded, t)
        base = evaluate(m, p, o, all_acts, stored_excluded, t, lab=False)
        if m == "A":
            hist = L.history("A", all_acts + list(stored_excluded), t, p, step_days=14, keep_separate=o["sep"],
                             excluded=o["stored_keys"] | o["gone"])
        else:
            hist = L.history(m, o["kept"], t, p, step_days=14, confirmed=o["confirmed"], keep_separate=o["sep"])
        rows = activity_rows(m, o["kept"], t, p, res, o, prov)
        for x in sorted(stored_excluded, key=lambda x: x.start, reverse=True):
            note = prov[x.key]["stored_exclude_note"]
            rows.append({"key": x.key, "start_utc": _iso(x.start), "type": x.type, "distance_m": x.distance_m,
                         "elapsed_s": x.elapsed_s, "moving_s": x.moving_s, "effort": x.effort, "used_for": [],
                         "dropped": None, "duplicate_of": None, "duplicate_kind": None, "t10_s": None,
                         "credited_km": None, "continuity": None, "overlap": None, "flags": [],
                         "state": "excluded (stored)",
                         "reasons": ["excluded by a stored annotation" + (": %s" % note if note else "")],
                         "duplicate_group": [], "provenance": prov[x.key]})
        lab_active = bool(o["gone"] or o["confirmed"] or (o["sep"] - set(base_sep)))
        return {
            "runner": runner_info, "method": m, "params": p, "version": L.VERSION, "excluded": o["recordings"],
            "excluded_efforts": o["efforts"], "confirmed": sorted(o["confirmed"]), "keep_separate": sorted(o["sep"]),
            "as_of_utc": _iso(t), "result": result(res), "explanation": explanation(m, p, res),
            "override_impact": {"active": lab_active, "without_lab_overrides": lite(base), "with": lite(res),
                                "excluded_ids": sorted(o["gone"], key=lambda k: (len(k), k))},
            "comparator": comparator(m),
            "history": [{"at_utc": _iso(h["at"]), "combined": h["combined"], "components": h["components"]}
                        for h in hist],
            "activities": rows, "stored_keep_separate": sorted(base_sep),
            "latest_activity_utc": max((_iso(x.start) for x in all_acts), default=None)}

    def comparator(m):
        if m != "A":
            return None
        return ("Method A runs the production Running MMR preprocessing and estimate (mmr.classify_history and "
                "mmr.estimate_at, %s): the same duplicate rule, stored exclusions and not-a-duplicate annotations. "
                "Lab exclusions are applied as production would apply a stored exclusion: an excluded recording "
                "still marks its duplicates, which count only if marked not a duplicate." % mmr.ALGORITHM_VERSION)

    async def runner(request):
        key = runner_of(request)
        m, p = method_and_params(request.query_params)
        out = payload(m, p, request.query_params, C.acts(key), S.at(C.AS_OF_DAY),
                      {"key": key, "label": S.RUNNERS[key][0], "data_kind": "synthetic"})
        out["source"] = {"key": "synthetic", "label": SOURCES["synthetic"], "database": None, "demo_mode": None,
                         "available": True, "reason": None, "as_of_basis": "fixed synthetic reference date (day %d "
                         "of the generated histories)" % C.AS_OF_DAY, "as_of_date": S.at(C.AS_OF_DAY).date().isoformat(),
                         "today": None}
        out["coverage_notes"] = []
        return JSONResponse(out)

    def explain_payload(m, p, q, all_acts, aid, stored_excluded=(), base_sep=frozenset()):
        o = overrides(m, p, q, all_acts, stored_excluded, base_sep)
        if aid not in {x.key for x in o["kept"]}:
            raise ApiError(404, "not_found", "no activity %s in the Lab input" % aid)
        if m == "A":
            e = L.explain_activity("A", all_acts + list(stored_excluded), aid, p, keep_separate=o["sep"],
                                   excluded=o["stored_keys"] | o["gone"])
        else:
            e = L.explain_activity(m, o["kept"], aid, p, o["confirmed"], o["sep"])
        x = next(y for y in o["kept"] if y.key == aid)
        return {"activity": {"key": x.key, "start_utc": _iso(x.start), "type": x.type,
                             "distance_m": x.distance_m, "elapsed_s": x.elapsed_s,
                             "moving_s": x.moving_s, "effort": x.effort,
                             "pace": mmr.fmt(x.elapsed_s / x.distance_m * 1000)},
                "method": m, "params": p, "before": result(e["before"]), "after": result(e["after"]),
                "deltas": e["deltas"], "reasons": e["reasons"]}

    async def activity(request):
        key = runner_of(request)
        m, p = method_and_params(request.query_params)
        return JSONResponse(explain_payload(m, p, request.query_params, C.acts(key), request.path_params["aid"]))

    # ------------------------------------------------ stored histories (read-only connection)

    def source_info():
        info = {"key": "database", "label": SOURCES["database"], "database": database, "demo_mode": demo_mode,
                "available": db_file is not None, "reason": None if db_file else "no database configured"}
        if db_file:
            try:
                DB.connect_ro(db_file).close()
            except DB.Unavailable as exc:
                info.update(available=False, reason=str(exc))
        return info

    def ro():
        if not db_file:
            raise ApiError(409, "unavailable", "no application database is configured for the Lab")
        try:
            return closing(DB.connect_ro(db_file))
        except DB.Unavailable as exc:
            raise ApiError(409, "unavailable", str(exc))

    def stored(con, request):
        try:
            pid = int(request.path_params["pid"])
        except ValueError:
            raise ApiError(400, "bad_request", "runner id must be an integer", "pid")
        info = DB.runner(con, pid)
        if info is None:
            raise ApiError(404, "not_found", "no stored runner %d" % pid)
        return info, DB.history(con, pid)

    def as_of(q):
        day = date_param(q, "as_of", None)
        return (day or today()), ("explicit date" if day else "today (default)")

    async def db_runners(request):
        with ro() as con:
            return JSONResponse({"source": source_info(), "runners": DB.runners(con)})

    async def db_runner(request):
        m, p = method_and_params(request.query_params)
        day, basis = as_of(request.query_params)
        t = end_of_day(day)
        with ro() as con:
            info, (acts, stored_ex, base_sep, prov) = stored(con, request)
        out = payload(m, p, request.query_params, acts, t, info, stored_ex, base_sep, prov)
        out["source"] = dict(source_info(), as_of_basis=basis, as_of_date=day.isoformat(),
                             today=today().isoformat())
        out["coverage_notes"] = DB.coverage_notes(acts + stored_ex, acts, stored_ex, t)
        return JSONResponse(out)

    async def db_activity(request):
        m, p = method_and_params(request.query_params)
        with ro() as con:
            _, (acts, stored_ex, base_sep, _) = stored(con, request)
        return JSONResponse(explain_payload(m, p, request.query_params, acts, request.path_params["aid"],
                                            stored_ex, base_sep))

    async def compare(request):
        return JSONResponse({"version": L.VERSION, "as_of_utc": _iso(S.at(C.AS_OF_DAY)), "rows": C.table(),
                             "tradeoffs": C.tradeoffs(), "improvements": C.improvements(),
                             "matched": C.matched_rewards()})

    return [Route("/api/lab/meta", meta), Route("/api/lab/compare", compare),
            Route("/api/lab/runners/{key}", runner), Route("/api/lab/runners/{key}/activities/{aid}", activity),
            Route("/api/lab/db/runners", db_runners), Route("/api/lab/db/runners/{pid}", db_runner),
            Route("/api/lab/db/runners/{pid}/activities/{aid}", db_activity)]
