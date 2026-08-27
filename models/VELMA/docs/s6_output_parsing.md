# Stage 6: Output Parsing

## Purpose
Extract daily discharge from `tools/run_velma.py` JSON, compute validation metrics, and optionally write a CSV and validation figure.

## Inputs
- `simulation.json` or `calibrated.json` from Stage 5.
- Optional observed discharge CSV/TSV with a date column and a discharge column such as `Q`, `discharge`, `streamflow`, or `Q_m3s`.
- Warmup length in days, defaulting to 365.
- References: `tools/parse_output_velma.py`, `docs/validation_convention.yaml`, `SKILL.md` Section 9, and `diagnostics/triplets.yaml`.

## Outputs
- CSV containing `Q_sim_m3s` and optional `Q_obs_m3s`.
- Metrics JSON containing NSE, KGE, correlation `r`, RMSE, PBIAS, point count, and model diagnostics.
- Optional validation figure.

## Procedure
Parse and validate a simulation against observations:

```bash
python tools/parse_output_velma.py \
  --input simulation.json \
  --observed /path/to/observed_Q.csv \
  --warmup-days 365 \
  --output results.csv \
  --metrics-json metrics.json \
  --figure validation.png
```

Parse a calibration output with embedded observed discharge:

```bash
python tools/parse_output_velma.py \
  --input calibrated.json \
  --warmup-days 365 \
  --output calibrated_results.csv \
  --metrics-json calibrated_metrics.json
```

Check the CLI:

```bash
python tools/parse_output_velma.py --help
```

## Verification
- The tool reports `status: success`.
- Metrics use at least 10 valid overlapping observed and simulated points.
- The first spin-up year is excluded unless there is a documented reason not to.
- `metrics_json` includes `diagnostics` from the model output.
- If a figure path is supplied and matplotlib is installed, the figure is written.

## Traps
- `dt_velma_007`: simulated and observed discharge differ by 100-1000x because basin area was provided in the wrong unit.
- `dt_velma_010`: metrics include the spin-up transient.
- `dt_velma_013`: observed discharge in runoff depth (`mm/d`) was compared directly to simulated `m3/s`.
- `dt_velma_015`: non-finite simulated discharge propagates into invalid metrics.
- `docs/validation_convention.yaml`: validation is against basin-outlet daily discharge, not distributed grid cells.

## Example
For the Bengbu validation period, keep the 1980 spin-up out of metrics:

```bash
python tools/parse_output_velma.py \
  --input simulation_bengbu.json \
  --observed /data/ObservedQ/bengbu_daily_q.csv \
  --warmup-days 365 \
  --output bengbu_results.csv \
  --metrics-json bengbu_metrics.json \
  --figure bengbu_validation.png
```
