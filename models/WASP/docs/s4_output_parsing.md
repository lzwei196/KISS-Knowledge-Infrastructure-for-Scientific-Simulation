# s4 Output Parsing

## Purpose

Parse model output and compute validation summaries using `tools/parse_output_wasp.py`. This stage reads JSON from `tools/run_wasp.py`, extracts seasonal time series and vertical profiles, computes R/RMSE/bias/MAE where observed and simulated arrays are present, exports CSV tables, writes metrics JSON, and optionally creates a validation figure.

## Inputs

- `tools/parse_output_wasp.py`
- A JSON output from `tools/run_wasp.py`
- Optional output CSV path passed with `--output`
- Optional metrics JSON path passed with `--metrics-json`
- Optional PNG path passed with `--figure`
- `docs/validation_convention.yaml` for cited metric thresholds and pass-band interpretation

## Outputs

- A parser result printed to stdout
- Optional CSV export: a single profile table or per-variable seasonal/profile CSV files
- Optional metrics JSON with temperature, dissolved oxygen, profile, TSI, and warning blocks as available
- Optional validation figure generated with matplotlib when installed

## Procedure

Run from the KI root after stage 3:

```bash
python tools/parse_output_wasp.py \
  --input /tmp/wasp_simulation.json \
  --output /tmp/wasp_results.csv \
  --metrics-json /tmp/wasp_metrics.json \
  --figure /tmp/wasp_validation.png
```

For profile-mode output:

```bash
python tools/convert_parameters_to_wasp.py --lake-preset erie --output /tmp/wasp_params.json
python tools/run_wasp.py --mode profile --params /tmp/wasp_params.json --output /tmp/wasp_profiles.json
python tools/parse_output_wasp.py --input /tmp/wasp_profiles.json --output /tmp/wasp_profiles.csv --metrics-json /tmp/wasp_profile_metrics.json
```

Use `dag.yaml` to identify which outputs are observable and `docs/validation_convention.yaml` to interpret the metric bands.

## Verification

- The parser command exits 0.
- `--metrics-json` exists and has `warnings`, even if the list is empty.
- For seasonal output, metrics include `R`, `RMSE`, `bias`, `MAE`, and `n` when observed and simulated arrays are present.
- For profile output, the CSV columns include `depth_m`, `T_sim_C`, `DO_sim_mg_l`, and `DOsat_mg_l`.
- If a figure was requested, the log should include `Figure saved`.

## Traps

- `dt_wasp_017`: zero or negative Chl-a, TP, or Secchi values make Carlson TSI invalid.
- `dt_wasp_020`: wrong date parsing or DOY alignment destroys seasonal validation correlation.
- `dt_wasp_021`: profile metrics must be interpreted as summer-stratification metrics unless a seasonal profile extension exists.
- `dt_wasp_023`: disagreement among TSI_chla, TSI_secchi, and TSI_tp is a water-quality diagnostic, not automatically a model execution failure.

## Example

```bash
python tools/parse_output_wasp.py \
  --input /tmp/erie_profile.json \
  --output /tmp/erie_profile.csv \
  --metrics-json /tmp/erie_profile_metrics.json
```

