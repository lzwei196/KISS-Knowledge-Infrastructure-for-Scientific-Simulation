# s4 Output parsing and scoring (real engine)

## Purpose
Turn the engine's extract CSV into daily series per segment and score them against observations
with the shared metrics. The surrogate parser `parse_output_wasp.py` reads only surrogate JSON.

## Inputs
- `<run-dir>/<model>_extract.csv` (s3). DO scoring needs "Dissolved Oxygen"; the DO-saturation
  diagnostic also needs "Water Temperature" (without it DO is still scored and `sim_do_sat_note`
  says the diagnostic was skipped).
- observations from `tools/prepare_wqp_lake_obs.py`: one row per station-day with
  `date, station_id, lat, lon, value, value_qc, n_values, n_values_qc, n_cruises, cruise,
  cruises_qc_excluded, qc_flag, qc_diag, support` (`support = station_day`), plus the sidecar
  `<obs stem>.cruise_qc.json` (every cruise, its stats and flags). With `--network-mean` the rows
  are per day (`support = network_mean_variable`).

## Outputs
`<out-dir>/sim_daily_seg<N>.csv`, `pairs_do.csv`, `pairs_temperature.csv`, `scores.json`,
optional figure (observed black, simulated #2563EB, metrics box).

`scores.json` keys:
- `metrics.do_all` — **the headline** (`headline = "do_all.pooled"`): column `value` of every row,
  i.e. ALL data, no cruise QC. `pooled` = all pairs; `per_station` = metrics per station with
  n >= `--min-station-n` and their median.
- `metrics.do_sensor_qc` — column `value_qc` of the rows that have one (cruises with an
  EXCLUDING sensor flag left out). Reported, not claimed (`qc_subset_note`).
- `metrics.temperature_all` — water temperature, same layout.
- `flagged_cruises` (excluding flags) and `diagnostic_cruises` (diagnostic flags only) — copied
  from the sidecar; without the sidecar `flagged_cruises` is null, `flagged_cruises_note` says
  why and `flagged_rows` lists the rows with an excluding flag as written.
- `n_obs_rows_with_excluded_cruise`, `sim_do_over_sat_mean` (null when temperature was not
  extracted), `support` (read from the obs files, never assumed).

## Procedure
```bash
python tools/prepare_wqp_lake_obs.py --lake Lake_Erie_Central --variable do \
    --bbox -82.5 41.35 -80.4 42.6 --site-types "Great Lake" --start 2005-01-01 --end 2014-12-31 \
    --max-depth-m 5 --station-cache wqp_stations_cache.csv --out obs_do_surface5m.csv
python tools/prepare_wqp_lake_obs.py --lake Lake_Erie_Central --variable temperature \
    --bbox -82.5 41.35 -80.4 42.6 --site-types "Great Lake" --start 2005-01-01 --end 2014-12-31 \
    --max-depth-m 5 --station-cache wqp_stations_cache.csv --out obs_temperature_surface5m.csv
python tools/parse_wasp_engine_output.py --extract run/erie_cb_surface_extract.csv --segment 1 \
    --out-dir scores --obs-do obs_do_surface5m.csv --obs-temp obs_temperature_surface5m.csv \
    --elev 174 --score-start 2005-01-01 --figure validation.png
```
WQP data root: `--wqp-dir` → `$WASP_WQP_DIR` → the server's `data/obs/water_quality/wqp`.

## Cruise sensor QC (in prepare_wqp_lake_obs.py; dt_wasp_041)
Run per cruise (organisation + method + month) on the cruise's own data, all depths, before the
range filter, for sensor methods only (LG301 CTD, LG501Y YSI; Winkler is never flagged).
- EXCLUDING (left out of `value_qc`) only when the sensor is shown to be wrong: `sensor_dead`
  (more than half the values negative), `winkler_disagree` (CTD vs Winkler at the SAME depth,
  within 1 m, median ratio outside 0.85–1.15; near anoxia, Winkler < 1 mg/L, a difference > 0.5 mg/L).
- DIAGNOSTIC only (data kept): `sat_offset_unconfirmed` (whole-column median DO/saturation outside
  0.70–1.30; the QC json also gives the surface median and `column_mixed`) and
  `winkler_disagree_unmatched_depth` (Winkler of unknown or different depth). Low DO alone is not
  proof of a fault: summer hypolimnetic depletion is real.

## Verification
- `headline` is `do_all.pooled`; `do_sensor_qc` is never reported alone.
- No repeated (date, station_id) rows (the scorer refuses them).
- `sim_do_over_sat_mean` checks the engine's DO against APHA saturation with pressure correction
  (Lake Erie box: 1.027; the deck has no algae, dt_wasp_042).

## Traps
- Most "Lake_Erie_Central" WQP stations are streams (dt_wasp_035): always type-filter.
- GLNPO depth lives only in `ResultCommentText` (dt_wasp_036).
- Whole cruises with a failed DO sensor (dt_wasp_037, dt_wasp_041): report all data first.
- Extract column names are space-padded and there is a trailing empty column; the parser strips them.
- `all_metrics` keys are `NSE/KGE/PBIAS/RMSE` (upper case) and `r`.

## Example (Lake Erie Central Basin, 2005–2014; existing engine run re-scored 2026-10-07)
Station-day rows (fixed support), 11 GLNPO stations, samples <= 5 m, pooled over all pairs:

| variable | rows | NSE | r | KGE | PBIAS % | RMSE |
|---|---|---|---|---|---|---|
| surface DO, all data (headline) | 176 | −0.011 | 0.671 | 0.605 | +20.0 | 2.91 mg/L |
| surface DO, cruise-QC subset (reported) | 176 | −0.011 | 0.671 | 0.605 | +20.0 | 2.91 mg/L |
| surface water temperature | 197 | 0.992 | 0.997 | 0.953 | +2.8 | 0.96 °C |

The QC subset equals all data here: the only excluded cruises (2009-08, 2010-04, dead sensors)
have no in-range values. Five cruises carry diagnostic flags (2005-04, 2006-08, 2012-04, 2012-08,
2013-04); leaving them out is a sensitivity check only (NSE 0.80, n 124), not a result.
