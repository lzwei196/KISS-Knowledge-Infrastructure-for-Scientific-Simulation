# Stage 5: Output Analysis

## Purpose

Parse PRMS output files, compute hydrologic performance metrics, and generate validation figures.

## Inputs

- PRMS output files (CSV summary, model output, NetCDF, statvar)
- Observed streamflow data (optional, for validation)

## Outputs

- Parsed CSV with standardized columns
- Performance metrics (NSE, KGE, PBIAS, RMSE, R2)
- Validation hydrograph figure

## Procedure

### Step 1: Discover output files

```python
from tools.parse_prms_output import find_output_files
found = find_output_files("/prms/output")
```

### Step 2: Parse CSV summary

The PRMS CSV output contains basin-averaged daily values:

| Column | Unit | Description |
|--------|------|-------------|
| basin_ppt | inches | Basin precipitation |
| basin_rain | inches | Basin rain |
| basin_snow | inches | Basin snow |
| basin_actet | inches | Actual ET |
| basin_potet | inches | Potential ET |
| basin_sroff | inches | Surface runoff |
| basin_ssflow | inches | Subsurface flow |
| basin_gwflow | inches | Groundwater flow |
| basin_stflow_out | inches | Total streamflow |
| basin_cfs | cfs | Streamflow in cfs |
| basin_cms | cms | Streamflow in cms |

### Step 3: Compute metrics

```python
from tools.parse_prms_output import compute_all_metrics
metrics = compute_all_metrics(observed, simulated)
```

| Metric | Formula | Good | Acceptable |
|--------|---------|------|------------|
| NSE | 1 - SS_res/SS_tot | > 0.7 | > 0.5 |
| KGE | 1 - sqrt((r-1)^2 + (a-1)^2 + (b-1)^2) | > 0.7 | > 0.5 |
| PBIAS | 100 * sum(S-O)/sum(O) | |PBIAS| < 10% | < 25% |
| RMSE | sqrt(mean((O-S)^2)) | small | — |
| R2 | r^2 | > 0.7 | > 0.5 |

### Step 4: Generate validation figure

```python
from tools.parse_prms_output import create_validation_figure
create_validation_figure(obs_series, sim_series, metrics, "validation.png")
```

Figure layout:
- Top panel: Observed (black) vs Simulated (#2563EB blue) hydrograph
- Bottom panel: Residuals bar chart
- Metrics box in top-right corner

## Verification

- [ ] All key water balance variables present in output
- [ ] No NaN values in parsed output
- [ ] basin_ppt > 0 (non-zero precipitation)
- [ ] basin_actet > 0 (non-zero actual ET)
- [ ] basin_stflow_out > 0 (non-zero streamflow)
- [ ] Water balance: |ppt - actet - stflow| / ppt < 0.1 (10% closure)
- [ ] If observed available: NSE > 0.5 indicates acceptable calibration

## Traps

### 1. Output units

PRMS CSV output uses inches for depth variables and cfs/cms for flow. Don't compare inches (depth) directly with cfs (volume rate) — they have different units.

Conversion: `basin_stflow_out` (inches) = `basin_cfs` * 86400 / (basin_area_acres * 43560) * 12

### 2. Warmup period in output

If `prms_warmup = 1`, the first year is a warmup. PRMS may or may not include warmup in the CSV output depending on the version. Always check the date range.

### 3. Missing columns

The CSV output only contains variables that are enabled by the selected modules. If you didn't enable snowmelt output, `basin_snowmelt` won't appear.

### 4. Streamflow comparison requires unit matching

If observed data is in m3/s (cms) and PRMS output is in cfs, convert before computing metrics. CFS = CMS / 0.028317.

## Example

```bash
python tools/parse_prms_output.py \
    --output_dir /prms/output \
    --observed /data/observed_flow.csv \
    --results_dir /prms/results \
    --figure /prms/figures/validation.png \
    --basin_name "Sagehen Creek"
```

Output:
```
Parsed CSV: prms_summary.csv (10958 rows)
Metrics (n=10958):
  NSE   = 0.65
  KGE   = 0.72
  PBIAS = -8.3%
  RMSE  = 15.2
  R²    = 0.71
Saved: /prms/figures/validation.png
```
