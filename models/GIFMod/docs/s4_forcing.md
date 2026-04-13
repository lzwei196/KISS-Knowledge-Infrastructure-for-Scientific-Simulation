# Stage 4: Meteorological Forcing

## Purpose

Convert meteorological data from global reanalysis products (ERA5, CMFD, MSWX,
NASA POWER) or local weather stations into GIFMod time series format with
correct units.

## Inputs

| Input          | Source        | Common Unit     | Required |
|----------------|---------------|-----------------|----------|
| Precipitation  | Met station   | mm/hr or mm/day | Yes      |
| Temperature    | Met station   | Celsius         | Yes      |
| Humidity       | Met station   | % or fraction   | Depends  |
| Wind speed     | Met station   | m/s             | Depends  |
| Solar radiation| Met station   | W/m^2           | Depends  |
| Start date     | User          | YYYY-MM-DD      | Yes      |

## Outputs

| Output         | Format | GIFMod Unit   |
|----------------|--------|---------------|
| Precipitation  | CSV    | m/day         |
| Temperature    | CSV    | Celsius       |
| Humidity       | CSV    | fraction 0-1  |
| Wind speed     | CSV    | m/s           |
| Time           | CSV    | days from t0  |

## Procedure

1. **Read input data**: Parse CSV/NetCDF with datetime column and met variables.

2. **Convert time axis**: Transform datetime to fractional days from simulation
   start date. GIFMod uses day-based time internally.

3. **Convert precipitation** (CRITICAL - dt_002):
   - mm/hr -> m/day: multiply by 0.024
   - mm/day -> m/day: multiply by 0.001
   - in/hr -> m/day: multiply by 0.6096
   - cm/day -> m/day: multiply by 0.01

4. **Convert temperature** (dt_008):
   - Fahrenheit -> Celsius: (F - 32) * 5/9
   - Kelvin -> Celsius: K - 273.15

5. **Convert humidity**:
   - Percent -> fraction: divide by 100
   - If vapor pressure (hPa), convert using Tetens formula:
     `RH = VP / (6.1078 * exp(17.27 * T / (T + 237.3)))`

6. **Validate converted values**:
   - Precip >= 0 and typically < 0.5 m/day (500 mm/day extreme)
   - Temperature: -60 to +60 C
   - Humidity: 0.0 to 1.0
   - Wind: >= 0 m/s

7. **Check temporal consistency**:
   - No gaps in time series
   - Monotonically increasing time values
   - Consistent timestep interval

## Verification

- [ ] Precipitation in m/day (values typically 0-0.05 for normal rain)
- [ ] Temperature in Celsius (range check for region)
- [ ] Humidity as fraction (max value <= 1.0)
- [ ] Time axis starts at 0.0 (or specified offset)
- [ ] No NaN or missing values in output

## Traps

| ID     | Trap                              | Error Factor | Consequence                    |
|--------|-----------------------------------|--------------|--------------------------------|
| dt_002 | Precip mm/day entered as m/day    | 1000x high   | Catastrophic flooding          |
| dt_008 | Temperature in F not C            | ~1.8x offset | Wrong evaporation/reaction     |
| --     | Humidity as percent not fraction   | 100x high    | RH > 1.0 → nonsensical ET     |
| --     | Time in hours not days            | 24x offset   | Compressed simulation          |

## Example

```bash
python convert_forcing.py \
  --input weather_station.csv \
  --output gifmod_met.csv \
  --precip-unit mm/hr \
  --temp-unit celsius \
  --humidity-unit percent \
  --wind-unit m/s \
  --start-date 2020-06-01
```

Input format:
```csv
datetime,precip,temperature,humidity,wind_speed
2020-06-01 00:00:00,2.5,22.3,75,3.1
2020-06-01 01:00:00,1.2,21.8,78,2.9
```

Output format:
```csv
Time,Precipitation,Temperature,Humidity,WindSpeed
0.000000,0.06000000,22.30,0.7500,3.10
0.041667,0.02880000,21.80,0.7800,2.90
```
