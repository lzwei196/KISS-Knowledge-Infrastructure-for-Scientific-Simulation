# s9 Validation -- official ARS samples and Walnut Gulch flume 11

## Purpose
Show that this KI drives the real engine correctly (official samples reproduced) and how the model
compares with an independent observation (flume 11 runoff, 4 Aug 1980).

## Inputs
- `examples/ars_samples/` (ARS Samples.zip, sha256 48427371...7dc34ca151e25c95eb950dc7c): EX1.PAR/EX1.PRE,
  wg11.par/4Aug80.pre, the readme's run settings, `expected_results.json` (build-log values).
- `examples/wg11_observed/flume11_19800804_breakpoint_cfs.txt`: USDA-ARS WGEW DAP flume 11 hydrograph
  (event 3054: start 13:27, 181.5 min, 4.43 mm over the nominal 2035 ac, peak 11.07 mm/hr = 894 cfs).

## Outputs
`run_result.json` for each sample (with `example_check.reproduced`), `score.json` and the figure
`figures/s8_validation.png` (observed black, simulated #2563EB).

## Procedure
```
python3 tools/run_kineros2_engine.py --example ex1  --check --out-dir OUT/ex1
python3 tools/run_kineros2_engine.py --example wg11 --check --out-dir OUT/wg11
python3 tools/score_kineros2_event.py --sim OUT/wg11/run_result.json --obs examples/wg11_observed/flume11_19800804_breakpoint_cfs.txt --obs-offset-min 52 --clock-origin "1980-08-04 12:35" --out OUT/wg11/score.json --figure OUT/wg11/score.png
```
`--clock-origin` gives the scored series real timestamps (passed to `all_metrics(dates=...)`); the
aligned series actually scored is written to `OUT/wg11/score_paired.csv` (date,time_min,obs,sim in m3/s).

## Verification (2026-10-06)
| Check | Result |
|---|---|
| EX1: rain 77.0 mm, plane infiltration 41.51009 mm, outflow 35.29868 mm / 705.974 m3, sediment 5.172343 t/ha, element peaks 133.335 / 130.816 mm/hr | all equal to the build log |
| WG11: rain 1.3642 in, plane infil 0.94959 in, channel infil 0.099552 in, interception 0.014 in, outflow 0.292209 in / 1,645,201 ft3, area 1551.028 ac, outlet peak 668.4023 cfs at 64.7 min | all equal to the build log |
| WG11 rain file rebuilt from raw DAP gage data | identical to 4Aug80.pre (10/10 gages), same engine result |
| WG11 vs flume 11 (ARS multipliers Ks 0.5, G 1.5) | NSE 0.812, KGE 0.720, r 0.910, peak 18.84 vs 25.32 m3/s (-25.6 %), time to peak 66 vs 72 min, volume 46,544 vs 36,490 m3 (+27.6 %) |

## Traps
- Clock: 4Aug80.pre times are minutes after 12:35; flume 11 starts 13:27 -> offset 52 min. The simulated
  rise starts at the same minute as the observed one, which confirms the alignment (dt_kineros2_049).
- Area: the model covers 1551 ac (the eastern part sits behind two stock ponds and seldom contributes,
  per the ARS KINEROS2 home page); flume 11's nominal area is 2035 ac. Compare m3/s and m3, never mm (dt_kineros2_033).
- Tier: observations are independent of the model, but the readme multipliers were set by ARS for this
  storm, so this is an in-sample comparison, not a blind validation.

## Example
See Procedure. Expected console end lines: `EXAMPLE ex1: reproduced ...`, `EXAMPLE wg11: reproduced ...`.
