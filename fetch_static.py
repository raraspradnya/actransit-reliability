#!/usr/bin/env python3
"""Download the current static GTFS schedule (needed to compute scheduled times).

Usage: python fetch_static.py
Saves data/static/actransit_gtfs_<date>.zip (AC Transit API) and
data/static/511_gtfs_<date>.zip (511 API, operator AC) when keys are set.
"""
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

out = Path("data/static")
out.mkdir(parents=True, exist_ok=True)
day = datetime.now(timezone.utc).strftime("%Y-%m-%d")

jobs = []
if os.environ.get("ACT_TOKEN"):
    jobs.append(("actransit", "https://api.actransit.org/transit/gtfs/download",
                 {"token": os.environ["ACT_TOKEN"]}))
if os.environ.get("API_511_KEY"):
    jobs.append(("511", "https://api.511.org/transit/datafeeds",
                 {"api_key": os.environ["API_511_KEY"], "operator_id": "AC"}))

for name, url, params in jobs:
    r = requests.get(url, params=params, timeout=120)
    r.raise_for_status()
    p = out / f"{name}_gtfs_{day}.zip"
    p.write_bytes(r.content)
    print(f"saved {p} ({len(r.content)/1e6:.1f} MB)")
