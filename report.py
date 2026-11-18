#!/usr/bin/env python3
"""Write data/report.html: what the collector has saved so far.

Runs at the end of every GitHub Actions collection run, so `git pull` always
brings an up-to-date report. Open data/report.html in a browser.

Shows totals and coverage per source and feed (from file names, so it stays fast
as data grows), the newest snapshot of each feed in full, and what every column means.

Usage: python report.py
"""
import gzip
import csv
import html
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
REPORT_PATH = ROOT / "data" / "report.html"
TZ = ZoneInfo("America/Los_Angeles")
MAX_ROWS = 300  # rows shown per table from the newest snapshot

SOURCES = {"511": "511.org", "act": "AC Transit API"}
FEEDS = {"trips": "Trip updates", "vehicles": "Vehicle positions"}
FILE_RE = re.compile(r"(\d{6})_(\w+?)_(trips|vehicles)\.csv\.gz$")

UNIX_COLS = {"fetched_at", "feed_ts", "arrival_time", "departure_time", "timestamp"}

# Code meanings from the GTFS-Realtime spec.
ENUMS = {
    "schedule_relationship": {"0": "scheduled", "1": "skipped", "2": "no data", "3": "unscheduled"},
    "current_status": {"0": "arriving", "1": "stopped at", "2": "in transit to"},
    "occupancy_status": {"0": "empty", "1": "many seats", "2": "few seats", "3": "standing room",
                         "4": "crushed standing", "5": "full", "6": "not accepting", "7": "no data",
                         "8": "not boardable"},
}

COLUMNS = {
    "trips": {
        "fetched_at": "When our collector polled the feed. Same for every row of one snapshot.",
        "feed_ts": "When the agency generated the feed. Usually a few seconds from fetched_at.",
        "trip_id": "Scheduled trip. Matches trip_id in the static GTFS schedule.",
        "route_id": "Route name, e.g. 51A, NL, 72M.",
        "direction_id": "0 or 1: the two directions of a route (defined in the static schedule).",
        "start_date": "Service day of the trip, YYYYMMDD.",
        "start_time": "Scheduled start of the trip, HH:MM:SS. Can pass 24:00 for trips after midnight.",
        "vehicle_id": "Bus number running the trip.",
        "stop_rank": "Position in the upcoming-stops list: 0 = next stop, up to 4. Added by our collector.",
        "stop_id": "Stop the prediction is for. 511 and AC Transit use different stop IDs.",
        "stop_sequence": "Order of this stop along the trip (1 = first stop).",
        "arrival_delay": "Seconds late vs. schedule. Not filled by either feed; compute it from the static schedule.",
        "arrival_time": "Predicted arrival at the stop.",
        "departure_delay": "Seconds late vs. schedule. Not filled by either feed.",
        "departure_time": "Predicted departure. Mostly only at first stops and timepoints.",
        "schedule_relationship": "0 scheduled, 1 stop will be skipped, 2 no prediction, 3 unscheduled.",
    },
    "vehicles": {
        "fetched_at": "When our collector polled the feed.",
        "feed_ts": "When the agency generated the feed.",
        "vehicle_id": "Bus number.",
        "trip_id": "Trip the bus is running. Empty when it isn't on a trip.",
        "route_id": "Route of that trip.",
        "direction_id": "0 or 1. Not filled by the AC Transit feed; the 511 feed has it.",
        "start_date": "Service day of the trip, YYYYMMDD.",
        "start_time": "Scheduled start of the trip.",
        "lat": "Latitude in degrees.",
        "lon": "Longitude in degrees.",
        "bearing": "Heading in degrees clockwise from north (0 = north, 90 = east).",
        "speed": "Meters per second (x 2.237 = mph).",
        "current_stop_sequence": "stop_sequence of the stop the bus is at or heading to.",
        "stop_id": "That stop's ID (different ID systems per source).",
        "current_status": "0 about to arrive at the stop, 1 stopped at it, 2 in transit to it.",
        "timestamp": "When the bus reported this position.",
        "occupancy_status": "Crowding: 0 empty, 1 many seats, 2 few seats, 3 standing room, "
                            "4 crushed, 5 full, 6 not accepting passengers, 7 no data.",
    },
}

STYLE = """
body{font-family:-apple-system,Helvetica,Arial,sans-serif;color:#222;margin:0;background:#fff}
main{max-width:1100px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:8px 0 4px} h2{font-size:17px;margin:32px 0 6px}
h3{font-size:15px;margin:20px 0 6px}
.muted{color:#777;font-size:13px}
table{border-collapse:collapse;font-size:12.5px;margin:6px 0 12px}
th,td{border-bottom:1px solid #e5e5e5;padding:4px 8px;text-align:left;vertical-align:top;white-space:nowrap}
th{background:#f6f6f6;position:sticky;top:0}
td.num{text-align:right;font-variant-numeric:tabular-nums}
td.desc{white-space:normal;min-width:320px}
.scroll{max-height:520px;overflow:auto;border:1px solid #e5e5e5}
.bad{color:#b00020} .warn{color:#b36b00} .ok{color:#1e7e34}
details{margin:8px 0} summary{cursor:pointer;font-weight:600;font-size:14px}
"""


def esc(x):
    return html.escape(str(x))


def local(ts):
    return datetime.fromtimestamp(int(ts), timezone.utc).astimezone(TZ)


def snapshot_time(day_dir, hhmmss):
    return datetime.strptime(day_dir + hhmmss, "%Y-%m-%d%H%M%S").replace(tzinfo=timezone.utc).astimezone(TZ)


def index_files():
    """{(source, feed): [(local_dt, path, size_bytes), ...]} sorted by time."""
    out = defaultdict(list)
    for day in sorted(p for p in RAW.iterdir() if p.is_dir()) if RAW.exists() else []:
        for f in day.iterdir():
            m = FILE_RE.match(f.name)
            if m:
                out[(m[2], m[3])].append((snapshot_time(day.name, m[1]), f, f.stat().st_size))
    for v in out.values():
        v.sort()
    return out


def read_csv(path):
    with gzip.open(path, "rt", newline="") as fh:
        rows = list(csv.reader(fh))
    return (rows[0], rows[1:]) if rows else ([], [])


def fmt_cell(col, val):
    if val == "":
        return '<span class="muted">·</span>'
    if col in UNIX_COLS:
        try:
            return f'{local(val):%m-%d %H:%M:%S}'
        except ValueError:
            return esc(val)
    if col in ENUMS and val in ENUMS[col]:
        return f'{esc(val)} <span class="muted">{ENUMS[col][val]}</span>'
    if col in ("lat", "lon"):
        return f"{float(val):.5f}"
    if col in ("speed", "bearing"):
        return f"{float(val):.1f}"
    return esc(val)


def table(header, rows, num_cols=(), wrap_cols=()):
    def td(i, c):
        cls = "num" if i in num_cols else "desc" if i in wrap_cols else ""
        return f'<td class="{cls}">{c}</td>' if cls else f"<td>{c}</td>"
    head = "".join(f"<th>{esc(h)}</th>" for h in header)
    body = "\n".join("<tr>" + "".join(td(i, c) for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f"<table><tr>{head}</tr>\n{body}</table>"


def gap_stats(times):
    if len(times) < 2:
        return "", ""
    gaps = sorted((b - a).total_seconds() / 60 for a, b in zip(times, times[1:]))
    return f"{gaps[len(gaps) // 2]:.1f}", f"{gaps[-1]:.0f}"


def build():
    idx = index_files()
    now = datetime.now(TZ)
    parts = [
        "<!doctype html>", '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        "<title>AC Transit collection report</title>", f"<style>{STYLE}</style>", "<main>",
        "<h1>AC Transit collection report</h1>",
        f'<p class="muted">Generated {now:%Y-%m-%d %H:%M %Z}. All times Pacific. '
        "Regenerated after every collector run; <code>git pull</code> to update.</p>",
    ]
    if not idx:
        parts.append("<p>No data collected yet.</p></main>")
        return "\n".join(parts)

    # Overview
    rows = []
    for (src, feed), files in sorted(idx.items()):
        times = [t for t, _, _ in files]
        med, longest = gap_stats(times)
        age_min = (now - times[-1]).total_seconds() / 60
        cls = "ok" if age_min < 30 else "warn" if age_min < 180 else "bad"
        rows.append([
            esc(SOURCES.get(src, src)), esc(FEEDS[feed]), f"{len(files):,}",
            f"{times[0]:%Y-%m-%d %H:%M}",
            f'<span class="{cls}">{times[-1]:%Y-%m-%d %H:%M} ({age_min:.0f} min ago)</span>',
            med, longest, f"{sum(s for _, _, s in files) / 1e3:,.0f}",
        ])
    parts += ["<h2>Overview</h2>", table(
        ["Source", "Feed", "Snapshots", "First", "Latest", "Median gap (min)",
         "Longest gap (min)", "Size (KB)"], rows, num_cols=(2, 5, 6, 7))]

    # Snapshots per day and per hour (latest 3 days)
    per_day, per_hour = defaultdict(Counter), defaultdict(Counter)
    keys = sorted(idx)
    for k in keys:
        for t, _, _ in idx[k]:
            per_day[t.date()][k] += 1
            per_hour[t.replace(minute=0, second=0, microsecond=0)][k] += 1
    labels = [f"{SOURCES.get(s, s)} {f}" for s, f in keys]
    parts += ["<h2>Snapshots per day</h2>",
              '<p class="muted">At one run every 5 minutes, a full day is 288.</p>',
              table(["Date"] + labels,
                    [[f"{d:%a %Y-%m-%d}"] + [per_day[d][k] for k in keys] for d in sorted(per_day, reverse=True)],
                    num_cols=range(1, len(keys) + 1))]
    recent = sorted(per_hour, reverse=True)[:72]
    parts += ["<details><summary>Snapshots per hour (last 72 hours with data)</summary>",
              '<div class="scroll">',
              table(["Hour"] + labels,
                    [[f"{h:%a %m-%d %H:00}"] + [per_hour[h][k] for k in keys] for h in recent],
                    num_cols=range(1, len(keys) + 1)),
              "</div></details>"]

    # Latest snapshot of each feed, with column reference
    for (src, feed), files in sorted(idx.items()):
        t, path, _ = files[-1]
        header, data = read_csv(path)
        filled = {c: sum(1 for r in data if r[i] != "") for i, c in enumerate(header)}
        n = len(data)
        extra = ""
        if feed == "trips" and n:
            extra = (f", {len({r[header.index('trip_id')] for r in data}):,} trips, "
                     f"{len({r[header.index('route_id')] for r in data})} routes")
        elif n:
            extra = f", {len({r[header.index('vehicle_id')] for r in data}):,} buses"
        parts.append(f"<h2>{esc(SOURCES.get(src, src))}: {esc(FEEDS[feed])}</h2>")
        parts.append(f'<p class="muted">Latest snapshot {t:%Y-%m-%d %H:%M:%S}: {n:,} rows{extra}. '
                     f"File <code>{esc(path.relative_to(ROOT))}</code>.</p>")

        ref = []
        for c in header:
            pct = 100 * filled[c] / n if n else 0
            cls = "bad" if pct == 0 else "warn" if pct < 90 else ""
            ref.append([f"<code>{esc(c)}</code>", f'<span class="{cls}">{pct:.0f}%</span>',
                        esc(COLUMNS[feed].get(c, ""))])
        parts.append("<details><summary>Columns</summary>")
        parts.append(table(["Column", "Filled", "Meaning"], ref, num_cols=(1,), wrap_cols=(2,)))
        parts.append("</details>")

        shown = data[:MAX_ROWS]
        note = f" (first {MAX_ROWS} of {n:,})" if n > MAX_ROWS else ""
        parts.append(f"<details open><summary>Rows{note}</summary>")
        parts.append('<div class="scroll">' + table(
            header, [[fmt_cell(c, v) for c, v in zip(header, r)] for r in shown]) + "</div>")
        parts.append("</details>")

    parts.append('<p class="muted">Unix times are shown as Pacific MM-DD HH:MM:SS. '
                 "Coded columns show the code and its meaning. A dot means empty.</p></main>")
    return "\n".join(parts)


def write_report():
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(build())
    return REPORT_PATH


if __name__ == "__main__":
    print(f"wrote {write_report()}")
