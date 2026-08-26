# s7 Calibration

## Purpose

Optimize the eight KINEROS2 lumped parameters against observed discharge with SciPy differential evolution. Calibration is implemented as `--mode calibrate` in `tools/run_kineros2.py`; it repeatedly executes the same model core used in stage 5 and scores the calibration window with a combined KGE/NSE objective.

## Inputs

- Stage 1 forcing JSON.
- Observed discharge CSV/TSV readable by `tools/run_kineros2.py::load_observed`.
- Basin area in `km2` and latitude in degrees.
- Calibration start and end dates. The KI's validation section uses `1981-01-01` to `1985-12-31` after a 1980 spinup year.
- Optimization controls `--maxiter`, `--popsize`, and `--seed`.

## Outputs

- A calibrated JSON containing aligned dates, `Q_sim_m3s`, embedded `Q_obs_m3s`, optimized parameters, bounds, calibration metrics, optional validation metrics, and optimization metadata.
- This output can go directly to stage 6 for CSV export and plotting.

## Procedure

1. Confirm SciPy is available through preflight:

   ```bash
   python preflight_check.py
   ```

2. Run calibration:

   ```bash
   python tools/run_kineros2.py \
     --mode calibrate \
     --forcing work/forcing.json \
     --observed /path/to/observed_Q.csv \
     --basin-area-km2 121330 \
     --latitude 33 \
     --cal-start 1981-01-01 \
     --cal-end 1985-12-31 \
     --maxiter 150 \
     --popsize 20 \
     --seed 42 \
     --output work/calibrated.json
   ```

3. Parse the calibrated output with stage 6:

   ```bash
   python tools/parse_output_kineros2.py \
     --input work/calibrated.json \
     --warmup-days 365 \
     --output work/calibrated_results.csv \
     --metrics-json work/calibrated_metrics.json
   ```

## Verification

The calibration run should report at least 100 calibration days, nonempty date overlap, optimized parameters within the hard bounds in `PARAM_BOUNDS`, and finite `NSE`/`KGE` values. The final JSON should contain `output.calibration_metrics` and `output.optimization`.

## Traps

- `dt_kineros2_011`: Too short a calibration period, no overlap, or including the spinup year can force poor NSE and unrealistic parameters.
- `dt_kineros2_015`: `alpha` hitting or exceeding its physical range indicates overfitting or upstream unit errors.
- `dt_kineros2_016`: `fc` at a bound usually means `Smax` or soil units need review.
- `dt_kineros2_022`: Calibration fails without SciPy.
- `dt_kineros2_025`: The first year should be treated as spinup and excluded from objective calculations.

## Example

Calibrate the Huai/Bengbu daily lumped setup:

```bash
python tools/run_kineros2.py \
  --mode calibrate \
  --forcing work/forcing_1980_1990.json \
  --observed /data/observed/bengbu_Q.csv \
  --basin-area-km2 121330 \
  --latitude 33 \
  --cal-start 1981-01-01 \
  --cal-end 1985-12-31 \
  --maxiter 150 \
  --popsize 20 \
  --seed 42 \
  --output work/calibrated_bengbu.json
```
