#!/usr/bin/env python3
"""Download hourly weather for points across AC Transit's service area.

Source: Open-Meteo Historical Forecast API (free, no key). Values are modeled
from high-resolution weather models (about 2-3 km grid in the US), not from a
single weather station, so every location has complete hourly data.

Files land in data/weather/YYYY-MM.csv.gz, one row per location per hour (UTC).
Each run only fetches what's missing: months with no file, and the latest month
once its newest hour is more than a day old. So it's cheap to run every time the
collector runs; it actually downloads about once a day.

Usage:
  python fetch_weather.py                     # fill everything since START, then keep up to date
  python fetch_weather.py --start 2024-01     # different first month
"""
import argparse
import csv
import gzip
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

OUT_DIR = Path("data/weather")
START = "2026-11"  # first month of our own collection; use --start for earlier months
URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"

# Spread across the service area so local differences (e.g. rain in the hills vs. the
# flats, fog at the Bay Bridge) are captured. Join each stop to its nearest location.
LOCATIONS = {
    "oakland_downtown": (37.8044, -122.2712),
    "berkeley": (37.8716, -122.2727),
    "richmond": (37.9358, -122.3477),
    "san_leandro": (37.7249, -122.1561),
    "hayward": (37.6688, -122.0808),
    "fremont": (37.5485, -121.9886),
    "sf_transbay": (37.7897, -122.3972),
}

# Open-Meteo variable -> our column name (units in the name).
VARIABLES = {
    "temperature_2m": "temp_c",
    "precipitation": "precip_mm",
    "rain": "rain_mm",
    "weather_code": "weather_code",
    "cloud_cover": "cloud_cover_pct",
    "visibility": "visibility_m",
    "wind_speed_10m": "wind_kmh",
    "wind_gusts_10m": "wind_gust_kmh",
}
COLS = ["time_utc", "location", "lat", "lon"] + list(VARIABLES.values())


def month_range(first, last):
    y, m = map(int, first.split("-"))
    while (y, m) <= (last.year, last.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def latest_hour(path):
    """Newest time_utc in a month file, or None if it's missing or empty."""
    if not path.exists():
        return None
    with gzip.open(path, "rt", newline="") as f:
        times = [row["time_utc"] for row in csv.DictReader(f)]
    return max(times) if times else None


def fetch_month(y, m, now):
    first = date(y, m, 1)
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
    last = min(last, now.date())
    names = list(LOCATIONS)
    r = requests.get(URL, timeout=120, params={
        "latitude": ",".join(str(LOCATIONS[n][0]) for n in names),
        "longitude": ",".join(str(LOCATIONS[n][1]) for n in names),
        "start_date": first.isoformat(),
        "end_date": last.isoformat(),
        "hourly": ",".join(VARIABLES),
        "timezone": "GMT",
    })
    r.raise_for_status()
    results = r.json()
    if isinstance(results, dict):  # a single location comes back as an object
        results = [results]

    cutoff = now.strftime("%Y-%m-%dT%H:00")  # drop forecast hours later than now
    rows = []
    for name, res in zip(names, results):
        h = res["hourly"]
        lat, lon = LOCATIONS[name]
        for i, t in enumerate(h["time"]):
            if t > cutoff:
                continue
            vals = [h[v][i] for v in VARIABLES]
            if all(v is None for v in vals):
                continue
            rows.append([t, name, lat, lon] + ["" if v is None else v for v in vals])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=START, help="first month, YYYY-MM")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    stale_before = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:00")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    todo = []
    for y, m in month_range(args.start, now.date()):
        path = OUT_DIR / f"{y:04d}-{m:02d}.csv.gz"
        newest = latest_hour(path)
        month_end = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).isoformat() + "T23:00"
        # Complete = has data through the month's last hour (or, for the current
        # month, through about a day ago). Anything short of that is (re)fetched.
        if newest is None or newest < min(month_end, stale_before):
            todo.append((y, m, path))

    if not todo:
        print("[ok] weather up to date")
        return
    failed = 0
    for y, m, path in todo:
        try:
            rows = fetch_month(y, m, now)
            with gzip.open(path, "wt", newline="") as f:
                w = csv.writer(f)
                w.writerow(COLS)
                w.writerows(rows)
            print(f"[ok] weather {y:04d}-{m:02d}: {len(rows)} rows")
        except Exception as exc:  # keep going; the next run retries
            print(f"[fail] weather {y:04d}-{m:02d}: {exc}", file=sys.stderr)
            failed += 1
    sys.exit(1 if failed == len(todo) else 0)


if __name__ == "__main__":
    main()
