# s1 Rainfall input (.pre file)

## Purpose
Give KINEROS2 the storm: breakpoint rainfall from one or more recording gages on one shared minute
clock. Rainfall is the only time-series input of the model (no temperature, no PET).

## Inputs
- Recording-gage breakpoints. For Walnut Gulch / Santa Rita: `tools/fetch_wgew_dap.py precip --gages ... --start D --end D --units inches|mm`.
- Or a CSV `gage,time_min,depth` already on the run clock.
- Or (last resort, ungauged site) gridded hourly rain via `ki_tools_common.load_hourly_forcing`.
- Gage metadata: X, Y in the SAME coordinate system as the elements' X/Y; optional SAT.

## Outputs
A `.pre` file: one `BEGIN GAGE <id> ... END` block per gage with `N`, `TIME`/`DEPTH` columns
(cumulative depth), optional `SAT`, `X`, `Y`.

## Procedure
1. Pick the parameter file's UNITS first. Depth MUST be in mm for METRIC, inches for ENGLISH.
2. Pick one clock origin (HH:MM) at or before the earliest gage start; every gage time = local
   start time - origin + elapsed minutes.
3. `tools/build_kineros2_rainfall.py --from-wgew precip.txt --clock-origin 12:35 --template old.pre --tfin 360 --units english --out storm.pre`
   (`--template` copies SAT/X/Y per gage id; `--gauge-meta` CSV instead for a new gage set).
4. Keep observed runoff on the same clock: the obs offset is (flume start - origin) minutes.

## Verification
- The tool re-reads the file with the engine's tag rules: N matches rows, time increases, depth never
  decreases, X/Y present when >1 gage, storm totals plausible for the unit system.
- Proven end to end: rebuilding the ARS file `4Aug80.pre` from the raw DAP export for 4 Aug 1980
  (10 gages, origin 12:35, tfin 360) gives identical breakpoints, SAT, X, Y for all 10 gages, and the
  engine reproduces the official run (outlet peak 668.4023 cfs at 64.7 min).

## Traps
- Units are never converted: an inch file with a METRIC parameter file is 25.4x too little rain (dt_kineros2_032).
- Gage SAT silently OVERRIDES element SA for every element the gage covers (dt_kineros2_030).
- A decreasing depth or non-increasing time stops the engine -- with exit status 0 (dt_kineros2_039, dt_kineros2_027).
- Gridded hourly rain smears convective bursts: NASA POWER's wettest 2006 hour at Walnut Gulch is 1.9 mm
  while gages record tens of mm/h -- infiltration-excess runoff collapses (dt_kineros2_036).
- `+` is a separator for the reader: never write `1e+01` (dt_kineros2_031).
- Times are rounded by the engine to 0.1 min; if the last time is before tfin the engine holds the last depth.

## Example
```
python3 tools/fetch_wgew_dap.py precip --gages 89,51,90,54,88,55,91,56,52,44 --start 1980-08-04 --end 1980-08-04 --units inches --out precip.txt
python3 tools/build_kineros2_rainfall.py --from-wgew precip.txt --clock-origin 12:35 --template examples/ars_samples/4Aug80.pre --tfin 360 --units english --out 4Aug80_rebuilt.pre
```
