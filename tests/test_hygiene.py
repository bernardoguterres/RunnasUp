"""Hygiene review regressions (D1, D2, D4): each test reproduces the failing input.

D3 (legacy 5K ranking) was archived with the legacy score on 2026-10-25."""
import io
import zipfile

from runrank import store

HDR = "Activity ID,Activity Date,Activity Type,Elapsed Time,Distance,Elapsed Time,Distance\n"


def _status(con, imp):
    return tuple(con.execute("SELECT status, message FROM imports WHERE id=?", (imp,)).fetchone())


def test_d1_damaged_deflate_stream_is_rejected_not_crashing(con):
    pid = store.create_participant(con, "P", True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("activities.csv", bytes(range(256)) * 50)
    raw = bytearray(buf.getvalue())
    start = 30 + len("activities.csv")
    for i in range(start + 5, start + 40):
        raw[i] ^= 0x5A
    status, msg = _status(con, store.import_file(con, pid, "damaged.zip", bytes(raw)))
    assert status == "file_rejected" and "cannot read activities.csv" in msg
    assert con.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 0


def test_d2_encrypted_member_is_rejected_not_crashing(con):
    pid = store.create_participant(con, "P", True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("activities.csv", b"a,b\n")
    raw = bytearray(buf.getvalue())
    raw[6] |= 0x01
    raw[raw.rfind(b"PK\x01\x02") + 8] |= 0x01
    status, msg = _status(con, store.import_file(con, pid, "enc.zip", bytes(raw)))
    assert status == "file_rejected" and "encrypted" in msg


def test_d4_ignored_optional_values_are_counted_as_needing_attention(con):
    pid = store.create_participant(con, "W", True)
    hdr = HDR.strip() + ",Average Heart Rate\n"
    imp = store.import_file(con, pid, "w.csv", (hdr + '1,"Mar 1, 2024, 7:00:00 AM",Run,1500,5.00,1500,5000.0,300\n').encode())
    assert sum("warnings:" in (r["detail"] or "") for r in store.import_rows(con, imp)) == 1
    assert con.execute("SELECT avg_hr FROM activities").fetchone()[0] is None   # stays missing


def test_overlapping_exports_and_reconnect_are_idempotent(tmp_path):
    path = str(tmp_path / "o.sqlite")
    c = store.connect(path)
    p = store.create_participant(c, "O", True)
    rows = {i: '%d,"Mar %d, 2024, 7:00:00 AM",Run,1500,5.00,1500,5000.0\n' % (i, i) for i in (1, 2, 3)}
    store.import_file(c, p, "first.csv", (HDR + rows[1] + rows[2]).encode())
    imp = store.import_file(c, p, "second.csv", (HDR + rows[1] + rows[2] + rows[3]).encode())
    assert tuple(c.execute("SELECT inserted, duplicates FROM imports WHERE id=?", (imp,)).fetchone()) == (1, 2)
    c.close()
    c = store.connect(path)
    imp = store.import_file(c, p, "again.csv", (HDR + rows[1] + rows[2] + rows[3]).encode())
    assert tuple(c.execute("SELECT inserted, duplicates FROM imports WHERE id=?", (imp,)).fetchone()) == (0, 3)
    assert c.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 3
