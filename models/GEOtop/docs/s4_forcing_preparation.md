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
| JDfrom0      | GEOtop clock: days since 0001-01-01 + 367 (overrides Date) | days | yes | dt_021 |
| Iprec        | Precipitation intensity (HeaderIPrec) | **mm/h** | yes | dt_004        |
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
   Precipitation:  mm/hr -> mm per record  multiply by dt/3600
   Precipitation:  m/s -> mm per record  multiply by 1000*dt
   Precipitation:  kg/m2/s -> mm per record  multiply by dt (density=1000)
   (dt here = the INPUT record spacing. convert_forcing.py turns a rate into a
   depth per input record first, then moves depth to the --dt grid: hourly
   1 mm/h at --dt 10800 gives 3 mm per 3 h, not 9. When the file is written
   the depth is divided by the --dt length in hours, because HeaderIPrec is an
   intensity in mm/h (keywords.h:437): 3 mm per 3 h is written as 1.0.)
   Radiation:      J/m2 -> W/m2  divide by dt (accumulated -> instantaneous)
   Pressure:       Pa -> mbar  divide by 100
   ```

3. **Format dates** as DD/MM/YYYY hh:mm (European format, NOT American):
   - 2009-10-02T00:00 -> 02/10/2009 00:00
   - If your data uses YYYY-MM-DD, parse and reformat

4. **Set missing values** to exactly -9999 (not NaN, -999, or blank)

4b. **Stamp each record at the END of the interval it covers.** GEOtop uses a
   record stamped t for (t-dt, t] (meteodata.cc:137-245). convert_forcing.py does
   this for every load_forcing source (stamp_rules): CMFD rain is kept; CMFD
   srad/lrad (centred) and temp/pres/shum/wind (instant) become the mean of the
   records at t-3 h and t; MSWX shortwave (centred, checked 2026-10-20) is paired
   the same way; the other MSWX variables and NASA POWER hourly (interval start)
   move one step later; daily records (day D stamped D 00:00) move to D+1 00:00. For a CSV
   pass what a row stamped t holds (dt_026): `--csv-stamp end` (default,
   means/totals over (t-step, t]), `start` (over [t, t+step)) or `instant` (state
   values measured AT t, as most station files are; rain = total since the row
   before). With end/start the state columns must be interval means, or they are
   used step/2 late (1.5 h for 3-hourly data).
   This rule assumes GEOtop's default `LinearInterpolation = 0`: GEOtop does NOT
   interpolate between records, it holds each one over (t-dt, t]
   (parameters.cc:2166, meteo.cc:54 -> time_interp_constant).

5. **Match header names** to HeaderXXX settings in geotop.inpts:
   - Default mapping: Date, JDfrom0, Iprec, WindSp, WindDir, RelHum, AirT, Swglobal, CloudTrans

6. **Temporal interpolation**: GEOtop itself does not interpolate (default
   LinearInterpolation = 0, see 4b), so a 3-hourly meteo file with a 900 s model
   step uses each record for its whole 3 h. To get a finer meteo file, pass a
   smaller --dt: state values are interpolated, precipitation depth is
   distributed uniformly within the 3-hour window.
   When convert_forcing.py upsamples (--dt finer than the input), state values
   are interpolated between interval CENTRES (t - step/2), since each record is
   the mean over its interval.

## Verification

- [ ] Temperature range is reasonable for the location/season (e.g., -30 to +40 C)
- [ ] RelHum is in percent, 0-100 (NOT fraction 0-1)
- [ ] Precipitation is non-negative, in mm/h (HeaderIPrec)
- [ ] JDfrom0 equals Date days since 0001-01-01 + 367 (run_and_score.py check_meteo)
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
| ERA5      | Precip      | m per record   | mm/h         | *1000/(dt/3600)   | dt_004|
| ERA5      | Radiation   | J/m2 (accum)   | W/m2         | /dt               |       |
| ERA5      | Pressure    | Pa             | mbar         | /100              |       |
| CMFD      | Temperature | K              | C            | -273.15           |       |
| CMFD      | Humidity    | kg/kg          | %            | Tetens formula    | dt_005|
| CMFD      | Precip      | kg/m2/s        | mm/h         | *3600             | dt_004|
| CMFD      | Radiation   | W/m2           | W/m2         | 1.0 (no change)   |       |
| Station   | Temperature | C              | C            | 1.0               |       |
| Station   | Humidity    | %              | %            | 1.0               |       |
| Station   | Precip      | mm/hr          | mm/h         | 1.0               | dt_004|

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

CSV input rules (`--source csv`): the time column is read as ISO 8601
(`2009-10-02 00:00`) unless `--date-format` is given (e.g. `'%d/%m/%Y %H:%M'`);
the records around --start..--end must be evenly spaced with no gaps there; every column named in
`--col-map` must exist; `--rh-unit specific` (kg/kg) needs `temp` and `pres`
columns in the col-map (`--pres-unit Pa|hPa`), no standard pressure is assumed.
Output covers exactly `--start` .. `--end` at `--dt`, or the tool stops.
Say what each CSV row stamped t holds: `--csv-stamp end` (default; means/totals over
(t-step, t]), `start` (over [t, t+step), moved one step later; the window is checked
after the move) or `instant` (state values measured AT t: each interval gets the mean
of its two end values, rain = total since the row before, the first row is dropped,
no time stamp may repeat). With end/start the state columns must be interval means.

Expected first lines of output:
```
Date,JDfrom0,Iprec,WindSp,WindDir,RelHum,AirT,Swglobal,CloudTrans
02/10/2009 00:00,734048.000000,0.000000,3.91,6.99,37.63,13.01,0.00,-9999
02/10/2009 01:00,734048.041667,0.000000,3.49,11.28,40.46,13.58,0.00,-9999
```
