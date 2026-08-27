# s6 Output Parsing

## Purpose

Convert the simulation or calibration JSON into a discharge time-series CSV, compute validation metrics against observed discharge when available, and optionally draw a validation figure. This stage is implemented by `tools/parse_output_kineros2.py`.

## Inputs

- Stage 5 simulation JSON or stage 7 calibrated JSON.
- Optional observed discharge CSV/TSV. The parser accepts date columns such as `dates`, `date`, `Date`, `time`, `Time` and discharge columns such as `Q`, `discharge`, `streamflow`, or `Q_m3s`.
- Warmup days to skip before metrics, typically `365`.
- Optional figure path; matplotlib is optional and the tool skips the figure if unavailable.

## Outputs

- A CSV with simulated discharge and, when provided, observed discharge.
- A metrics JSON with `NSE`, `KGE`, `r`, `RMSE`, `PBIAS`, and `n_points` when enough overlapping observations exist.
- An optional validation PNG.

## Procedure

1. Confirm the parser interface:

   ```bash
   python tools/parse_output_kineros2.py --help
   ```

2. Parse and score a simulation against observations:

   ```bash
   python tools/parse_output_kineros2.py \
     --input work/simulation.json \
     --observed /path/to/observed_Q.csv \
     --warmup-days 365 \
     --output work/results.csv \
     --metrics-json work/metrics.json \
     --figure work/validation.png
   ```

3. For calibrated output containing embedded observed values, omit `--observed`:

   ```bash
   python tools/parse_output_kineros2.py \
     --input work/calibrated.json \
     --warmup-days 365 \
     --output work/calibrated_results.csv \
     --metrics-json work/calibrated_metrics.json
   ```

## Verification

Check that the CSV row count matches the simulation period and that the metrics JSON reports enough `n_points` after warmup. Compare the metric interpretation to `docs/validation_convention.yaml`, where discharge validation is tied to NSE, PBIAS, and R2-style correlation evidence.

## Traps

- `dt_kineros2_009`: Observed discharge files with unexpected dates, delimiters, or column names can fail parsing.
- `dt_kineros2_012`: A large simulated/observed mean ratio points back to forcing or basin-area units.
- `dt_kineros2_025`: Including the first spinup year in metrics can make otherwise usable simulations look bad.
- `dt_kineros2_013`: Peak timing error can remain even when volume metrics are acceptable on large lumped basins.

## Example

Parse a Bengbu-style simulation and skip the 1980 spinup year:

```bash
python tools/parse_output_kineros2.py \
  --input work/simulation_bengbu.json \
  --observed /data/observed/bengbu_Q.csv \
  --warmup-days 365 \
  --output work/bengbu_timeseries.csv \
  --metrics-json work/bengbu_metrics.json \
  --figure work/bengbu_validation.png
```
