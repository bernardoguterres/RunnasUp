# Acceptance: walkthrough and verification status

Everything here uses **synthetic** data in the separate demo database. Expected values come from `docs/RATING_METHOD.md`, and synthetic results show implementation behaviour only.

## 1. Verification status

| What | How it is checked | Status |
|---|---|---|
| Production effort cap removed (`mmr-envelope-v2`) | `tests/test_mmr.py`: any label gives an identical score; label change keeps the score; v1 provenance rows preserved. Lab method A now passes I1 | passes |
| Running MMR arithmetic and behaviour | `tests/test_mmr.py`: hand values from `math.log`; easy, longer and hilly runs; uploads; declared effort; inactivity; ultras; duplicates; prefix stability | passes |
| Running MMR, frozen-method review (effort-cap counterexamples C1–C7; new robustness scenarios R1–R8; sensitivity) | `tools/mmr_experiment.py` §5–6 → `docs/evidence/mmr_experiment.txt`; summarised in `docs/RATING_METHOD.md` §A12 | R: 3 pass, 6 fail (model shortcomings, reported, not tuned) |
| Ratings Lab experiment (methods A–D; invariants, desired behaviour, grid, seeds, held-out; exp5) | `tools/rating_lab.py` → `docs/evidence/rating_lab.txt` and `rating_lab/*.svg`; `tests/test_lab.py` (hand values) | B: all invariants, 9/9 desired; D: 7/9; A rejected (fails label invariance) |
| Ratings Lab over stored histories (read-only; 2026-10-23) | `tests/test_api_lab_db.py`: synthetic CSV through the importer; result equals direct calculation and hand arithmetic (1790.33); stored exclusion, not-a-duplicate, missing moving time, < 3 km and Ride states; every table and the file bytes unchanged; no `store.connect` on Lab routes; today default; old/empty histories explained. Journey L in `docs/evidence/journeys_api.txt` | passes (API and headless only; no browser) |
| Lab exclusion semantics and method A parity (2026-10-23) | `tests/test_api_lab_db.py`: recording vs effort exclusion on a duplicate pair with separate activities (hand values 1916.70 / 1814.24), no grouping of ambiguous overlaps or not-a-duplicate pairs; A equals production on the duplicate history, after Lab exclusions vs the same stored exclusion, and on 35 demo comparisons. Production reports unchanged | passes (API and headless only) |
| Ratings Lab never writes stored ratings | `tests/test_api_lab.py::test_lab_controls_never_change_stored_ratings`: identical database bytes, MMR and Elo after every control | passes |
| Running MMR candidate choice | `tools/mmr_experiment.py` → `docs/evidence/mmr_experiment.txt`: 13 scenarios with expectations written first, 7 archetypes, sensitivity | B meets all 13; A fails 7 |
| API contracts | `tests/test_api*.py`, `tests/test_mmr.py`: keys checked against `web/src/api/types.ts` | passes |
| **React frontend** | `web/src/**/*.test.tsx` (Vitest + jsdom). MMR and Lab pages use real API responses (`tools/export_fixtures.py`) | passes. **No browser** |
| Full-history import → MMR → add a run → explanation → restart; runner, import, annotation, CSV, restart and crash journeys | `tools/journeys.py` (in-process API) → `docs/evidence/journeys_api.txt` | 26 checks pass (2026-10-25) |
| MMR stays uncoupled after the archive | `tests/test_mmr.py::test_mmr_stays_uncoupled_after_race_elo_was_archived`: no live module imports the archived race or legacy modules; `mmr.py` imports the standard library only | passes |
| Archived routes are gone | `tests/test_api.py::test_archived_routes_are_gone`: legacy and race routes return 404 | passes |
| Server binding | `./run.sh demo`, then `lsof -nP -iTCP:8600 -sTCP:LISTEN` | observed `127.0.0.1:8600` only |
| Real browser: rendering, 390, 768 and 1440 px, focus, contrast, downloads, console | — | **NOT DONE.** Browser tools are denied (`"mcp__*"`); see `docs/proposals/install-browser-testing.sh` (unapplied). No screenshots exist |
| Real exports, calibration | — | **NOT DONE:** no real data supplied |

**Commands:**
- `.venv/bin/python -I -m pytest -q tests`
- `npm --prefix web test`
- `npm --prefix web run build`
- `.venv/bin/python -I tools/journeys.py`
- `.venv/bin/python -I tools/mmr_experiment.py`
- `.venv/bin/python -I tools/rating_lab.py`

Race Elo, the legacy 5K score and the Streamlit fallback were archived on 2026-10-25. Their verification rows,
walkthrough steps and evidence are in the local backup `archive/2026-10-25-before-cleanup/docs/ACCEPTANCE.md` (not in the repository).

## 2. Walkthrough (about 10 minutes, React app)

**Running MMR: the primary journey**
1. Run `./run.sh demo` and open http://127.0.0.1:8600. **Overview** shows *Upload a running history*. Click **Load synthetic histories**: seven invented runners. Loading again changes nothing.
2. In the top bar, select *Improving runner (synthetic)*. The MMR card shows:
   - **1869**, *High evidence coverage* (a heuristic label);
   - estimated ability **46:17** (10 km-equivalent), set by activity 750213 (5 km in 22:12);
   - an uncertainty line.

   Below it:
   - **Data quality:** 214 activities, 214 informative, 12 declared efforts, 33 hilly flags, and the missing-field counts;
   - **Training volume (not part of MMR)**;
   - **Evidence by distance**;
   - the history chart;
   - recent changes, each with a reason and an **Explain** link;
   - *What the app showed after each import or annotation*.
3. Select *Ultra specialist*. A warning notice reads *Some runs do not contribute to Running MMR*: 3 runs over 42.5 km (longest 160.93 km) are stored but do not change MMR, and ultra ability is not represented, with a link to those activities. The ultra band reads "over 42.5 km (ultra; not converted)".
4. **Import** with the improving runner selected: `examples/synthetic/mmr/add_runs_improving.csv`.
   - The preview shows 2 new rows.
   - Import it, then return to Running MMR: **1902**, set by 759002 (10 km in 45:30).
   - Its change reads "New best evidence: activity 759002".
5. **Activities** → 759001 (an easy 8 km): the Running MMR panel shows 1869 → 1869 and "an easier or slower run is not read as lower ability". Activity 759002: +33.57.
6. Import the same file again: *already imported*. Repeating it reports duplicates, and MMR is unchanged.
7. **Compare** shows every runner on the absolute scale, ranked only at medium or high evidence coverage. *Endurance*, *Returning* and *Recreational* are unranked, at low confidence.
8. On a run's activity page, tick *Exclude* and save: MMR recalculates, and the change is listed with a new stored calculation.

**Ratings Lab trial (experimental; method B; nothing is stored)**
1. Open **Ratings Lab (experimental)** (`/lab`). Choose *Marathon specialist*, method *B*, and set `long_performance` to **bridged**.
2. **Expected values:**
   - combined **2094.5**;
   - **performance 2159.3**, with "⚠ set by flagged activity 930265: review: ambiguous overlap with 930235…" shown next to the score;
   - **endurance 2029.6** (as of 2025-12-31).
3. The *How this score is determined* panel names:
   - activity **930265**: 42.195 km in 3:02:20 on 2025-11-17;
   - what raises and lowers each component;
   - the 50/50 exchange rate (1 % faster ≈ +19.5 performance points; 1 % longer ≈ +5.4 endurance points);
   - the unvalidated assumptions.
4. In the input table, **930235** (20.77 km starting during the race) shows state **held**: a segment inside a longer recording. **930265** shows **flagged**.
5. Click **Exclude** on 930265.
   - Expected: combined **2035.9**, performance **2073.6**, now set by 930264.
   - The warning next to the score disappears, and "Excluded in this Lab view only" is shown.
6. Click **Include all again**: combined **2094.5** again.
7. Change `speed_weight`: 0.75 gives combined **2126.9**; 0.25 gives **2062.0**. The components are unchanged (performance 2159.3, endurance 2029.6), and the weighting sentence names the new exchange rate.
**Ratings Lab on stored histories (demo database; synthetic)**
- Start `./run.sh demo`, load the demo histories, open `/lab`. The page opens on *Built-in synthetic examples*.
- Select **Histories in the currently selected application database: the demo database (synthetic runners only)**. The *Active source* box names it, the runner (e.g. *Consistent recreational (synthetic) — synthetic*), **As of 2026-10-23 (today (default))**, and the method version and parameters.
- Observed through the live API on 2026-10-23 for that runner, method B: today 1320.1 (speed 1380.9, endurance 1259.4; 162 activities *outside window*); *Use the latest activity date* (2025-12-30): 1491.1 (1648.3 / 1333.9); speed_weight 0.25: 1412.5; method A: 1648.32, identical to the stored production MMR. Demo database bytes identical before and after.
- In the *Exclude (Lab only)* column, **Recording** removes one activity; **Effort (ids)** appears only on identified duplicates and removes them all. The *Lab exclusions* panel lists the removed ids and the score without → with. Observed via the live API for the demo runner above: recording 209 removes [209]; effort 209 removes [209, 210] under B; under A, production's rule does not pair them, so the effort is [209] alone; combined unchanged (neither sets a component); method A 1648.32 = production; database bytes identical.
- In the input table, a stored exclusion shows *excluded (stored)* with its note and no Exclude button; unsupported rows give their reason; *Stored as* shows the source id, import file and missing fields.

8. Navigate to another page and back. By the code, Lab selections are React component state and **reset** to runner *Beginner*, method B and defaults; they are not persisted. This has not been observed in a browser.
- **Not yet observed in a browser:** rendering, desktop and phone layouts, keyboard navigation and focus, chart readability, console errors, and selection persistence. All values above were checked against the running API (2026-10-23).
9. Optional: *Beginner*, method B: endurance **1128**, and **Explain** on the 8 km run. *Compare runners* shows all seven runners and the matched "what B rewards" table.

**Persistence**
- Restart `./run.sh demo`: everything persists, and the reconstructed histories are identical. `./run.sh demo-reset` deletes only the demo database.

## 3. Manual browser checks still required

Walk through §2 at 390, 768 and 1440 px widths and check:
- no page-wide horizontal scroll, and wide tables scroll inside their own frame;
- a visible focus outline when tabbing, and the skip link;
- readable charts;
- **Download CSV** files that match the tables;
- no errors in the browser console.

Record anything that looks wrong. No one has done these checks yet.

## 4. Evidence files (synthetic, reproducible)

| File | Produced by |
|---|---|
| `docs/evidence/mmr_experiment.txt` | `tools/mmr_experiment.py`: scenarios with expectations, candidates A and B, 7 archetype trajectories with explanations, sensitivity, separation check. Also writes `examples/synthetic/mmr/*.csv` and `manifest.json` deterministically |
| `docs/evidence/journeys_api.txt` | `tools/journeys.py` (journeys M, L and the runner, import, annotation, export and restart journeys) |
| `docs/evidence/rating_lab.txt`, `rating_lab/*.svg` | `tools/rating_lab.py`: Ratings Lab methods A–D on the synthetic runners |
