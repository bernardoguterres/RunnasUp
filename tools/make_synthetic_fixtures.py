#!/usr/bin/env python3
"""Write SYNTHETIC Strava-style fixtures to examples/synthetic/.

Every value is hand-chosen so expected results can be worked out on paper
(docs/RATING_METHOD.md C3). These are not real people or real runs.
The column layout imitates a Strava bulk-export activities.csv as recalled,
not as verified against a real export.
Run: .venv/bin/python -I tools/make_synthetic_fixtures.py
"""
import csv
import io
import pathlib
import zipfile
from datetime import datetime

OUT = pathlib.Path(__file__).resolve().parent.parent / "examples" / "synthetic"

HEADER = ["Activity ID", "Activity Date", "Activity Name", "Activity Type", "Activity Description",
          "Elapsed Time", "Distance", "Max Heart Rate", "Relative Effort", "Commute",
          "Activity Private Note", "Activity Gear", "Filename", "Athlete Weight", "Bike Weight",
          "Elapsed Time", "Moving Time", "Distance", "Max Speed", "Average Speed", "Elevation Gain",
          "Elevation Loss", "Average Heart Rate", "Perceived Exertion"]


def strava_date(text):
    dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    h12 = dt.hour % 12 or 12
    return "%s %d, %d, %d:%02d:%02d %s" % (dt.strftime("%b"), dt.day, dt.year, h12, dt.minute,
                                           dt.second, "AM" if dt.hour < 12 else "PM")


def row(aid, when, typ, metres, elapsed, moving="", hr="", rpe="", name=None, shown=None,
        date_text=None, elapsed2=None, filename=""):
    shown = "%.2f" % (metres / 1000) if shown is None else shown
    return [aid, date_text or strava_date(when), name or "SYNTHETIC %s %s" % (typ, aid), typ, "",
            str(elapsed), shown, "", "", "false", "synthetic fixture", "", filename, "", "",
            str(float(elapsed)) if elapsed2 is None else elapsed2, str(moving), "%.1f" % metres,
            "", "", "", "", str(hr), str(rpe)]


def csv_bytes(rows, header=HEADER):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


RUNNER_A = [
    row("1001", "2024-03-01 07:00:00", "Run", 5000, 1500, 1490, 152, 6),
    row("1002", "2024-03-15 07:00:00", "Run", 5000, 1440, 1435, 160, 8),
    row("1003", "2024-03-20 07:00:00", "Run", 5050, 1818, 1800),            # easy, HR/RPE missing
    row("1004", "2024-03-22 07:00:00", "Ride", 20000, 2400, 2350, 130, 4),
    row("1005", "2024-03-24 08:00:00", "Run", 10000, 3000, 2990, 158, 7),
    row("1006", "2024-03-26 07:00:00", "Run", 5000, 660, 650),             # implausibly fast
    row("1007", "2024-03-15 07:01:00", "Run", 5020, 1446, 1440, 161, ""),  # second device copy of 1002
    row("1008", "2024-03-28 07:00:00", "Virtual Run", 5000, 1400, 1400),
    row("1009", "", "Run", 5000, 1500, date_text="not a date"),
    row("1010", "2024-03-29 07:00:00", "Run", 6500, 1500, shown="5.00"),   # matches no unit (km, mi, m)
    row("1011", "2024-03-30 07:00:00", "Run", 5000, -5, elapsed2="-5.0"),
    row("", "2024-03-31 07:00:00", "Run", 5000, 1500),                     # missing ID
]
RUNNER_A_LATER = [row("1012", "2024-06-01 07:00:00", "Run", 5000, 1470, 1465, 158, 8)]
RUNNER_A_HISTORICAL = [row("1013", "2024-02-20 07:00:00", "Run", 5100, 1428, 1420, 165, 9)]
RUNNER_A_CORRECTED = [row("1003", "2024-03-20 07:00:00", "Run", 5050, 1780, 1770)]
RUNNER_B = [
    row("2001", "2024-03-02 07:00:00", "Run", 5100, 1530, 1520, 150, 6, filename="activities/2001.gpx"),
    row("2002", "2024-03-10 18:30:00", "Run", 5000, 1560, 1550, "", 7),
    row("2003", "2024-03-30 07:00:00", "Run", 4980, 1494, 1490, 149, ""),
]
RUNNER_B_COLLISION = [
    row("1001", "2024-03-01 07:00:00", "Run", 5000, 1500, 1490, 152, 6),   # Runner A's activity ID
    row("2004", "2024-04-05 07:00:00", "Run", 5000, 1620, 1610, 147, 5),
]
EDGE_UNICODE = [   # long and non-English names, commas and quotes inside names
    row("3001", "2024-05-02 06:30:00", "Run", 5000, 1530, 1520, 150, 6,
        name='Corrida matinal — São Paulo, "parque" ☀️ ' + "muito longa " * 12),
    row("3002", "2024-05-09 06:30:00", "Run", 5010, 1500, 1495, "", "", name="東京マラソン練習 5km テンポ走"),
    row("3003", "2024-05-16 06:30:00", "Run", 5000, 1560, "", "", "", name="Läufchen am Rhein; Ölweg (Ü-Strecke)"),
]
EDGE_SINGLE = [row("4001", "2024-05-05 08:00:00", "Run", 5000, 1620, 1600, "", "", name="SYNTHETIC only activity")]
EDGE_NO_QUALIFYING = [row("5001", "2024-05-03 07:00:00", "Run", 10000, 3300, 3250, 140, 5),
                      row("5002", "2024-05-10 07:00:00", "Ride", 30000, 3600, 3550),
                      row("5003", "2024-05-17 07:00:00", "Walk", 4000, 2700, 2600)]
EDGE_TIE_A = [row("6001", "2024-05-01 07:00:00", "Run", 5000, 1500), row("6002", "2024-05-08 07:00:00", "Run", 5000, 1550),
              row("6003", "2024-05-15 07:00:00", "Run", 5000, 1580)]
EDGE_TIE_B = [row("7001", "2024-05-02 07:00:00", "Run", 5100, 1530), row("7002", "2024-05-09 07:00:00", "Run", 5000, 1600),
              row("7003", "2024-05-16 07:00:00", "Run", 5000, 1620)]
FAKE_GPX = b"""<?xml version="1.0"?>
<gpx version="1.1" creator="SYNTHETIC"><trk><name>SYNTHETIC - not a real place</name><trkseg>
<trkpt lat="0.000000" lon="0.000000"><time>2024-03-02T07:00:00Z</time></trkpt>
</trkseg></trk></gpx>
"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    files = {
        "runner_a_activities.csv": csv_bytes(RUNNER_A),
        "runner_a_later.csv": csv_bytes(RUNNER_A_LATER),
        "runner_a_historical.csv": csv_bytes(RUNNER_A_HISTORICAL),
        "runner_a_corrected.csv": csv_bytes(RUNNER_A_CORRECTED),
        "runner_b_collision.csv": csv_bytes(RUNNER_B_COLLISION),
        "bad_empty.csv": b"",
        "bad_wrong_columns.csv": b"Date,Distance,Time\n2024-03-01,5.0,25:00\n",
        "bad_single_distance.csv": csv_bytes([[c for i, c in enumerate(r) if i != 17]
                                              for r in RUNNER_B],
                                             [c for i, c in enumerate(HEADER) if i != 17]),
        "bad_notes.txt": b"SYNTHETIC: this is not an export\n",
        "edge_unicode_names.csv": csv_bytes(EDGE_UNICODE),
        "edge_single_activity.csv": csv_bytes(EDGE_SINGLE),
        "edge_no_qualifying.csv": csv_bytes(EDGE_NO_QUALIFYING),
        "edge_tie_a.csv": csv_bytes(EDGE_TIE_A),
        "edge_tie_b.csv": csv_bytes(EDGE_TIE_B),
    }
    for name, data in files.items():
        (OUT / name).write_bytes(data)
    with zipfile.ZipFile(OUT / "runner_b_export.zip", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("export_synthetic_b/activities.csv", csv_bytes(RUNNER_B))
        z.writestr("export_synthetic_b/activities/2001.gpx", FAKE_GPX)
    with zipfile.ZipFile(OUT / "bad_unsafe_paths.zip", "w") as z:
        z.writestr("activities.csv", csv_bytes(RUNNER_B))
        z.writestr("../escape.txt", b"SYNTHETIC path traversal probe\n")
    for p in sorted(OUT.iterdir()):
        print("%8d  %s" % (p.stat().st_size, p.name))


if __name__ == "__main__":
    main()
