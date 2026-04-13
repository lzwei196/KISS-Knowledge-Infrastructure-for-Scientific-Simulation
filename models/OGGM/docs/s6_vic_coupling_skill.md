# Stage 6: OGGM-VIC Hydrological Coupling

## Purpose

Couple OGGM glacier model outputs with HydroCraft's VIC hydrological model to produce integrated cryospheric-hydrological simulations for glacierized basins. This stage converts OGGM's per-glacier melt runoff into VIC grid cell format, handles the critical double-counting problem (VIC also simulates snowmelt on glacier cells), performs unit conversions, aligns temporal resolutions, and quantifies the glacier contribution to total basin discharge. This is where glacier science meets operational hydrology.

## Prerequisites

- **OGGM simulation completed** (Stage 5 — with `store_monthly_hydro=True`)
- **VIC simulation completed** — VIC run with grid, soil, vegetation, forcing, and routing
- **Glacier inventory CSV** from Stage 1 (with centroid coordinates)
- **VIC grid NetCDF** (`basin_grid.nc`) for spatial mapping

## Inputs

| Input | Type | Required | Description |
|-------|------|----------|-------------|
| `oggm_output` | file | Yes | Compiled OGGM output NetCDF |
| `vic_grid_nc` | file | Yes | VIC grid NetCDF |
| `glacier_csv` | file | Yes | Glacier inventory with centroids |
| `vic_snowmelt_dir` | directory | No | VIC result for double-counting correction |
| `vic_discharge` | file | No | VIC/routing discharge for contribution analysis |
| `basin_shp` | file | No | Basin shapefile for plotting |
| `basin_area_km2` | float | No | Basin area for fraction computation |
| `output_dir` | directory | Yes | Output directory |

## Procedure

### Step 1: Spatial Mapping (Glacier to VIC Grid)

Each glacier must be assigned to one or more VIC grid cells based on its location and extent:

**Simple method (centroid-based):**
- Assign each glacier to the VIC grid cell containing its centroid
- Works well when glaciers are smaller than VIC grid cells (typical for 0.25 deg grid)
- Fast, deterministic

**Area-weighted method (for large glaciers or fine VIC grid):**
- Intersect glacier polygon with VIC grid cells
- Distribute glacier runoff proportional to area in each cell
- More accurate but requires glacier outlines (not just centroids)

**Implementation:**
```python
# For each glacier, find nearest VIC grid cell
for glacier in glaciers:
    distances = haversine(glacier.lat, glacier.lon, vic_lats, vic_lons)
    nearest_cell = np.argmin(distances)
    mapping[glacier.rgi_id] = nearest_cell
```

Output: `glacier_vic_cell_mapping.csv` with columns: rgi_id, glacier_area_km2, vic_cell_lat, vic_cell_lon, area_fraction_in_cell.

### Step 2: Unit Conversion (CRITICAL)

OGGM and VIC use different units. Conversion must be exact — errors are silent and produce wrong discharge magnitudes.

**OGGM output units:**
- `melt_on_glacier`: kg/m2/month (equivalent to mm w.e./month)
- This is a flux density — the melt per unit glacier area per month

**VIC/routing units:**
- Discharge: mm/day over the grid cell, or m3/s at routing outlet

**Conversion to volumetric flow rate (m3/s):**
```
Q_glacier(m3/s) = melt_on_glacier(mm_we/month) * glacier_area(m2) / (1000 * seconds_in_month)
```

Where:
- `melt_on_glacier` is in mm w.e./month = kg/m2/month
- `glacier_area` is in m2 (from glacier CSV, convert from km2: * 1e6)
- `1000` converts mm to meters
- `seconds_in_month` varies: Jan=2678400, Feb=2419200/2505600, etc. Use actual calendar days.

**Common error (dt_018):** Using a fixed 30 days/month (2592000 seconds) instead of actual month lengths introduces up to 10% error in February and 3% in other months.

### Step 3: Double-Counting Avoidance (CRITICAL)

VIC simulates the energy and water balance for ALL grid cells, including those partially or fully covered by glaciers. VIC will compute snowmelt on glacier cells, treating them as snow-covered land. OGGM independently computes melt (ice + snow) on the same glacier surfaces. Simply adding OGGM output to VIC output double-counts melt on glacier areas.

**Method A: Subtract VIC snowmelt from glacier cells**
```python
for cell in glacier_cells:
    vic_snowmelt = extract_vic_snowmelt(vic_result, cell.lat, cell.lon)
    glacier_fraction = cell.glacier_area / cell.total_area
    # VIC snowmelt that overlaps with glacier area
    double_counted = vic_snowmelt * glacier_fraction
    # Net glacier contribution = OGGM melt - double-counted VIC snowmelt
    net_glacier = oggm_melt[cell] - double_counted
    net_glacier = max(net_glacier, 0)  # Cannot be negative
```

**Method B: Mask glacier cells in VIC**
Before running VIC, set glacier cells to bare rock (vegetation class = bare soil, no snow accumulation). Then OGGM handles all ice/snow processes on glacier cells. This is cleaner but requires modifying VIC input and re-running.

**Method C: Post-hoc fraction correction (approximate)**
```python
# For small glacier fractions (<5%)
correction_factor = 1.0 - glacier_fraction * 0.5  # Approximate
total_discharge = vic_discharge * correction_factor + oggm_runoff
```

**Recommendation:** Use Method A for production. It does not require re-running VIC and handles double-counting explicitly. Method B is ideal but requires VIC re-run. Method C is only for quick estimates.

### Step 4: Temporal Alignment

**OGGM hydrological year:** October 1 - September 30 (Northern Hemisphere)
**VIC calendar year:** January 1 - December 31

OGGM's monthly output uses hydrological year indexing:
- OGGM "month 1" of hydrological year 2010 = October 2009
- OGGM "month 12" of hydrological year 2010 = September 2010

**Solution:** OGGM NetCDF output includes actual datetime coordinates. Always use these dates, never month indices:

```python
import xarray as xr
ds = xr.open_dataset('run_output_hydro_historical.nc')
# Use ds.time (actual dates) not ds.month_2d (month indices)
oggm_monthly = ds['melt_on_glacier'].sel(time=slice('2000-01', '2010-12'))
```

### Step 5: Inject into Routing

After computing net glacier runoff per VIC grid cell per month, add it to VIC's routing input:

**For Lohmann routing:**
- Convert monthly glacier m3/s to daily by distributing evenly within each month (or use a melt timing curve: peak melt in afternoon, less at night)
- Add to VIC preprocessed output (the 7-column files) as additional runoff
- Re-run routing with modified input

**For CaMa-Flood:**
- Add glacier runoff to the NetCDF files prepared by `process_vic_for_cama.py`
- Glacier runoff goes into the `runoff` variable alongside VIC surface runoff and baseflow

### Step 6: Contribution Analysis

Quantify glacier's role in basin hydrology:

**Monthly glacier percentage:**
```python
glacier_pct_monthly = glacier_discharge / total_discharge * 100
```

**Seasonal pattern:** In glacierized basins:
- Winter (DJF): Glacier contribution ~0-5% (ice is frozen)
- Spring (MAM): Rising, ~5-15% (early melt begins)
- Summer (JJA): Peak, ~20-60% (maximum melt)
- Autumn (SON): Declining, ~10-20% (melt slowing)

**Peak water detection:** For projection simulations, find the year when glacier runoff reaches its maximum before declining:
```python
annual_glacier_runoff = glacier_discharge.resample('Y').sum()
peak_water_year = annual_glacier_runoff.idxmax().year
```

### Step 7: Visualization

Generate plots using `plot_glacier_hydro.py`:

1. **Stacked runoff components** — Monthly stacked area chart:
   - Glacier melt (blue), snowmelt (cyan), rainfall runoff (green), baseflow (brown)
   - Shows seasonal contributions

2. **Glacier evolution** — Volume, area, length time series:
   - Historical + projections with multi-SSP comparison
   - Volume in km3, area in km2

3. **Contribution fraction** — Monthly bar chart:
   - What percentage of total discharge comes from glaciers each month
   - Highlights summer dependence

4. **Spatial map** — Basin with glacier outlines:
   - Glaciers colored by specific runoff or mass balance
   - VIC grid overlay showing glacier fraction per cell

## Expected Outputs

| Output | Location | Description |
|--------|----------|-------------|
| `glacier_runoff_vic_grid.nc` | output_dir | Monthly glacier runoff per VIC cell (m3/s) |
| `glacier_vic_cell_mapping.csv` | output_dir | Glacier-to-VIC-cell spatial mapping |
| `glacier_contribution.json` | output_dir | Monthly/annual glacier discharge fraction |
| Plots (4 types) | output_dir | PNG visualizations |

## Validation Checks

1. **Volume conservation** — Total OGGM melt (mm w.e. * area) = total converted runoff (m3) within 1%
2. **No negative runoff** — After double-counting correction, net glacier runoff >= 0
3. **Glacier fraction consistency** — Sum of glacier area fractions per VIC cell <= 1.0
4. **Temporal alignment** — OGGM and VIC outputs cover the same dates
5. **Magnitude check** — Glacier discharge << total discharge for low glacier fraction basins
6. **Seasonal pattern** — Glacier contribution peaks in summer (NH) or appropriate season

## Common Pitfalls

### Hydrological Year Mismatch (dt_016)
The #1 coupling error. Using OGGM month indices (1=October) as if they were calendar months (1=January) shifts glacier melt by 3 months. Always use actual datetime coordinates.

### Double-Counting Snowmelt (dt_017)
If not corrected, glacier melt is counted twice — once by VIC (as snowmelt) and once by OGGM. For basins with >10% glacier fraction, this can inflate total discharge by 10-30%.

### Unit Conversion Error (dt_018)
mm w.e./month to m3/s conversion requires careful attention to area units (km2 vs m2) and time units (month vs seconds). A km2-to-m2 factor-of-1e6 error produces discharge off by 6 orders of magnitude.

### Spatial Mapping Ambiguity (dt_019)
When a glacier straddles two VIC grid cells, its melt must be split proportionally. Assigning all melt to the centroid cell can produce grid cells with >100% glacier coverage, leading to physically impossible double-counting correction.

### Missing store_monthly_hydro
If the OGGM simulation was run without `store_monthly_hydro=True`, monthly melt data is unavailable. Only annual diagnostics exist, which are too coarse for monthly VIC coupling. The simulation must be re-run.

## Tools Reference

| Tool | Script | Purpose |
|------|--------|---------|
| `oggm_to_vic_runoff` | `tools/s6_vic_coupling/oggm_to_vic_runoff.py` | Spatial mapping + unit conversion |
| `glacier_contribution_analysis` | `tools/s6_vic_coupling/glacier_contribution_analysis.py` | Quantify glacier contribution |
| `plot_glacier_hydro` | `tools/s6_vic_coupling/plot_glacier_hydro.py` | Generate visualizations |
