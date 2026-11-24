# Route-hour delay risk model (Toronto TTC, 2022): design

Status: draft for approval, 2026-11-22. Branch `abraham`.

## Why

AC Transit's APIs keep no history, so the team's collector (`collect.py`) has only been building one since 2026-11-18. While that history grows, we use a fixed dataset from another city, Toronto's TTC bus delay log (Jan–Jun 2022), to learn **which kinds of features predict bus delays and which modeling setup works**. If the approach carries over, we rerun it on AC Transit data with UC Berkeley features. If it doesn't, a Toronto-only model is still a valid result. The project is early, so this is exploratory.

## Goals

- Predict **how many delay incidents a route has in a given hour** (route-hour delay risk), as a rate per scheduled trip.
- Find out which outside factors move that rate: weather, holidays, school and university terms, route traits, and recent delays.
- Build the pipeline so that most of it carries over to AC Transit: a route-hour table, exposure from GTFS, a weather join, calendar flags and the same models.

## Non-goals (for now)

- Predicting how long a single delay lasts.
- Sports and event schedules (second round, once the simple features are measured).
- Geocoding the free-text `Location` column or making maps.
- Any AC Transit modeling; that waits for more collected data.
- An app or dashboard.

## Anti-goals (would make this a failure even if it runs)

- A model that wins only because it leaks the answer, e.g. by using `Incident`, `Min Delay`, `Min Gap`, `Direction` or `Vehicle` from the same hour, or by using a random train/test split.
- A model that just learns "busy routes have more delays" because it was never normalized by service volume.
- A sprawl of files. The work is two notebooks plus a small `data/toronto/` folder.

## Constraints

- Data: `ttc-bus-delay-data-2022.csv`, 27,351 rows (27,197 after exact duplicates are dropped), 223 routes, 1 Jan – 30 Jun 2022. No coordinates.
- Sparse target: ~27k incidents over ~220 routes × 4,344 hours, so most route-hours are zero.
- January 2022 is unusual (Omicron staffing, schools and UofT online, the 17 Jan snowstorm). It needs to be controlled for, not learned as a general pattern.
- Weather: Open-Meteo historical-forecast API covers Toronto 2022 (checked: 17 Jan 2022 shows ~19 cm snow). It's the same API the team's `fetch_weather.py` uses, with no key.
- Schedule (exposure and route traits): City of Toronto Open Data publishes only the **current** TTC GTFS (29 MB zip, Nov 2026). The 2022 archive at transitfeeds.com refuses automated downloads. So exposure comes from the current schedule as an approximation; see Data below.
- Stay within pandas, numpy, matplotlib, seaborn, plus scikit-learn and pyarrow, which are new. These go in the shared `requirements.txt`. The collector's GitHub Action installs its own two packages and doesn't read that file, so data collection isn't affected.
- Commit messages are short one-liners.

## Approaches considered

1. **EDA notebook + model notebook (picked).** `eda.ipynb` gains a part 2 that builds and explores the route-hour table and saves it once. `model.ipynb` reads it and models. Teammates can read the EDA without the modeling, and model reruns don't rerun the EDA.
2. **One notebook for everything.** Fewest files, but 40+ cells mixing exploration and modeling; every model rerun reruns the EDA.
3. **Shared `features.py` + notebooks.** Reusable for AC Transit, but it builds that reuse layer before we know which features matter. Code can be pulled out later, once a feature has proven itself.

## Design

### Files

```
data/toronto/ttc-bus-delay-data-2022.csv   raw, moved here from data/ (committed, 2 MB)
data/toronto/weather_2022.csv              Open-Meteo hourly, downloaded by eda.ipynb if missing (committed, small)
data/toronto/opendata_ttc_schedules.zip    current TTC GTFS, downloaded if missing (git-ignored, 29 MB)
data/toronto/route_hour.parquet            the modeling table, written by toronto_eda.ipynb (committed, 5 MB, so modeling needs no rebuild)
toronto_eda.ipynb                          renamed from eda.ipynb; part 1 (existing) + part 2: build and explore the route-hour table
toronto_model.ipynb                        baseline -> Poisson regression -> gradient-boosted trees
```

Toronto files live in `data/toronto/` and the notebooks carry a `toronto_` prefix, so they don't mix with the team's AC Transit `data/raw`, `data/static`, `data/weather` and `explore.ipynb`. Part 1's read path changes to `data/toronto/`. Before committing, each notebook's kernel metadata is the generic `python3`, not a local kernel name.

### The table: one row per route × hour

- **Hours:** local Toronto time, 1 Jan 00:00 – 30 Jun 23:00 2022. The 13 Mar daylight-saving jump leaves one hour that doesn't exist; skip it. Weather is requested with `timezone=America/Toronto`, so it joins on the same local hour.
- **Target `n_delays`:** incidents in that route-hour with `Min Delay > 0`, after duplicates are dropped. Zero-minute rows (4.8%) are logged events, not delays.
- **Exposure `trips`:** scheduled trips for that route in that hour, by day type (weekday / Saturday / Sunday-holiday), from the current GTFS. Holidays use the Sunday schedule.
- **Rows kept:** only route-hours with `trips > 0`. This removes "zero delays" for routes that weren't running.
- **Route match check:** report what share of incidents fall on routes found in the current GTFS. If it's under 90%, fall back for unmatched routes to the hours the route ever had an incident, with `trips` taken as that route's median. List which routes fell back.

### Features (v1)

| Group | Features | Carries over to AC Transit |
|---|---|---|
| Time | hour, weekday, day type (week number in EDA only: trees and linear trends extrapolate badly past the training weeks) | yes |
| Calendar | Ontario statutory holidays; UofT term phases (classes, reading week, exams, break, summer); UofT online period; Toronto public-school days, remote period and March break | yes, as the UC Berkeley calendar |
| Unusual period | flag for the Omicron period (Jan 2022), as a control | no |
| Weather (hourly, one downtown point) | temperature, precipitation, rain, snowfall, snow depth, wind, gusts, visibility | yes, rain and fog matter most there |
| Route traits (GTFS) | trips per hour, route length (km), number of stops, route group (regular / express 900s / night 300s) | yes |
| Recent delays (past only) | same route's incidents in the previous 1 h and 3 h; city-wide incidents in the previous hour | yes |

Every calendar date gets a source link in a markdown cell, and the dates are checked against official pages (UofT sessional dates, TDSB calendar, Ontario holidays).

### EDA part 2 (in `eda.ipynb`, same chart rules as part 1)

- Table profile: rows, share of zero route-hours, distribution of `trips`, the route match rate.
- Delay rate (incidents per 100 trips) against each feature group: holiday vs regular day; term phase; snowfall bins; hour × day type heatmap; route group.
- Whether recent delays predict the next hour (rate by lag-1 count).
- Ends by writing `data/toronto/route_hour.parquet`, with an assert on row count and no missing features.

### Models (in `model.ipynb`)

- **Split:** train 1 Jan – 30 Apr, test 1 May – 30 Jun. Tuning uses time-ordered folds inside the training period. Caveat to state: the test period has no snow, so snow effects are measured only in training.
- **Baseline:** the training-period rate per route × hour × day type, times `trips`.
- **Poisson regression** (scikit-learn `PoissonRegressor`) on `n_delays / trips`, with `sample_weight = trips`. One-hot categoricals, scaled numerics. Effects are reported as rate ratios (e.g. "snow > 5 cm: ×1.4").
- **Gradient-boosted trees** (`HistGradientBoostingRegressor(loss="poisson")`), same target and weights.
- **Metrics on test:** weighted mean Poisson deviance, against the baseline. Capture rate: the share of actual incidents falling in the 10% of route-hours the model ranks riskiest. A predicted-vs-actual chart by decile.
- **Ends with** a findings cell: which features matter, whether trees beat the regression, and what that implies for AC Transit.

### Done means

- Both notebooks pass Restart & Run All with no errors, from a fresh clone plus the downloads they do themselves.
- No file beyond the list above.
- The model results are reported honestly against the baseline, even if the model doesn't beat it.

## Left to the builder

- GTFS parsing details (service calendars, trips crossing hour boundaries: count by departure from the first stop).
- Exact weather variables and the single coordinate.
- Encodings, scaling and hyperparameters.
- Chart choices within the eda-notebook rules.

## My calls (not discussed, open to change)

- Count only `Min Delay > 0` incidents.
- Use the current GTFS as exposure, with a fallback.
- One downtown weather point, not several.
- UofT and public schools only (not TMU/York).
- Split at 30 Apr.
- Move the Toronto CSV into `data/toronto/` and prefix both notebooks with `toronto_`.
- Add scikit-learn and pyarrow to `requirements.txt`.
- Commit the small Toronto data and the modeling table; ignore the GTFS zip.
