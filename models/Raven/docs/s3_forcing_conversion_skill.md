# s3: Forcing Conversion and Unit Handling

## Purpose

Convert CMFD, MSWX, or VIC forcing data into Raven .rvt format with correct units. **This is the single most critical stage in the entire Raven pipeline.** Raven explicitly states: "Raven ignores units and will not do units conversion." Every unit error produces a silent failure — the model runs fine with completely wrong results.

## Prerequisites

- VIC forcing files in `forcing_final/` (7-column ASCII: PRECIP TMAX TMIN WIND SW LW PRESS)
- OR direct CMFD/MSWX NetCDF files
- Grid coordinates (from basin_grid.nc)
- Start and end year

## CRITICAL: Unit Conversion Table

| Variable | VIC Pipeline Unit | CMFD Raw Unit | Raven Expected Unit | Conversion from VIC | Conversion from CMFD |
|----------|------------------|---------------|---------------------|---------------------|---------------------|
| PRECIP | mm/3hr | mm/3hr | **mm/d** | Sum 8 timesteps | Sum 8 timesteps |
| TEMP_MAX | degC | K | **degC** | No conversion | Subtract 273.15 |
| TEMP_MIN | degC | K | **degC** | No conversion | Subtract 273.15 |
| TEMP_AVE | (not in VIC) | K | **degC** | Compute (Tmax+Tmin)/2 | Subtract 273.15 |
| WIND_VEL | m/s | m/s | **m/s** | No conversion | No conversion |
| SW_RADIA | W/m2 (inst.) | W/m2 (inst.) | **MJ/m2/d** | Mean * 0.0864 | Mean * 0.0864 |
| LW_INCOMING | W/m2 (inst.) | W/m2 (inst.) | **MJ/m2/d** | Mean * 0.0864 | Mean * 0.0864 |
| AIR_PRES | kPa | Pa | **kPa** | No conversion | Divide by 1000 |

## Procedure

1. **Read grid cells** from basin_grid.nc or infer from forcing filenames
2. **Read all forcing files** — 7-column ASCII from VIC pipeline
3. **Compute basin-mean forcing** by averaging all grid cells
4. **Aggregate 3-hourly to daily**:
   - PRECIP: **SUM** of 8 values (NOT mean)
   - TEMP_MAX: **MAXIMUM** of 8 values
   - TEMP_MIN: **MINIMUM** of 8 values
   - Others: **MEAN** of 8 values
5. **Convert units**: Apply the conversion table above
6. **Bounds checking**: Verify values are physically reasonable
7. **Write .rvt file** in Raven gauge format

### Tool command:
```bash
python convert_forcing_to_rvt.py \
    --forcing_dir <path> --grid_nc <path> \
    --output_dir <path> --basin_name <name> \
    --start_year <year> --end_year <year> \
    --forcing_source cmfd
```

## Validation Checks

After generating .rvt, verify these values:

- [ ] Mean annual precipitation: 200-3000 mm/yr (most basins)
- [ ] Temperature range: -40 to +50 degC (if 230-320, still in Kelvin!)
- [ ] Shortwave radiation: 0-40 MJ/m2/d (if 0-400, still in W/m2!)
- [ ] Air pressure: 60-110 kPa (if 60000-110000, still in Pa!)
- [ ] Daily precip max < 500 mm/d (if > 500, likely not aggregated from 3hr)
- [ ] Data count in .rvt header matches actual data lines

## Common Pitfalls

- **dt_001**: Precip not summed to daily — 8x overestimate. The most common error.
- **dt_002**: Temperature in Kelvin — PET calculations and snowmelt completely wrong.
- **dt_003**: Shortwave in W/m2 instead of MJ/m2/d — PET 10x too high.
- **dt_004**: Pressure in Pa instead of kPa — vapor pressure calculations break.
- **dt_005**: Timestep mismatch — .rvt says interval=1.0 but data is actually 3-hourly.
- **dt_010**: PRECIP not in .rvt at all — Raven fills with zeros, no warning.

## Minimum vs Full Forcing

| PET Method | Minimum Forcing | Full Forcing Recommended? |
|-----------|----------------|--------------------------|
| PET_OUDIN | PRECIP + TEMP_AVE | No — temperature-only |
| PET_HARGREAVES_1985 | PRECIP + TEMP_MIN + TEMP_MAX | No |
| PET_PENMAN_MONTEITH | PRECIP + TEMP + WIND + RH + SW + PRESS | Yes — needs all 7 |
| PET_PRIESTLEY_TAYLOR | PRECIP + TEMP + SW | Recommended |

When in doubt, provide at minimum: PRECIP, TEMP_MIN, TEMP_MAX, TEMP_AVE. Raven will generate all other variables internally using its 40+ forcing function generators.
