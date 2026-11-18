# AC Transit Reliability

A growing history of live bus data from **AC Transit**, the public bus operator for the East
Bay (Oakland, Berkeley, Richmond, Hayward, Fremont and nearby cities, plus Transbay routes to
San Francisco). We use it to model delays and how fragile each route is.

**The collector is already running on GitHub. You don't need to set anything up**: no API
keys, no scripts to run. Just pull the repo and read the data.

## Data sources

Both sources publish live data in **GTFS-Realtime**, the standard format transit agencies
use for real-time information (it's what powers live arrival times in Google Maps and
transit apps). We save two of its feeds:

- **Trip updates**: for every bus trip in progress, the *predicted* arrival and departure
  time at its upcoming stops.
- **Vehicle positions**: where every bus is right now: location, speed, heading, which stop
  it's at or approaching, and how crowded it is.

We pull both feeds from two places:

| Source | What it is |
|---|---|
| [AC Transit API](https://api.actransit.org/transit) | AC Transit's own developer API. |
| [511.org](https://511.org/open-data/transit) | The Bay Area's regional open-data portal, run by the Metropolitan Transportation Commission. Republishes feeds from all Bay Area agencies; we request AC Transit only. |

They describe the same buses, so they mostly agree, but they use different stop IDs and
generate their feeds at slightly different times. Keeping both gives a backup if one is
down and lets us cross-check.

These feeds only show what's happening **right now**; neither keeps a history. So every
~5 minutes we save a snapshot. On a weekday midday that's about 300 buses on roughly 60
routes and ~2,300 stop predictions per feed.

We also save AC Transit's **static GTFS schedule** (`data/static/`): the planned timetable,
routes and stops. The live feeds don't report delays directly, so the schedule is what we
compare predicted times against.

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

## Running the scripts locally (optional)

You don't need to do this: GitHub already collects everything, and reading the data needs
no keys. It's only for testing changes to the scripts, or collecting faster than every 5
minutes from your own computer.

The API keys used on GitHub are stored as repository secrets and can't be copied, so you
need your own (both free):

1. Get the keys:
   - `ACT_TOKEN`: register at https://api.actransit.org/transit
   - `API_511_KEY`: request one at https://511.org/open-data/token
2. Set them in your terminal (never commit them to the repo):
   ```bash
   export ACT_TOKEN=your_actransit_token
   export API_511_KEY=your_511_key
   ```
3. Run what you need:
   ```bash
   python collect.py              # one snapshot of every feed
   python collect.py --loop 60    # keep polling every 60 s until you stop it (Ctrl+C)
   python fetch_static.py         # download the static schedule
   ```

If a key isn't set, `collect.py` skips that source and says so. Snapshots you collect
locally go into the same `data/raw/` folders; commit and push them if you want to share them.
Don't run `report.py` locally; GitHub regenerates the report, and a local copy will block
your next `git pull` (fix with `git checkout data/report.html`).

## Known limits

- Gaps happen when both triggers miss; check snapshots per day in the report.
- Each trip keeps only its next 5 predicted stops per snapshot (`STOPS_PER_TRIP` in
  `collect.py`), to keep files small.
- The repo grows with every snapshot. If cloning gets slow, use
  `git clone --depth 1` to skip the history.
