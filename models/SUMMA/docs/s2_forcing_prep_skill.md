# Forcing Data Preparation -- Skill Document

> **Stage ID**: s2_forcing_prep
> **Pipeline order**: 2 of 7
> **Depends on**: s1_domain_setup

## Purpose

Convert meteorological forcing data into SUMMA's NetCDF format with correct variable names, units, and dimensions. SUMMA requires 7 forcing variables, all at the same temporal resolution. Incorrect unit conversions here are the #1 source of silent errors -- the model runs fine but produces scientifically meaningless output.

## Prerequisites

Before starting this stage, verify:

- [ ] Local attributes NetCDF exists from Stage 1 (`attributes.nc`)
- [ ] VIC forcing files exist (from HydroCraft forcing preparation)
- [ ] Know the forcing temporal resolution (3-hourly = 10800s, hourly = 3600s)
- [ ] Know the forcing source (CMFD, MSWX, or NASA POWER)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| vic_forcing_dir | directory | HydroCraft VIC forcing | Directory of VIC ASCII forcing files |
| attributes_nc | file | Stage 1 | SUMMA local attributes NetCDF |
| start_year | value | user | Start year of forcing period |
| end_year | value | user | End year of forcing period |
| data_step | value | derived | Time step in seconds (10800 or 3600) |

## CRITICAL: Unit Conversion Table

| Variable | VIC Unit | SUMMA Unit | Conversion | If Wrong (silent error) |
|----------|----------|------------|------------|-------------------------|
| Precipitation | mm/timestep | kg m-2 s-1 | divide by DATA_STEP | Runoff 3-8x wrong |
| Temperature | Celsius | Kelvin | add 273.15 | Energy balance fails |
| Shortwave radiation | W/m2 | W m-2 | none | -- |
| Longwave radiation | W/m2 | W m-2 | none | -- |
| Wind speed | m/s | m s-1 | none | -- |
| Air pressure | kPa | Pa | multiply by 1000 | ET 100x wrong, NaN |
| Specific humidity | kg/kg | g/g | none (same ratio) | -- |

## Procedure

### Step 1: Identify VIC forcing format

```bash
ls outputs/<run>/vic_temp/forcing/forcing_final/ | head -5
head -2 outputs/<run>/vic_temp/forcing/forcing_final/<first_file>
wc -l outputs/<run>/vic_temp/forcing/forcing_final/<first_file>
```

**Expected result**: ASCII files with 7-8 columns, rows per timestep. Count rows per year: 2920 (3-hourly, non-leap) or 8760 (hourly, non-leap).

### Step 2: Convert VIC forcing to SUMMA format

```bash
python tools/s2_forcing_prep/convert_vic_forcing_to_summa.py \
  --vic_forcing_dir outputs/<run>/vic_temp/forcing/forcing_final/ \
  --attributes_nc outputs/<run>/summa_settings/attributes.nc \
  --output_dir outputs/<run>/summa_forcing/ \
  --start_year <start> --end_year <end> \
  --data_step 10800 \
  --vic_prefix "<basin>_0.25deg_"
```

**Expected result**: One NetCDF file per year in `summa_forcing/`, plus `forcingFileList.txt`.

**If this fails**: See diagnostic triplet dt_005 (hruId mismatch).

### Step 3: Validate forcing units

```bash
python -c "
from netCDF4 import Dataset
ds = Dataset('outputs/<run>/summa_forcing/forcing_<year>.nc')
import numpy as np
for var in ['pptrate', 'airtemp', 'SWRadAtm', 'LWRadAtm', 'windspd', 'airpres', 'spechum']:
    vals = ds.variables[var][:]
    print(f'{var}: mean={np.nanmean(vals):.6e}, min={np.nanmin(vals):.4e}, max={np.nanmax(vals):.4e}, units={ds.variables[var].units}')
ds.close()
"
```

**Expected ranges** (temperate climate):
| Variable | Expected Mean | Red Flag |
|----------|--------------|----------|
| pptrate | 1e-5 to 1e-4 kg/m2/s | > 1e-3 or < 1e-7 |
| airtemp | 275-295 K | < 200 or > 320 |
| SWRadAtm | 100-250 W/m2 | negative values |
| LWRadAtm | 250-400 W/m2 | < 100 or > 500 |
| windspd | 1-5 m/s | negative values |
| airpres | 80000-105000 Pa | < 1000 (still in kPa!) |
| spechum | 0.002-0.015 g/g | > 1 (still in g/kg!) |

**If values are outside expected ranges**: See diagnostic triplets dt_003, dt_004, dt_012.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| Forcing NetCDFs | `outputs/<run>/summa_forcing/forcing_YYYY.nc` | One per year, all 7 vars present |
| Forcing file list | `outputs/<run>/summa_forcing/forcingFileList.txt` | Lists all forcing files |

## Validation Checks

1. **All 7 variables present**: `ncdump -h forcing.nc | grep -c 'pptrate\|airtemp\|SWRadAtm\|LWRadAtm\|windspd\|airpres\|spechum'` should return 7.
2. **Time dimension correct**: For 3-hourly, 365 days = 2920 steps. `ncdump -h forcing.nc | grep 'time ='`
3. **HRU IDs match attributes**: Compare hruId in forcing and attributes files. See dt_005.
4. **No fill values in data**: Check for -9999 or NaN values. See dt_013.

## Common Pitfalls

> **PITFALL**: Dividing precipitation by 86400 instead of 10800 for 3-hourly data.
> This makes precipitation 8x too low. Runoff will be near-zero. See dt_003.

> **PITFALL**: Forgetting to multiply pressure by 1000 (kPa to Pa).
> SUMMA energy balance fails, soil temperatures diverge, then NaN. See dt_004.

> **PITFALL**: Reusing forcing files from a different domain setup.
> hruId mismatch causes immediate crash. Always regenerate after changing GRU/HRU structure. See dt_005.

---

*This skill document is part of the hydrocraft-summa knowledge infrastructure.*
*Stage 2 of 7 | Tools used: convert_vic_forcing_to_summa | Related triplets: dt_003, dt_004, dt_005, dt_012, dt_013*
