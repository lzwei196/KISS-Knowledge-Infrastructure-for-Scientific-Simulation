# Stage 7: Calibration

## Purpose
Optimize the 14 VELMA process parameters against observed daily discharge using the differential evolution path in `tools/run_velma.py --mode calibrate`.

## Inputs
- Forcing JSON from Stage 1.
- Optional base parameter JSON from Stage 2 for layer properties and priors.
- Observed discharge CSV/TSV in `m3/s`.
- Basin area in `km2`.
- Calibration start and end dates, excluding spin-up.
- Differential evolution controls `--maxiter` and `--popsize`.
- References: `SKILL.md` Sections 7, 9, and 12; `dag.yaml` module `CalibrationDE`; `diagnostics/triplets.yaml`.

## Outputs
- Calibrated JSON with best parameters, `Q_sim_m3s`, aligned `Q_obs_m3s`, calibration period, objective value, NSE, KGE, PBIAS, and diagnostics.
- Optional downstream CSV, metrics JSON, and figure when passed through Stage 6.

## Procedure
Run calibration through the model runner:

```bash
python tools/run_velma.py \
  --mode calibrate \
  --forcing forcing.json \
  --params params.json \
  --observed /path/to/observed_Q.csv \
  --basin-area-km2 121330 \
  --cal-start 1981-01-01 \
  --cal-end 1985-12-31 \
  --maxiter 80 \
  --popsize 20 \
  --output calibrated.json
```

Then parse the calibrated output:

```bash
python tools/parse_output_velma.py \
  --input calibrated.json \
  --warmup-days 365 \
  --output calibrated_results.csv \
  --metrics-json calibrated_metrics.json \
  --figure calibrated_validation.png
```

The objective in `tools/run_velma.py` is `-(0.5*NSE + 0.5*KGE - 0.002*abs(PBIAS))` with scipy `differential_evolution(seed=42)`.

## Verification
- `output.calibration.n_days` is positive and matches the configured date range.
- The calibration period starts at least one year after the forcing begins for the Bengbu-style setup.
- `output.metrics.NSE`, `KGE`, and `PBIAS` are finite.
- The best parameters remain inside bounds listed in `PARAM_BOUNDS`.
- Validation on a separate period is checked with Stage 6, not inferred from calibration metrics alone.

## Traps
- `dt_velma_010`: spin-up contamination gives excellent calibration and failed validation.
- `dt_velma_012`: excessive fast/slow split overfits peaks and removes baseflow.
- `dt_velma_013`: PET scale outside useful bounds biases ET and runoff volume.
- `dt_velma_014`: low L4 drainage coefficients create multi-year storage drift.
- `dt_velma_018`: scipy is missing, so differential evolution cannot run.
- `dt_velma_023`: broad parameter bounds or too few evaluations prevent convergence in the 14-dimensional search.

## Example
The KI validation described in `SKILL.md` calibrates Bengbu on 1981-1985 after using 1980 as spin-up:

```bash
python tools/run_velma.py \
  --mode calibrate \
  --forcing forcing_bengbu_1980_1990.json \
  --params params_bengbu.json \
  --observed /data/ObservedQ/bengbu_daily_q.csv \
  --basin-area-km2 121330 \
  --cal-start 1981-01-01 \
  --cal-end 1985-12-31 \
  --maxiter 80 \
  --popsize 20 \
  --output calibrated_bengbu.json
```
