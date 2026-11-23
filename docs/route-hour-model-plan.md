# Route-hour delay model: implementation plan

**Goal:** Build a route × hour table of TTC bus delays with exposure, calendar, weather and route features, explore it, and model the delay rate against a baseline.

**Architecture:** Two notebooks. `toronto_eda.ipynb` (part 1 is the existing EDA) gains a part 2 that downloads the outside data if it's missing, builds the table and writes `data/toronto/route_hour.parquet`. `toronto_model.ipynb` reads that file and fits a baseline, then a Poisson regression, then gradient-boosted trees. No `.py` modules. Checks are `assert` lines in the notebook cells, verified by executing the notebook headless.

**Tech stack:** Python 3, pandas, numpy, matplotlib, seaborn, scikit-learn, pyarrow, Jupyter (nbconvert to execute).

**Spec:** `docs/route-hour-model-design.md`

## Global constraints

- Files: only those listed in the spec's Files block. No helper modules, no saved PNGs, no extra CSVs.
- Leaky columns are never model features: `Incident`, `Min Delay`, `Min Gap`, `Direction`, `Vehicle`, `Location`.
- Target: incidents with `Min Delay > 0`, after `drop_duplicates()`.
- Hours are local `America/Toronto`, from 2022-01-01 00:00 to 2022-06-30 23:00.
- Split: train before 2022-05-01, test from 2022-05-01 on.
- Charts follow the eda-notebook rules: the title states the finding, axes carry units, one accent colour, bars start at zero.
- Commit messages are one short line. Never mention any AI tool.
- Kernel metadata in committed notebooks is `python3`.
- Run notebooks with: `.venv/bin/jupyter nbconvert --to notebook --execute --inplace <nb>`

## Review focus

1. **The 13 Mar DST jump.** 02:00 local doesn't exist. Weather and the hour grid must both skip it, and the join must not create NaNs. Pinned in Tasks 2 and 5.
2. **Route IDs.** Incident `Route` is text and is sometimes missing. GTFS `route_short_name` must be compared as stripped text, so "7" matches "7" and isn't confused with "07" or 7.0. Pinned in Task 4.
3. **GTFS times past 24:00** (e.g. `25:10:00`). These map to hour `h % 24`, not a crash or a NaN. Pinned in Task 4.
4. **Incidents in route-hours with zero scheduled trips.** These are dropped by the `trips > 0` filter. They must be counted and reported, not lost silently. Pinned in Task 5.
5. **Holidays.** A holiday falling on a weekday must get the `sunday` day type, both for exposure and for the feature. Pinned in Tasks 3 and 5.

---

### Task 1: Move the Toronto files and add dependencies

**Files:**
- Move: `data/ttc-bus-delay-data-2022.csv` → `data/toronto/ttc-bus-delay-data-2022.csv`
- Move: `eda.ipynb` → `toronto_eda.ipynb` (change the read path in its load cell; kernelspec becomes `python3`)
- Modify: `.gitignore` (add `data/toronto/*.zip` and `data/toronto/route_hour.parquet`)
- Modify: `requirements.txt` (add `matplotlib`, `seaborn`, `scikit-learn`, `pyarrow`, `ipykernel`, `nbconvert`)

**Interfaces:**
- Produces: `toronto_eda.ipynb` reading `data/toronto/ttc-bus-delay-data-2022.csv`. Part 1 variables `raw` and `df` stay as they are; `df` gains no columns here.

- [ ] Step 1: `git mv` is not possible (both files are untracked). Use `mkdir -p data/toronto && mv ...` and rename the notebook.
- [ ] Step 2: Edit the load cell path, then set `metadata.kernelspec` to `{"name": "python3", "display_name": "Python 3", "language": "python"}`.
- [ ] Step 3: Add the requirements lines, then run `uv pip install --python .venv/bin/python -r requirements.txt`. Expected: installs cleanly.
- [ ] Step 4: Execute `toronto_eda.ipynb`. Expected: no error outputs, 6 images.
- [ ] Step 5: `git status --short` shows only the intended files. Commit `"Add Toronto EDA notebook and data"`.

### Task 2: Outside data downloads (top of part 2 of `toronto_eda.ipynb`)

**Files:**
- Modify: `toronto_eda.ipynb` (new markdown heading "Part 2: building the route-hour table", then one download cell)
- Creates when run: `data/toronto/weather_2022.csv`, `data/toronto/opendata_ttc_schedules.zip`

**Interfaces:**
- Produces: `weather`, a DataFrame with `ts` (tz-aware `America/Toronto`, hourly, unique) plus `temp_c, precip_mm, rain_mm, snowfall_cm, snow_depth_m, wind_kmh, wind_gust_kmh, visibility_m`. Also `GTFS_ZIP`, a `Path`.

- [ ] Step 1: Write the assert cell first:
  ```python
  assert weather["ts"].is_unique and weather["ts"].dt.tz is not None
  assert len(weather) >= 4343                      # 181 days x 24 h, minus the DST hour
  assert weather.loc[weather.ts.dt.date.astype(str) == "2022-01-17", "snowfall_cm"].sum() > 10
  assert GTFS_ZIP.stat().st_size > 10_000_000
  ```
- [ ] Step 2: Execute. Expected: fails with NameError `weather`.
- [ ] Step 3: Implement the download cell, skipping any file that already exists.
  - Weather: Open-Meteo `https://historical-forecast-api.open-meteo.com/v1/forecast`, lat 43.6532, lon -79.3832, 2022-01-01 to 2022-06-30, `timezone=America/Toronto`.
    - Hourly variables: `temperature_2m, precipitation, rain, snowfall, snow_depth, visibility, wind_speed_10m, wind_gusts_10m`, renamed to the columns above.
    - Fetch the JSON with `urllib`, make a DataFrame from `["hourly"]`, and save it as CSV.
    - On load: `ts = pd.to_datetime(time).dt.tz_localize("America/Toronto", nonexistent="NaT", ambiguous="NaT")`, then drop NaT rows and duplicate `ts`.
  - GTFS: `urllib.request.urlretrieve` of the City of Toronto URL in the spec's Constraints.
- [ ] Step 4: Execute. Expected: the asserts pass.
- [ ] Step 5: Commit `"Download Toronto weather and schedule"` (the weather CSV is committed; the zip is ignored).

### Task 3: Calendar flags

**Files:**
- Modify: `toronto_eda.ipynb` (a markdown cell with a source link for each date group, then one code cell)

**Interfaces:**
- Produces: `day_info(d: datetime.date) -> dict` with keys `day_type` (`"weekday" | "saturday" | "sunday"`), `holiday` (bool), `uoft_phase` (`"break" | "classes" | "reading_week" | "exams" | "summer"`), `uoft_online` (bool), `school` (`"in_person" | "remote" | "off"`), `omicron` (bool).

Dates to encode. Check each against its source and correct it if the source differs:
- **Ontario holidays:** 2022-01-01, 2022-01-03 (New Year's observed), 2022-02-21, 2022-04-15, 2022-05-23. Source: ontario.ca, "public holidays" under employment standards.
- **UofT (Faculty of Arts & Science 2021–22 sessional dates):**
  - classes 2022-01-10 to 2022-04-08
  - reading week 2022-02-21 to 2022-02-25
  - exams 2022-04-11 to 2022-04-29
  - summer from 2022-05-09
  - break otherwise
  - online until 2022-02-06
- **TDSB:**
  - remote 2022-01-05 to 2022-01-14
  - March break 2022-03-14 to 2022-03-18
  - last day 2022-06-29
  - off on weekends, holidays, and 2022-01-01 to 2022-01-04
- **Omicron flag:** 2022-01-01 to 2022-01-31 (our call, stated in the markdown).

- [ ] Step 1: Write the asserts first:
  ```python
  assert day_info(date(2022, 2, 21))["day_type"] == "sunday" and day_info(date(2022, 2, 21))["holiday"]
  assert day_info(date(2022, 2, 22))["uoft_phase"] == "reading_week"
  assert day_info(date(2022, 3, 15))["school"] == "off"
  assert day_info(date(2022, 1, 12))["school"] == "remote" and day_info(date(2022, 1, 12))["omicron"]
  assert day_info(date(2022, 6, 4))["day_type"] == "saturday"
  ```
- [ ] Step 2: Execute. Expected: fails with NameError.
- [ ] Step 3: Implement `day_info` as plain `if`/`elif` over date ranges. Holiday is checked before weekday/weekend.
- [ ] Step 4: Execute. Expected: passes.
- [ ] Step 5: Commit `"Add Toronto calendar flags"`.

### Task 4: Scheduled trips and route traits from GTFS

**Files:**
- Modify: `toronto_eda.ipynb` (one code cell, plus one line of output for the match rate)

**Interfaces:**
- Consumes: `GTFS_ZIP`, `df` (part 1).
- Produces:
  - `sched`: columns `route` (str), `day_type`, `hour` (0–23), `trips` (int > 0).
  - `traits`: columns `route` (str), `length_km`, `n_stops`, `group` (`"regular" | "express" | "night"`).
  - `match_rate`: float, the share of `Min Delay > 0` incidents whose route is in `traits`.

- [ ] Step 1: Write the asserts first:
  ```python
  assert set(sched.day_type) == {"weekday", "saturday", "sunday"}
  assert sched.hour.between(0, 23).all() and (sched.trips > 0).all()
  assert sched.query("route == '36' and day_type == 'weekday' and hour == 8").trips.iloc[0] > 0
  assert traits.route.map(type).eq(str).all()
  assert traits.loc[traits.route.str.fullmatch(r"3\d\d"), "group"].eq("night").all()
  print(f"incident route match rate: {match_rate:.1%}")
  ```
- [ ] Step 2: Execute. Expected: fails with NameError.
- [ ] Step 3: Implement.
  - Read `routes`, `trips`, `stop_times` (columns `trip_id, stop_sequence, departure_time` only), `calendar` and `shapes` from the zip, with `dtype=str`.
  - Pick one reference date per day type inside the feed's `calendar` range: the first Wednesday, Saturday and Sunday. Use the services active on those dates, applying `calendar_dates` exceptions.
  - A trip's hour is the hour of its first stop's `departure_time`, as `int(hh) % 24`.
  - `length_km` is the shape's max `shape_dist_traveled` (convert units if it's in metres), or a haversine sum if that column is empty. `n_stops` is the median stop count per trip.
  - `group`: 300–399 is night, 900–999 is express, everything else is regular. Use `route_short_name` stripped.
- [ ] Step 4: Execute. Expected: passes. Record the match rate.
- [ ] Step 5: Commit `"Add scheduled trips and route traits"`.

### Task 5: Build and save the route-hour table

**Files:**
- Modify: `toronto_eda.ipynb` (one build cell, one assert/save cell)
- Creates when run: `data/toronto/route_hour.parquet` (ignored)

**Interfaces:**
- Consumes: `df`, `weather`, `day_info`, `sched`, `traits`, `match_rate`.
- Produces: `rh`, a DataFrame with one row per (`route`, `ts`) and `trips > 0`. Columns:
  - `route, ts, date, hour, weekday, n_delays, trips`
  - the `day_info` keys
  - the weather columns
  - `length_km, n_stops, group`
  - `lag1, lag3` (same route's `n_delays` in the previous 1 hour and the sum over the previous 3 hours)
  - `city_lag1` (all routes, previous hour)
  - `fallback` (bool)
  
  It's saved to `data/toronto/route_hour.parquet`; `toronto_model.ipynb` relies on exactly these names.

- [ ] Step 1: Write the asserts first:
  ```python
  pos = df[df["Min Delay"] > 0]
  assert not rh.duplicated(["route", "ts"]).any() and (rh.trips > 0).all()
  assert rh.notna().all().all()                    # includes the weather join
  assert (rh.loc[rh.holiday, "day_type"] == "sunday").all()
  assert not (rh.ts.dt.strftime("%Y-%m-%d %H") == "2022-03-13 02").any()
  kept = rh.n_delays.sum()
  print(f"incidents kept {kept:,} of {len(pos):,} ({kept / len(pos):.1%}); dropped in zero-trip hours: {len(pos) - kept:,}")
  assert kept / len(pos) >= 0.85
  ```
- [ ] Step 2: Execute. Expected: fails with NameError `rh`.
- [ ] Step 3: Implement.
  - `ts` comes from `pd.date_range("2022-01-01", "2022-07-01", freq="h", tz="America/Toronto", inclusive="left")`; this skips the DST hour.
  - Count incidents by (route, floor-hour of the localized `Date` + `Time`).
  - Cross routes with `ts`, attach `day_info(ts.date())`, and merge `sched` on (`route`, `day_type`, `hour`).
  - Fallback for routes with no match: trips = 1 for the hours of the day in which that route ever had an incident; set `fallback=True`.
  - Compute `lag1`, `lag3` and `city_lag1` on the full route × `ts` grid **before** filtering. After the filter, rows aren't consecutive hours, so `shift(1)` would be wrong. Fill the first hours with 0. `city_lag1` counts all incidents, matched or not.
  - Then keep `trips > 0`. Join weather on `ts` and traits on `route`. For fallback routes, fill traits with the median and group `regular`.
  - Write the parquet.
- [ ] Step 4: Execute. Expected: passes. Note the kept share.
- [ ] Step 5: Commit `"Build route-hour table"`.

### Task 6: EDA part 2 charts

**Files:**
- Modify: `toronto_eda.ipynb` (question-headed sections, each with code, a chart and a one-sentence takeaway; findings updated at the end)

**Interfaces:**
- Consumes: `rh`, `ACCENT`, `MUTED`.

Charts. The rate is `100 * sum(n_delays) / sum(trips)`, "delays per 100 trips".
1. Table profile (printed, no chart): rows, the share of route-hours with 0 delays, the distribution of `trips`, `match_rate`, the fallback routes.
2. Rate by calendar: holiday vs not, each `uoft_phase`, each `school` value. Horizontal bars; the phase carrying the finding gets the accent.
3. Rate by snowfall bin (0, 0–1, 1–5, >5 cm) and by rain (yes/no). Bars, with n hours labelled.
4. Hour × day type heatmap of the rate. Sequential palette; values are rates, not counts.
5. Rate by route `group`. Bars with n route-hours.
6. Rate by `lag1` (0, 1, 2+). Bars: does a delay predict the next hour?

- [ ] Step 1: Add the sections. Each title is written after you see the number (a finding, not just the variable names).
- [ ] Step 2: Execute. Expected: no errors. Extract the images and look at each one for collisions and a correct zero baseline.
- [ ] Step 3: Update the final findings cell with part 2 results.
- [ ] Step 4: Commit `"Explore route-hour delay rates"`.

### Task 7: Model notebook

**Files:**
- Create: `toronto_model.ipynb`

**Interfaces:**
- Consumes: `data/toronto/route_hour.parquet` (the columns from Task 5).
- Produces: a test-set results table with rows `baseline, poisson, trees` and columns `deviance, capture_top10`, plus the findings cell.

Cells:
1. Title, the question, and a link to the spec.
2. Setup: the same style block as the EDA.
3. Load and split.
4. Features: one-hot `hour, weekday, day_type, uoft_phase, school, group`; booleans as 0/1; scale the numerics for Poisson only.
5. Baseline: the training rate per (`route`, `hour`, `day_type`), backing off to the rate per (`hour`, `day_type`), then the overall rate, times `trips`.
6. `PoissonRegressor(max_iter=1000)` fit on `y = n_delays / trips`, `sample_weight = trips`. `alpha` is picked from `[1e-4, 1e-2]`.
7. `HistGradientBoostingRegressor(loss="poisson", max_iter=300, learning_rate=0.05)`, same target and weights. `max_leaf_nodes` is picked from `[15, 63]`.
   - Tuning for 6 and 7 uses time-ordered folds inside training: fit before Feb/Mar/Apr and score on that month, then average the weighted Poisson deviance. Refit the winner on all of training.
8. Metrics: `mean_poisson_deviance(n_delays, pred_rate * trips)` and capture rate. Capture rate: sort test rows by predicted count, take the top 10%, and divide their actual `n_delays` by the total.
9. Chart: predicted vs actual delays per 100 trips by predicted decile, for the best model.
10. Chart: Poisson rate ratios `exp(coef)` for the 12 largest effects. Horizontal bars, log x-axis, a reference line at 1.
11. Findings and the carry-over notes for AC Transit.

- [ ] Step 1: Write the assert cell after the split:
  ```python
  assert train.ts.max() < pd.Timestamp("2022-05-01", tz="America/Toronto") <= test.ts.min()
  leaky = {"Incident", "Min Delay", "Min Gap", "Direction", "Vehicle", "Location", "n_delays"}
  assert not leaky & set(X_train.columns)
  ```
  After the metrics:
  ```python
  assert np.isfinite(results.values).all() and (results.capture_top10 <= 1).all()
  ```
- [ ] Step 2: Execute. Expected: fails until the cells exist, then passes.
- [ ] Step 3: Write the findings honestly against the baseline, including if the trees or the Poisson model don't beat it.
- [ ] Step 4: Commit `"Add route-hour delay model"`.

### Task 8: Clean run and push

- [ ] Step 1: Delete `data/toronto/route_hour.parquet`, then execute `toronto_eda.ipynb` then `toronto_model.ipynb`. Expected: both pass and the parquet is regenerated.
- [ ] Step 2: `git status --short` shows nothing unexpected; `git ls-files data/toronto` lists only the CSV and `weather_2022.csv`.
- [ ] Step 3: Read `git log --oneline origin/main..` and `git diff origin/main --stat`. Every message is one short line, and only planned files changed.
- [ ] Step 4: Commit any output refresh `"Rerun Toronto notebooks"`, then `git push origin abraham`.
