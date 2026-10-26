# RunnasUP rating method (authoritative)

This is the single authoritative description of RunnasUP's rating, **Running MMR `mmr-envelope-v2`** (since
2026-10-22: no effort cap; v1 calculations keep their own version), displayed on scale `mmr-scale-v1`. It is a
personal ability estimate from one runner's own activity history. Parameters: `PARAMS` in `runrank/mmr.py`. The
Ratings Lab (§A15) holds an experimental speed and endurance profile; Method B is preferred there but not promoted.

**Archived on 2026-10-25:** race Elo (`pairwise-elo-v1`, formerly Part B) and the legacy 5K score
(`best5k-90d-v1`, formerly Part C) were removed from the app. Their method text, code, tests and evidence are kept
unchanged in the local backup `archive/2026-10-25-before-cleanup/`, which is not in the repository (this file's full
previous version is `archive/2026-10-25-before-cleanup/docs/RATING_METHOD.md`). Existing databases keep their race and legacy tables
and rows; nothing reads or writes them any more. Running MMR was never coupled to either, so no MMR value changed.

Every parameter is a provisional choice made by the assistant under delegated authority. None has been reviewed by
the user or calibrated on real data, and every example uses invented runners.

# Part A: Running MMR

## A1. What it measures, kept apart from everything else

| Quantity | Meaning | Where |
|---|---|---|
| Observed performance | each run's recorded distance and elapsed time (pace = elapsed / distance, never counted twice) | activity pages |
| **Estimated ability** | a **10 km-equivalent time T̂10**: the best converted evidence of how fast this runner can currently run. It is an *estimate*: the distance conversion can be wrong in either direction | MMR overview |
| Displayed MMR | the points mapping of T̂10 (§A6) | MMR overview, compare |
| Evidence coverage | a **heuristic label**, not calibrated statistical confidence: how many runs support the estimate, the age of the best evidence, and whether a declared maximal effort confirms it | MMR overview |
| Training volume | km and runs in the last 28 days; active weeks | shown separately; **never** part of MMR |

Running MMR is **not Elo**: there are no opponents and no win probabilities. A difference of about 20 points means about 1 % of speed.

## A2. Inputs (only what the importer provides)

| Field (Strava `activities.csv`) | Use |
|---|---|
| Activity Type | only `Run` is informative. `Trail Run` (terrain) and `Virtual Run` (treadmill) are kept for exploration only |
| Distance (metres) and Elapsed Time | the single conversion (§A3) |
| Start date | evidence age and history order |
| Effort annotation (set in RunnasUP: easy, moderate, **hard** or **race**) | hard and race mark a near-maximal effort; can only **lower** older evidence (§A4) |
| Exclude / not-duplicate annotations | eligibility |
| Elevation Gain | **flag only**: 20 m/km or more of climbing is flagged *hilly* (§A7) |
| Moving time, Average Heart Rate, Perceived Exertion | **displayed only**; missing values stay missing |
| GPS tracks and streams | never read |

File, column and row rules: §A11.

## A3. Which runs are informative, and the one conversion

All valid activities are stored and browsable. A run is **informative** when all of the following hold:
- type `Run`;
- **3 ≤ d ≤ 42.5 km**;
- not a possible duplicate, using the import rule: same type, start within 120 s, distance within 2 %;
- not excluded;
- 10 km-equivalent not faster than 26:00, which would be implausible.

```
T10_i = elapsed_i × (10000 / distance_i) ^ 1.06        (Riegel 1981; one conversion of (distance, time))
```

**Supported range:**
- The range 3–42.5 km is an **engineering choice**. Riegel's exponent was fitted to record performances, commonly cited for roughly 3.5–230 minutes; that citation is from memory and was not re-checked this session.
- Runs over 230 min are flagged.
- Ultras over 42.5 km and runs under 3 km are **not converted**. Extrapolating a road formula to 100 miles is not defensible. They appear as **distance-specific evidence** (count, fastest pace, longest) and never change MMR.

## A4. The estimate (`runrank/mmr.py: estimate_at`; `mmr-envelope-v2`)

Effort is normally unknown, so **no single run is read as the runner's maximum**: an easy 8 km shows at least that level was run. After conversion, each value is only an *estimate* of 10 km ability. A converted value can overstate ability (GPS noise, downhill, a saved fast segment, a personal endurance profile; see §A12) as well as understate it. At an instant T, using informative runs with T − 365 d < start ≤ T:

```
aged_i = T10_i × (1 + 0.0005 × max(0, age_i − 30 days))          recency assumption (A5)
T̂10    = min_i aged_i                                            effort labels play no part (v2)
```

**Consequences:**
- **Easy, slower, longer or hilly runs never lower MMR.** They are weaker evidence.
- **More uploads add nothing.** Only the best evidence counts, and volume is shown separately.
- **Effort labels are context only (v2).** Changing an easy / hard / race label never changes MMR (tested for every label). A recent hard or race label that agrees with the estimate within 3 % can raise the *evidence-coverage label* from medium to high; it never changes the number.
- **What v1 did:** `mmr-envelope-v1` let a later hard/race label cap older evidence at 3 % better than it. One weaker declared effort could lower MMR, so withholding a label paid (§A12). The user removed this rule on 2026-10-22.
- **Provenance:** stored v1 calculations (`mmr_runs`) keep `algorithm_version = mmr-envelope-v1` and their parameters; new calculations are stored as v2.
- **The only path down** is now time: the recency assumption (A5), and evidence leaving the 365-day window.
- **Splitting:** a 10 km in 49:00 converts to 49:00; either 5 km half in 24:00 converts to 50:02, so the whole is the better evidence. Cropping only the fast part of a run is genuine evidence of that part and can raise MMR (a known limitation).

## A5. Recency, inactivity and uncertainty

**The point estimate declines only by the recency assumption:** evidence keeps full value for 30 days, then counts 0.05 % slower per day (1.5 % per 30 days). After 365 days it is not used at all, and the result is *insufficient evidence*.
- This is an **assumption**, not measured detraining. It is explicit in every explanation, e.g. "Recency assumption: evidence from activity X is 130 days old, so it counts 5.00 % slower than recorded".

**Evidence coverage is separate from the estimate.** It is a heuristic label, not calibrated confidence:

| Label | Rule |
|---|---|
| **high** | at least 2 runs support it (within 3 % of T̂10); the best evidence is no more than 180 days old; and a declared hard or race effort in the last 90 days agrees within 3 % |
| **medium** | at least 2 runs support it, and the best evidence is no more than 180 days old |
| **low** | otherwise |
| **insufficient evidence** | no informative run in 365 days; no number is shown |

- Inactivity therefore shows up as **lower evidence coverage**, and as a decline only through the stated recency rate.
- Unless a recent declared effort confirms it, the interface says ability may be higher, or that the conversion may misjudge it.

## A6. Display scale (`mmr-scale-v1`; `runrank/mmr.py: points`)

A **fixed mapping** of T̂10 onto points. It is not a population ranking and not a validated ability scale.

```
MMR = 3000 × ln(7200 s / T̂10) / ln(7200 / 1560),   clamped at 0
```

**Scale points:**

| 10 km-equivalent | 2:00:00 | 1:20:00 | 1:00:00 | 50:00 | 45:00 | 40:00 | 30:00 | 26:00 |
|---|---|---|---|---|---|---|---|---|
| MMR | 0 | 795 | 1360 | 1717 | 1924 | 2155 | 2719 | 3000 |

**How the mapping was chosen:**
- **Logarithmic in speed,** so equal speed ratios give equal point differences anywhere on the scale: 1 % ≈ 19.5 points.
- **Fixed anchors:** a 12 min/km walk-jog is 0, and roughly world-class is 3000.
- **Absolute:** the same history gives the same MMR whoever else is imported. Adding a runner never rescales anyone (tested).

**What the scale does not mean:**
- There is no normal-distribution forcing and no percentile; no reference population exists.
- Race-Elo win probabilities do **not** apply.
- The anchors are a provisional, versioned convention.

## A7. Elevation, heart rate and effort

**Elevation**
- **Available:** the importer reads only *summary* ascent (`Elevation Gain`). Strava's CSV may also carry loss, high and low, and grade columns; that is the assistant's recollection, not imported and unverified. Distance and elevation samples exist only in the GPS files, which are never opened.
- **Gradient-based methods (not possible here):** methods such as the energy cost of running on gradients (Minetti et al., *J Appl Physiol* 2002, cited from memory) and grade-adjusted pace need those samples, smoothed, distance-aligned and with extreme grades handled.
- **Summary-only correction (rejected):** total ascent does not describe the route. 300 m spread over a whole course and 300 m in one steep climb cost differently. Ascent and descent do not cancel, and descent is not imported, so net-downhill courses cannot be detected.
- **Decision:** **no elevation adjustment.** Values stay unadjusted. A hilly run (20 m/km or more) is flagged as "probably understates", which is safe under the lower-bound model, and cannot cap older evidence.
- **Limitation:** a net-downhill run can overstate.

**Heart rate**
- Not used. Lower heart rate is not "better" across people. A personal pace–heart-rate model would need clean, calibrated data per runner, which isn't available yet.
- A missing value, or an erroneous one (e.g. 300, which the importer stores as missing), cannot change MMR.

**Perceived effort**
- Not used; the CSV value is self-reported. Only the explicit RunnasUP *hard/race* annotation is used, and only in the direction that lowers older evidence, so effort can never be a bonus.

## A8. History, explanations, imports (`history`, `explain`, `counterfactual`; `runrank/store.py: mmr_observations, _record_mmr`)

**History and explanations**
- **History:** a deterministic reconstruction from the *current* stored activities, at every activity start and weekly in between. It is labelled as a reconstruction.
- **Change explanations:** each change gets a plain-language reason:
  - new best evidence;
  - the recency assumption;
  - a declared effort capping older evidence;
  - evidence leaving the 365-day window;
  - an evidence-coverage change;
  - aging of a capping declared effort.
- **Per-activity effect:** shows the estimate at the activity's start **without vs with** it, and why. An easy run says "evidence that does not beat the current estimate".

**Imports and stored calculations**
- **Duplicate import:** identical rows are duplicates and change nothing (tested).
- **Late historical import:** it changes the estimate only from its own date onward. Earlier history points are identical (prefix stability, tested).
- **Corrections and exclusions:** these recalculate.
- **What the app showed:** after every import or annotation, an `mmr_runs` row stores the version, parameters, trigger and the MMR at the latest activity.

## A9. Candidate comparison and worked examples

**Candidates.** Two were compared (`tools/mmr_experiment.py` → `docs/evidence/mmr_experiment.txt`), with the expected direction of 13 controlled scenarios written before computing:
- **A: recency-weighted mean** of 10 km-equivalents over 90 days, half-life 30 days. It failed 7 of 13 under v1 expectations (S1, S3a, S4, S5, S6, S7, S12), and 8 under v2, where S3b expects labels to change nothing:
  - easy runs, longer runs and hills pulled it down;
  - 100 easy uploads dropped it 666 points;
  - it went blank after 90 days.
- **B: aged lower-bound envelope (chosen).** It met all 13 scenarios.

**Counterexamples investigated and fixed**
- **Hilly declared race (v1; moot in v2, where labels never cap):** a hilly declared race capped older evidence and pulled the returning runner below the generator's truth. Hilly and over-230-minute efforts now cannot cap.

**Remaining counterexamples (accepted, see A10)**
- **Endurance runners:** their marathons convert optimistically, by about 4 % at a personal exponent of 1.03.
- **Riegel exponent:** the exponent choice moves runners by up to ±113 points.
- **Recency rate:** the rate moves the returning runner by up to 208 points.

**Hand-worked values** (`tests/test_mmr.py`; computed independently with `math.log`):

| Case | Arithmetic | Result |
|---|---|---|
| 10 km in 45:00 | T10 = 2700; 3000 × ln(2.6667) / 1.5293952 | **1923.96** |
| 5 km in 24:00 | 1440 × 2^1.06 = 1440 × 2.084931 | T10 = **3002.30 s** (50:02) |
| half marathon in 1:42:00 | 6120 × (10000 / 21097.5)^1.06 | **2773.75 s** (46:14): slower than 45:00, so no change |
| 45:00 seen 130 days later | 2700 × (1 + 0.0005 × 100) = 2835 | **1828.25** |
| 45:00, then three declared 47:00 | v2: labels ignored; 45:00 at day 21 is within the 30-day grace | **1923.96** (v1 gave 1898.40 through the cap) |
| added 10 km in 48:00 (journey M) | 3000 × ln(7200 / 2880) / 1.5293952 | **1797.36** |
| 1 % faster | | **+19.52** |

**Synthetic histories (7 archetypes, imported through the real importer, as of 2025-12-31):**

| Runner | Generator's true 10K | MMR | T̂10 | Evidence coverage |
|---|---|---|---|---|
| fast short-distance | 34:00 | 2425 | 34:52 | high |
| endurance | 40:00 | 2157 | 39:57 | low |
| improving | 55 → 45:00 | 1869 | 46:17 | high |
| ultra | 46:00 | 1847 | 46:49 | medium |
| returning after a gap | 42 → 48:00 | 1732 | 49:38 | low |
| recreational | 50:00 | 1647 | 51:49 | low |
| beginner | 70 → 62:00 | 1213 | 1:04:39 | medium |

The generator's assumptions are listed in the report. Its own normal-ish effort model is not evidence about real runners.

## A10. Parameters, limitations, evidence needed

**Parameters (P), all provisional**

| Parameter | Value |
|---|---|
| informative types | `Run` |
| conversion range | 3–42.5 km |
| Riegel k | 1.06 |
| implausibility floor | 26:00 per 10 km-equivalent |
| grace period | 30 days |
| aging | 0.05 %/day |
| window | 365 days |
| support tolerance | 3 % |
| hilly flag | 20 m/km |
| scale anchors | 7200 s = 0 and 1560 s = 3000 |

Changing any of these requires a new `ALGORITHM_VERSION` or `SCALE_VERSION`.

**Limitations**
- **Under-estimation:** a runner who never runs hard is usually under-estimated (R7: −359 points). Evidence coverage is a heuristic and does not quantify this.
- **One Riegel exponent:** it fits some runners better than others; personal endurance profiles differ.
- **Recency rate:** an assumption, not measured detraining.
- **No elevation, surface, weather or heat correction.** Net-downhill runs may overstate.
- **Measurement:** GPS distance errors move T10 about one-for-one. Elapsed time includes stops, which understates.
- **Cropping:** saving only a fast segment raises MMR.

**Evidence needed:** real histories with labelled race results. The test is whether T̂10, computed only from earlier data, predicts later race times (chronological split); that would set k, the recency rate, the cap and the confidence thresholds.

## A11. Activity import rules (shared importer: Strava `activities.csv`; `runrank/strava_csv.py`)

- **Upload:** a bare CSV, or the export `.zip`, which must contain exactly one `activities.csv` at the root or one folder down.
  - The zip is rejected for unsafe paths or symlinks, or for damaged or encrypted members.
  - Limit 50 MB. GPS files are never opened.
- **Unverified layout:** the column layout is the assistant's recollection of Strava's export and has not been checked against a real export. Run `tools/inspect_export.py <file>` (read-only) first.
- **Columns:** headers are matched by name, and repeated names by order of appearance.
  - Required: `Activity ID`, `Activity Date`, `Activity Type`, `Elapsed Time`, and two `Distance` columns (display units, then metres).
  - Optional: `Moving Time`, `Average Heart Rate` (20–250), `Perceived Exertion` (1–10), `Elevation Gain` (0–10 000 m). An out-of-range or non-numeric optional value becomes missing, with a warning.

**Field rules:**
- **Date:** `Mar 1, 2024, 7:00:00 AM` plus 3 fallback formats, **assumed UTC**. A date before 1990 or more than a day in the future is rejected.
- **Distance:** the 2nd `Distance` column, in metres. The display value must agree with it within 2 % + 0.006 units, for ×1, ×1000 or ×1609.344. A blank display value gives a warning.
- **Duration:** the 1st `Elapsed Time`; the 2nd is a fallback. If both are present and differ by more than 1 s, the row is rejected. **Elapsed time is used, not moving time.**
- **Numbers:** plain decimals only. `5,000` and `1_500` are refused.

**Row rejected:**
- missing ID or type;
- bad date;
- distance or elapsed time ≤ 0, or their two columns disagree;
- wrong field count;
- an ID repeated in the file;
- an ID that belongs to another participant.

**Re-import:**
- an identical row is a duplicate;
- a changed row is a *conflict* (the stored version is kept) unless *apply corrections* is ticked;
- each corrected field is logged.

## A12. Critical review of the v1 method (historical: the effort cap reviewed here was removed in v2) (2026-10-22; `tools/mmr_experiment.py` §5–6)

**Method checked against code.** Every formula in A3–A6 matches the implementation:

| Rule | Implementation |
|---|---|
| Conversion | `ten_k_equivalent_s` |
| Aging and cap | `aged`, `estimate_at`; the cap uses only `can_cap` efforts, i.e. not hilly and ≤ 230 min |
| Evidence-coverage labels | `estimate_at` |
| Scale | `points` |

**Confirmed implementation defect (fixed).**
- **Problem:** while a declared effort's cap bound the estimate and aged, MMR fell (−57.9 points between day 40 and day 100), but the explanation said "No change: no new evidence beats the current estimate".
- **Fix:** the explanation now names the aging capping effort, and "No change" is only stated when nothing changed. Regression test: `tests/test_mmr.py::test_explanation_never_says_no_change_when_the_value_moved`.
- **Wording:** "lower bound", "confidence" and the scale description were also corrected. Numbers are unchanged.

**Effort cap: what it does (C1–C7)**

| Case | Result | Classification |
|---|---|---|
| C1: same history, 52:00 run unlabelled vs honestly labelled *hard* | 1924.0 vs 1700.1: **withholding the label gains +223.9** | model shortcoming (as specified: labels can only lower) |
| C2: one vs three declared 47:00 after 45:00 | identical, 1898.4: **one declared effort suffices**; only the latest counts | as specified (earlier docs wrongly said "repeated") |
| C3: poor declared race (50:00), then a normal 46:00 run | 1777.0, then 1880.8: later normal evidence overrides the cap | as specified |
| C3: poor declared race, then only easy runs | 1700.1 at day 120: the poor day keeps capping, and ages | model shortcoming |
| C4: declared 46:00, then later declared 49:00; import order reversed | both 1816.7: the later, weaker effort sets the cap; import order irrelevant | latest-only is a shortcoming; order-independence correct |
| C5: label removed later | 1924.0: full deterministic reconstruction | correct |
| C6 / C7: identical declared efforts at 199 vs 200 m gain, 229.9 vs 230.1 min | **steps of 146.9 / 146.0 points** | model shortcoming (hard thresholds) |

**Frozen-method robustness (R1–R8; intended behaviour stated first; the method was not tuned)**

| Scenario | Intended | Result |
|---|---|---|
| R1: GPS distance noise, sd 2 %, 30 identical efforts | within ±20 | **FAIL, +53.6** (the best-of rule selects favourable errors) |
| R2: downhill point-to-point 10 km, 4 % assisted, no gain recorded | not above ability | **FAIL, +80.1** |
| R3: fast 3 km segment saved separately, speed type (k 1.10) | not above ability | **FAIL, +94.5** |
| R4a / R4b: endurance type (k 1.02) halves only / speed type (k 1.12) 5 km only | within ±39 | **FAIL, +58.6 / +81.6** |
| R5: honest labels on 6 % and 3 % below-par races | labelling costs ≤ 20 | PASS, 0.0. In this order the cap barely binds; C1 shows the general failure |
| R6: 200-day gap, return at true 50:00 with easy runs only | ≤ +59 | PASS, +19.7 |
| R7: easy-only runner | coverage not *high* | PASS: −359.0, coverage *medium* |
| R8: 199 vs 200 m declared race | step < 5 | **FAIL, 127.2** |

**Sensitivity**
- **Aging rate:** it decides R6 alone. 0/day gives +206.7, 0.001/day gives −151.0.
- **Riegel exponent:** k trades R3 against R4. k = 1.03 gives R3 +165.3 and R4a +14.6; k = 1.10 gives R3 0.0 and R4a +117.2.
- **Cap tolerance:** it changes only the label cases (R5, R8).
- **Noise and downhill (R1, R2):** no parameter fixes them.

**Real observations that would distinguish the choices**
- **Recency rate:** race results after periods of easy-only training.
- **Exponent:** each runner's own results at two or more distances, giving a personal exponent.
- **Noise bias:** GPS distance compared with certified course distance.
- **Cap tolerance:** declared efforts compared with a race within a few weeks.
- **Downhill:** start and finish elevation, or net descent, for routes that are not loops.

## A13. Ultras: current non-contribution and recommended approach

**Current state:** runs over 42.5 km (and under 3 km) are stored, browsable and listed with their pace. The MMR page states in a notice how many there are and that they **do not change MMR**, and each activity page states why.
- An ultra specialist's MMR therefore reflects only their 3–42.5 km runs.
- **The requirement to represent ultra runners is not met.**

**Recommended bounded approach (not implemented):** a separate **distance-band estimate** for ultras.
- **Bands:** each band has its own reference distance, e.g. 50 km for 42.5–80 km and 100 km for 80–170 km.
- **Conversion:** only *within* a band, at most ±40 % of the reference distance, so there is never 10 km-to-100-mile extrapolation.
- **Exponent and limits:** the band exponent and terrain limits would be estimated from real multi-ultra histories before use.
- **Display:** shown next to MMR as "ultra evidence", never merged into it and never given a bonus.
- **Until then:** ultras remain evidence only.

## A14. Recommended next modelling decision (v1; resolved: the user chose (a), remove the cap, implemented as v2)

**Decide how declared efforts should work before tuning anything.** The cap is the only path by which MMR can fall on evidence, yet as specified it penalises honest labelling (C1) and steps at hard thresholds (C6, C7). Minimal options for the user to choose between, with no new parameters invented here:
- **(a) Remove the cap,** so labels never change MMR and declines come only from recency.
- **(b) Keep the cap but require that it is corroborated** by the next comparable effort.
- **(c) Replace the hilly and 230-minute exclusions with the existing flags only** (no capping exclusion), which removes the thresholds.

Then evaluate on real data (A10, "Evidence needed"). Until real data exists, every parameter stays provisional.

## A15. Experimental speed and endurance profile (Ratings Lab, `ratings-lab-exp5`; not the production formula)

**Status**
- This is an experiment on synthetic data only. **Method B is the preferred experimental direction; it has not been promoted.**
- **Production Running MMR is `mmr-envelope-v2`.** The effort cap was removed on 2026-10-22 at the user's explicit authorisation; see A4. Method B is not promoted.

**Where it lives**

| What | Where |
|---|---|
| Methods | `runrank/lab_methods.py` |
| Generator (kept separate) | `runrank/lab_synthetic.py` |
| Probes and tables | `runrank/lab_compare.py` |
| Entry point | `tools/rating_lab.py` → `docs/evidence/rating_lab.txt` and `rating_lab/*.svg` |
| Ratings Lab page | `/lab` |

**Method A in the Lab** is the *current production calculation*, called live (`runrank.mmr`). It is a comparator, not a frozen copy, and it changes if production changes.

### A15.1 Component definitions (method B)

**Speed S (points; recency-aged estimate of demonstrated running speed)**

```
eligible: type Run, 3 ≤ d ≤ 42.5 km, not a duplicate recording, T10 ≥ 1560 s (26:00)
T10 = elapsed_s × (10000 / distance_m)^1.06                      (Riegel; elapsed time, so stops slow it)
aged T10 = T10 × (1 + 0.0005 × max(0, age_days − 30)), within 365 days
S = 3000 × ln(7200 / best aged T10) / ln(7200 / 1560)            (10 km-equivalent 2:00:00 = 0, 26:00 = 3000)
```

**Endurance E (points; demonstrated distance completion, not estimated capacity and not sustained performance)**

```
eligible: type Run or Trail Run, ≥ 1 km, not a duplicate recording, pace not faster than 2:30/km
running pace f = clamp((1.1 L − pace) / (0.2 L), 0, 1),  L = 600 s/km × (km / 10)^0.10   (walking anchor)
              pace = moving pace; elapsed pace when moving time is missing (never more favourable)
continuity    exp3 default "label": shown as continuous / with stops (x %) / unknown; NOT subtracted
              exp2 "scalar" (kept for comparison): c = 1 up to 5 % stopped, then max(0.5, 1 − (stopped − 0.05)),
              missing moving time -> 0.5
credited km = recorded distance × f [× c in scalar mode]; aged = credited / (1 + 0.0005 × max(0, age − 30)); 365 d
E = 3000 × ln(best aged credited km) / ln(250)                   (1 km = 0, 8 km = 1130, 42.2 km = 2033, 100 km = 2502)
```

**What the components mean**
- E rewards having *completed* a distance. Its units are km of completed distance on a log scale.
- **Missing distance evidence is not low ability:** a component with no eligible activity is shown as missing, never as zero.
- **Combined score:** w × S + (1 − w) × E. Both are fixed scales, but the slopes differ: 1 % faster = +19.5 S, while 1 % longer = +5.4 E. At 50/50, one per cent of speed is worth about 3.6 % of distance. The weight is a product choice.
- **Evidence status:** a component is **provisional** when no other independent session supports it within 3 %, or when it is set by an activity in an ambiguous overlap.
- **Credibility (exp3; §A15.8):** a new best counts at once only when it passes explicit checks. Otherwise it is *pending review* and counts for nothing until corroborated or excluded. **Flags never delete data.** Summary data cannot reliably tell a bike ride from a run, and the checks catch only the listed patterns.

### A15.2 Evidence handling (exp2; `prepare`)

| Class | Rule | Rating treatment |
|---|---|---|
| Same activity id | uploaded twice | counted once |
| Exact duplicate | same type, starts within 120 s, distance and elapsed time within 2 % | one copy used. The others stay listed as dropped |
| Probable duplicate recording | same type, ≥ 80 % time overlap of *both* activities, distances within 10 % | the copy **with moving time** is used, then the earlier start, then the smaller id. **Not the longest.** Originals preserved |
| Ambiguous overlap | any other overlap: different types, a crop, a watch left running | **both kept** and judged on their own validity, flagged for review, and put in the same session so they can never corroborate each other. A Walk, or a watch-left-running Run, cannot suppress a genuine run |
| Separate sessions | no overlap, more than 10 min apart | independent |

Cases 15a–15d test same-type and different-type overlaps.

**Continuity is a separate, continuous factor:**
- **No cliffs:** 4.9 / 5.0 / 5.1 % stopped on 100 miles in 26 h give E 2760.7 / 2760.7 / 2760.1; 14.9 / 15.0 / 15.1 % give 2704.0 / 2703.4 / 2702.8; 54.9 / 55.0 / 55.1 % (floor) give 2385.2 / 2384.1 / 2384.1. Invariant I10 checks this.
- **Realistic ultras:** 100 km with 8 % aid stops is credited as 97 km (2485.6); 24 h, 160 km with 20 % rest as 136 km (2669.2).
- **Missing moving time:** the same 24 h race without moving time is credited as 80 km (2380.9). That is never higher than any known case, but not erased.

### A15.3 What B rewards (default parameters; change in points; `docs/evidence/rating_lab.txt` §8)

| Change | Speed | Endurance | 75/25 | 50/50 | 25/75 |
|---|---|---|---|---|---|
| 5 km best 25:00 → 23:00 | +163.6 | 0 | +122.7 | +81.8 | +40.9 |
| longest run 5 → 8 km (5:45/km) | 0 | +255.4 | +63.8 | +127.7 | +191.5 |
| longest run 20 → 30 km (6:20/km) | 0 | +220.3 | +55.1 | +110.2 | +165.2 |
| same 20 km faster (6:00 → 5:30/km) | **0** | **0** | 0 | 0 | 0 |
| speed specialist adds a slow 25 km | 0 | +498.9 | +124.7 | +249.5 | +374.2 |
| ultra specialist adds an easy 6 km | 0 | 0 | 0 | 0 | 0 |

**Reading the table**
- **Log scales reward ratios:** 5 → 8 km (×1.6) earns more than 20 → 30 km (×1.5).
- **One slow long run is worth a lot:** the speed specialist's first 25 km is worth about three 5 km improvements of 25 → 23 minutes at 50/50.
- **B does not reward a faster long run** unless its 10 km equivalent beats the speed evidence (here, 5:30/km over 20 km converts to 52:46, slower than the 5 km-based 52:07). Sustained performance is therefore **not** measured. This is a model gap, kept visible.
- **Choosing weights:** 50/50 is not neutral. Choose weights by asking how much distance completion should be worth relative to speed, e.g. "a first 8 km should be worth about as much as an X % faster 5 km".

### A15.4 Results (exp2 record, superseded by A15.8 for exp3)

| Method | Invariants (I1–I11) | Desired | Notes |
|---|---|---|---|
| A (production, live) | **fails I1**: the hard label on the 8 km costs 159 | 4/9 | rejected as a candidate |
| **B** | all | **9/9** | grid 36/36 invariants, 72 % desired; k = 2 fails D1, D3, D4, D8, D9 |
| C | all | 7/9 | fails D1, D4: no endurance credit within a category |
| D | all | 6/9 | fails D3 (bounded steps cap a stop-heavy and a continuous run alike), D8 (upward drift +30 to +65 under noise), D9 |

**Finalists by the predeclared rule:** B and C. C replaced D in exp2 because D now fails D3.

**Specification changes, made at the user's direction (2026-10-22):**
- D3 is revised: distance completion is separate from continuity.
- I10 (no stop-time cliff) and I11 (overlapping junk never suppresses a genuine run) are new.

**Held-out scenarios (B; failures kept)**

| Scenario | Effect | Result |
|---|---|---|
| H1: GPS reading 3 % long | speed +61, endurance +16 | fail |
| H2: downhill-assisted 10 km | speed +80 | fail (undetectable) |
| H3: fast 3 km segment overlapping its 10 km | speed +160 | **fail.** The segment is an ambiguous overlap, kept and now marked provisional with a review flag |
| H4: slow 15 km at 9:45/km | endurance credited, 677 → 1373 | walking and very slow running are indistinguishable |
| H5: treadmill only | — | missing, not zero |
| H6: 100 miles with 20 % stops | endurance 2730 → 2663 | smooth, not erased |
| H7: shuffled and doubled upload | — | identical |

**Fictional runners (B 50/50; speed / endurance), as of 2025-12-31**

| Runner | Combined | Speed / endurance |
|---|---|---|
| Beginner | 1311 | 1495 / 1128 |
| Speed specialist | 1794 | 2338 / 1250 |
| Steady | 1512 | 1689 / 1335 |
| Marathon | 2094 | 2159 / 2030 |
| Ultra | 2258 | 1785 / 2730 |
| Improving | 1559 | 1782 / 1336 |
| Many easy | 1496 | 1646 / 1347 |

**Reconciliation of the two beginner figures**
- **1636 / 1130** is hand-designed case `01`: four 5 km runs, best 25:00, then the 8 km on 2025-01-29, evaluated that day.
- **1495 / 1128** is the generated Lab runner `runner("beginner", seed=1)` (184 activities), evaluated on 2025-12-31.
  - Its speed comes from activity 900176: 4.05 km in 21:29 on 2025-12-10.
  - Its endurance comes from 900175: 7.97 km, which beats its own aged 8 km from 2025-03-13.
- Both use B at defaults (k = 1, 50/50).

### A15.5 Defects fixed (with regression tests in `tests/test_lab.py`)
1. **k-th best fallback:** a weaker second session could lower a component.
2. **Repeated activity ids:** both copies were dropped.
3. **Missing moving time:** could raise endurance (exp1). In exp2, missing moving time gives the 0.5 floor, never more than any known case.
4. **Naive datetimes:** a crash on naive/aware mixing.
5. **Overlap rule (exp1):** it let a Walk or watch-left-running activity delete real runs; replaced by the classes in A15.2.
6. **The 15 % stop cliff (exp1):** a 0.2-point change in stopped share moved E by about 1900 points; replaced by the continuous factor.
7. **Harness:** I8 compared an input with itself; the I6 stop case was missing; the I4 bound was wrong for k = 2.

**Remaining model limitations (reported, not tuned away)**
- **Cropping:** a crop or segment that overlaps its parent can set speed. It is flagged and marked provisional, but still counted.
- **Plausible-looking outliers:** a bike ride as a Run gives speed 2883. It is flagged when more than 10 % better than the runner's next-best session, and provisional when uncorroborated.
- **Walking vs slow running:** the anchor cannot separate them.
- **Faster long runs:** not rewarded (A15.3).
- **Activity type:** relabelling Run → Trail Run removes speed evidence.
- **Measurement:** GPS distance error and downhill courses are undetectable.

### A15.6 Ratings Lab (`/lab`)
- **Explore a runner:** pick a fictional runner, a method and predeclared parameter values. The page shows the components, the combined score and history, the **evidence behind each component** (activity, date, value, provisional or corroborated, concerns), the input activities with credited distance, continuity and review flags, and "Explain" for any activity.
- **Compare runners:** every runner under every configuration, the improvement table and the trade-off probes.
- **Data source (2026-10-23):** an explicit selector. *Built-in synthetic examples* use a fixed reference date (day 364). *Histories in the currently selected application database* (the one the app was started with: `./run.sh` personal, `./run.sh demo` demo; the Lab never switches) use an as-of date that defaults to **today (UTC)** and is shown with its basis.
- **Stored histories (`runrank/lab_source.py`):** read through SQLite `mode=ro` plus `PRAGMA query_only`, never `store.connect`. Mapping: activity id → key (source id and import file kept as provenance), `start_utc` → UTC datetime, type unchanged, metres and seconds unchanged, missing moving time / elevation / heart rate stay missing (listed per activity). Stored `exclude` removes the activity from the Lab input (state *excluded (stored)*, with its note; it cannot be re-included from the Lab). Stored `not_duplicate` becomes keep-separate. Effort labels are context only, as everywhere.
- **States shown:** counted, flagged, held, dropped (duplicate), invalid, unsupported (type or range, with the reasons), outside window (older than 365 days), after as-of, excluded (stored). Coverage notes explain an absent score (no activities; all excluded; all evidence older than 365 days, "missing recent evidence, not low ability").
- **Two Lab exclusions (2026-10-23):** *Exclude recording* removes one activity; under B–D another valid recording of the same effort then becomes the scoring representative (the duplicate rule runs on what remains). *Exclude effort* removes the recording and every **identified** duplicate of it under the selected method's rule (A: production's `activity_rules.possible_duplicates`; B–D: exact or probable duplicates). Ambiguous overlaps and recordings marked not-a-duplicate are never grouped. The page lists the removed ids and the score without vs with all Lab overrides. Both are temporary; stored exclusions and original records are untouched.
- **Method A is production's own calculation:** `mmr.classify_history` (the preprocessing `store.mmr_observations` now calls) and `mmr.estimate_at`, with production's ids, duplicate rule, stored exclusions and not-a-duplicate annotations. A Lab exclusion under A is applied as production applies a stored one: the excluded recording still marks its duplicate, which counts only if marked not a duplicate. Previously A removed excluded rows before the duplicate rule and ignored not-a-duplicate, so it could differ from production. Parity is tested on the duplicate test history (six dates, plus Lab exclusions against a database copy with the same exclusion stored) and on every demo history at five dates (35 comparisons; the demo has one production duplicate).
- **Isolation:** synthetic routes never open the database; stored-history routes open it read-only. Lab exclusions, confirmations, keep-separate and parameters live only in the request. Tests confirm every table, the database bytes, MMR and Elo are identical after every control, and that no Lab route calls `store.connect` (`tests/test_api_lab.py`, `tests/test_api_lab_db.py`; journey L).

### A15.7 Readiness and remaining product choices

**B is ready for a read-only evaluation on real data, not for promotion.** The next step is to import a consenting runner's export and compare B's selected evidence and flags with what the runner recognises as their real efforts.

**Choices for the user**
- **Weights:** the speed/endurance weight, expressed as an exchange rate (A15.3), not as "balanced".
- **Corroboration:** whether new capacity must be corroborated (k = 2) before it counts, or shown as provisional (current).
- **Sustained performance:** whether to measure it, so that a faster long run counts (a third component, or a distance-specific speed); this needs a new, separately tested definition.
- **Continuity floor:** whether 0.5 credit for unverifiable continuity is right.

### A15.8 exp3 (2026-10-22): long-distance performance, unknown continuity, credible new bests

**Why "the same 20 km run faster" scored 0.** The fixture is `lab_compare.improvements()`, row 4:
- four 5 km runs (best 25:00, 2025-01-11) and a 20 km in 2:00:00 on 2025-01-26;
- then the same 20 km in 1:50:00 on 2025-01-31, evaluated that day.

Breakdown:
- **Speed:** the faster 20 km converts to a 10 km-equivalent of 52:46, i.e. 1611.9 speed points. That does **not exceed** the selected speed evidence: the 5 km in 25:00, i.e. 52:07 and 1635.7.
- **Endurance:** it counts distance only (20 km before and after).

So this was the first situation: it does not beat the existing best. It was **not** an inability at 20 km: a runner with only those 20 km runs goes 1441.2 → 1611.9. B could not recognise performance beyond 42.5 km, though: those activities never feed speed.

**Matched cases** (`lab_synthetic.long_matched`): only performances at one distance. Four runs at time T, then the same distance at 0.95 T, with the same type, 2 % stops and no label; scored on 2025-05-01. Combined is 50/50.

| Distance | B performance | B+LP performance | Endurance | Combined (B+LP) | +5 repeats of the faster run |
|---|---|---|---|---|---|
| 20 km (2:10:00 → 2:03:30) | 1284.2 → 1384.8 | same | 1627.7 (unchanged) | 1456.0 → 1506.3 | 1506.3 |
| marathon (4:10:00 → 3:57:30) | 1553.8 → 1654.4 | same | 2033.3 | 1793.6 → 1843.9 | 1843.9 |
| 50 km (5:30:00 → 5:13:30) | **none** (combined missing) | 1356.9 → 1473.3 | 2125.5 | 1741.2 → 1799.4 | 1799.4 |
| 100 km (12:00:00 → 11:24:00) | **none** | 1287.6 → 1416.9 | 2502.1 | 1894.9 → 1959.5 | 1959.5 |

**The extension (LP, `long_performance = on`; experimental, default off).**
- **Formula:** each activity over 42.5 km gets P = 3000 × ln(v / 5 km/h) / ln(v_top(d) / 5 km/h), on the synthetic anchor curve at **its own distance**. It is aged like speed.
- **No 10 km conversion:** at 10 km the anchor curve coincides with the speed scale (2:00:00 = 0, 26:00 = 3000).
- **Combination:** performance = max(speed, LP), and combined = w × performance + (1 − w) × endurance.

**Why this does not double count:**
- an activity's *time* enters exactly one performance measure: speed for 3–42.5 km, LP for over 42.5 km;
- its *distance* enters endurance only;
- performance takes the maximum, so a runner never receives both;
- repeats add nothing: max, not sum.

**Limitation found:** the switch at 42.5 km is a discontinuity. At the same 5:55/km, 42.5 km scores speed 1557.4, while 42.6 km scores LP 1488.1 (−69). Recommended follow-up: use the anchor curve for both sides of a short overlap band, or for all distances. That needs its own test.

**Missing moving time**

| Item | Detail |
|---|---|
| Credit function | credited km = recorded distance × f(pace) [× c in scalar mode]. f uses moving pace, or elapsed pace when moving time is missing |
| Full-range check | 360 grid points: distance 1.5–160.9 km × moving pace 4:00–15:00/km × stopped 0–99 %. Missing moving time **never increased** credit in either mode (0 violations). In label mode, missing data can only lower f |
| exp2's fixed 0.5 was not a fact | it "passed" the invariant only by being the minimum, and it claimed half the distance was not completed |
| exp3 default (label) | keeps the **recorded distance** and marks continuity *unknown* (flagged); it does not invent moving time. Elapsed time still governs performance |

| Activity | Label (exp3) | Scalar (exp2) |
|---|---|---|
| 24 h race, 160 km without moving time | 160 km | 80 km |
| 12 km with 41 min stopped | 12 km | 8.13 km |
| watch left running, 12 km | 12 km, flagged | 6 km |

**Remaining limitation:** without moving time, a stop-heavy activity's elapsed pace can fall under the walking anchor and lose credit. The data cannot distinguish that case from walking.

**Credible new bests**

A speed result counts **immediately** (provisional until corroborated) when all of these hold:
- **C1:** type Run, 3–42.5 km.
- **C2:** not an exact or probable duplicate recording.
- **C3:** 10 km-equivalent not faster than 26:00, and pace not faster than 2:30/km.
- **C4:** not inside a longer, plausible same-type recording (a possible crop or segment).
- **C5:** not more than 10 % better than the runner's best *earlier* counted evidence. A first result passes C5.

Otherwise it is **pending review**:
- it counts for **nothing** (speed, endurance or long-distance performance) until another independent session corroborates it within 3 %, or it is excluded;
- in the Lab, use the per-activity **Exclude** toggle (never stored); in production, use the activity's *Exclude* annotation;
- these checks catch only the listed patterns, not every invalid recording.

On the speed specialist (B defaults):
- one 10 km 3 % faster than their best counts at once: +32.3 combined, provisional;
- a "Run" of 40 km in 2:00:00 (a ride?) is pending: +0.0. In exp3's first version it still added +377.1 through endurance; fixed, with a test.

**Results (exp3 defaults: label continuity, LP off)**

| Method | Invariants | Desired | Notes |
|---|---|---|---|
| A, production v2 | all 11 (I1 now holds) | 4/9 | — |
| **B** | all | **9/9** | — |
| C | all | 7/9 | — |
| D | all | 7/9 | D8 drift; D9 |

- **Spec change:** D3 was revised a third time, at the user's direction. A stop-heavy run keeps its recorded distance, is labelled *with stops*, and does not raise speed.
- **Finalists by the predeclared rule:** B and D.

**exp3 defects fixed (tests in `tests/test_lab.py`)**
1. The session best was chosen before the credibility check, so a pending crop hid the genuine race in its session.
2. A held activity still counted for endurance.
3. A first draft of C5 compared with the *next-best* session, which held genuine races after easy training. It now compares with earlier counted evidence.

**Smallest defensible improvement to B (still experimental, not promoted):**
- label-mode continuity (the exp3 default);
- the credibility checks C1–C5, with pending review;
- `long_performance = on`, so 50 km and 100 km improvements count without a 10 km conversion.

The weights stay 75/25, 50/50 and 25/75 comparisons, as instructed. The 42.5 km boundary step should be resolved before weights are discussed.

### A15.9 exp4 (2026-10-22): credibility audit, a continuous performance rule, what the score rewards

**Credibility gate (exp3, as implemented)**
- **Rules:**
  - **C4:** an activity inside a longer same-type recording was **held**.
  - **C5:** an activity more than 10 % faster than the best earlier counted evidence was **held**. It was compared against *aged* values.
  - A held activity counted for no component until another session within 3 % corroborated it.
- **Audit (`rating_lab.txt` §13 and pre-change runs):**
  - a first genuine race after easy-only training was held, losing its speed *and* its endurance;
  - a genuine > 10 % improvement was held until repeated;
  - a recorded 9 % improvement was held, because the older evidence had already been aged (**defect**);
  - a genuine race and its crop were both held;
  - a second similar ride "corroborated" the first, and both counted.
  - Import order (chronological, backwards, interleaved batches) changed nothing.
- **Policy problem:** exceeding earlier evidence was being treated as invalidity.

**exp4 policy (no new threshold)**

| State | Applies to | Effect | Resolution |
|---|---|---|---|
| **Dropped** | exact or probable duplicate recordings | one copy counts | — |
| **Excluded** | outside the physical floors (10 km-equivalent faster than 26:00, pace faster than 2:30/km) | never counts | — |
| **Held** | *data contradiction:* a segment inside a longer, plausible same-type recording | counts for **no** component | the user confirms it is a separate activity (Lab: *Confirm separate*), or leaves it held. Confirmation is labelled "confirmed by the user (not independent validation)" |
| **Flagged** | *suspicious or large new achievement:* more than 10 % faster than the runner's best earlier **recorded** evidence in the 365 days before it (the existing 10 %, now a flag only); ambiguous overlaps; pace near walking; watch left running | **counted at once**, provisional until another independent session within 3 % corroborates it | exclusion if it is invalid (Lab *Exclude*; production *Exclude* annotation). Corroboration by another session is **not** validation: two mislabelled rides corroborate each other (audit: speed 2882.5) |

- **Order independence:** results are identical for backwards and batched imports (components, held set and flags).

**Performance boundary: the equations before the change**
- **Speed (3–42.5 km Runs):**
  - T10 = elapsed × (10000 / d)^1.06 (Riegel's exponent; Riegel, *American Scientist*, 1981);
  - S = 3000 × ln(7200 / T10) / ln(7200 / 1560), where 7200 s is 10 km at 5 km/h and 1560 s is a rounded near-elite 10 km. Both anchors are synthetic.
- **exp3 "anchor" LP (over 42.5 km, Run or Trail Run):**
  - P = 3000 × ln(v / 5) / ln(v_top(d) / 5), with v in km/h from elapsed time;
  - v_top is log-linear in ln(d) through anchors that are a **synthetic assumption**: rounded times written from memory (5 km 12:30 … 250 km 21:00). They are not verified records, not an established elite reference and not population standards (§A15.10).
  - The two rules share anchors only at 10 km.

**Problems with the exp3 rule**
- **Discontinuity:** at 5:55/km, 42.5 km scored 1557.4 and 42.6 km scored 1488.1. At 7:30/km the drop was −103.6.
- **Longer could score lower:** running further at the same pace sometimes scored lower.
- **Type rules differed:** Trail Run was eligible on one side of the boundary only.

**exp4 "bridged" (`long_performance = bridged`; `bridged_t10`)**
- **Up to 42.5 km:** exactly the production 10 km-equivalent.
- **Beyond:** the time is mapped to an equivalent 42.5 km time with the anchor curve's own slowdown, t × t_top(42.5) / t_top(d), then converted the same way.
- **Eligibility:** Run and Trail Run at every distance. Terrain is not adjusted.

**Expected properties, fixed before evaluating** (`rating_lab.py` SPEC, §12):

| Property | Result |
|---|---|
| BP1 < 1 point per 0.01 km | **pass**: largest 0.05 km step 1.95 points (near 3 km, where the slope is 117.7 / d points per km) |
| BP2 faster is always higher | **pass** |
| BP3 same pace, longer, never lower | **pass**: no drop at any pace |
| BP4 one rule for Run and Trail Run | **pass** |
| BP5 equals production for 3–42.5 km Runs | **pass** (exact) |
| BP6 defined across 3–160.9 km | pass. At 4:00/km very long distances fall under the implausibility floor and show as missing |

- **At the old boundary (5:55/km):** 42.4 / 42.5 / 42.6 km give 1557.1 / 1557.4 / 1560.2.
- **Hand value (tested):** 100 km in 11:00:00 is mapped to 39600 × t_top(42.5) / t_top(100), then scored as a 42.5 km time.
- **Continuous is not validated:** the bridge borrows the slowdown of the *synthetic* anchor curve, which is an assumption about non-elite runners. Riegel's exponent is likewise not personal.

**Held-out boundary cases (after choosing; reported, not tuned)**
- **H8, anchor kinks** at 50, 100 and 160.9 km stay continuous: 49.9 / 50.0 / 50.1 km give 1576.7 / 1579.4 / 1580.1.
- **H9, GPS sensitivity beyond 42.5 km is larger:** a 1 % long reading adds +20.7 at 42 km and +31.6 at 43 km.
- **H10, flat beyond 250 km:** the anchor curve ends there, so 250 and 300 km at 8:00/km both score 2063.1. Further distance earns no performance.
- **H11, the 3 km floor** behaves as specified.
- **H12, terrain:** a 30 km Trail Run equals the same Run (1488.9).

**What B rewards (bridged, label continuity; `rating_lab.txt` §14)**

| Matched change | Performance | Endurance | 75/25 | 50/50 | 25/75 |
|---|---|---|---|---|---|
| 10 km, 50:00 → 45:00 | +206.7 | 0 | +155.0 | +103.3 | +51.7 |
| 10 → 21.1 km at the same 5:00/km | **+87.9** | **+405.6** | +167.3 | +246.8 | +326.2 |
| 10 → 12 km in the same 50:00 | +379.1 | +99.1 | +309.1 | +239.1 | +169.1 |
| 21.1 km in 1:50:00, moving 1:48 → 1:35 | 0 | 0 | 0 | 0 | 0 (label: 13.6 % stopped) |
| the same with moving time missing | 0 | 0 | 0 | 0 | 0 (label: unknown) |

- **Distance enters twice:** through performance normalisation (holding a pace for longer converts to a better 10 km-equivalent) and through endurance (log of distance).
- **Moving time changes no number:** it only changes the continuity label.
- **50/50 is an experimental setting,** not a neutral weight.

**Not determinable from summary CSV data**
- whether an activity was a ride, a run, or a run with walking;
- whether a split, crop or second recording is the same effort;
- true continuity when moving time is absent, and what auto-pause recorded;
- course profile (net descent), surface and weather;
- GPS distance error;
- whether a "race" label is accurate.

User confirmation records a belief; it does not verify any of these.

**Unchanged:** production `mmr-envelope-v2` and race Elo. Method B is still experimental. Browser verification is still blocked by the project's `"mcp__*"` deny.

### A15.10 exp5 (2026-10-22): extreme values kept and warned, one supported range, reviewable duplicates

**Plausibility rules (each listed with its units and current treatment)**

| Class | Rule | Treatment (exp5) |
|---|---|---|
| Structurally invalid | distance or elapsed time not a positive finite number | record kept, **not scored**, state *invalid* |
| Contradictory field | moving time ≤ 0 or longer than elapsed | moving time ignored (continuity unknown), flagged; the rest of the record is used |
| Suspicious recorded measurement | average elapsed pace faster than 2:30/km (24 km/h; the existing number) | **kept and counted**, warning "possibly not running (GPS, vehicle or bike)" |
| Exceptional modelled score | converted 10 km-equivalent faster than the 26:00 scale anchor (score above 3000), or speed above the anchor curve at that distance | **kept and counted**, warning "the conversion or recording may be wrong". Exp1–4 *excluded* these |

- **No new threshold was introduced.** The existing numbers now produce warnings instead of exclusions.
- **Production `mmr-envelope-v2` keeps its own 26:00 exclusion, unchanged.** Lab method A shows that rule.

**Targeted cases (method B, bridged)**
- **3 km in 7:00:** T10 = 420 × (10/3)^1.06 = 1504.9 s, giving performance **3070.6**. It counts, with three warnings: exceptional modelled score, suspicious recorded pace (2:20/km) and large improvement.
- **100 km in 6:00:00 (Trail Run):** bridged to 21600 × t_top(42.5) / t_top(100) = 7244.2 s at 42.5 km, giving performance **2996.5**. It counts, flagged "faster than the synthetic anchor curve at 100 km".
- **Excluding either one** restores the previous components.

**The anchor curve is a synthetic assumption.** All anchors are rounded times written from memory of roughly elite performances. None was checked against a source, and they are **not** an established elite reference.

| Distance | 5 km | 10 km | 21.1 km | 42.2 km | 50 km | 100 km | 160.9 km | 250 km |
|---|---|---|---|---|---|---|---|---|
| Anchor time | 12:30 | 26:00 | 57:00 | 2:01:00 | 2:40:00 | 6:05:00 | 11:00:00 | 21:00:00 |

The curve is retained unchanged for this trial.

**One supported range: 3–250 km for method B, for performance and endurance alike.**
- **Below 3 km and above 250 km:** activities are kept and listed as "outside the supported range: not scored". Nothing is clamped.
  - Previously the curve clamped below 5 km and above 250 km, and endurance was capped at 3000, so 300 km scored like 250 km.
  - Example: 300 km is now kept and unscored, and endurance stays at the runner's in-range best.
- **Curve range:** the anchor curve is defined on 5–250 km only, with no extrapolation. B uses it only between 42.5 and 250 km.
- **Method C (corrected 2026-10-23):** un-clamping the *shared* curve function had removed C's 3–5 km scores (it fell to 6/9). That was accidental coupling, not intended.
  - C now keeps its exp1–4 behaviour as an explicit, labelled rule inside C only: for 3–5 km, the 5 km anchor speed is used.
  - B and D results are byte-identical before and after this fix, and C is back to 7/9.
- **The same ranges appear** in the code (`PERFORMANCE_RANGE_KM`, `CURVE_RANGE_KM`), the API (`/api/lab/meta`) and the Lab.

**Evidence preservation**
- **Nothing is deleted:**
  - Production never deletes imported activities. The production possible-duplicate rule only marks eligibility, and the "not a duplicate" annotation reverses it.
  - In the Lab, every record stays listed.
- **What is shown for each duplicate:** exact and probable duplicates name the copy that is **scored** and why (moving time present, then earlier start, then smaller id). Ambiguous overlaps keep both copies.
- **Reversing a decision:** "Keep separate" reverses a probable-duplicate decision without editing the input. The record is then flagged "kept separate by the user's review (raw import unchanged)".

**Trial presentation (Lab)**
- Each component shows the determining activity, its date and its evidence.
- If that activity is flagged, a **⚠ warning is shown next to the score itself**.
- A *How this score is determined* panel lists what raises and lowers each component, what the weighting means as an exchange rate, and the unvalidated assumptions.

**Specification change:** I9 was revised at the user's direction. A single implausibly fast observation is now kept and visibly warned, and the user can exclude it; earlier versions required "raises nothing". Results: B passes all 11 invariants and 9/9 desired behaviours, D 7/9, C 7/9 (after the coupling fix). Finalists: B and D.
