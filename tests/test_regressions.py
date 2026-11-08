"""Regression tests for import concurrency and storage safeguards.

1. Atomic repeat-import concurrency guard (TOCTOU race with real SQLite contention)
2. WAL mode and busy_timeout enabled for SQLite concurrency
"""
import os
import tempfile
import threading
import time
from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

from runrank import api, store

HDR = "Activity ID,Activity Date,Activity Type,Elapsed Time,Distance,Elapsed Time,Distance,Elevation Gain\n"


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


def test_wal_mode_and_busy_timeout_enabled(tmp_path):
    db_path = str(tmp_path / "wal_test.sqlite")
    con = store.connect(db_path)
    mode = con.execute("PRAGMA journal_mode").fetchone()[0]
    timeout = con.execute("PRAGMA busy_timeout").fetchone()[0]
    con.close()
    assert mode.lower() == "wal"
    assert timeout >= 5000
