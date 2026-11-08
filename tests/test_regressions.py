"""Regression tests for overnight engineering pass defects.

1. elevation_gain_m in CORRECTABLE tuple (data integrity)
2. Atomic repeat-import concurrency guard (TOCTOU race with real SQLite contention)
3. CSV formula injection escaping tabs, newlines, and leading whitespace
4. Zero-distance activity handled in mmr.bands without ZeroDivisionError
5. explain() does not contradict itself when evidence coverage improves
6. WAL mode and busy_timeout enabled for SQLite concurrency
7. Date parser handles ISO timestamps with offsets and fractional seconds
8. Method A history optimization preserves exact historical trajectory across duplicate pairs and overrides
"""
import os
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from starlette.testclient import TestClient

from runrank import api, lab_methods as L, mmr, store, strava_csv

HDR = "Activity ID,Activity Date,Activity Type,Elapsed Time,Distance,Elapsed Time,Distance,Elevation Gain\n"


def test_elevation_gain_correction_is_applied_when_requested(con):
    pid = store.create_participant(con, "Elev Runner", True, "synthetic")
    row1 = '101,"Mar 1, 2024, 7:00:00 AM",Run,1500,5.00,1500,5000.0,50.0\n'
    row2 = '101,"Mar 1, 2024, 7:00:00 AM",Run,1500,5.00,1500,5000.0,100.0\n'
    store.import_file(con, pid, "a.csv", (HDR + row1).encode())
    initial = con.execute("SELECT elevation_gain_m FROM activities WHERE source_activity_id = '101'").fetchone()[0]
    assert initial == 50.0

    # Re-import with apply_corrections=True
    imp = store.import_file(con, pid, "a.csv", (HDR + row2).encode(), apply_corrections=True)
    status = tuple(con.execute("SELECT inserted, corrected, duplicates FROM imports WHERE id = ?", (imp,)).fetchone())
    assert status == (0, 1, 0)
    updated = con.execute("SELECT elevation_gain_m FROM activities WHERE source_activity_id = '101'").fetchone()[0]
    assert updated == 100.0


def test_concurrent_duplicate_import_raises_409(tmp_path):
    """Verify duplicate-import race through the real commit API under real SQLite contention.

    Exercises contention inside store.import_file where Thread 1 holds the BEGIN IMMEDIATE
    write lock while Thread 2 executes concurrently with an independent connection.
    Verifies that one succeeds (201), the other returns HTTP 409 with duplicate_file error,
    and the final database has exactly 1 completed import, 1 set of activity rows, and
    no partial writes or orphan records.
    Repeated across multiple fresh databases to verify stability.
    """
    csv_data = (HDR + '101,"Mar 1, 2024, 7:00:00 AM",Run,1500,5.00,1500,5000.0,50.0\n').encode()

    for iter_idx in range(5):
        db_path = str(tmp_path / f"concurrent_race_{iter_idx}.sqlite")
        con = store.connect(db_path)
        con.close()

        app = api.create_app(db_path)
        client = TestClient(app, base_url="http://127.0.0.1")

        res = client.post("/api/participants", json={"label": f"Concurrent Runner {iter_idx}", "data_kind": "synthetic"}).json()
        pid = res["id"]

        t1_in_store = threading.Event()
        t2_called = threading.Event()
        orig_import_row = store._import_row

        def hooked_import_row(*args, **kwargs):
            if not t1_in_store.is_set():
                t1_in_store.set()
                t2_called.wait(timeout=2.0)
                time.sleep(0.02)
            return orig_import_row(*args, **kwargs)

        store._import_row = hooked_import_row
        results = {}
        try:
            def upload1():
                c = TestClient(app, base_url="http://127.0.0.1")
                results["t1"] = c.post(f"/api/participants/{pid}/imports", files={"file": ("runs.csv", csv_data, "text/csv")})

            def upload2():
                t1_in_store.wait(timeout=2.0)
                t2_called.set()
                c = TestClient(app, base_url="http://127.0.0.1")
                results["t2"] = c.post(f"/api/participants/{pid}/imports", files={"file": ("runs.csv", csv_data, "text/csv")})

            th1 = threading.Thread(target=upload1)
            th2 = threading.Thread(target=upload2)
            th1.start()
            th2.start()
            th1.join()
            th2.join()
        finally:
            store._import_row = orig_import_row

        r1 = results["t1"]
        r2 = results["t2"]
        statuses = sorted([r1.status_code, r2.status_code])
        assert statuses == [201, 409], f"Iteration {iter_idx} got unexpected status codes: {[r1.status_code, r2.status_code]}"

        success_resp = r1 if r1.status_code == 201 else r2
        conflict_resp = r2 if r2.status_code == 409 else r1

        assert success_resp.json()["import"]["status"] == "completed"
        assert conflict_resp.json()["error"]["code"] == "duplicate_file"
        assert "this exact file was already imported" in conflict_resp.json()["error"]["message"]
        assert conflict_resp.json()["error"]["previous_import"]["id"] == success_resp.json()["import"]["id"]

        # Verify database integrity: exactly 1 completed import, 1 activity, 0 partial writes
        check_con = store.connect(db_path)
        try:
            imports = check_con.execute("SELECT * FROM imports").fetchall()
            assert len(imports) == 1, f"Expected 1 import, got {len(imports)}"
            imp = imports[0]
            assert imp["status"] == "completed"
            assert imp["rows_total"] == 1
            assert imp["inserted"] == 1
            assert imp["duplicates"] == 0
            assert imp["conflicts"] == 0
            assert imp["corrected"] == 0
            assert imp["rejected"] == 0

            activities = check_con.execute("SELECT * FROM activities").fetchall()
            assert len(activities) == 1
            assert activities[0]["source_activity_id"] == "101"

            import_rows = check_con.execute("SELECT * FROM import_rows").fetchall()
            assert len(import_rows) == 1
            assert import_rows[0]["outcome"] == "inserted"
        finally:
            check_con.close()


def test_csv_formula_injection_sanitizes_leading_tabs_and_whitespace():
    # Rows with dangerous spreadsheet formula injection prefixes
    rows = [
        ["1001", "2024-03-01T07:00:00Z", "\t=2+2", "Run", 5000.0, 1500.0, 1500.0, 300.0, 300.0, None, None, None, "unknown"],
        ["1002", "2024-03-02T07:00:00Z", "  +cmd|' /C calc'!A0", "Run", 5000.0, 1500.0, 1500.0, 300.0, 300.0, None, None, None, "unknown"],
        ["1003", "2024-03-03T07:00:00Z", "\r-1337", "Run", 5000.0, 1500.0, 1500.0, 300.0, 300.0, None, None, None, "unknown"],
        ["1004", "2024-03-04T07:00:00Z", "@SUM(A1:A10)", "Run", 5000.0, 1500.0, 1500.0, 300.0, 300.0, None, None, None, "unknown"],
    ]
    cols = ["id", "start_utc", "name", "type", "distance_m", "elapsed_s", "moving_s", "pace_s_per_km",
            "moving_pace_s_per_km", "avg_hr", "perceived_exertion", "elevation_gain_m", "effort"]
    resp = api._csv(cols, rows, "test.csv")
    body = resp.body.decode("utf-8")

    # Every formula must be safely prefixed with an apostrophe
    assert "'\t=2+2" in body
    assert "'  +cmd" in body
    assert "'\r-1337" in body
    assert "'@SUM(A1:A10)" in body


def test_zero_distance_run_does_not_crash_bands():
    now = datetime(2025, 6, 1, tzinfo=timezone.utc)
    zero_obs = mmr.Obs("zero_run", now, "Run", 0.0, 100.0)
    normal_obs = mmr.Obs("normal_run", now, "Run", 5000.0, 1500.0)
    classified = [mmr.classify(zero_obs), mmr.classify(normal_obs)]

    # Must compute distance bands without ZeroDivisionError
    b = mmr.bands(classified, now)
    assert len(b) > 0
    under3 = next(x for x in b if "under 3 km" in x["label"])
    # 0 distance runs must not be counted as valid under-3km pace runs
    assert under3["count"] == 0
    assert under3["best_pace_s_per_km"] is None


def test_coverage_change_does_not_claim_no_change():
    t0 = datetime(2025, 1, 1, 7, tzinfo=timezone.utc)
    r1 = mmr.classify(mmr.Obs("1", t0, "Run", 10000.0, 2700.0))
    # Slower run within 3% tolerance that corroborates and elevates coverage from low to medium
    r2 = mmr.classify(mmr.Obs("2", t0, "Run", 10000.0, 2720.0))

    e1 = mmr.estimate_at([r1], t0)
    e2 = mmr.estimate_at([r1, r2], t0)
    assert e1.status == "low"
    assert e2.status == "medium"
    assert e1.mmr == e2.mmr

    reasons = mmr.explain(e1, e2)
    # The explanation must NOT claim "No change: no new evidence beats the current estimate"
    assert not any("No change" in r for r in reasons)
    assert any("Evidence coverage: low → medium" in r for r in reasons)


def test_wal_mode_and_busy_timeout_enabled(tmp_path):
    db_path = str(tmp_path / "wal_test.sqlite")
    con = store.connect(db_path)
    mode = con.execute("PRAGMA journal_mode").fetchone()[0]
    timeout = con.execute("PRAGMA busy_timeout").fetchone()[0]
    con.close()
    assert mode.lower() == "wal"
    assert timeout >= 5000


def test_date_parser_handles_iso_with_offsets_and_milliseconds():
    # ISO dates with offset (+00:00) and milliseconds (.000Z)
    dt1 = strava_csv._date("2024-03-01T07:00:00+00:00")
    assert dt1 == datetime(2024, 3, 1, 7, 0, 0, tzinfo=timezone.utc)

    dt2 = strava_csv._date("2024-03-01T07:00:00.000Z")
    assert dt2 == datetime(2024, 3, 1, 7, 0, 0, tzinfo=timezone.utc)


def test_method_a_history_optimization_parity_across_duplicates_and_overrides():
    """Verify that precomputing preps in Method A history produces 100% bit-for-bit parity
    at every single timestamp across possible duplicates on opposite sides of history cutoffs,
    with exclusion and keep-separate overrides."""
    t0 = datetime(2025, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
    end = t0 + timedelta(days=90)

    def make_act(key, dt, dist, elapsed, gain, effort):
        return L.Act(key=key, start=dt, type="Run", distance_m=dist, elapsed_s=elapsed,
                     moving_s=elapsed, gain_m=gain, effort=effort, source_id=key)

    acts = [
        make_act("b0", t0 - timedelta(days=5), 5000.0, 1500.0, 10.0, "moderate"),
        make_act("d1", t0, 10000.0, 2700.0, 50.0, "hard"),
        make_act("d2", t0 + timedelta(minutes=20), 10000.0, 2710.0, 50.0, "moderate"),
        make_act("d3", t0 + timedelta(days=40), 10000.0, 2600.0, 40.0, "hard"),
        make_act("d4", t0 + timedelta(days=40, hours=1), 10000.0, 2605.0, 40.0, "hard"),
        make_act("d5", t0 + timedelta(days=85), 12000.0, 3100.0, 60.0, "hard"),
        make_act("d6", t0 + timedelta(days=85, minutes=15), 12000.0, 3100.0, 60.0, "hard"),
        make_act("post_end", t0 + timedelta(days=100), 10000.0, 2400.0, 30.0, "hard"),
    ]

    test_cases = [
        ("Default (no overrides)", frozenset(), frozenset()),
        ("Exclusion on d3 (first of pair across cutoff)", frozenset(["d3"]), frozenset()),
        ("Exclusion on d4 (second of pair across cutoff)", frozenset(["d4"]), frozenset()),
        ("Keep-separate on d3 & d4", frozenset(), frozenset(["d3", "d4"])),
        ("Keep-separate on d1 & d2, excluded d4", frozenset(["d4"]), frozenset(["d1", "d2"])),
        ("Keep-separate on d5 & d6 (near end cutoff)", frozenset(), frozenset(["d5", "d6"])),
        ("Excluded d5 (first near end cutoff)", frozenset(["d5"]), frozenset()),
    ]

    for label, excl, keep_sep in test_cases:
        # Reconstruct old history manually (calling evaluate without preps at every instant)
        starts = sorted({a.start for a in acts if a.start <= end and a.key not in excl})
        instants = set(starts)
        t = starts[0]
        while t < end:
            instants.add(t)
            t += timedelta(days=14)
        instants.add(end)

        old_out = []
        for t_inst in sorted(instants):
            r = L.evaluate("A", acts, t_inst, None, None, frozenset(), keep_sep, excl)
            old_out.append({
                "at": t_inst,
                "combined": r.combined,
                "components": r.components,
                "activities": [a.key for a in acts if a.start == t_inst],
                "setter": r.evidence.get("setter"),
                "coverage": r.evidence.get("coverage"),
            })

        # New history with precomputed preps
        new_res = L.history("A", acts, end, excluded=excl, keep_separate=keep_sep)
        assert len(old_out) == len(new_res), f"{label}: count mismatch {len(old_out)} vs {len(new_res)}"

        for idx, (o, n) in enumerate(zip(old_out, new_res)):
            assert o["at"] == n["at"], f"{label} @ {idx}: timestamp mismatch"
            assert o["combined"] == n["combined"], f"{label} @ {idx}: combined mismatch"
            assert o["components"] == n["components"], f"{label} @ {idx}: components mismatch"
            assert o["activities"] == n["activities"], f"{label} @ {idx}: activities mismatch"
            # Verify details match
            new_eval = L.evaluate("A", acts, n["at"], None, L.production_classified(acts, frozenset(excl), frozenset(keep_sep)), frozenset(), keep_sep, excl)
            assert o["setter"] == new_eval.evidence.get("setter"), f"{label} @ {idx}: setter mismatch"
            assert o["coverage"] == new_eval.evidence.get("coverage"), f"{label} @ {idx}: coverage mismatch"
