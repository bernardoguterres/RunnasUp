# RunnasUP local API

**Source of truth for types:** `web/src/api/types.ts`. **Server:** `runrank/api.py` (Starlette), started by `runrank/serve.py`.

**Binding:** `127.0.0.1:8600` only. `TrustedHostMiddleware` allows `localhost` and `127.0.0.1`. The same process serves the built SPA (`web/dist`), with a fallback to `index.html` for client routes.

**Databases:**

| Start | Database | Demo loaders (`/api/demo/histories`) |
|---|---|---|
| `./run.sh` | `data/runrank.sqlite` (personal) | refused (`409 demo_only`) |
| `./run.sh demo` | `data/demo/runrank-demo.sqlite` (synthetic only) | allowed |
| `RUNRANK_DB=<path> ./run.sh` | custom | refused |

The personal database is never touched in demo mode.

**Errors:** every non-2xx response is `{"error": {"code", "message", "field"?}}`. Codes:
- `bad_request` (400)
- `not_found` (404)
- `conflict` (409)
- `duplicate_file` (409; includes `previous_import`)
- `demo_only` (409)
- `payload_too_large` (413; the limit is 50 MB)
- `internal` (500)

Messages never echo activity data, and 500s are logged without request bodies.

| Method and path | Purpose |
|---|---|
| GET `/api/health` | database kind, schema version, Running MMR version, `reference_date` (today in UTC, or in demo mode the latest stored activity date) |
| GET/POST `/api/participants` | list / create (real requires `consent: true`) |
| GET `/api/participants/{pid}/activities[.csv]` | search (name, or exact activity ID), filter, sort, page (`q, from, to, min_km, max_km, type, sort, order, limit, offset`; `sort` is `start`, `distance`, `elapsed`, `pace` or `name`). Rows hold recorded and derived fields only. CSV cells that could start a spreadsheet formula are prefixed with `'` |
| GET `/api/participants/{pid}/activities/{id}` | recorded and derived fields, the Running MMR classification (`mmr`), annotation and its log |
| PUT `/api/participants/{pid}/activities/{id}/annotation` | validated annotation update; records a new Running MMR calculation; returns the detail |
| POST `/api/participants/{pid}/imports/preview` | dry-run validation (transaction rolled back), honouring `apply_corrections` |
| POST `/api/participants/{pid}/imports` | transactional import; server-side repeat guard (`confirm_repeat`) |
| GET `/api/participants/{pid}/imports`, `/api/imports/{id}` | import history and rows |

Dates are UTC `YYYY-MM-DD`, inclusive. The legacy 5K score and race Elo routes (`/overview`, `/history`, `/explain`,
`/recalculations`, `/comparison`, `/method`, `/demo/load`, `/elo/*`, `/races/*`) were archived on 2026-10-25 and
now return 404; their previous description is in the local backup `archive/2026-10-25-before-cleanup/docs/API.md` (not in the repository).


## Running MMR (`runrank/api_mmr.py`, method in `docs/RATING_METHOD.md` Part A)

Every value is computed by `runrank/mmr.py` from one runner's stored activities. The default `as_of` is now, or the latest activity in demo mode.

| Method and path | Purpose |
|---|---|
| GET `/api/mmr/participants/{pid}?as_of=` | estimate (MMR, 10 km-equivalent, evidence-coverage label in `status`, setter, `cap` (always null since v2), evidence counts), data quality, evidence by distance, training volume (separate), recent changes with reasons, stored calculations |
| GET `/api/mmr/participants/{pid}/history?as_of=` | reconstructed estimate at every activity start and weekly, each with an explanation |
| GET `/api/mmr/participants/{pid}/explain?at=` | before, after and reasons at one history instant |
| GET `/api/mmr/participants/{pid}/observations` | every activity classified: informative, T10, reasons, flags |
| GET `/api/mmr/participants/{pid}/activities/{aid}/effect` | the estimate at the activity's start without vs with it, and why |
| GET `/api/mmr/comparison?as_of=` | every runner's own estimate on the absolute scale. Ranked only at medium or high evidence coverage, per data kind |
| GET `/api/mmr/method` | parameters, meaning, scale examples, limitations |
| POST `/api/demo/histories` | load the seven synthetic histories (demo database only; idempotent) |

`/api/participants/{pid}/activities/{id}` also returns `mmr` (informative, reasons, flags, T10, points).

## Ratings Lab (experimental; `runrank/api_lab.py`, method in `docs/RATING_METHOD.md` §A15)

Nothing is stored. Overrides exist only in the query string: `exclude` (recordings), `exclude_effort` (a recording and its identified duplicates under the method's rule), `confirm`, `keep_separate` and predeclared parameters. Responses include `override_impact` (removed ids; result without vs with Lab overrides) and, for method A, `comparator`.

| Method and path | Purpose |
|---|---|
| GET `/api/lab/meta` | methods, parameters, scales, anchors, and `sources` (synthetic; the app's database with its kind and availability) |
| GET `/api/lab/runners/{key}`, `.../activities/{aid}` | built-in synthetic runner (fixed reference date); never opens the database |
| GET `/api/lab/db/runners` | stored runners with data kind and activity counts (read-only connection) |
| GET `/api/lab/db/runners/{pid}?as_of=&method=&...` | stored history evaluated by the Lab; `as_of` defaults to today (UTC); stored exclusions and not-a-duplicate annotations applied; provenance and coverage notes |
| GET `/api/lab/db/runners/{pid}/activities/{aid}` | one stored activity: components without vs with it |
| GET `/api/lab/compare` | synthetic runners under every configuration |
