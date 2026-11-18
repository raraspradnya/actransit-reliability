#!/usr/bin/env python3
"""Snapshot live GTFS-Realtime feeds from AC Transit and 511 into compact CSVs.

One run = one snapshot per (source, feed). Files land in
data/raw/YYYY-MM-DD/<HHMMSS>_<source>_<trips|vehicles>.csv.gz  (UTC timestamps).

Env vars:
  ACT_TOKEN     AC Transit API token  (https://api.actransit.org/transit)
  API_511_KEY   511.org API key       (https://511.org/open-data/token)

Usage:
  python collect.py                      # one snapshot of every configured source
  python collect.py --loop 60            # keep polling every 60 s (run on an always-on machine)
  python collect.py --sources 511        # only one source
"""
import argparse
import csv
import gzip
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from google.transit import gtfs_realtime_pb2

OUT_DIR = Path(os.environ.get("OUT_DIR", "data/raw"))
STOPS_PER_TRIP = 5  # keep the next N predicted stops per trip (keeps files small)

SOURCES = {
    "act": {
        "env": "ACT_TOKEN",
        "url": "https://api.actransit.org/transit/gtfsrt/{feed}",
        "params": lambda key: {"token": key},
        "feeds": {"trips": "tripupdates", "vehicles": "vehicles"},
    },
    "511": {
        "env": "API_511_KEY",
        "url": "https://api.511.org/transit/{feed}",
        "params": lambda key: {"api_key": key, "agency": "AC"},
        "feeds": {"trips": "tripupdates", "vehicles": "vehiclepositions"},
    },
}

TRIP_COLS = [
    "fetched_at", "feed_ts", "trip_id", "route_id", "direction_id", "start_date",
    "start_time", "vehicle_id", "stop_rank", "stop_id", "stop_sequence",
    "arrival_delay", "arrival_time", "departure_delay", "departure_time",
    "schedule_relationship",
]
VEH_COLS = [
    "fetched_at", "feed_ts", "vehicle_id", "trip_id", "route_id", "direction_id",
    "start_date", "start_time", "lat", "lon", "bearing", "speed",
    "current_stop_sequence", "stop_id", "current_status", "timestamp",
    "occupancy_status",
]


def fetch(source, kind, key):
    cfg = SOURCES[source]
    url = cfg["url"].format(feed=cfg["feeds"][kind])
    r = requests.get(url, params=cfg["params"](key), timeout=30)
    r.raise_for_status()
    feed = gtfs_realtime_pb2.FeedMessage()
    try:
        feed.ParseFromString(r.content)
    except Exception:
        raise RuntimeError(f"not protobuf; first bytes: {r.content[:200]!r}")
    return feed


def _opt(msg, field, default=""):
    return getattr(msg, field) if msg.HasField(field) else default


def parse_trips(feed, fetched_at):
    rows = []
    feed_ts = feed.header.timestamp
    for e in feed.entity:
        if not e.HasField("trip_update"):
            continue
        tu = e.trip_update
        t = tu.trip
        base = [fetched_at, feed_ts, t.trip_id, t.route_id, _opt(t, "direction_id"),
                t.start_date, t.start_time, tu.vehicle.id]
        for rank, st in enumerate(tu.stop_time_update[:STOPS_PER_TRIP]):
            a, d = st.arrival, st.departure
            rows.append(base + [
                rank, st.stop_id, _opt(st, "stop_sequence"),
                _opt(a, "delay"), _opt(a, "time"), _opt(d, "delay"), _opt(d, "time"),
                st.schedule_relationship,
            ])
    return rows


def parse_vehicles(feed, fetched_at):
    rows = []
    feed_ts = feed.header.timestamp
    for e in feed.entity:
        if not e.HasField("vehicle"):
            continue
        v = e.vehicle
        t, p = v.trip, v.position
        rows.append([
            fetched_at, feed_ts, v.vehicle.id, t.trip_id, t.route_id,
            _opt(t, "direction_id"), t.start_date, t.start_time,
            p.latitude, p.longitude, _opt(p, "bearing"), _opt(p, "speed"),
            _opt(v, "current_stop_sequence"), v.stop_id, _opt(v, "current_status"),
            v.timestamp, _opt(v, "occupancy_status"),
        ])
    return rows


def write_gz(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)


def snapshot(sources):
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%H%M%S")
    day_dir = OUT_DIR / now.strftime("%Y-%m-%d")
    fetched_at = int(now.timestamp())
    ok = 0
    for source in sources:
        key = os.environ.get(SOURCES[source]["env"])
        if not key:
            print(f"[skip] {source}: {SOURCES[source]['env']} not set", file=sys.stderr)
            continue
        for kind, parser, cols in (("trips", parse_trips, TRIP_COLS),
                                   ("vehicles", parse_vehicles, VEH_COLS)):
            try:
                rows = parser(fetch(source, kind, key), fetched_at)
                write_gz(day_dir / f"{stamp}_{source}_{kind}.csv.gz", cols, rows)
                print(f"[ok] {source} {kind}: {len(rows)} rows")
                ok += 1
            except Exception as exc:  # keep going; one bad feed shouldn't kill the run
                print(f"[fail] {source} {kind}: {exc}", file=sys.stderr)
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", nargs="+", default=list(SOURCES), choices=list(SOURCES))
    ap.add_argument("--loop", type=int, default=0, help="poll every N seconds (0 = once)")
    args = ap.parse_args()

    if not args.loop:
        sys.exit(0 if snapshot(args.sources) else 1)
    while True:
        started = time.time()
        snapshot(args.sources)
        time.sleep(max(1, args.loop - (time.time() - started)))


if __name__ == "__main__":
    main()
