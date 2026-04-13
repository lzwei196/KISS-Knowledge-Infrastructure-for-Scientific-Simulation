# S1: Data Preparation

## Purpose

Gather and convert meteorological forcing data and boundary condition time series
into OpenHydroQual-compatible CSV format. This stage ensures all input data uses
OHQ's internal unit system before model construction.

## Inputs

| Data Type          | Common Source       | Raw Format            | Raw Unit              |
|--------------------|---------------------|-----------------------|-----------------------|
| Temperature        | ERA5, weather stn   | CSV with dates        | K or C                |
| Wind speed         | ERA5, weather stn   | CSV with dates        | m/s or km/h           |
| Solar radiation    | ERA5, NASA POWER    | CSV with dates        | W/m^2 or MJ/m^2/day  |
| Relative humidity  | ERA5, weather stn   | CSV with dates        | % or fraction         |
| Precipitation      | ERA5, gauge          | CSV with dates        | mm/hr or mm/day       |
| Inflow hydrograph  | Gauging station     | CSV (time, Q)         | m^3/s or m^3/day      |
| Constituent loads  | Lab analysis        | CSV (time, mass rate) | g/day or mg/L         |

## Outputs

| File                   | Format       | Unit             | Description              |
|------------------------|--------------|------------------|--------------------------|
| Temperature_ohq.csv    | time,value   | days, Celsius    | Air temperature          |
| Wind_ohq.csv           | time,value   | days, m/s        | Wind speed at z2 height  |
| Solar_ohq.csv          | time,value   | days, W/m^2      | Shortwave radiation      |
| Humidity_ohq.csv       | time,value   | days, fraction   | Relative humidity 0-1    |
| inflow.txt             | time,value   | days, m^3/day    | Inflow time series       |
| *_loading.txt          | time,value   | days, g/day      | Constituent mass loads   |

## Procedure

1. **Identify data sources**: Determine what forcing variables are needed for
   the model domain. A Pond model with Penman ET needs all four meteorological
   variables. A simple groundwater model may only need recharge.

2. **Download or extract raw data**: Get CSV files covering the simulation period.

3. **Run the converter**:
   ```bash
   python ki/tools/convert_forcing.py \
     --input-dir ./raw_data/ \
     --output-dir ./forcing/ \
     --temp-file temp_raw.csv --temp-unit kelvin \
     --wind-file wind_raw.csv --wind-unit km/h \
     --solar-file solar_raw.csv --solar-unit MJ/m2/day \
     --humidity-file rh_raw.csv --rh-unit percent \
     --time-unit date --start-date 2010-01-01
   ```

4. **Verify conversion**: Check that output ranges are physically reasonable.

5. **Copy to model directory**: Place converted files in the same directory as
   the .ohq input file (OHQ resolves paths relative to the working folder).

## Verification

- Temperature range: -40 to +50 C is typical globally
- Wind speed: 0 to 30 m/s for normal conditions
- Solar radiation: 0 to 1200 W/m^2 (daytime peak)
- Relative humidity: 0.0 to 1.0
- Precipitation: >= 0
- Inflow: >= 0

Check output JSON for warnings about out-of-range values.

## Traps

| Trap                                | Impact   | Prevention                        |
|-------------------------------------|----------|-----------------------------------|
| RH as percentage (0-100) not (0-1)  | Silent   | Use --rh-unit percent flag        |
| Solar in MJ/m^2/day not W/m^2       | Silent   | Use --solar-unit MJ/m2/day       |
| Wind in km/h not m/s                | Silent   | Use --wind-unit km/h             |
| Temperature in K not C              | Silent   | Use --temp-unit kelvin           |
| Time in hours not days              | Silent   | Use --time-unit hours            |
| Flow in m^3/s not m^3/day           | Silent   | Multiply by 86400                |
| Missing time gaps                   | Degraded | Check for monotonic time column  |

## Example

Converting ERA5 data for a wet pond simulation (2010-2012):

```bash
# ERA5 data comes in: T(K), Wind(m/s), Solar(W/m^2), RH(fraction)
python ki/tools/convert_forcing.py \
  --input-dir /data/era5/ \
  --output-dir Examples/Wet_pond/ \
  --temp-file era5_t2m.csv --temp-unit kelvin \
  --wind-file era5_wind.csv \
  --solar-file era5_ssrd.csv \
  --humidity-file era5_rh.csv \
  --time-unit date --start-date 2010-01-01

# Verify
head -5 Examples/Wet_pond/Temperature_ohq.csv
# Expected: 0.000000,15.200000 (day 0, ~15 C)
```
