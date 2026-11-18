# AC Transit Reliability

Collects live AC Transit GTFS-Realtime data (from the AC Transit API and 511.org) every 5
minutes, so we have a history to model delays and route fragility. Both APIs only show the
*current* state, so the history exists only because we save it.

**The collector is already running. There is nothing to set up.** API keys and the
schedule are in place; you only need to pull the data and read it.

## Getting the data

```bash
git clone https://github.com/raraspradnya/actransit-reliability.git
cd actransit-reliability
pip install -r requirements.txt
```

New snapshots are committed every ~5 minutes, so run `git pull` whenever you want the latest.

## Looking at what's been collected

**Quick look: `data/report.html`.** Open it in a browser after `git pull`. It's regenerated
after every collection and shows:

- each source and feed: number of snapshots, first and latest, gaps between snapshots, size
  (the latest time turns orange or red if collection has stopped)
- snapshots per day and per hour, to spot missing periods (a full day is ~288 per feed)
- the newest snapshot of each feed, with timestamps in Pacific time and codes labeled
- what every column means and how often it's filled

**Full data in pandas: `explore.ipynb`.** Open it and **Run All**. It runs `git pull`, then
loads every snapshot into four DataFrames: `trips_511`, `veh_511`, `trips_act`, `veh_act`.
Add your own cells below. The notebook also has a full column reference.

Or load the files directly:

```python
import glob, pandas as pd
ids = {c: str for c in ["trip_id", "route_id", "vehicle_id", "stop_id", "start_date", "start_time"]}
trips = pd.concat(pd.read_csv(f, dtype=ids) for f in sorted(glob.glob("data/raw/*/*_511_trips.csv.gz")))
```

Read the ID columns as text, or route names like `51A` and stop IDs can get mangled.

## What's in the data

Files are at `data/raw/YYYY-MM-DD/HHMMSS_<source>_<feed>.csv.gz`. The folder date and file
time are **UTC** (Pacific + 8 h in winter), so evening Pacific data lands in the next day's
folder.

| Source | `<source>` | Notes |
|---|---|---|
| 511.org | `511` | Has `direction_id` on vehicles. |
| AC Transit API | `act` | Same buses; uses a different set of stop IDs than 511. |

| Feed | `<feed>` | One row per |
|---|---|---|
| Trip updates | `trips` | trip × upcoming stop: the next 5 predicted stops of each active trip (`stop_rank` 0 = next stop) |
| Vehicle positions | `vehicles` | bus: location, speed, heading, current stop, crowding |

Things to know before analyzing:

- **No delays are reported.** `arrival_delay` and `departure_delay` are always empty in both
  feeds. The feeds only give *predicted* times (`arrival_time`, `departure_time`, unix
  seconds). Delay = predicted time − scheduled time, using the static schedule in
  `data/static/` (GTFS zips, refreshed weekly). The latest prediction just before a bus
  reaches a stop is the best proxy for its actual arrival.
- **Duplicates.** Two runs can land seconds apart and get the identical feed (same
  `feed_ts`). Drop exact repeats before counting:
  `df.drop_duplicates(subset=[c for c in df.columns if c not in ("fetched_at", "fetched_dt")])`
- **Times.** `fetched_at` = when we polled, `feed_ts` = when the agency built the feed,
  `timestamp` = when the bus reported its position. All unix seconds (UTC).
- **Codes.** `current_status`, `occupancy_status` and `schedule_relationship` are
  GTFS-Realtime codes; their meanings are in the report and the notebook.

## How collection works

- `.github/workflows/collect-realtime.yml` runs `collect.py`, which saves one snapshot of
  each feed, then `report.py`, and commits the new files.
- It's triggered every 5 minutes by **cron-job.org** (calling GitHub's API), and also by
  GitHub's own 5-minute schedule as a backup. GitHub's scheduler is often late or skips,
  which is why cron-job.org is the main trigger. Having both sometimes produces two
  snapshots close together; that's expected (see Duplicates).
- The AC Transit and 511 API keys are stored as GitHub secrets (`ACT_TOKEN`, `API_511_KEY`),
  not in the code.
- The static schedule is re-downloaded automatically when the newest copy is over 7 days old.

To check that it's healthy: look at the "Latest" column in `data/report.html`, or the
**Actions** tab on GitHub. Each run's log lists `[ok]` or `[fail]` per feed.

## If something stops

- **Report shows the latest snapshot as hours old, or runs disappear from the Actions tab:**
  the cron-job.org job or its GitHub token may have expired. GitHub's own schedule keeps
  running in the meantime, just less regularly. Ask the repo owner, who manages both.
- **A run fails with `[fail]` for a feed:** usually an API key problem or a temporary outage
  at AC Transit or 511. One failed feed doesn't stop the others.
- **Manual run:** Actions tab → *collect-realtime* → *Run workflow*.

## Files

| File | What it does |
|---|---|
| `collect.py` | Fetches one snapshot of each feed and saves the CSVs. |
| `report.py` | Builds `data/report.html`. |
| `fetch_static.py` | Downloads the static GTFS schedule to `data/static/`. |
| `explore.ipynb` | Loads all collected data into pandas. |

Running the scripts yourself needs your own API keys (`ACT_TOKEN` from
https://api.actransit.org/transit, `API_511_KEY` from https://511.org/open-data/token),
set as environment variables. You don't need them to read the data.

## Known limits

- Gaps happen when both triggers miss; check snapshots per day in the report.
- Each trip keeps only its next 5 predicted stops per snapshot (`STOPS_PER_TRIP` in
  `collect.py`), to keep files small.
- The repo grows with every snapshot. If cloning gets slow, use
  `git clone --depth 1` to skip the history.
