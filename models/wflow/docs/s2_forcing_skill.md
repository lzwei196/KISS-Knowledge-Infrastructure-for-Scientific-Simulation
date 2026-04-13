# s2 — Forcing Data Preparation Skill Document

## Purpose

Convert CMFD/MSWX meteorological forcing to wflow NetCDF format with correct units. wflow requires precipitation (mm/timestep), temperature (degC), and PET (mm/timestep). Unit errors here produce silent failures — the model runs but results are scientifically meaningless (dt_w001, dt_w002, dt_w003).

## Prerequisites

- Stage s1 complete (staticmaps.nc or grid_nc exists for grid definition)
- Forcing data available: CMFD (China), MSWX (global), or VIC ASCII forcing files
- Python packages: xarray, netCDF4, numpy, pandas

## Inputs

| Name | Type | Source | Description |
|------|------|--------|-------------|
| forcing_dir | directory | VIC pipeline | Pre-processed VIC ASCII forcing files |
| grid_nc or staticmaps.nc | file | s1 | Grid definition for spatial alignment |
| start_year, end_year | int | s0 config | Simulation period |

## Procedure

1. **Select forcing source**: VIC ASCII files (easiest — already processed), or raw CMFD/MSWX
2. Run `convert_forcing_to_wflow.py` with appropriate source
3. **Verify units immediately after conversion**:
   - Mean daily precip: 1-10 mm/day for most basins (check: `ncdump -v precip forcing.nc | tail`)
   - Temperature range: -30 to 45 degC (if > 200, still in Kelvin — dt_w002)
   - Mean PET: 1-8 mm/day depending on climate
4. If PET is missing, run `calculate_pet.py` (Hargreaves or Penman-Monteith)
5. Verify forcing.nc spatial dimensions match staticmaps.nc (dt_w008)

## Unit Conversion Table (CRITICAL)

| Variable | CMFD Unit | MSWX Unit | wflow Unit | Conversion |
|----------|-----------|-----------|------------|------------|
| Precipitation | mm/3hr | mm/3hr | mm/day | Sum 8 values per day |
| Temperature | K | K | degC | Subtract 273.15 |
| Specific humidity | kg/kg | kg/kg | — | Used for PET calc |
| Shortwave radiation | W/m2 | W/m2 | — | Used for PET calc |
| Wind speed | m/s | m/s | — | Used for PET calc |
| Pressure | Pa | Pa | — | Used for PET calc |

## Expected Outputs

| Output | Path | Verification |
|--------|------|-------------|
| forcing.nc | outputs/<run>/wflow_project/forcing.nc | Has precip, temp, pet variables |

## Validation Checks

1. forcing.nc has 3 variables: precip, temp, pet
2. Time dimension length = (end_year - start_year + 1) * 365 (approximately)
3. Spatial dimensions match staticmaps.nc
4. Mean precip is 1-10 mm/day
5. Temperature range is physically plausible (-30 to 45 degC)
6. PET is 0-15 mm/day (no negatives)
7. No NaN values in active cells

## Common Pitfalls

- **dt_w001**: Precip in mm/s instead of mm/day (runoff 86400x too high)
- **dt_w002**: Temperature in Kelvin (no snow in cold basins, wrong PET)
- **dt_w003**: PET missing or zero (all precip becomes runoff)
- **dt_w004**: Snow in tropical basins (temperature offset not applied)
- **dt_w008**: Grid mismatch between forcing and staticmaps (DimensionMismatch)
