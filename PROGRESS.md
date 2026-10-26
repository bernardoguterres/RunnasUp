# RunnasUP progress

**Updated:** 2026-10-25. This file is the single place for status, blockers, pending decisions and the next action.
History lives elsewhere: method and experiment detail in `docs/RATING_METHOD.md` (§A12–A15 for the MMR review and
Ratings Lab rounds), and verification evidence in `docs/ACCEPTANCE.md` §1.

## Current state

**Running MMR `mmr-envelope-v2` / `mmr-scale-v1`: primary, implemented.**
- **Estimate:** a personal ability estimate from one runner's own activities. Each informative Run of 3–42.5 km
  becomes a Riegel 10 km-equivalent; the score is the best aged converted evidence in 365 days.
- **Effort labels:** context only and never change the score (the v1 cap was removed; v1 rows keep their version).
- **Evidence coverage:** a heuristic label, not calibrated confidence.
- **Scale:** a fixed logarithmic mapping, not a population ranking.
- **Ultras:** do not contribute (shown as such); the requirement is not met (§A13).

**Ratings Lab `ratings-lab-exp5`: experiment, Method B preferred but not promoted** (§A15; `/lab`).
- **Data:** synthetic examples, or stored histories through a read-only connection (`runrank/lab_source.py`;
  SQLite `mode=ro` plus `query_only`).
- **Method A:** reuses production preprocessing (`mmr.classify_history`) and equals production in every
  comparison tested.
- **Exclusions:** recording-level and effort-level exclusions are temporary and show their score impact.

**Archived (2026-10-25, user direction):** race Elo, the legacy 5K score and the Streamlit fallback are removed
from the app.
- **Where they are:** code, tests, docs and evidence are unchanged in the git-ignored local backup
  `archive/2026-10-25-before-cleanup/`, which is
  a full pre-cleanup copy of every edited file (see `archive/README.md`).
- **Stored data:** databases keep their race and legacy tables and rows; the schema (v5) is unchanged.
- **Moved, not removed:** the duplicate rule and the training-volume summary now live in
  `runrank/activity_rules.py`. They were checked identical on every demo runner and 2,000 random histories.

**Frontend:** React is the only UI (redesigned and renamed RunnasUP, 2026-10-23). **The visual result is
unverified**: no browser check has been possible.

**Name:** the display name is RunnasUP. The compatibility names stay: `runrank/`, `RUNRANK_DB`, database
filenames, `runrank.*` storage keys and the session lock. `docs/evidence/` and the protected hook keep the old
name.

**Checks (2026-10-25, after the archive):**
- pytest 115 passed; Vitest 38 passed; type-check and build OK; API journeys 26 checks, 0 failed.
- The 108 pytest and 12 Vitest tests removed were for the archived features.
- **MMR and Lab unchanged, independently checked:**
  - regenerated frontend fixtures match the old ones apart from run timestamps and today's date;
  - the MMR experiment report differs only in its race-separation lines, and all 9 MMR example files are
    byte-identical;
  - the Lab report body and its charts are identical;
  - journey values match the earlier ones (1647.4, 1797.36, 1790.33, 1923.96).
- Status per area is in `docs/ACCEPTANCE.md` §1.

**Safeguards:** unchanged. SHA-1 values: `settings.json` 567a9e75c866…, `guard_bash.py` e5850704e9c2…,
`test_guard_bash.py` b6207a6f2185….

**Git:** private repository `github.com/bernardoguterres/RunnasUp`, branch `main`, created 2026-10-25/26 by the
user, who makes every commit (sole author, conventional-commit messages, no co-author lines). `.gitignore`
excludes `data/`, Strava export shapes, secrets, environments, caches, builds, local tool state, `archive/`, and
(as in the user's other repos) `.claude/` and `CLAUDE.md`, which stay on disk and keep working locally. The agent
has staged, committed, pushed, deployed and uploaded nothing.

**Cleanup (2026-10-25):**
- Removed regenerated caches: `__pycache__/`, `.pytest_cache/`, `web/tsconfig.tsbuildinfo`.
- Deleted the accidental empty database `data/runrank.sqlite.accidental-empty` (0 rows in every data table,
  re-checked before deletion).
- Archived the three features above.
- Removed dead code left behind: 35 CSS classes, 5 formatters and 2 Python helpers (3 of the classes, 1 formatter
  and both helpers were already unused before).
- Renamed `tools/export_elo_fixtures.py` to `tools/export_fixtures.py`.
- Rewrote this file from a dated log to current state.

## Blockers
1. **Browser verification.** `.claude/settings.json` still denies `"mcp__*"`. The ready, unapplied installer is
   `docs/proposals/install-browser-testing.sh`; details are in `browser-testing-permissions.md`.
   - **Installer:** syntax-checked only, never executed. Its embedded validator was not tested separately,
     because the Bash guard blocked the synthetic fixture.
   - **Fail-closed:** depends on `"onFailure": "block"`, verified on Claude Code 2.1.309 only. `|| exit 2` does
     not cover timeouts.
2. **Real data.** No real Strava export or race results have been supplied, so the CSV layout, calibration and
   validity are unknown.

## Known trade-offs (not fixed)
- **MMR modelling:**
  - a runner who never runs hard is under-estimated;
  - Riegel k = 1.06 favours endurance types (sensitivity up to ±113 points);
  - the recency rate drives declines (up to 208 points for a returning runner);
  - there is no elevation adjustment, so net-downhill runs can overstate;
  - saving only a fast segment raises MMR.
- **Frozen-method robustness:** 3 scenarios pass and 6 fail (GPS noise, downhill, saved segment, endurance
  profiles, threshold step; §A12). These failures are reported, not tuned away.
- **Other:**
  - the comparison as-of date defaults to each runner's latest activity in demo mode, otherwise today;
  - `localStorage` is shared between the demo and personal databases;
  - the repeat-import guard matches identical bytes only;
  - npm needs `legacy-peer-deps`;
  - `requirements.lock` still lists Streamlit, pandas, altair and their dependencies, which nothing imports any
    more. Left in place: trimming it safely needs a fresh install to verify.

## Decisions pending (user)
- **Ratings Lab:**
  - the speed/endurance weight, as an exchange rate (§A15.3);
  - corroboration of new capacity (k = 2) or provisional display (current);
  - whether a faster long run should count.
- **Ultras:** whether to build the bounded within-band estimate (§A13).
- **MMR parameters:** 3–42.5 km, k = 1.06, the recency rate, the 365-day window, coverage thresholds.
- **Effort data:** whether perceived exertion or heart rate should ever inform MMR. This needs real data first.
- **Dependencies:** whether to trim `requirements.lock` (needs a network install to verify).

## Next action
1. **User:** run `cd ~/Desktop/"Strava Elo" && /bin/bash docs/proposals/install-browser-testing.sh`, then
   connect an isolated, account-free Chrome profile with `/chrome` while `./run.sh demo` runs.
   - **My first session:** check enforcement first (the hook fires, local navigation is allowed, external
     navigation is refused) and stop if any check fails. Then inspect Overview, Activities, Compare, Import and
     Ratings Lab at 1440×900 and 390×844, plus keyboard use and 200% zoom.
   - **Without the installer:** run `docs/ACCEPTANCE.md` §2 yourself.
2. **User:** place a real Strava export under `data/`, run `.venv/bin/python -I tools/inspect_export.py data/<file>`
   (read-only), import it in `./run.sh`, then review it in `/lab` against your stored history (README "Ratings
   Lab"). Evaluate against later race results before tuning any parameter.
