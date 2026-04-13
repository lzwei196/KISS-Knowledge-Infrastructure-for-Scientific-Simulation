# Yield Analysis and Multi-Model Ensemble — Skill Document

> **Stage ID**: s8_yield_analysis
> **Pipeline order**: 8 of 8
> **Depends on**: s7_output_parsing

## Purpose

Analyze WOFOST simulation results across multiple grid cells, create spatial yield maps, and optionally compare with DSSAT results for multi-model ensemble estimation. When integrated with HydroCraft, WOFOST runs on each VIC grid cell using cell-specific weather and soil data. This stage aggregates individual cell results into basin-level statistics and visualizations. The WOFOST-DSSAT ensemble provides uncertainty bounds on yield estimates.

## Prerequisites

- [ ] WOFOST simulation completed for all grid cells (Stages 6-7)
- [ ] Per-cell output CSVs available in output directory
- [ ] Basin grid NetCDF available (for spatial coordinates)
- [ ] If ensemble: DSSAT gridded yield CSV also available

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| cell_outputs_dir | directory | Stage 7 | Directory with per-cell WOFOST daily output CSVs |
| grid_nc | file | VIC grid generation | Basin grid NetCDF with cell coordinates |
| wofost_yield_csv | file | this stage | Aggregated WOFOST gridded yield (created in Step 1) |
| dssat_yield_csv | file | DSSAT pipeline | DSSAT gridded yield CSV (for ensemble comparison) |
| shp_path | file | basin delineation | Basin boundary shapefile (for map overlay) |

## Procedure

### Step 1: Aggregate cell outputs to gridded yield

```python
import pandas as pd
import xarray as xr
import glob

# Read grid coordinates
grid = xr.open_dataset(grid_nc)
lats = grid['lat'].values
lons = grid['lon'].values

# Collect per-cell yield
results = []
for cell_csv in glob.glob(f'{cell_outputs_dir}/daily_output_*.csv'):
    # Extract lat/lon from filename
    parts = cell_csv.split('_')
    lat = float(parts[-2])
    lon = float(parts[-1].replace('.csv', ''))

    df = pd.read_csv(cell_csv, index_col='day', parse_dates=True)
    results.append({
        'lat': lat,
        'lon': lon,
        'twso_kgha': df['TWSO'].iloc[-1],
        'tagp_kgha': df['TAGP'].iloc[-1],
        'lai_max': df['LAI'].max(),
        'dvs_final': df['DVS'].iloc[-1],
    })

gridded = pd.DataFrame(results)
gridded.to_csv(f'outputs/{run_name}/wofost/gridded_yield.csv', index=False)
print(f"Cells: {len(gridded)}, Mean yield: {gridded['twso_kgha'].mean():.0f} kg/ha")
```

### Step 2: Quality check spatial results

```python
# Check for failed cells
failed = gridded[gridded['dvs_final'] < 2.0]
if len(failed) > 0:
    print(f"WARNING: {len(failed)} cells did not reach maturity:")
    print(failed[['lat', 'lon', 'dvs_final', 'twso_kgha']])

zero_yield = gridded[gridded['twso_kgha'] <= 0]
if len(zero_yield) > 0:
    print(f"WARNING: {len(zero_yield)} cells have zero yield")

# Spatial statistics
print(f"Yield range: {gridded['twso_kgha'].min():.0f} - {gridded['twso_kgha'].max():.0f} kg/ha")
print(f"Mean: {gridded['twso_kgha'].mean():.0f}, Std: {gridded['twso_kgha'].std():.0f}")
```

### Step 3: Generate yield map

Use the HydroCraft plotting tools:
```bash
python skills/plot/plot_crop_yield_map.py \
  --csv outputs/{run_name}/wofost/gridded_yield.csv \
  --value_col twso_kgha \
  --shp data/shp/{basin}_shp/{basin}.shp \
  --title "WOFOST Yield — {Basin Name}" \
  --label "Yield (kg/ha)" \
  --output outputs/{run_name}/wofost/yield_map.png
```

### Step 4: Compare with DSSAT (multi-model ensemble)

```python
# Load both model outputs
wofost = pd.read_csv('outputs/{run}/wofost/gridded_yield.csv')
dssat = pd.read_csv('outputs/{run}/dssat/gridded_yield.csv')

# Merge on grid coordinates
merged = wofost.merge(dssat, on=['lat', 'lon'],
                       suffixes=('_wofost', '_dssat'))

# Ensemble mean and uncertainty
merged['yield_ensemble'] = (merged['twso_kgha_wofost'] + merged['hwam_kgha_dssat']) / 2
merged['yield_range'] = abs(merged['twso_kgha_wofost'] - merged['hwam_kgha_dssat'])

print(f"WOFOST mean: {merged['twso_kgha_wofost'].mean():.0f} kg/ha")
print(f"DSSAT mean:  {merged['hwam_kgha_dssat'].mean():.0f} kg/ha")
print(f"Ensemble mean: {merged['yield_ensemble'].mean():.0f} kg/ha")
print(f"Model spread: {merged['yield_range'].mean():.0f} kg/ha")

merged.to_csv(f'outputs/{run_name}/wofost/ensemble_comparison.csv', index=False)
```

### Step 5: Phenology comparison

```python
# Compare development timing between models
# WOFOST: DVS 0→1→2 (continuous)
# DSSAT: ADAT/MDAT (days after planting)

# Extract WOFOST phenology
for _, cell in gridded.iterrows():
    cell_df = pd.read_csv(f'daily_output_{cell.lat}_{cell.lon}.csv',
                          index_col='day', parse_dates=True)
    anthesis_idx = (cell_df['DVS'] - 1.0).abs().idxmin()
    maturity_idx = (cell_df['DVS'] - 2.0).abs().idxmin()
    # Compare with DSSAT ADAT/MDAT for same cell
```

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| Gridded yield CSV | `outputs/{run}/wofost/gridded_yield.csv` | lat, lon, twso_kgha columns; N rows = grid cells |
| Yield map PNG | `outputs/{run}/wofost/yield_map.png` | Spatial map showing yield distribution |
| Ensemble CSV | `outputs/{run}/wofost/ensemble_comparison.csv` | Side-by-side WOFOST vs DSSAT with ensemble mean |

## Validation Checks

1. **Yield range plausible**: TWSO 500-20000 kg/ha for grain crops
   - If all cells < 500: systematic underestimation — check weather units
   - If all cells > 15000 and WLP mode: check soil parameters (too much water available?)

2. **Spatial coherence**: Neighboring cells should have similar yields (no sharp boundaries)
   - Sharp boundaries suggest forcing data artifacts or soil parameter jumps

3. **No systematic WOFOST-DSSAT bias**: If one model is consistently 3x higher, check unit conversions
   - WOFOST TWSO = DSSAT HWAM (both in kg/ha)

## Common Pitfalls

> **PITFALL**: Comparing WOFOST potential with DSSAT water-limited
> WOFOST in PP mode gives potential yield; DSSAT with water balance gives water-limited. Comparing them is meaningless — ensure both models use the same production level.
> **Do this instead**: Run both in water-limited mode for fair comparison.

> **PITFALL**: Column name mismatch between models
> WOFOST uses TWSO for grain yield, DSSAT uses HWAM/HWAH. They are the same physical quantity but different column names.
> **Do this instead**: Explicitly map column names when merging datasets.

---

*This skill document is part of the wofost-pcse-knowledge infrastructure.*
*Stage 8 of 8 | Tools: compute_gridded_yield, compare_wofost_dssat, generate_yield_map | Related triplets: dt_003, dt_008*
