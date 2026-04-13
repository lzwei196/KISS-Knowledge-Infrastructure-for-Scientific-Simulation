# Skill: Output Analysis and Validation

## Purpose

Parse openAMUNDSEN output files, extract key snow and hydrometeorological variables,
compute summary statistics, and validate against observations using standard metrics.

## Inputs

| Input | Format | Source |
|-------|--------|--------|
| Model output | NetCDF or CSV | results_dir from s4_model_execution |
| Observed data | CSV (optional) | Snow monitoring stations, SWE pillows |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Parsed time series | CSV | Per-point extracted variables |
| Summary statistics | JSON | Peak SWE, melt-out date, totals |
| Validation metrics | JSON | NSE, KGE, RMSE, bias, correlation |
| Figures | PNG | Time series plots, scatter plots |

## Procedure

### Step 1: List Available Output

```bash
ls -la output/
# Typical contents:
# output/point_summit_station.nc    (point time series)
# output/swe_monthly_*.nc           (gridded SWE maps)
```

### Step 2: Extract Point Time Series

```bash
python parse_output.py --results-dir ./output --export-csv ./analysis/
```

This produces CSV files like `summit_station_parsed.csv`:
```csv
time,swe,snow_depth,temp,precip,snowfall,sw_in
2020-10-01 00:00:00,0.0,0.0,275.3,0.0,0.0,0.0
2020-10-01 03:00:00,0.0,0.0,274.1,1.2,1.2,0.0
```

### Step 3: Compute Snow Statistics

The parser automatically computes:

| Statistic | Unit | Description |
|-----------|------|-------------|
| peak_swe_kg_m2 | kg m⁻² | Maximum SWE during period |
| peak_swe_date | date | Date of peak SWE |
| peak_depth_m | m | Maximum snow depth |
| snowfree_date | date | First snow-free date after peak |
| total_melt_kg_m2 | kg m⁻² | Cumulative melt |
| total_precip_kg_m2 | kg m⁻² | Total precipitation |
| snow_fraction | - | Fraction of precip as snow |
| mean_temp_K | K | Mean air temperature |

### Step 4: Validate Against Observations

Prepare observed data CSV:
```csv
date,swe,snow_depth
2020-10-01,0.0,0.0
2020-10-15,25.3,0.08
2020-11-01,120.5,0.35
```

Run validation:
```bash
python parse_output.py --results-dir ./output --observed obs.csv --metrics all
```

### Step 5: Interpret Metrics

| Metric | Formula | Good | Acceptable | Poor |
|--------|---------|------|------------|------|
| NSE | 1 - SS_res/SS_tot | > 0.7 | 0.5–0.7 | < 0.5 |
| KGE | 1 - √((r-1)² + (α-1)² + (β-1)²) | > 0.7 | 0.5–0.7 | < 0.5 |
| RMSE | √(mean((sim-obs)²)) | Domain-specific | | |
| PBIAS | 100 × Σ(sim-obs)/Σ(obs) | |±10%| | |±25%| | > |±25%| |
| r | Pearson correlation | > 0.9 | 0.7–0.9 | < 0.7 |

For snow models specifically:
- SWE RMSE < 50 kg m⁻² is typically acceptable
- Snow depth RMSE < 0.15 m is good
- Melt-out date within ±7 days is excellent

### Step 6: Diagnose Poor Performance

If metrics are poor, check these in order:

1. **Temperature bias** → Shifts melt timing. Check temp unit (dt_001).
2. **Precipitation total** → Controls total SWE. Check precip unit (dt_002).
3. **Rain/snow partition** → Wrong snow fraction. Check threshold_temp.
4. **Albedo decay** → Controls melt rate. Tune albedo parameters.
5. **Wind correction** → Affects precipitation totals in exposed sites.

### Step 7: Create Validation Figure

```python
import matplotlib.pyplot as plt
import pandas as pd

sim = pd.read_csv("analysis/summit_station_parsed.csv", parse_dates=[0], index_col=0)
obs = pd.read_csv("obs.csv", parse_dates=[0], index_col=0)

fig, ax = plt.subplots(figsize=(12, 5))
ax.plot(obs.index, obs["swe"], "k-", linewidth=1.5, label="Observed")
ax.plot(sim.index, sim["swe"], color="#2563EB", linewidth=1.0, label="Simulated")
ax.set_ylabel("SWE (kg m⁻²)")
ax.set_xlabel("Date")
ax.legend()
ax.set_title("Snow Water Equivalent Validation")

# Add metrics box
metrics_text = f"NSE = 0.82\nKGE = 0.78\nRMSE = 35.2 kg/m²"
ax.text(0.98, 0.98, metrics_text, transform=ax.transAxes,
        verticalalignment='top', horizontalalignment='right',
        bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

plt.tight_layout()
plt.savefig("validation_swe.png", dpi=150)
```

## Verification

1. Check output time range covers the full simulation period
2. Verify SWE peaks in spring (Northern Hemisphere) or late winter
3. Confirm snow-free date is physically reasonable (not July at 3000m)
4. Check total precipitation matches input data (conservation)
5. Verify radiation has diurnal cycle (not flat)

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Variable name mismatch | KeyError extracting "snow.swe" | Use output name "swe" not internal "snow.swe" |
| Time zone offset in output | Obs/sim shifted by hours | Align to same timezone |
| Gridded output all zeros | Empty NetCDF | Check output_data.grids config is populated |
| Monthly aggregation mismatch | Comparing instantaneous to mean | Match aggregation method |
| Missing write_freq | No output files generated | Set output_data.timeseries.write_freq |

## Example

Full analysis pipeline:

```bash
# Parse and export
python parse_output.py \
  --results-dir ./output \
  --export-csv ./analysis/ \
  --variables swe,snow_depth,temp,precip,snowfall

# Validate
python parse_output.py \
  --results-dir ./output \
  --observed ./obs/station_swe.csv \
  --metrics nse,kge,rmse,pbias,r
```
