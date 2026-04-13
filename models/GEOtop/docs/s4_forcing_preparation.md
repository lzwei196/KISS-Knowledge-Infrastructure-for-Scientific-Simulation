# s4: Meteorological Forcing Preparation

## Purpose

Convert global reanalysis or station meteorological data into GEOtop's `meteoXXXX.txt`
format. This stage contains the highest density of unit-conversion traps -- most silent
model failures originate here.

## Inputs

| Input               | Source                    | Format        | Resolution      |
|---------------------|---------------------------|---------------|-----------------|
| Air temperature     | CMFD, ERA5, MSWX, station| NetCDF/CSV    | Hourly to 3-hr  |
| Precipitation       | CMFD, ERA5, MSWX, station| NetCDF/CSV    | Hourly to 3-hr  |
| Relative humidity   | CMFD, ERA5, MSWX, station| NetCDF/CSV    | Hourly to 3-hr  |
| Wind speed          | CMFD, ERA5, MSWX, station| NetCDF/CSV    | Hourly to 3-hr  |
| Shortwave radiation | CMFD, ERA5, MSWX, station| NetCDF/CSV    | Hourly to 3-hr  |
| Longwave radiation  | CMFD, ERA5 (optional)     | NetCDF/CSV    | Hourly to 3-hr  |

## Outputs

| Output              | File                    | Format    | Notes               |
|---------------------|-------------------------|-----------|---------------------|
| meteoXXXX.txt       | sim_dir/meteo/meteoXXXX.txt | CSV   | One per station     |

### Meteo File Columns

| Column       | Variable                  | Unit           | Required | Trap          |
|--------------|---------------------------|----------------|----------|---------------|
| Date         | Date/time                 | DD/MM/YYYY hh:mm | yes   | dt_006        |
| JDfrom0      | Julian day from year 0    | days           | yes      |               |
| Iprec        | Precipitation             | **mm/step**    | yes      | dt_004        |
| WindSp       | Wind speed                | m/s            | yes      |               |
| WindDir      | Wind direction            | degrees (0-360)| recommended |            |
| RelHum       | Relative humidity         | **% (0-100)**  | yes      | dt_005        |
| AirT         | Air temperature           | **Celsius**    | yes      |               |
| Swglobal     | Global shortwave radiation| W/m2           | yes      |               |
| CloudTrans   | Cloud transmissivity      | 0-1 or -9999   | optional |               |
| LWin         | Incoming longwave         | W/m2           | optional |               |
| DewT         | Dew point temperature     | Celsius        | optional |               |
| AirPress     | Air pressure              | mbar           | optional |               |

## Procedure

1. **Extract data** at simulation point from global gridded product:
   - CMFD: 0.1deg, 3-hourly, 1979-2018 (China)
   - ERA5: 0.25deg, hourly, 1940-present (global)
   - MSWX: 0.1deg, 3-hourly (global)
   - NASA POWER: 0.5deg, hourly (global)

2. **Convert units** (CRITICAL -- see unit trap table below):
   ```
   Temperature:    K -> C      subtract 273.15
   Humidity:       fraction -> %  multiply by 100
   Humidity:       specific -> relative  use Tetens formula
   Precipitation:  mm/hr -> mm/step  multiply by dt/3600
   Precipitation:  m/s -> mm/step  multiply by 1000*dt
   Precipitation:  kg/m2/s -> mm/step  multiply by dt (density=1000)
   Radiation:      J/m2 -> W/m2  divide by dt (accumulated -> instantaneous)
   Pressure:       Pa -> mbar  divide by 100
   ```

3. **Format dates** as DD/MM/YYYY hh:mm (European format, NOT American):
   - 2009-10-02T00:00 -> 02/10/2009 00:00
   - If your data uses YYYY-MM-DD, parse and reformat

4. **Set missing values** to exactly -9999 (not NaN, -999, or blank)

5. **Match header names** to HeaderXXX settings in geotop.inpts:
   - Default mapping: Date, JDfrom0, Iprec, WindSp, WindDir, RelHum, AirT, Swglobal, CloudTrans

6. **Temporal interpolation**: If source is 3-hourly and model time step is 900s,
   interpolate linearly for temperature, humidity, wind, radiation.
   For precipitation, distribute uniformly within the 3-hour window.

## Verification

- [ ] Temperature range is reasonable for the location/season (e.g., -30 to +40 C)
- [ ] RelHum is in percent, 0-100 (NOT fraction 0-1)
- [ ] Precipitation is non-negative, in mm per time step
- [ ] Shortwave radiation is 0 at night, > 0 during day
- [ ] Dates are in DD/MM/YYYY hh:mm format
- [ ] No NaN values -- all missing data is -9999
- [ ] Time series is continuous with no gaps
- [ ] File is comma-separated (not tab or space)

## Unit Trap Table

| Source    | Variable     | Source Unit    | GEOtop Unit  | Conversion Factor | Trap  |
|-----------|-------------|----------------|--------------|-------------------|-------|
| ERA5      | Temperature | K              | C            | -273.15           |       |
| ERA5      | Dewpoint    | K              | C            | -273.15           |       |
| ERA5      | Humidity    | kg/kg (specific)| % (relative) | Tetens formula   | dt_005|
| ERA5      | Precip      | m              | mm/step      | *1000             | dt_004|
| ERA5      | Radiation   | J/m2 (accum)   | W/m2         | /dt               |       |
| ERA5      | Pressure    | Pa             | mbar         | /100              |       |
| CMFD      | Temperature | K              | C            | -273.15           |       |
| CMFD      | Humidity    | kg/kg          | %            | Tetens formula    | dt_005|
| CMFD      | Precip      | mm/hr          | mm/step      | *dt/3600          | dt_004|
| CMFD      | Radiation   | W/m2           | W/m2         | 1.0 (no change)   |       |
| Station   | Temperature | C              | C            | 1.0               |       |
| Station   | Humidity    | %              | %            | 1.0               |       |
| Station   | Precip      | mm/hr          | mm/step      | *dt/3600          | dt_004|

## Traps

| Trap ID | Symptom                                         | Severity |
|---------|-------------------------------------------------|----------|
| dt_004  | Precipitation in wrong units -> 1000x too much/little | silent |
| dt_005  | RelHum as fraction -> model treats 0.5 as 0.5% | silent   |
| dt_006  | MM/DD/YYYY dates -> wrong month parsed          | silent   |
| dt_007  | NaN instead of -9999 -> treated as 0            | silent   |
| dt_016  | Accumulated radiation not deaccumulated          | silent   |

## Example

Converting from ERA5 hourly to GEOtop format:
```bash
python convert_forcing.py \
    --source csv \
    --input era5_point.csv \
    --lat 46.668 --lon 10.579 --elev 1480 \
    --start "02/10/2009 00:00" --end "02/11/2009 00:00" \
    --dt 3600 \
    --temp-unit K --rh-unit fraction --precip-unit mm_hr \
    --output sim/meteo/meteo0001.txt
```

Expected first lines of output:
```
Date,JDfrom0,Iprec,WindSp,WindDir,RelHum,AirT,Swglobal,CloudTrans
02/10/2009 00:00,734047.0000,0.0000,3.91,6.99,37.63,13.01,0.00,-9999
02/10/2009 01:00,734047.0417,0.0000,3.49,11.28,40.46,13.58,0.00,-9999
```
