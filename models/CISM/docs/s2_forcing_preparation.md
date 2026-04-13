# Stage 2: Forcing Preparation

## Purpose

Convert climate/reanalysis data into CISM-compatible forcing fields.
CISM requires surface mass balance (acab, m/yr) and surface air temperature
(artm, deg C). Climate datasets typically provide precipitation and
temperature in different units that must be converted.

## Inputs

| Input | Source | Required |
|-------|--------|----------|
| Temperature data | ERA5, CMFD, MSWX, RACMO | Yes |
| Precipitation data | ERA5, CMFD, MSWX, RACMO | Yes |
| Grid specification | s0 (ewn, nsn, dew, dns) | Yes |
| PDD factors | Literature or calibration | For PDD SMB |

## Outputs

| Output | Format | Used by |
|--------|--------|---------|
| forcing.nc | NetCDF (artm, acab) | s1 or s3 ([CF forcing]) |

## Procedure

1. **Temperature conversion**:
   - Kelvin to Celsius: T_C = T_K - 273.15
   - Fahrenheit to Celsius: T_C = (T_F - 32) * 5/9
   - Apply lapse rate correction if needed: T_corrected = T + dT/dz * (z_model - z_data)

2. **Precipitation to SMB conversion**:

   **Units first** (dt_001 critical):
   | From | To m/yr | Factor |
   |------|---------|--------|
   | mm/day | m/yr | * 0.36525 |
   | kg/m^2/s | m/yr | * 31536 |
   | mm/yr | m/yr | / 1000 |
   | m/day | m/yr | * 365.25 |

   **Ice equivalent**: Divide water-equivalent by (rhoi/rhow) = 0.917

   **PDD ablation** (if using degree-day scheme):
   - PDD = sum(max(T_daily, 0)) over year (degree-days)
   - Snow melt = min(PDD * ddf_snow, accumulation)
   - Ice melt = max(0, PDD - snow_melt/ddf_snow) * ddf_ice
   - SMB = accumulation - snow_melt - ice_melt

   Typical PDD factors:
   - ddf_snow: 0.003 m/degC/day (3 mm/degC/day)
   - ddf_ice: 0.008 m/degC/day (8 mm/degC/day)

3. **Geothermal heat flux** (if converting from global datasets):
   - Common datasets provide mW/m^2 (positive upward)
   - CISM requires W/m^2, **negative = upward** (dt_003)
   - Conversion: bheatflx_cism = -ghf_data / 1000.0

4. **Regridding**:
   - Climate data is typically coarser than ice sheet grid
   - Use bilinear interpolation for smooth fields (artm)
   - Use conservative remapping for fluxes (acab)

5. **Write to NetCDF**: Either as static fields in input.nc or as
   time-varying forcing in a separate [CF forcing] file.

## Verification

- [ ] artm is in degrees Celsius (range: -60 to +20 for ice sheets)
- [ ] acab is in m/yr ice equivalent (range: -30 to +5 for ice sheets)
- [ ] No NaN values in output fields
- [ ] Spatial patterns make physical sense (colder at elevation, positive SMB in interior)
- [ ] If bheatflx provided, values are negative (upward)

## Traps

| ID | Trap | Prevention |
|----|------|-----------|
| dt_001 | Precipitation in mm/yr not m/yr | Check max(abs(acab)) < 50 m/yr |
| dt_003 | Geothermal positive (should be negative) | Auto-negate in converter |
| dt_008 | Basal melt in m/s not m/yr | Apply scyr factor if needed |
| dt_013 | Velocity units mixed up in forcing | Forcing has no velocities -- N/A |

## Example

```bash
# Uniform forcing (for testing)
python tools/convert_forcing_to_cism.py --source uniform \
    --artm_value -15.0 --acab_value 0.3 \
    --grid_ewn 31 --grid_nsn 31 --grid_dew 2000 --output forcing.nc

# From ERA5 with PDD
python tools/convert_forcing_to_cism.py --source era5 \
    --input era5_monthly.nc --temp_unit K --precip_unit mm/day \
    --pdd_factor_snow 0.003 --pdd_factor_ice 0.008 \
    --grid_ewn 301 --grid_nsn 561 --grid_dew 5000 --output greenland_smb.nc
```
