# Postprocessing & Visualization — Skill Document

> **Stage ID**: s9_postprocessing
> **Pipeline order**: 9 of 9
> **Depends on**: s8_output_extraction

## Purpose

Generate publication-quality visualizations and export data for coupling with other HydroCraft models. Key outputs: water table contour maps, head time series at observation points, cross-sections, water budget bar charts, and NetCDF files for integration with VIC recharge feedback and routing baseflow contributions.

## Prerequisites

Before starting this stage, verify:

- [ ] Head and budget data extracted successfully (S8 complete)
- [ ] matplotlib, numpy, and optionally xarray/netCDF4 are installed
- [ ] Basin shapefile available for map overlays
- [ ] Observation well locations known (if comparing to measured data)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| hds_path | file | S7 output | Binary head file |
| cbc_path | file | S7 output | Cell budget file |
| listing_file | file | S7 output | Model listing file (.lst) |
| model_path | directory | workspace | For grid geometry |
| shapefile_path | file | HydroCraft | Basin boundary overlay |
| obs_wells | config | user | Observation well locations and measured heads |
| output_dir | directory | user | Where to save outputs |

## Procedure

### Step 1: Generate Water Table Contour Map

```bash
python tools/s9/plot_head_map.py
```

Set variables:
- `HDS_PATH`: path to gwf.hds
- `MODEL_PATH`: workspace directory
- `OUTPUT_PNG`: output image path
- `KSTPKPER`: timestep/period to plot, default last timestep
- `SHAPEFILE_PATH`: optional basin overlay

**Expected result**: PNG file showing water table contours with basin boundary overlay.

Mention in chat: "Water table contour map: outputs/<run>/modflow_head_map.png"

### Step 2: Generate Water Budget Bar Chart

```bash
python tools/s9/plot_water_budget.py
```

Set variables:
- `LISTING_FILE`: path to gwf.lst
- `OUTPUT_PNG`: output image path

The plot shows inflows (positive) and outflows (negative) by component:
- RCH (recharge inflow)
- DRN (drain outflow)
- RIV (net river exchange)
- WEL (pumping outflow)
- STO (storage change)

**Expected result**: Bar chart PNG.

### Step 3: Head Time Series at Key Locations

For observation wells or points of interest:

```python
import flopy.utils.binaryfile as bf
import numpy as np

hds = bf.HeadFile("workspace/gwf.hds")
times = hds.get_times()

# Extract head at a specific cell (layer=0, row=25, col=50) through time
head_ts = []
for t in times:
    h = hds.get_data(totim=t)
    head_ts.append(h[0, 25, 50])

# Plot
import matplotlib.pyplot as plt
plt.figure(figsize=(12, 4))
plt.plot(times, head_ts)
plt.xlabel("Time (days)")
plt.ylabel("Head (m)")
plt.title("Head at Observation Well")
plt.savefig("outputs/head_timeseries.png", dpi=150)
```

### Step 4: Export to NetCDF for HydroCraft Coupling

```bash
python tools/s9/export_to_netcdf.py
```

The NetCDF file contains:
- **head**: 4D array (time, layer, row, col) in meters
- **water_table**: 3D array (time, row, col) in meters
- **recharge_flux**: 3D array (time, row, col) in m3/day
- **drain_flux**: 3D array (time, row, col) in m3/day
- **lat/lon coordinates**: derived from grid geometry

This NetCDF is the interface for:
1. **VIC feedback**: water table depth -> VIC soil moisture adjustment
2. **Routing baseflow**: drain flux -> Lohmann/CaMa-Flood input
3. **Comparison**: water table depth vs VIC soil moisture

### Step 5: Compare with Observations (If Available)

If observed well data is available:

```python
# Calculate statistics
from scipy.stats import pearsonr

obs_heads = [...]  # measured heads at observation points
sim_heads = [...]  # simulated heads at same locations

rmse = np.sqrt(np.mean((np.array(obs_heads) - np.array(sim_heads))**2))
r, _ = pearsonr(obs_heads, sim_heads)
bias = np.mean(np.array(sim_heads) - np.array(obs_heads))

print(f"RMSE: {rmse:.2f} m")
print(f"Correlation: {r:.3f}")
print(f"Bias: {bias:.2f} m")
```

**Acceptable ranges**:
- RMSE < 2 m for regional models
- Correlation > 0.8
- Bias within +/- 1 m

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| Head contour map | `outputs/<run>/modflow_head_map.png` | PNG > 10 KB with visible contours |
| Water budget chart | `outputs/<run>/modflow_budget.png` | PNG > 10 KB with labeled bars |
| Head time series | `outputs/<run>/modflow_head_ts.png` | PNG with time on x-axis |
| NetCDF export | `outputs/<run>/modflow_results.nc` | Has head, water_table, lat, lon, time variables |

## Validation Checks

1. **Contour map shows reasonable pattern**: Head decreases from recharge areas to discharge areas
   - Expected: Head gradient from highlands to river valleys
   - If unexpected: Boundary conditions may be reversed

2. **Budget chart shows balance**: Inflows approximately equal outflows
   - Expected: Bars roughly symmetric around zero
   - If unexpected: See dt_mf6_003

3. **NetCDF variables have correct dimensions**: (time, nlay, nrow, ncol) for head
   - Expected: Dimensions match model grid
   - If unexpected: Export script may have transposed arrays

4. **Time series is smooth**: No sudden jumps in head unless pumping changes
   - Expected: Gradual head changes
   - If unexpected: Convergence issues in certain stress periods

## Common Pitfalls

> **PITFALL**: Plotting HDRY cells as real data
> If dry cells (head = 1e30) are included in contour plots, matplotlib will scale the colorbar to include 1e30, making all real data appear as a single color.
> **Do this instead**: Mask HDRY before plotting: `heads = np.ma.masked_where(heads > 0.9e30, heads)`

> **PITFALL**: NetCDF export without coordinates
> If the NetCDF only has array indices without spatial coordinates, downstream tools cannot georeference the data.
> **Do this instead**: Include lat/lon coordinates computed from grid origin and cell sizes.

> **PITFALL**: Forgetting to negate drain flux for routing
> MODFLOW budget convention: drain outflow is negative. Routing models expect positive baseflow.
> **Do this instead**: `baseflow = -drain_flux` before passing to routing.
> See diagnostic triplet dt_mf6_015.

> **PITFALL**: Mismatched grid coordinates between MODFLOW and VIC
> MODFLOW uses projected coordinates (meters from origin). VIC uses geographic (lat/lon degrees). Coordinate transformation is required for coupling.
> **Do this instead**: Use the grid metadata from create_grid_from_basin to establish the coordinate mapping.

---

*This skill document is part of the modflow6-knowledge-infrastructure package.*
*Stage 9 of 9 | Tools used: plot_head_map, plot_water_budget, export_to_netcdf | Related triplets: dt_mf6_003, dt_mf6_006, dt_mf6_015*
