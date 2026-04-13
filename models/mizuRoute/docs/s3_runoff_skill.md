# Stage 3: Runoff Format Conversion — Unit Conversion Guide

## Purpose

Convert VIC or WRF-Hydro runoff output to mizuRoute input NetCDF format with correct units. **This is the #1 silent error risk in VIC-mizuRoute coupling.** Getting the unit conversion wrong produces discharge that is 8x, 24x, or 86400x too high or low with NO error message.

If skipped: mizuRoute cannot read VIC output directly (wrong format, wrong units).

## Prerequisites

- [ ] VIC simulation complete: flux files exist in `vic_result/`
- [ ] VIC output preprocessed (22 -> 7 columns) OR raw VIC output with known column layout
- [ ] Basin grid NetCDF exists (`basin_grid.nc`)

## Unit Conversion Table (CRITICAL)

| Source model | Source variable | Source units | mizuRoute units | Conversion |
|-------------|----------------|-------------|-----------------|------------|
| VIC (daily) | OUT_RUNOFF + OUT_BASEFLOW | mm/day | mm/s | divide by 86400 |
| VIC (3-hourly) | OUT_RUNOFF + OUT_BASEFLOW | mm/3hr | mm/s | divide by 10800 |
| VIC (hourly) | OUT_RUNOFF + OUT_BASEFLOW | mm/hr | mm/s | divide by 3600 |
| WRF-Hydro | SFCRNOFF + UGDRNOFF | mm/output_interval | mm/s | divide by interval_seconds |

### How to detect wrong units

| Symptom | Probable cause | Factor |
|---------|---------------|--------|
| Discharge 86400x too high | Daily VIC not divided by 86400 | /86400 |
| Discharge 8x too high | 3-hourly VIC not divided by 10800 | /10800 |
| Discharge 24x too high | Hourly VIC not divided by 3600 | /3600 |
| Discharge reasonable but 8x too low | Divided by 86400 instead of 10800 (3-hourly VIC) | x8 |

### Validation: max RUNOFF values in output NetCDF

| Climate zone | Expected max mm/s | If exceeds | Action |
|-------------|-------------------|-----------|--------|
| Humid tropical | 0.001 - 0.005 | 0.01 | OK |
| Temperate | 0.0005 - 0.003 | 0.01 | Check |
| Semi-arid | 0.0001 - 0.001 | 0.005 | Check |
| Any basin | > 0.1 | Clearly wrong | Fix unit conversion |
| Any basin | > 1.0 | 100% wrong | Conversion was skipped entirely |

## Procedure

1. **Determine VIC timestep**: Check `global_param` for `FORCE_STEPS_PER_DAY`:
   - 8 steps/day = 3-hourly
   - 24 steps/day = hourly
   - 1 step/day = daily (most common)

2. **Run convert_vic_runoff.py**:
   ```bash
   python tools/s3_runoff/convert_vic_runoff.py \
     --vic_result_dir outputs/<run>/vic_result \
     --grid_nc outputs/<run>/vic_temp/grid/basin_grid.nc \
     --output outputs/<run>/mizuroute_input/runoff.nc \
     --start_year 2000 --end_year 2010 \
     --vic_timestep daily
   ```

3. **Validate output**:
   ```bash
   python -c "
   import netCDF4 as nc
   ds = nc.Dataset('outputs/<run>/mizuroute_input/runoff.nc')
   ro = ds.variables['RUNOFF'][:]
   valid = ro[ro != -9999]
   print(f'Units: {ds.variables[\"RUNOFF\"].units}')
   print(f'Max: {valid.max():.6f} mm/s')
   print(f'Mean: {valid.mean():.6f} mm/s')
   if valid.max() > 0.01:
       print('WARNING: Max > 0.01 mm/s — check unit conversion!')
   elif valid.max() > 1.0:
       print('ERROR: Max > 1.0 mm/s — unit conversion definitely wrong!')
   else:
       print('OK: Values look reasonable for mm/s')
   "
   ```

## Expected Outputs

| Output | Path | Verification |
|--------|------|-------------|
| Runoff NetCDF | `runoff.nc` | `ncdump -h` shows RUNOFF(time,lat,lon) with units='mm/s' |

## Common Pitfalls

- **Pitfall**: Forgetting to add BASEFLOW to RUNOFF (dt_m003 variant)
  - Only routing RUNOFF (surface) without BASEFLOW (subsurface) loses ~30-70% of total flow
  - convert_vic_runoff.py adds both automatically

- **Pitfall**: Using wrong column indices from raw VIC output
  - Preprocessed VIC (7 cols): RUNOFF=col3, BASEFLOW=col4
  - Raw VIC (22 cols): RUNOFF=col5, BASEFLOW=col6
  - convert_vic_runoff.py auto-detects based on column count

- **Pitfall**: Time zone offset (dt_m013)
  - VIC output may be in UTC or local time depending on forcing
  - Ensure consistency with mizuRoute control file time settings
