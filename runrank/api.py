"""RunnasUP local JSON API (Starlette). Contract: web/src/api/types.ts, docs/API.md.

Reuses runrank.store; Running MMR and Ratings Lab routes live in api_mmr / api_lab. No formula lives here
or in the frontend. The legacy 5K score and race Elo routes were removed on 2026-10-25 (kept in a local backup, not in the repository). One SQLite connection per request. Errors are always
{"error": {"code", "message"}} and never echo activity data.
"""
import csv
import io
import json
import logging
import math
import pathlib
from contextlib import closing
from datetime import date, datetime, timezone

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from . import api_lab, api_mmr, mmr, store

log = logging.getLogger("runrank.api")
ROOT = pathlib.Path(__file__).resolve().parent.parent
DIST = ROOT / "web" / "dist"
MAX_UPLOAD = 50 * 1024 * 1024
EFFORTS = store.EFFORTS


class ApiError(Exception):
    def __init__(self, status, code, message, field=None, **extra):
        super().__init__(message)
        self.status, self.code, self.message, self.field, self.extra = status, code, message, field, extra


def _err(status, code, message, field=None, **extra):
    body = {"code": code, "message": message}
    if field:
        body["field"] = field
    body.update(extra)
    return JSONResponse({"error": body}, status_code=status)


# ---------------------------------------------------------------- parsing helpers

def _date(q, name, default=None):
    raw = q.get(name)
    if raw in (None, ""):
        return default
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ApiError(400, "bad_request", "%s must be a date YYYY-MM-DD" % name, name)


def _float(q, name):
    raw = q.get(name)
    if raw in (None, ""):
        return None
    try:
        v = float(raw)
    except ValueError:
        raise ApiError(400, "bad_request", "%s must be a number" % name, name)
    if not math.isfinite(v) or v < 0:
        raise ApiError(400, "bad_request", "%s must be a non-negative number" % name, name)
    return v


def _int(q, name, default, lo, hi):
    raw = q.get(name)
    if raw in (None, ""):
        return default
    try:
        v = int(raw)
    except ValueError:
        raise ApiError(400, "bad_request", "%s must be an integer" % name, name)
    if not lo <= v <= hi:
        raise ApiError(400, "bad_request", "%s must be between %d and %d" % (name, lo, hi), name)
    return v


def _choice(q, name, options, default):
    v = q.get(name) or default
    if v not in options:
        raise ApiError(400, "bad_request", "%s must be one of %s" % (name, ", ".join(options)), name)
    return v


def _today():
    return datetime.now(timezone.utc).date()


# ---------------------------------------------------------------- shapes

def _participant(con, p):
    st = store.data_status(con, p["id"])
    return {"id": p["id"], "label": p["label"], "data_kind": p["data_kind"], "created_utc": p["created_utc"],
            "activity_count": st["activities"], "first_activity_utc": st["first_activity_utc"],
            "last_activity_utc": st["last_activity_utc"], "last_import_utc": st["last_import_utc"]}


def _get_participant(con, pid):
    p = con.execute("SELECT * FROM participants WHERE id = ?", (pid,)).fetchone()
    if p is None:
        raise ApiError(404, "not_found", "no runner with id %d" % pid)
    return p


def _row(a):
    d = a["distance_m"]
    return {"id": a["source_activity_id"], "start_utc": a["start_utc"], "name": a["name"],
            "type": a["activity_type"], "distance_m": d, "elapsed_s": a["elapsed_s"], "moving_s": a["moving_s"],
            "pace_s_per_km": round(a["elapsed_s"] / (d / 1000), 2),
            "moving_pace_s_per_km": None if a["moving_s"] is None else round(a["moving_s"] / (d / 1000), 2),
            "avg_hr": a["avg_hr"], "perceived_exertion": a["perceived_exertion"],
            "elevation_gain_m": a["elevation_gain_m"], "effort": a["effort"]}


SORT_KEYS = {"start": lambda r: r["start_utc"], "distance": lambda r: r["distance_m"],
             "elapsed": lambda r: r["elapsed_s"], "pace": lambda r: r["pace_s_per_km"],
             "name": lambda r: (r["name"] or "").lower()}


def _filtered_rows(con, pid, q):
    frm, to = _date(q, "from"), _date(q, "to")
    if frm and to and frm > to:
        raise ApiError(400, "bad_request", "from must not be after to", "from")
    mn, mx = _float(q, "min_km"), _float(q, "max_km")
    if mn is not None and mx is not None and mn > mx:
        raise ApiError(400, "bad_request", "min_km must not exceed max_km", "min_km")
    sort = _choice(q, "sort", tuple(SORT_KEYS), "start")
    order = _choice(q, "order", ("asc", "desc"), "desc")
    text = (q.get("q") or "").strip().lower()
    typ = q.get("type") or None
    all_rows = [_row(a) for a in store.activities(con, pid)]
    types = sorted({r["type"] for r in all_rows})
    rows = []
    for r in all_rows:
        day = r["start_utc"][:10]
        if text and text not in (r["name"] or "").lower() and text != r["id"].lower():
            continue
        if frm and day < frm.isoformat() or to and day > to.isoformat():
            continue
        km = r["distance_m"] / 1000
        if mn is not None and km < mn or mx is not None and km > mx:
            continue
        if typ and r["type"] != typ:
            continue
        rows.append(r)
    rows.sort(key=lambda r: (SORT_KEYS[sort](r), r["start_utc"], r["id"]), reverse=(order == "desc"))
    return types, rows


def _import_record(con, imp):
    warnings = con.execute("SELECT COUNT(*) FROM import_rows WHERE import_id = ? AND detail LIKE '%warnings:%'",
                           (imp["id"],)).fetchone()[0]
    return {"id": imp["id"], "participant_id": imp["participant_id"], "filename": imp["filename"],
            "imported_utc": imp["imported_utc"], "status": imp["status"], "message": imp["message"],
            "rows_total": imp["rows_total"], "inserted": imp["inserted"], "duplicates": imp["duplicates"],
            "conflicts": imp["conflicts"], "corrected": imp["corrected"], "rejected": imp["rejected"],
            "warnings": warnings}


def _import_rows(con, imp_id):
    return [{"line": r["line_no"], "activity_id": r["source_activity_id"], "outcome": r["outcome"],
             "detail": r["detail"] or "", "warning": "warnings:" in (r["detail"] or "")}
            for r in store.import_rows(con, imp_id)]


# ---------------------------------------------------------------- app factory

def create_app(db_path, demo_mode=False, database="custom", allowed_hosts=("127.0.0.1", "localhost")):
    def db():
        return closing(store.connect(db_path))

    def pid_of(request):
        try:
            return int(request.path_params["pid"])
        except (KeyError, ValueError):
            raise ApiError(400, "bad_request", "runner id must be an integer", "pid")

    async def health(request):
        ref = _today().isoformat()
        if demo_mode:          # synthetic fixtures are dated 2024: anchor defaults to the latest stored activity
            with db() as con:
                last = con.execute("SELECT MAX(start_utc) FROM activities").fetchone()[0]
            ref = last[:10] if last else ref
        return JSONResponse({"ok": True, "database": database, "demo_mode": demo_mode, "reference_date": ref,
                             "schema_version": store.SCHEMA_VERSION, "mmr_version": mmr.ALGORITHM_VERSION})

    async def participants(request):
        with db() as con:
            if request.method == "POST":
                body = await _json(request)
                kind = body.get("data_kind")
                if kind not in ("real", "synthetic"):
                    raise ApiError(400, "bad_request", "data_kind must be 'real' or 'synthetic'", "data_kind")
                if demo_mode and kind == "real":
                    raise ApiError(409, "demo_only", "the demo database holds synthetic runners only; "
                                                     "start ./run.sh for real data", "data_kind")
                try:
                    pid = store.create_participant(con, body.get("label"), bool(body.get("consent")), kind)
                except ValueError as exc:
                    raise ApiError(400, "bad_request", str(exc), "label" if "label" in str(exc) or
                                   "exists" in str(exc) else "consent")
                return JSONResponse(_participant(con, _get_participant(con, pid)), status_code=201)
            return JSONResponse([_participant(con, p) for p in store.participants(con)])

    async def activities(request):
        q = request.query_params
        with db() as con:
            pid = pid_of(request)
            _get_participant(con, pid)
            types, rows = _filtered_rows(con, pid, q)
            limit = _int(q, "limit", 50, 1, 500)
            offset = _int(q, "offset", 0, 0, 10 ** 7)
            return JSONResponse({"participant_id": pid,
                                 "total": len(rows), "offset": offset, "limit": limit, "types": types,
                                 "rows": rows[offset:offset + limit]})

    async def activities_csv(request):
        q = request.query_params
        with db() as con:
            pid = pid_of(request)
            p = _get_participant(con, pid)
            _types, rows = _filtered_rows(con, pid, q)
            cols = ["id", "start_utc", "name", "type", "distance_m", "elapsed_s", "moving_s", "pace_s_per_km",
                    "moving_pace_s_per_km", "avg_hr", "perceived_exertion", "elevation_gain_m", "effort"]
            return _csv(cols, [[r[c] for c in cols] for r in rows], "runnasup_activities_%d.csv" % p["id"])

    def _detail(con, pid, aid):
        p = _get_participant(con, pid)
        rows = {a["source_activity_id"]: a for a in store.activities(con, pid)}
        if aid not in rows:
            raise ApiError(404, "not_found", "no activity %s for this runner" % aid)
        a = rows[aid]
        ann = con.execute("SELECT * FROM annotations WHERE activity_id = ?", (a["id"],)).fetchone()
        act = dict(_row(a), source=a["source"], first_import_id=a["first_import_id"],
                   first_imported_utc=a["first_imported_utc"], first_import_file=a["first_import_file"],
                   last_import_id=a["last_import_id"])
        log_rows = [r for r in store.annotation_log(con, pid) if r["source_activity_id"] == aid]
        return {"participant": {"id": p["id"], "label": p["label"], "data_kind": p["data_kind"]},
                "activity": act,
                "annotation": {"exclude": bool(a["exclude"]), "exclude_note": a["exclude_note"],
                               "not_duplicate": bool(a["not_duplicate"]), "effort": a["effort"],
                               "updated_utc": ann["updated_utc"] if ann else None},
                "annotation_log": [{"changed_utc": r["changed_utc"], "field": r["field"],
                                    "old_value": r["old_value"], "new_value": r["new_value"]} for r in log_rows],
                "mmr": _mmr_of(con, pid, aid)}

    def _mmr_of(con, pid, aid):
        c = next(x for x in store.mmr_observations(con, pid) if x.obs.key == aid)
        return {"version": mmr.ALGORITHM_VERSION, "informative": c.informative, "reasons": list(c.reasons),
                "flags": list(c.flags), "t10_s": c.t10_s,
                "points": mmr.points(c.t10_s) if c.t10_s is not None else None}

    async def activity(request):
        with db() as con:
            return JSONResponse(_detail(con, pid_of(request), request.path_params["aid"]))

    async def annotation(request):
        body = await _json(request)
        for k in ("exclude", "not_duplicate"):
            if not isinstance(body.get(k), bool):
                raise ApiError(400, "bad_request", "%s must be true or false" % k, k)
        if body.get("effort") not in EFFORTS:
            raise ApiError(400, "bad_request", "effort must be one of %s" % ", ".join(EFFORTS), "effort")
        note = body.get("exclude_note")
        if note is not None and (not isinstance(note, str) or len(note) > 500):
            raise ApiError(400, "bad_request", "exclude_note must be text of at most 500 characters", "exclude_note")
        with db() as con:
            pid, aid = pid_of(request), request.path_params["aid"]
            detail = _detail(con, pid, aid)        # validates runner and activity ownership
            act = con.execute("SELECT id FROM activities WHERE participant_id = ? AND source_activity_id = ?",
                              (pid, aid)).fetchone()
            store.set_annotation(con, act["id"], body["exclude"], note, body["not_duplicate"], body["effort"])
            detail = _detail(con, pid, aid)
            return JSONResponse(detail)

    async def _upload(request):
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_UPLOAD + 1024 * 1024:
            raise ApiError(413, "payload_too_large", "files are limited to 50 MB")
        form = await request.form(max_files=1, max_fields=10)
        up = form.get("file")
        if up is None or not hasattr(up, "read"):
            raise ApiError(400, "bad_request", "attach the export as form field 'file'", "file")
        data = await up.read(MAX_UPLOAD + 1)
        await up.close()
        if len(data) > MAX_UPLOAD:
            raise ApiError(413, "payload_too_large", "files are limited to 50 MB")
        name = pathlib.PurePath(up.filename or "upload").name[:200]
        flags = {k: str(form.get(k, "false")).lower() == "true" for k in ("apply_corrections", "confirm_repeat")}
        return name, data, flags

    async def import_preview(request):
        name, data, flags = await _upload(request)
        with db() as con:
            pid = pid_of(request)
            _get_participant(con, pid)
            res = store.preview_import(con, pid, name, data, flags["apply_corrections"])
            prev = store.completed_import_of(con, pid, store.file_sha256(data))
            res["identical_previous_import"] = _import_record(con, prev) if prev else None
            for r in res["rows"]:
                r["detail"] = r["detail"] or ""
                r["warning"] = "warnings:" in r["detail"]
            return JSONResponse(res)

    async def imports(request):
        with db() as con:
            pid = pid_of(request)
            _get_participant(con, pid)
            if request.method == "GET":
                return JSONResponse([_import_record(con, i) for i in store.imports(con, pid)])
        name, data, flags = await _upload(request)
        with db() as con:
            prev = store.completed_import_of(con, pid, store.file_sha256(data))
            if prev is not None and not flags["confirm_repeat"]:
                raise ApiError(409, "duplicate_file", "this exact file was already imported for this runner; "
                                                      "importing it again only reports duplicates",
                               previous_import=_import_record(con, prev))
            imp_id = store.import_file(con, pid, name, data, flags["apply_corrections"])
            imp = con.execute("SELECT * FROM imports WHERE id = ?", (imp_id,)).fetchone()
            return JSONResponse({"import": _import_record(con, imp), "rows": _import_rows(con, imp_id)},
                                status_code=201)

    async def import_one(request):
        try:
            iid = int(request.path_params["iid"])
        except ValueError:
            raise ApiError(400, "bad_request", "import id must be an integer", "iid")
        with db() as con:
            imp = con.execute("SELECT * FROM imports WHERE id = ?", (iid,)).fetchone()
            if imp is None:
                raise ApiError(404, "not_found", "no import with id %d" % iid)
            return JSONResponse({"import": _import_record(con, imp), "rows": _import_rows(con, iid)})

    async def spa(request):
        rel = request.path_params.get("path", "")
        if rel.startswith("api/"):
            raise ApiError(404, "not_found", "unknown API route")
        target = (DIST / rel).resolve()
        if rel and target.is_file() and DIST.resolve() in target.parents:
            return FileResponse(target)
        index = DIST / "index.html"
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return HTMLResponse("<!doctype html><title>RunnasUP</title><p>The frontend is not built yet. Run "
                            "<code>./run.sh</code> (it builds <code>web/</code>) or <code>npm --prefix web run "
                            "build</code>.</p>", status_code=503)

    async def on_api_error(request, exc):
        return _err(exc.status, exc.code, exc.message, exc.field, **exc.extra)

    async def on_http_error(request, exc):
        code = {404: "not_found", 405: "bad_request", 413: "payload_too_large"}.get(exc.status_code, "bad_request")
        return _err(exc.status_code, code, exc.detail if isinstance(exc.detail, str) else "request failed")

    async def on_error(request, exc):
        log.error("internal error on %s %s: %s", request.method, request.url.path, type(exc).__name__)
        return _err(500, "internal", "unexpected server error; nothing was changed by a failed request")

    routes = [
        Route("/api/health", health),
        Route("/api/participants", participants, methods=["GET", "POST"]),
        Route("/api/participants/{pid}/activities", activities),
        Route("/api/participants/{pid}/activities.csv", activities_csv),
        Route("/api/participants/{pid}/activities/{aid}", activity),
        Route("/api/participants/{pid}/activities/{aid}/annotation", annotation, methods=["PUT"]),
        Route("/api/participants/{pid}/imports/preview", import_preview, methods=["POST"]),
        Route("/api/participants/{pid}/imports", imports, methods=["GET", "POST"]),
        Route("/api/imports/{iid}", import_one),
        *api_mmr.routes(db, demo_mode, ApiError, _date, store.end_of_day_utc, _get_participant, _participant),
        *api_lab.routes(ApiError, store.db_file(db_path), database, demo_mode, _date, _today, store.end_of_day_utc),
        Route("/{path:path}", spa),
    ]
    return Starlette(routes=routes,
                     middleware=[Middleware(TrustedHostMiddleware, allowed_hosts=list(allowed_hosts))],
                     exception_handlers={ApiError: on_api_error, HTTPException: on_http_error, Exception: on_error})


async def _json(request):
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ApiError(400, "bad_request", "request body must be JSON")
    if not isinstance(body, dict):
        raise ApiError(400, "bad_request", "request body must be a JSON object")
    return body


def _csv(header, rows, filename):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    # cells that a spreadsheet would evaluate as a formula are prefixed with an apostrophe
    w.writerows([["'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v for v in r]
                 for r in rows])
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="%s"' % filename})
