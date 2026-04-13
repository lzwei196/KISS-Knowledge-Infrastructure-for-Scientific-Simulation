# Stage 2: Atmospheric Forcing Preparation

## Purpose

Convert atmospheric reanalysis or coupled-model boundary conditions to MOM6 surface
forcing format. This stage produces the wind stress, heat fluxes, freshwater fluxes,
and radiation fields that drive the ocean model at the air-sea interface.

## Inputs

| Dataset   | Variables                       | Native Units                    |
|-----------|---------------------------------|---------------------------------|
| ERA5      | u10, v10, t2m, d2m, msdwswrf, msdwlwrf, mtpr, msl | m/s, K, W/m², kg/m²/s, Pa |
| JRA55-do  | uas, vas, tas, rsds, rlds, prra, prsn, huss, psl   | m/s, K, W/m², kg/m²/s, Pa |
| CORE/CIAF | U_10, V_10, T_10, Q_10, SWDN, LWDN, RAIN, SNOW    | m/s, K, W/m², kg/m²/s     |

## Outputs

| Variable | MOM6 Name | Units      | Sign Convention         |
|----------|-----------|------------|-------------------------|
| Wind stress (zonal)     | taux   | Pa       | + eastward              |
| Wind stress (meridional)| tauy   | Pa       | + northward             |
| Shortwave radiation     | SW     | W/m²     | + into ocean (downward) |
| Longwave radiation      | LW     | W/m²     | + into ocean (net)      |
| Latent heat flux        | laten  | W/m²     | + into ocean            |
| Sensible heat flux      | sens   | W/m²     | + into ocean            |
| Evaporation             | evap   | kg/m²/s  | negative (leaves ocean) |
| Precipitation           | precip | kg/m²/s  | positive (enters ocean) |
| Air temperature         | t_air  | degC     |                         |
| Specific humidity       | q_air  | kg/kg    |                         |
| Sea level pressure      | slp    | Pa       |                         |

## Procedure

1. **Download reanalysis** for the simulation period
2. **Run forcing converter**:
   ```bash
   python forcing_converter.py era5_2020.nc \
     --output INPUT/forcing_2020.nc \
     --dataset era5 \
     --json-report forcing_report.json
   ```
3. **Configure MOM_input**:
   ```fortran
   WIND_CONFIG = "file"
   WIND_FILE = "forcing_2020.nc"
   BUOY_CONFIG = "file"
   LONGWAVE_FILE = "forcing_2020.nc"
   SHORTWAVE_FILE = "forcing_2020.nc"
   PRECIP_FILE = "forcing_2020.nc"
   ```
4. **Verify temporal coverage** matches simulation period in input.nml

## Verification

- [ ] All forcing variables have correct MOM6 sign convention
- [ ] Temperature is in degC (not Kelvin) — check range is [-80, 60]
- [ ] Shortwave radiation is non-negative (no negative SW values)
- [ ] Precipitation is non-negative
- [ ] Evaporation is non-positive (negative = water leaving ocean)
- [ ] Wind stress magnitude is reasonable (typically < 1 Pa, max ~3 Pa in storms)
- [ ] Time axis covers full simulation period without gaps
- [ ] Spatial coverage matches model grid domain

## Traps

| Trap ID | Symptom                    | Cause                         | Fix                          |
|---------|----------------------------|-------------------------------|------------------------------|
| dt_001  | Unrealistic SST (>100 degC)| Temperature left in Kelvin    | Subtract 273.15              |
| dt_008  | Ocean cools when it should warm | Heat flux sign convention reversed | Negate flux values   |
| dt_009  | Extreme precipitation      | Units mm/day not converted    | Divide by 86400              |
| dt_012  | Persistent negative SW     | Shortwave sign error          | Take absolute value, clip <0 |
| dt_013  | Double-counted LW          | Using downwelling instead of net LW | Subtract upwelling LW  |

## Example

```python
from forcing_converter import validate_input, process_forcing, validate_output

info = validate_input("era5_monthly_2020.nc", "era5")
process_forcing(info, "INPUT/forcing_2020.nc")
report = validate_output("INPUT/forcing_2020.nc")

# Quick check: temperature should be in degC range
assert report["variables"]["t_air"]["min"] > -80, "Temperature may still be in Kelvin!"
assert report["variables"]["t_air"]["max"] < 60, "Temperature suspiciously high!"
```
