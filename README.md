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
4. *Actions tab > collect-realtime > Run workflow* to test.
5. Also trigger it every 5 minutes from [cron-job.org](https://cron-job.org), since GitHub's own
   scheduler runs late or skips. Both stay on; either keeps data coming if the other stops:
   - Create a fine-grained token at *GitHub > Settings > Developer settings > Personal access
     tokens > Fine-grained*: only this repository, permission **Actions: Read and write**.
   - New cron job, every 5 minutes, **POST** to
     `https://api.github.com/repos/<owner>/<repo>/actions/workflows/collect-realtime.yml/dispatches`
     with headers `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`
     and body `{"ref":"main"}`. A working call returns HTTP 204.

Check the first run's log for `[ok]` lines. If a feed says `[fail]`, fix it before leaving it running.

## Everyone else

```bash
git clone <repo-url> && cd ac-transit-reliability
pip install -r requirements.txt
git pull          # run before analysis to get the newest snapshots
```

To see what's been collected: `git pull`, then open `data/report.html` in a browser. Every
collector run regenerates it (`report.py`): totals and gaps per source and feed, snapshots
per day and hour, the newest snapshot of each feed, and what every column means.

To work with the full data in pandas, open `explore.ipynb` and **Run All**. It loads every
snapshot as `trips_511`, `veh_511`, `trips_act` and `veh_act`.

Note: neither feed fills in `arrival_delay` / `departure_delay`; they only give predicted
times. Delays have to be computed against the static schedule in `data/static`, which the
workflow downloads weekly.

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
