# Toronto route-hour dataset

`route_hour.parquet`: one row per TTC route per hour, Jan–Jun 2022, kept only when the route had scheduled trips (686,398 rows). Built by `toronto_eda.ipynb`; you don't need to rerun it.

```python
import pandas as pd
rh = pd.read_parquet("data/toronto/route_hour.parquet")  # needs pyarrow (in requirements.txt)
```

## Columns

| Column | Meaning |
|---|---|
| `n_delays` | **Target.** Delays longer than 0 min on that route in that hour |
| `trips` | **Exposure.** Scheduled trips that hour; model the rate `n_delays / trips` |
| `route`, `ts`, `date` | Route number, hour (Toronto local time), day |
| `hour`, `weekday` | 0–23; 0 = Monday |
| `day_type` | weekday / saturday / sunday (holidays count as sunday) |
| `holiday` | Ontario public holiday |
| `uoft_phase` | UofT term: classes / reading_week / exams / break / summer |
| `uoft_online` | UofT classes online (until 6 Feb) |
| `school` | Toronto public schools: in_person / remote / off |
| `omicron` | January 2022, an unusual month (staff shortages, remote school) |
| `temp_c`, `precip_mm`, `rain_mm`, `snowfall_cm`, `snow_depth_m`, `wind_kmh`, `wind_gust_kmh`, `visibility_m` | Hourly weather, downtown Toronto (Open-Meteo) |
| `length_km`, `n_stops` | Route length and stops per trip |
| `group` | regular / express (900s) / night (300s) |
| `lag1`, `lag3` | Same route's delays in the previous 1 and 3 hours |
| `city_lag1` | Delays on all routes in the previous hour |
| `fallback` | Always False; ignore |

## Notes

- Don't use `n_delays`, `ts`, `date` or `fallback` as model inputs.
- Split by time: train before 1 May 2022, test from 1 May on (as in `toronto_model.ipynb`).
- 96.7% of rows have zero delays, so predict a rate or count (e.g. Poisson), not yes/no.
- Trips come from TTC's current schedule, because the 2022 one isn't published; it still matches 98% of 2022 delays.
- Sources: [TTC delays (Kaggle)](https://www.kaggle.com/datasets/reihanenamdari/toronto-bus-delay-2022), [TTC schedule (Toronto Open Data)](https://open.toronto.ca/dataset/ttc-routes-and-schedules/), [weather (Open-Meteo)](https://open-meteo.com/en/docs/historical-forecast-api).
