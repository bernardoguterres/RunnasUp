#!/usr/bin/env python3
"""Read-only discovery summary of a Strava export (zip or activities.csv).

Prints aggregates only: archive member types, columns, activity types, date
range, optional-field coverage, elapsed vs moving time, duplicate IDs, and a
few reconciled rows. Never writes, extracts to disk or opens GPS files.
Run: .venv/bin/python -I tools/inspect_export.py PATH [--rows N]
"""
import argparse
import collections
import csv
import io
import pathlib
import sys
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from runrank import mmr, strava_csv  # noqa: E402


def fmt_duration(seconds):
    """m:ss or h:mm:ss (whole seconds)."""
    h, rem = divmod(int(round(seconds)), 3600)
    m, sec = divmod(rem, 60)
    return "%d:%02d:%02d" % (h, m, sec) if h else "%d:%02d" % (m, sec)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--rows", type=int, default=3)
    args = ap.parse_args()
    path = pathlib.Path(args.path)
    data = path.read_bytes()
    print("file: %s (%d bytes)" % (path.name, len(data)))
    if zipfile.is_zipfile(io.BytesIO(data)):
        zf = zipfile.ZipFile(io.BytesIO(data))
        exts = collections.Counter(pathlib.PurePosixPath(i.filename).suffix or "(dir/none)"
                                   for i in zf.infolist())
        print("archive members by extension:", dict(exts))
        print("total uncompressed bytes:", sum(i.file_size for i in zf.infolist()))
    try:
        body, member = strava_csv.read_upload(path.name, data)
        rows = strava_csv.parse_activities_csv(body)
    except strava_csv.FileRejected as exc:
        print("REJECTED:", exc)
        return 1
    header = next(csv.reader(io.StringIO(body.decode("utf-8-sig"))))
    dup_cols = {h: n for h, n in collections.Counter(header).items() if n > 1}
    print("csv member:", member or "(bare csv)")
    print("columns: %d; repeated names: %s" % (len(header), dup_cols))
    ok = [r for r in rows if not r.errors]
    bad = [r for r in rows if r.errors]
    print("rows: %d parsed, %d rejected" % (len(ok), len(bad)))
    for r in bad:
        print("  rejected line %d id=%s: %s" % (r.line_no, r.source_activity_id, "; ".join(r.errors)))
    if not ok:
        return 0
    vals = [r.values for r in ok]
    print("activity types:", dict(collections.Counter(v["activity_type"] for v in vals)))
    starts = sorted(v["start_utc"] for v in vals)
    print("date range (assumed UTC): %s .. %s" % (starts[0].isoformat(), starts[-1].isoformat()))
    for f in ("moving_s", "avg_hr", "perceived_exertion"):
        n = sum(v[f] is not None for v in vals)
        print("%-20s present in %d/%d" % (f, n, len(vals)))
    gaps = [v["elapsed_s"] - v["moving_s"] for v in vals if v["moving_s"] is not None]
    if gaps:
        gaps.sort()
        print("elapsed - moving (s): min %.0f, median %.0f, max %.0f" % (gaps[0], gaps[len(gaps) // 2], gaps[-1]))
    ids = collections.Counter(v["source_activity_id"] for v in vals)
    print("repeated activity IDs:", {k: n for k, n in ids.items() if n > 1} or "none")
    p = mmr.PARAMS
    runs = [v for v in vals if v["activity_type"] in p["sports"]]
    in_range = [v for v in runs if p["min_m"] <= v["distance_m"] <= p["max_m"]]
    print("Running MMR: %d of %d Runs are inside the %g-%g km conversion range (duplicate, annotation, plausibility "
          "and recency rules need the database and are not applied here)"
          % (len(in_range), len(runs), p["min_m"] / 1000, p["max_m"] / 1000))
    if runs:
        km = sorted(v["distance_m"] / 1000 for v in runs)
        print("Run distances km: min %.1f, median %.1f, max %.1f" % (km[0], km[len(km) // 2], km[-1]))
    print("reconciliation sample (distance, elapsed, derived pace):")
    for v in vals[:args.rows]:
        pace = v["elapsed_s"] / (v["distance_m"] / 1000)
        print("  id=%s %s %.3f km elapsed %s pace %s/km" % (
            v["source_activity_id"], v["activity_type"], v["distance_m"] / 1000,
            fmt_duration(v["elapsed_s"]), fmt_duration(pace)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
