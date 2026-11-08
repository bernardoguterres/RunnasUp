"""Regression tests for import concurrency, storage safeguards, and CSV handling.

1. elevation_gain_m in CORRECTABLE tuple (data integrity)
2. Atomic repeat-import concurrency guard (TOCTOU race with real SQLite contention)
3. CSV formula injection escaping tabs, newlines, and leading whitespace
4. WAL mode and busy_timeout enabled for SQLite concurrency
5. Date parser handles ISO timestamps with offsets and fractional seconds
"""
import os
import tempfile
import threading
import time
from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

from runrank import api, store, strava_csv

HDR = "Activity ID,Activity Date,Activity Type,Elapsed Time,Distance,Elapsed Time,Distance,Elevation Gain\n"


def test_elevation_gain_correction_is_applied_when_requested(con):
    pid = store.create_participant(con, "Elev Runner", True, "synthetic")
    row1 = '101,"Mar 1, 2024, 7:00:00 AM",Run,1500,5.00,1500,5000.0,50.0\n'
    row2 = '101,"Mar 1, 2024, 7:00:00 AM",Run,1500,5.00,1500,5000.0,100.0\n'
    store.import_file(con, pid, "a.csv", (HDR + row1).encode())
    initial = con.execute("SELECT elevation_gain_m FROM activities WHERE source_activity_id = '101'").fetchone()[0]
    assert initial == 50.0

    imp = store.import_file(con, pid, "a.csv", (HDR + row2).encode(), apply_corrections=True)
    status = tuple(con.execute("SELECT inserted, corrected, duplicates FROM imports WHERE id = ?", (imp,)).fetchone())
    assert status == (0, 1, 0)
    updated = con.execute("SELECT elevation_gain_m FROM activities WHERE source_activity_id = '101'").fetchone()[0]
    assert updated == 100.0


def test_concurrent_duplicate_import_raises_409(tmp_path):
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

    assert "'\t=2+2" in body
    assert "'  +cmd" in body
    assert "'\r-1337" in body
    assert "'@SUM(A1:A10)" in body


def test_wal_mode_and_busy_timeout_enabled(tmp_path):
    db_path = str(tmp_path / "wal_test.sqlite")
    con = store.connect(db_path)
    mode = con.execute("PRAGMA journal_mode").fetchone()[0]
    timeout = con.execute("PRAGMA busy_timeout").fetchone()[0]
    con.close()
    assert mode.lower() == "wal"
    assert timeout >= 5000


def test_date_parser_handles_iso_with_offsets_and_milliseconds():
    dt1 = strava_csv._date("2024-03-01T07:00:00+00:00")
    assert dt1 == datetime(2024, 3, 1, 7, 0, 0, tzinfo=timezone.utc)

    dt2 = strava_csv._date("2024-03-01T07:00:00.000Z")
    assert dt2 == datetime(2024, 3, 1, 7, 0, 0, tzinfo=timezone.utc)
