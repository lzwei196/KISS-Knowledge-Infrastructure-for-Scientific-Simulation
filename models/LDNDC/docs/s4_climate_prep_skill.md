# Climate Data Preparation — Skill Document

> **Stage ID**: s4_climate_prep
> **Pipeline order**: 4 of 10
> **Depends on**: s1_project_setup

## Purpose

Convert meteorological forcing data from external sources (CMFD, MSWX, ERA5, VIC forcing, NASA POWER) into LDNDC's tab-separated `climate.txt` format. This is the primary driver for all LDNDC processes: soil temperature, decomposition rates, ET, snow dynamics, and plant growth all depend on correct climate input.

## Prerequisites

- [ ] Project directory created (S1 complete)
- [ ] Forcing data source identified and accessible
- [ ] Simulation period matches forcing data availability
- [ ] Python environment activated with xarray, netCDF4 installed

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| forcing_source | string | User | cmfd, mswx, era5, vic_forcing, nasa_power, csv |
| forcing_path | directory | HydroCraft data | Path to forcing data files |
| lat, lon | number | S1 | Grid cell coordinates |
| start_date, end_date | string | S1 | Simulation period |
| output_path | file | S1 | Target climate.txt path in input/ |

## Procedure

### Step 1: Convert forcing to LDNDC format

```bash
python tools/s4_climate_prep/convert_forcing_to_ldndc_climate.py
```

Set all input variables before running.

**Unit conversion table** (applied automatically by the tool):

| Variable | CMFD unit | MSWX unit | VIC unit | LDNDC unit |
|----------|-----------|-----------|----------|------------|
| Temperature | K | K | K | C (subtract 273.15) |
| Precipitation | mm/3hr | mm/3hr | mm/timestep | mm/day (sum sub-daily) |
| SW radiation | W/m2 | W/m2 | W/m2 | W/m2 (daily mean) |
| LW radiation | W/m2 | W/m2 | W/m2 | W/m2 (daily mean) |
| Wind speed | m/s | m/s | m/s | m/s (daily mean) |
| Humidity | kg/kg (specific) | % (RH) | Pa (VP) | % (RH, 0-100) |
| Pressure | Pa | Pa | kPa | kPa (for RH calc) |

### Step 2: Validate climate file

```bash
python tools/s4_climate_prep/validate_climate_file.py
```

Set `climate_file` to the generated climate.txt path.

**Expected result**: Validation passes with no errors. Check:
- Header has required columns (tavg or tmin+tmax, prec)
- Temperature values in [-60, 60] C range
- Precipitation >= 0
- Relative humidity in [0, 100]
- No missing values

**If validation fails**: See dt_005 (temperature units) or dt_006 (format errors).

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| climate.txt | `{project_dir}/input/climate.txt` | Tab-separated, header + one row per day, covers simulation period |

## Validation Checks

1. **Row count**: Number of data rows = number of days in simulation period
   - Command: `wc -l climate.txt` minus 1 (header)
   - Expected: (end_date - start_date).days + 1
2. **Temperature range**: All tavg values in [-60, 60] C
   - If values > 100: temperatures are in Kelvin (see dt_005)
3. **Precipitation non-negative**: All prec values >= 0
4. **No NaN/missing**: No empty cells or NaN values
5. **Column count**: Consistent number of tab-separated columns across all rows

## Common Pitfalls

> **PITFALL**: Temperature in Kelvin
> CMFD and ERA5 provide temperature in Kelvin. If fed directly to LDNDC without K->C conversion, all temperature-dependent processes are wrong. LDNDC gives no error.
> **Do this instead**: Check first data row -- if tavg > 100, subtract 273.15.
> See diagnostic triplet dt_005.

> **PITFALL**: Sub-daily precipitation not summed
> VIC forcing uses 3-hourly timesteps (8 per day). Daily precip must be the SUM of all sub-daily values, not a single value. Taking only one value gives 1/8 the correct precipitation.
> See diagnostic triplet dt_014.

> **PITFALL**: Comma-separated instead of tab-separated
> LDNDC requires TAB separation. Comma-separated or space-separated files cause parse errors.
> See diagnostic triplet dt_006.

---

*This skill document is part of the ldndc-knowledge-infrastructure package.*
*Stage 4 of 10 | Tools used: convert_forcing_to_ldndc_climate, validate_climate_file | Related triplets: dt_005, dt_006, dt_014*
