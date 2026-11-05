# s8 Calibration with run-time multipliers

## Purpose
Adjust the engine's global multipliers (the ARS calibration handle) so a simulated event hydrograph
matches an observed one, running the real engine for every trial.

## Inputs
Parameter + rainfall files that run, an observed hydrograph (WGEW DAP export in cfs, or CSV
`time_min,discharge_m3s`), the obs clock offset, parameter bounds.

## Outputs
`trials.csv` (every trial incl. failures), `best.json` (best multipliers, score, in-sample caveat),
`best/` (the best run's files).

## Procedure
1. Fetch the observed event: `tools/fetch_wgew_dap.py runoff --flumes 11 --start 1980-08-04 --end 1980-08-04 --units cf --out obs.txt`
2. Make sure the outlet has PRINT = 2.
3. `tools/calibrate_kineros2_multipliers.py --par wg11.par --rain 4Aug80.pre --tfin 360 --dt 3 --courant --obs obs.txt --obs-offset-min 52 --params ks:0.25:1.0,manning:0.5:1.5 --fixed g=1.5 --objective nse --method nelder-mead --n-grid 4 --max-evals 40 --out-dir calib/`
4. Multipliers available: ks, manning, cv, g, interception, cohesion, splash; channel-only chan_ks,
   chan_g, chan_manning, woolhiser, chan_length, init_sat (writing any of these makes a 13-line file).

## Verification
- Each trial is a real `k2` run judged by the same success rules as s6; failed trials score -inf and
  stay in trials.csv.
- 2026-10-06, WG11 4 Aug 1980, 40 trials in 2.2 s: best Ks x0.611, n x0.874 (G x1.5 fixed) -> NSE 0.855,
  peak -31.0 %, volume +4.7 % vs the ARS multipliers (Ks 0.5, G 1.5) NSE 0.811, peak -25.6 %, volume +27.6 %.
  NSE improved by trading peak for volume; the slow simulated recession stays -- a structure/geometry
  limit of the 17-element cascade, not a multiplier problem.

## Traps
- One event = in-sample skill. Never report a calibrated NSE on the calibration storm as validation.
- Multipliers scale EVERY element (or the subset listed in `mlist.fil`, an engine feature this tool
  does not write).
- A G multiplier of 0 stops the engine ("zero multiplier", dt_kineros2_052).
- Scoring in depth units against a flume whose nominal area differs from the model area biases
  volume (dt_kineros2_033).

## Example
See Procedure step 3; best.json lists `best_multipliers` and `best_score`.
