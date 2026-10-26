"""Read a Strava bulk-export activities.csv (bare, or inside the export .zip).

Pure parsing: bytes in, normalized rows out. GPS files in the archive are
never opened. The column layout is an assumption until checked against a
real export (see docs/RATING_METHOD.md §A11).
"""
import csv
import io
import math
import re
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

MAX_CSV_BYTES = 50 * 1024 * 1024
MAX_ZIP_MEMBERS = 100_000
REQUIRED = ["Activity ID", "Activity Date", "Activity Type", "Elapsed Time", "Distance"]
DATE_FORMATS = [
    "%b %d, %Y, %I:%M:%S %p",   # Mar 1, 2024, 7:00:00 AM
    "%d %b %Y, %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
]
MILE_M = 1609.344


class FileRejected(Exception):
    """The whole file cannot be imported; nothing from it is stored."""


@dataclass
class ParsedRow:
    line_no: int
    source_activity_id: "str | None"
    values: "dict | None" = None          # normalized fields when accepted
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


@dataclass
class ParsedFile:
    source_member: "str | None"
    rows: list


def read_upload(filename, data):
    """Return (csv_bytes, member_name) or raise FileRejected."""
    if not data:
        raise FileRejected("file is empty")
    lower = filename.lower()
    if lower.endswith(".zip") or data[:4] == b"PK\x03\x04":
        return _read_zip(data)
    if lower.endswith(".csv"):
        if len(data) > MAX_CSV_BYTES:
            raise FileRejected("CSV larger than %d MB" % (MAX_CSV_BYTES // 2**20))
        return data, None
    raise FileRejected("unsupported file type %r: upload a Strava activities.csv or the export .zip"
                       % filename)


def _unsafe(name):
    return (name.startswith(("/", "\\")) or "\\" in name or re.match(r"^[A-Za-z]:", name)
            or any(part == ".." for part in name.split("/")))


def _read_zip(data):
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
    except (zipfile.BadZipFile, OSError) as exc:
        raise FileRejected("not a readable zip archive (%s)" % exc)
    if len(infos) > MAX_ZIP_MEMBERS:
        raise FileRejected("archive has too many entries")
    bad = [i.filename for i in infos if _unsafe(i.filename)]
    if bad:
        raise FileRejected("archive contains unsafe paths, refusing it: %s" % ", ".join(bad[:5]))
    links = [i.filename for i in infos if (i.external_attr >> 16) & 0o170000 == 0o120000]
    if links:
        raise FileRejected("archive contains symbolic links, refusing it: %s" % ", ".join(links[:5]))
    # activities.csv at the root or one folder down (the export's top folder)
    cands = [i for i in infos if i.filename.split("/")[-1] == "activities.csv"
             and i.filename.count("/") <= 1 and not i.is_dir()]
    if len(cands) != 1:
        raise FileRejected("expected exactly one activities.csv in the archive, found %d" % len(cands))
    info = cands[0]
    if info.file_size > MAX_CSV_BYTES:
        raise FileRejected("activities.csv larger than %d MB" % (MAX_CSV_BYTES // 2**20))
    try:
        with zf.open(info) as fh:             # bounded in-memory read, nothing written to disk
            body = fh.read(MAX_CSV_BYTES + 1)
    except (RuntimeError, NotImplementedError, zipfile.BadZipFile, zlib.error, OSError, EOFError) as exc:
        # encrypted members, unsupported compression, damaged data or CRC mismatch
        raise FileRejected("cannot read %s from the archive (%s: %s)" % (info.filename, type(exc).__name__, exc))
    if len(body) > MAX_CSV_BYTES:
        raise FileRejected("activities.csv larger than declared")
    return body, info.filename


def _num(text):
    t = text.strip()
    if t == "":
        return None
    # plain decimals only: "5,000" (thousands or European decimal?) and "1_500" are refused
    if not re.fullmatch(r"-?\d+(\.\d+)?", t):
        raise ValueError("not a plain number: %r" % text)
    v = float(t)
    if not math.isfinite(v):
        raise ValueError("not a finite number: %r" % text)
    return v


EARLIEST = datetime(1990, 1, 1, tzinfo=timezone.utc)


def _date(text):
    t = text.replace(" ", " ").replace("\xa0", " ").strip()
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(t, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if not EARLIEST <= dt <= datetime.now(timezone.utc) + timedelta(days=1):
            raise ValueError("implausible Activity Date %r (before 1990 or in the future)" % text)
        return dt
    raise ValueError("unrecognized Activity Date %r" % text)


def parse_activities_csv(body):
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise FileRejected("activities.csv is not UTF-8 text")
    if not text.strip():
        raise FileRejected("activities.csv is empty")
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = [h.strip() for h in next(reader)]
    except csv.Error as exc:
        raise FileRejected("cannot read CSV header (%s)" % exc)
    cols = {}
    for idx, name in enumerate(header):
        cols.setdefault(name, []).append(idx)
    missing = [c for c in REQUIRED if c not in cols]
    if missing:
        raise FileRejected("not a Strava activities.csv: missing column(s) %s" % ", ".join(missing))
    if len(cols["Distance"]) < 2:
        raise FileRejected("expected two 'Distance' columns (display units, then metres); "
                           "this layout is not supported yet")
    rows = []
    try:
        for record in reader:
            line_no = reader.line_num
            if not any(c.strip() for c in record):
                continue
            rows.append(_parse_row(line_no, record, header, cols))
    except csv.Error as exc:
        raise FileRejected("CSV is malformed near line %d (%s)" % (reader.line_num, exc))
    if not rows:
        raise FileRejected("activities.csv has a header but no activity rows")
    return rows


def _parse_row(line_no, record, header, cols):
    def get(name, occurrence=0):
        idx = cols.get(name, [])
        if occurrence >= len(idx):
            return ""
        return record[idx[occurrence]] if idx[occurrence] < len(record) else ""

    sid = get("Activity ID").strip() or None
    row = ParsedRow(line_no, sid)
    if len(record) != len(header):
        row.errors.append("row has %d fields, header has %d" % (len(record), len(header)))
        return row
    if sid is None:
        row.errors.append("missing Activity ID")
    start = None
    try:
        start = _date(get("Activity Date"))
    except ValueError as exc:
        row.errors.append(str(exc))
    typ = get("Activity Type").strip()
    if not typ:
        row.errors.append("missing Activity Type")

    dist_m = elapsed = None
    try:
        dist_m = _num(get("Distance", 1))
        if dist_m is None or dist_m <= 0:
            row.errors.append("invalid distance in metres: %r" % get("Distance", 1))
            dist_m = None
    except ValueError as exc:
        row.errors.append("distance (metres) " + str(exc))
    if dist_m is not None:
        try:
            shown = _num(get("Distance", 0))
        except ValueError:
            shown = "bad"
        if shown is None:
            row.warnings.append("display Distance blank; metres value used without cross-check")
        elif shown == "bad" or (not any(
                abs(shown * f - dist_m) <= 0.02 * dist_m + 0.006 * f for f in (1.0, 1000.0, MILE_M))):
            row.errors.append("distance columns disagree: %r (display) vs %r m; unit unknown"
                              % (get("Distance", 0), get("Distance", 1)))
    try:
        elapsed = _num(get("Elapsed Time", 0))
        if elapsed is None:
            elapsed = _num(get("Elapsed Time", 1))
        if elapsed is None or elapsed <= 0:
            row.errors.append("invalid elapsed time: %r" % get("Elapsed Time", 0))
            elapsed = None
        else:
            second = _num(get("Elapsed Time", 1))
            if second is not None and abs(second - elapsed) > 1:
                row.errors.append("elapsed time columns disagree: %r vs %r"
                                  % (get("Elapsed Time", 0), get("Elapsed Time", 1)))
    except ValueError as exc:
        row.errors.append("elapsed time " + str(exc))

    def optional(name, lo, hi, occurrence=0):
        raw = get(name, occurrence)
        try:
            v = _num(raw)
        except ValueError:
            row.warnings.append("%s ignored (not a number: %r)" % (name, raw))
            return None
        if v is None:
            return None
        if not (lo <= v <= hi):
            row.warnings.append("%s ignored (out of range %g-%g: %r)" % (name, lo, hi, raw))
            return None
        return v

    moving = optional("Moving Time", 1, 10 ** 7)
    avg_hr = optional("Average Heart Rate", 20, 250)
    rpe = optional("Perceived Exertion", 1, 10)
    elev = optional("Elevation Gain", 0, 10000)   # metres assumed; display only
    if row.errors:
        return row
    row.values = {
        "source_activity_id": sid,
        "start_utc": start,
        "activity_type": typ,
        "name": get("Activity Name").strip() or None,
        "distance_m": dist_m,
        "elapsed_s": elapsed,
        "moving_s": moving,
        "avg_hr": avg_hr,
        "perceived_exertion": rpe,
        "elevation_gain_m": elev,
    }
    return row
