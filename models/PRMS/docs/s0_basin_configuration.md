# Stage 0: Basin Configuration

## Purpose

Define the watershed study area, simulation period, and module selections before any data processing begins. This stage produces no files directly but determines all downstream decisions.

## Inputs

- Basin of interest (name, coordinates, or HRU shapefile)
- Desired simulation period (water year basis recommended: Oct 1 - Sep 30)
- Available forcing data source (CMFD, ERA5, MSWX, station data)
- Available soil/land use data source (HWSD, SOILGRIDS, local surveys)

## Outputs

- Configuration decisions documented for stages 1-5
- Module selection for control file (stage 3)

## Procedure

### Step 1: Define the basin

1. Obtain or delineate HRU boundaries (GIS shapefile or CSV with attributes)
2. For each HRU, determine: area (km2), mean elevation (m), centroid lat/lon, slope, aspect
3. Count total HRUs → `nhru` dimension
4. Identify stream segments → `nsegment` dimension
5. Identify observation stations → `nobs` dimension

### Step 2: Select simulation period

1. Choose start/end dates based on available forcing data
2. Use water year boundaries (Oct 1 to Sep 30) for US basins
3. Include at least 1 year warmup period (set `prms_warmup = 1` in control file)
4. Ensure forcing data covers the full period plus warmup

### Step 3: Select modules

Based on available data:

| Data Available | Temperature | Precipitation | ET | Solar Rad |
|---------------|-------------|--------------|-----|-----------|
| Single station | temp_1sta | precip_1sta | potet_jh | ddsolrad |
| Multiple stations | temp_dist2 | precip_dist2 | potet_jh | ddsolrad |
| Gridded per-HRU | climate_hru | climate_hru | potet_jh | ddsolrad |
| Full met suite | climate_hru | climate_hru | potet_pm | climate_hru |

**Default recommendation**: Use `climate_hru` for temp/precip when working with gridded global datasets. This avoids station interpolation issues.

### Step 4: Choose unit system

- Set `elev_units = 0` (feet) — this is the PRMS default
- Set `temp_units = 0` (Fahrenheit)
- Set `precip_units = 0` (inches)
- Set `runoff_units = 0` (cfs)

**TRAP**: If you set elev_units=1 (meters), you must ensure ALL elevation-dependent parameters match. It is safer to convert to feet.

## Verification

- [ ] nhru count matches number of HRU polygons/entries
- [ ] Start date is before end date
- [ ] Forcing data source covers simulation period
- [ ] Module selections are compatible with available data
- [ ] Unit conventions are documented

## Traps

1. **Water year vs calendar year**: PRMS can handle any start/end, but USGS convention is water year (Oct 1 - Sep 30). Starting Jan 1 in snowy basins means the first winter has no antecedent snowpack.

2. **Warmup period**: The first year of simulation should be discarded as spinup. Set `prms_warmup = 1` to exclude it from statistics.

3. **Module compatibility**: Some modules require specific data. `potet_pm` requires humidity and wind speed CBH files. If these aren't available, use `potet_jh` instead.

## Example

```python
config = {
    "basin_name": "Sagehen Creek",
    "nhru": 42,
    "nsegment": 15,
    "nobs": 1,
    "start_date": "1980-10-01",
    "end_date": "2010-09-30",
    "warmup_years": 1,
    "temp_module": "climate_hru",
    "precip_module": "climate_hru",
    "et_module": "potet_jh",
    "solrad_module": "ddsolrad",
    "srunoff_module": "srunoff_smidx",
    "strmflow_module": "strmflow",
}
```
