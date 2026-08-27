# S8 Execution

## Purpose
Run the assembled Pywr model, export reservoir operation results, plot them, check overtopping risk, and optionally inject regulated releases into CaMa-Flood runoff input. This stage corresponds to the S8 tools listed in `../SKILL.md` and the S8a-S8d branches in `../workflow/pywr_workflow.md`.

## Inputs
- Pywr model JSON from S7.
- Inflow CSV from S4 for plotting.
- Rules JSON from S5 for plotting control curves.
- Reservoir JSON from S3 or capacity value for overtopping checks.
- CaMa runoff NetCDF or directory for optional release injection.
- Tools in `../tools/s8_execution/`: `run_pywr.py`, `plot_reservoir_operations.py`, `check_overtopping.py`, and `inject_releases_to_cama.py`.

## Outputs
- Results directory from `run_pywr.py`, including storage and release timeseries CSVs.
- Plot image such as `operations_plot.png`.
- Overtopping report JSON.
- Optional regulated CaMa-Flood NetCDF runoff files.

## Procedure
Run Pywr and write result CSVs:

```bash
KI=KISSPATH_KI_ROOT/Pywr/knowledge_infrastructure
PYWR_PYTHON="KISSPATH_HOME/桌面/test/hydro-claude/python_env/bin/python3"

"$PYWR_PYTHON" "$KI/tools/s8_execution/run_pywr.py" \
  --model /tmp/pywr_model.json \
  --output_dir /tmp/pywr_results \
  --verbose
```

Plot reservoir operations:

```bash
"$PYWR_PYTHON" "$KI/tools/s8_execution/plot_reservoir_operations.py" \
  --storage_csv /tmp/pywr_results/storage_timeseries.csv \
  --release_csv /tmp/pywr_results/release_timeseries.csv \
  --inflow_csv /tmp/pywr_inflow.csv \
  --rules_json /tmp/pywr_rules.json \
  --output /tmp/pywr_results/operations_plot.png \
  --title "Huaihe Basin Reservoir"
```

Check overtopping:

```bash
"$PYWR_PYTHON" "$KI/tools/s8_execution/check_overtopping.py" \
  --storage_csv /tmp/pywr_results/storage_timeseries.csv \
  --reservoir_json /tmp/pywr_reservoir.json \
  --output /tmp/pywr_results/overtopping_report.json
```

Optionally inject regulated releases into CaMa-Flood runoff:

```bash
"$PYWR_PYTHON" "$KI/tools/s8_execution/inject_releases_to_cama.py" \
  --release_csv /tmp/pywr_results/release_timeseries.csv \
  --cama_nc outputs/bengbu/cama_input/bengbu_runoff_1d_1985.nc \
  --dam_lat 31.43 \
  --dam_lon 115.92 \
  --output /tmp/pywr_results/bengbu_runoff_1d_1985_regulated.nc
```

## Verification
- `run_pywr.py` exits `0` and writes non-empty storage and release CSVs.
- Storage values stay within reservoir bounds unless overtopping is intentionally being diagnosed.
- Release values are non-negative.
- Plot file exists and uses the same storage/release files produced by the run.
- CaMa injection output has non-negative runoff at the dam cell and should replace, not add to, natural runoff as described in `model_couplings.yaml`.

## Traps
- `dt_pywr_004`: dataframe path resolution can fail when model JSON and CSVs are separated.
- `dt_pywr_006`: storage oscillation indicates missing or ineffective control-curve behavior.
- `dt_pywr_008`: negative releases indicate result extraction/sign-convention problems.
- `dt_pywr_009`: infeasible LP usually means demands exceed supply or spill/slack routes are missing.
- `dt_pywr_011`: CaMa injection unit conversion or cell area errors can create negative runoff.
- `dt_pywr_012`: empty recorder output usually means recorder node references do not match actual model nodes.

## Example
```bash
KI=KISSPATH_KI_ROOT/Pywr/knowledge_infrastructure
PYWR_PYTHON="KISSPATH_HOME/桌面/test/hydro-claude/python_env/bin/python3"
"$PYWR_PYTHON" "$KI/tools/s8_execution/run_pywr.py" \
  --model /tmp/pywr_model.json \
  --output_dir /tmp/pywr_results
```
