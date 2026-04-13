# Stage 2: Rainfall Forcing Preparation

## Purpose

Prepare rainfall input timeseries for HAIL-CAESAR. Rainfall drives the hydrological model and is the primary input that determines flood dynamics and erosion.

## Inputs

| Input | Format | Units | Source |
|-------|--------|-------|--------|
| Precipitation data | CSV, NetCDF, or text | Various (see conversions) | ERA5, CMFD, gauge data, MSWX |
| Hydroindex raster (optional) | ASCII grid (.asc) | Integer zone IDs | Created from rainfall regions |

## Outputs

| Output | Format | Units | Description |
|--------|--------|-------|-------------|
| Rainfall timeseries | Plain text, headerless | mm/hr | Space-delimited, one row per timestep |
| Hydroindex raster (if spatial) | `.asc` | Integer zones | Maps cells to rainfall columns |

## Procedure

### Step 1: Obtain precipitation data

Common sources:
- **ERA5**: Hourly, ~31km, global. Variable `tp` in m/timestep (cumulative)
- **CMFD**: 3-hourly, 0.1 deg, China. Variable `prec` in mm/hr
- **Rain gauges**: Point data, various timesteps
- **MSWX**: Daily, 0.1 deg, global

### Step 2: Convert units to mm/hr

**HAIL-CAESAR always expects rainfall as instantaneous rate in mm/hr**, regardless of the `rain_data_time_step` setting. This is a critical point.

| Source | Source units | Conversion |
|--------|------------|------------|
| ERA5 | m/timestep (accumulated) | Diff consecutive steps, multiply by 1000 / dt_hours |
| CMFD | mm/hr | No conversion needed |
| Gauges | mm/day | Divide by 24 |
| MSWX | mm/day | Divide by 24 |
| WRF | kg/m2/s | Multiply by 3600 |
| Generic | m/s | Multiply by 3,600,000 |

### Step 3: Determine temporal resolution

The rainfall file timestep must match the `rain_data_time_step` parameter (in minutes) in the parameter file.

- Hourly data: `rain_data_time_step: 60`
- 5-minute data: `rain_data_time_step: 5`
- Sub-daily: Calculate number of rows = duration_hours * 60 / timestep_min

### Step 4: Format the file

The rainfall file is a **headerless** text file. Each row represents one timestep. Each column represents a rainfall zone (1 column for uniform rainfall, N columns for spatially variable).

**Uniform rainfall example** (5-min steps, 72 hours = 864 rows):
```
0.5 0.5 0.5 0.5 0.5 0.5 ...
0.5 0.5 0.5 0.5 0.5 0.5 ...
```
Note: The Boscastle test uses a single rainfall rate repeated across space (28 values per row for compatibility with the format, but only 1 rainfall zone).

**Spatially variable rainfall** (3 zones):
```
0.5 1.2 0.3
0.8 1.5 0.4
```
Each column maps to a zone defined in the hydroindex raster.

### Step 5: Create hydroindex (if spatially variable)

If using `spatial_var_rain: yes`, create an ASCII grid raster of the same size as the DEM, with integer values (1, 2, 3, ...) defining rainfall zones. Set `num_unique_rain_cells` to match.

### Step 6: Set parameter file entries

```
rainfall_data_on:           yes
rainfall_data_file:         rainfall.txt
rain_data_time_step:        60          # minutes, must match file
spatial_var_rain:           no          # or yes if using hydroindex
num_unique_rain_cells:      1           # number of zones
```

## Verification

1. Check total precipitation volume: `sum(rainfall_mm_hr * dt_hours)` should match expected total (e.g., 50-200mm for a storm event)
2. Check maximum rate: Typical UK storm ~50 mm/hr, tropical ~100+ mm/hr
3. Check file has correct number of rows: `duration_hours * 60 / rain_data_time_step`
4. No negative values
5. If spatially variable: number of columns matches `num_unique_rain_cells`

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Rainfall in mm/day, read as mm/hr | 24x too much rain, instant flooding | Divide by 24 |
| Rainfall in m/s | Astronomical values, model crashes | Multiply by 3.6e6 |
| ERA5 accumulated precip not differenced | Monotonically increasing "rain" | Take diff of consecutive timesteps |
| Wrong `rain_data_time_step` | Rain applied too fast or too slow | Must match actual file timestep |
| Fewer rows than simulation needs | Model reads zero rain after file ends | Ensure rows >= duration * 60 / timestep |
| Columns don't match `num_unique_rain_cells` | Model reads wrong zone data | Count columns carefully |
| Negative values from diff operations | Model may behave unexpectedly | Clip to zero |

## Example

Using the `convert_rainfall_to_caesar.py` tool:

```bash
python convert_rainfall_to_caesar.py \
    --input era5_precip.nc \
    --output rainfall.txt \
    --source_units m/s \
    --timestep_min 60 \
    --lat 50.68 --lon -4.68
```

This extracts the nearest grid point to Boscastle, converts m/s to mm/hr, and writes the headerless text file.
