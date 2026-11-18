# AC Transit Reliability

Collects live AC Transit GTFS-Realtime data (from the AC Transit API and 511.org) every few
minutes so we have a history to model delays and route fragility. Both APIs only expose the
*current* state, so the history exists only if we save it ourselves.

## One-time setup (one person)

1. Create a **public** GitHub repo (public = unlimited free Actions minutes) and push this folder.
2. Everyone's API keys stay out of the repo. Add two secrets under
   *Settings > Secrets and variables > Actions*:
   - `ACT_TOKEN`: token from https://api.actransit.org/transit
   - `API_511_KEY`: key from https://511.org/open-data/token
3. *Settings > Actions > General > Workflow permissions* -> **Read and write permissions**.
4. *Actions tab > collect-realtime > Run workflow* to test. Then it runs every ~5 minutes.

Check the first run's log for `[ok]` lines. If a feed says `[fail]`, fix it before leaving it running.

## Everyone else

```bash
git clone <repo-url> && cd ac-transit-reliability
pip install -r requirements.txt
git pull          # run before analysis to get the newest snapshots
```

Load the data:

```python
import glob, pandas as pd
trips = pd.concat(pd.read_csv(f) for f in glob.glob("data/raw/*/*_511_trips.csv.gz"))
veh   = pd.concat(pd.read_csv(f) for f in glob.glob("data/raw/*/*_511_vehicles.csv.gz"))
```

## Data layout

`data/raw/YYYY-MM-DD/HHMMSS_<source>_<trips|vehicles>.csv.gz` (UTC), `source` is `act` or `511`.

- **trips**: per trip, the next 5 predicted stops (`stop_rank` 0 = next stop) with
  `arrival_delay` / `departure_delay` in seconds vs. schedule. These are *predictions*, so
  the delay at `stop_rank` 0 just before a bus passes is our best proxy for the actual delay.
- **vehicles**: bus position, current stop, status, speed, occupancy.
- `fetched_at` = when we polled (unix), `feed_ts` = when the agency generated the feed.
- Static schedule: `python fetch_static.py` (saves GTFS zips to `data/static/`).

## Run a faster collector locally (optional)

GitHub's scheduler can't go below 5 minutes and often lags. Anyone with an always-on
machine can poll every 60 s and share the files:

```bash
export ACT_TOKEN=... API_511_KEY=...
python collect.py --loop 60
```

## Known limits

- Scheduled Actions runs are best-effort; gaps happen. Check `data/raw` file counts per day.
- Data volume: check repo size after day 1. If it's growing too fast, lower `STOPS_PER_TRIP`
  in `collect.py` or collect only for chosen routes.
