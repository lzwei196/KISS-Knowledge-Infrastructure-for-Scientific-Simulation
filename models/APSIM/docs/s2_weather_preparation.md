# S2 — Weather Data Preparation

## Purpose

Convert raw weather/climate forcing data into APSIM's custom .met text format
with correct units, header metadata, and column structure. This is the most
error-prone stage due to unit conversion traps.

## Inputs

| Input                | Format         | Source Units         | Source              |
|----------------------|---------------|----------------------|---------------------|
| Solar radiation      | NetCDF / CSV  | W/m² or J/m²/day    | ERA5, CMFD, MSWX   |
| Max temperature      | NetCDF / CSV  | K or °C              | ERA5, CMFD          |
| Min temperature      | NetCDF / CSV  | K or °C              | ERA5, CMFD          |
| Rainfall             | NetCDF / CSV  | mm/3hr, m/day, mm/d | ERA5, CMFD          |
| Vapor pressure       | NetCDF / CSV  | kPa or hPa           | ERA5                |
| Wind speed           | NetCDF / CSV  | m/s                  | ERA5                |
| Site coordinates     | numeric       | decimal degrees       | S0 configuration    |

## Outputs

| Output               | Format     | Description                          |
|----------------------|-----------|--------------------------------------|
| `site.met`           | APSIM .met| Daily weather file with correct units|
| Conversion report    | JSON      | Summary with tav, amp, warnings      |

## Procedure

1. **Run the conversion tool**:
   ```bash
   python convert_met.py --input era5_dalby.nc --output dalby.met \
       --lat -27.18 --lon 151.26 --station "Dalby" --source era5 \
       --start 1990-01-01 --end 2020-12-31
   ```

2. **Unit conversions** (CRITICAL — handled automatically):

   | Variable    | Source → APSIM                    | Factor              |
   |-------------|----------------------------------|---------------------|
   | Radiation   | W/m² → MJ/m²/day                | × 0.0864            |
   | Radiation   | J/m²/day → MJ/m²/day            | ÷ 1,000,000         |
   | Temperature | K → °C                           | − 273.15            |
   | Rainfall    | m/day → mm/day                   | × 1000              |
   | Rainfall    | mm/3hr → mm/day                  | Sum 8 intervals     |
   | Vap. press. | kPa → hPa                        | × 10                |

3. **Header metadata**: The tool computes `tav` and `amp` from the data:
   - `tav` = annual average of daily mean temperature
   - `amp` = range between warmest and coolest monthly means
   - Both are REQUIRED by APSIM's soil temperature model

4. **Quality checks**: Review the conversion report for warnings about
   out-of-range values.

## Verification

- [ ] Radiation values between 0 and 35 MJ/m²/day (typical)
- [ ] Temperature in °C, not K (check values < 100)
- [ ] Rainfall ≥ 0, no negative values
- [ ] tav and amp present in header
- [ ] Column headers match APSIM convention exactly
- [ ] Year and day-of-year are integers
- [ ] No missing data gaps (APSIM requires continuous daily records)

## Traps

- **Radiation in W/m² instead of MJ/m²/day** (dt_001): This is the #1 error.
  ERA5 `ssrd` is in J/m²/day (divide by 1e6). CMFD `srad` is often W/m²
  (multiply by 0.0864). If radiation is 100-400 instead of 5-30, it's W/m².
  Result: biomass is 10-50× too high.

- **Missing tav/amp** (dt_002): Without these, APSIM's CERES soil temperature
  model uses defaults that may be wildly wrong for the location. Germination
  and root growth depend on soil temperature.

- **Temperature in Kelvin** (dt_007): If maxt shows values like 300, it's
  still in Kelvin. Must subtract 273.15.

- **Rainfall in wrong temporal resolution** (dt_011): CMFD rainfall at
  mm/3hr must be summed to daily. Forgetting this gives 1/8 of actual rain.

- **Day-of-year vs date**: APSIM .met uses integer day-of-year (1-366),
  NOT date strings. Leap years have day 366.

## Example

Input: ERA5 NetCDF for Dalby (ssrd in J/m²/day, t2m in K, tp in m/day)

Output .met file:
```
[weather.met.weather]
!station name = Dalby
latitude = -27.18  (DECIMAL DEGREES)
longitude = 151.26  (DECIMAL DEGREES)
tav =  19.09 (oC) ! annual average ambient temperature
amp =  14.63 (oC) ! annual amplitude in mean monthly temperature

    year       day      radn      maxt      mint      rain
      ()        ()  (MJ/m^2)      (oC)      (oC)      (mm)
    2000         1      24.0      29.4      18.6       0.0
    2000         2      25.0      31.6      17.2       0.0
    2000         3      18.5      28.3      15.9      12.5
```
