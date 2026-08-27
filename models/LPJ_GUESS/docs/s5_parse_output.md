# Stage 5: Parse Output

## Purpose

Post-process the raw CSV from `tools/run_lpjguess.py` into selected timeseries, monthly or annual means, summary statistics, and validation metrics against observation columns when available.

## Inputs

- `tools/parse_output_lpjguess.py`
- Raw model output CSV from `docs/s4_run_lpjguess.md`
- Optional aggregation: `--aggregate monthly` or `--aggregate annual`
- Optional observation column names:
  - `--obs-gpp`
  - `--obs-nee`
  - `--obs-reco`
- Optional output files:
  - `--output-csv`
  - `--summary-csv`
  - `--metrics-json`
- Optional variable list via `--variables`

## Outputs

- Parsed output CSV containing `date`, `year`, `month`, selected model variables, and selected observation columns.
- Summary CSV with count, min, max, mean, standard deviation, median, p05, and p95.
- Metrics JSON with `R`, `RMSE`, `bias`, `NSE`, and `KGE` for paired observations and simulations.

## Procedure

Check the parser interface:

```bash
cd KISSPATH_KI_ROOT/LPJ_GUESS/knowledge_infrastructure
python3 tools/parse_output_lpjguess.py --help
```

Create a clean daily output and summary:

```bash
cd KISSPATH_KI_ROOT/LPJ_GUESS/knowledge_infrastructure
python3 tools/parse_output_lpjguess.py \
  --input /tmp/lpjguess_model_output.csv \
  --output-csv /tmp/lpjguess_parsed_daily.csv \
  --summary-csv /tmp/lpjguess_summary.csv
```

Create monthly means and metrics when observation columns are present:

```bash
cd KISSPATH_KI_ROOT/LPJ_GUESS/knowledge_infrastructure
python3 tools/parse_output_lpjguess.py \
  --input /tmp/lpjguess_model_output.csv \
  --output-csv /tmp/lpjguess_parsed_monthly.csv \
  --aggregate monthly \
  --obs-gpp obs_GPP \
  --obs-nee obs_NEE \
  --metrics-json /tmp/lpjguess_metrics.json \
  --summary-csv /tmp/lpjguess_monthly_summary.csv
```

For admissible validation targets and metric interpretation, use `docs/validation_convention.yaml` and the observability blocks in `dag.yaml`.

## Verification

Inspect produced files:

```bash
python3 - <<'PY'
import json
import pandas as pd
parsed = pd.read_csv("/tmp/lpjguess_parsed_daily.csv")
summary = pd.read_csv("/tmp/lpjguess_summary.csv")
print(parsed.columns.tolist())
print(summary)
try:
    print(json.load(open("/tmp/lpjguess_metrics.json")))
except FileNotFoundError:
    print("metrics file not requested or no observation pairs available")
PY
```

Expected checks:

- Parsed variables stay within the ranges in `tools/parse_output_lpjguess.py` `OUTPUT_VARIABLES`.
- Monthly aggregation requires `year` and `month`; annual aggregation requires `year`.
- Metrics are only written when matching observation columns are present.
- The command exits with `status: success` in its final JSON.

## Traps

- `dt_lpjguess_018`: this parser can aggregate daily runner output to monthly or annual means, but it cannot recover monthly/daily detail from an already annual-only file.
- `dt_lpjguess_004`: validation observations and parsed model variables must share `umol CO2/m2/s` units.
- `dt_lpjguess_014`: if parsed `NEE` no longer matches `Reco - GPP`, the input raw CSV or selected variables are wrong; do not reinterpret the sign convention.
- `dt_lpjguess_007`: parser input must be the raw CSV emitted by `tools/run_lpjguess.py`, not raw LPJ-GUESS driver NetCDF or unrelated FLUXNET forcing.

## Example

```bash
cd KISSPATH_KI_ROOT/LPJ_GUESS/knowledge_infrastructure
python3 tools/parse_output_lpjguess.py \
  --input /tmp/us_ha1_lpjguess_raw.csv \
  --output-csv /tmp/us_ha1_lpjguess_daily.csv \
  --variables GPP NEE Reco NPP \
  --summary-csv /tmp/us_ha1_lpjguess_summary.csv
```

Use the parsed CSV for downstream validation and reporting.
