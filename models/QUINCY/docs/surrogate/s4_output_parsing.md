# S4 Output Parsing

## Purpose

Parse QUINCY model output into a clean timeseries CSV, optionally extract variables, aggregate seasonal or annual means, compute observation metrics, and write summary statistics. The parser is `tools/parse_output_quincy.py`.

## Inputs

- `--input`: output CSV from S3, or a NetCDF file for the declared full-QUINCY path.
- `--format csv|netcdf|auto`; analytic S3 output is CSV.
- `--variables`: optional subset such as `GPP NEE RECO LE H LAI`.
- `--aggregate seasonal|annual`: optional aggregation.
- `--compute-metrics`: computes metrics when observation columns such as `GPP_OBS` are present.
- `--summary`: path to write summary JSON.

## Outputs

- Parsed timeseries CSV with `TIMESTAMP` and selected variables.
- Optional summary JSON containing `summary` and `metrics`.
- CLI JSON result with row counts, variables, warnings, summary, and metrics.

## Procedure

Inspect parser metadata and CLI:

```bash
cd KISSPATH_KI_ROOT/QUINCY/knowledge_infrastructure
sed -n '1,130p' tools/parse_output_quincy.py
python3 tools/parse_output_quincy.py --help
```

Parse the analytic model CSV:

```bash
cd KISSPATH_KI_ROOT/QUINCY/knowledge_infrastructure
python3 tools/parse_output_quincy.py \
  --input /tmp/quincy_fi_hyy/quincy_output.csv \
  --format csv \
  --output /tmp/quincy_fi_hyy/parsed_quincy.csv \
  --summary /tmp/quincy_fi_hyy/summary.json
```

Extract a validation-focused subset and compute metrics if observation columns were carried through S1 and S3:

```bash
cd KISSPATH_KI_ROOT/QUINCY/knowledge_infrastructure
python3 tools/parse_output_quincy.py \
  --input /tmp/quincy_fi_hyy/quincy_output.csv \
  --format csv \
  --output /tmp/quincy_fi_hyy/fluxes_only.csv \
  --variables GPP NEE RECO LE H \
  --compute-metrics \
  --summary /tmp/quincy_fi_hyy/flux_metrics.json
```

## Verification

- Parser input validation finds at least one expected model output column from `QUINCY_OUTPUT_VARS`.
- Output validation checks ranges for `GPP`, `NEE`, `RECO`, `RA`, `RH`, `LAI`, `LE`, and `H`.
- Summary JSON exists and includes non-empty statistics for parsed variables.
- If `--aggregate seasonal` or `--aggregate annual` is used, confirm `MONTH` or `YEAR` was present in the S3 output; otherwise the parser warns that aggregation cannot be computed.

## Traps

- `dt_quincy_012`: do not flip NEE sign during parsing or metrics.
- `dt_quincy_025`: delimiter assumptions can produce headers but all-NaN data for custom text output; analytic S3 output is comma-delimited CSV.
- `dt_quincy_013`: very high `LE` and negative `H` should be treated as a model/parameter diagnostic, not just parser noise.
- `dt_quincy_006`: all-NaN fluxes usually trace back to unhandled missing values in S1 forcing.

## Example

```bash
cd KISSPATH_KI_ROOT/QUINCY/knowledge_infrastructure
python3 tools/parse_output_quincy.py \
  --input /tmp/quincy_fi_hyy/quincy_output.csv \
  --format csv \
  --output /tmp/quincy_fi_hyy/parsed_quincy.csv \
  --variables GPP NEE RECO LE H LAI \
  --summary /tmp/quincy_fi_hyy/summary.json
head -n 5 /tmp/quincy_fi_hyy/parsed_quincy.csv
```
