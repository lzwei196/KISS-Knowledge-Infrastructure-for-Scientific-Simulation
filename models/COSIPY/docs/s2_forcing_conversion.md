# Stage 2: Forcing Data Conversion

## Purpose

Convert meteorological forcing data from various sources (ERA5, AWS stations, WRF output) into COSIPY's netCDF input format with correct units, dimensions, and variable names.

## Inputs

| Input | Source | Format |
|-------|--------|--------|
| Meteorological data | ERA5 / AWS / WRF | CSV or netCDF |
| Static file | Stage 1 output | netCDF |
| Station metadata | User / config | Lat, lon, altitude |

### Required forcing variables

| Variable | COSIPY name | COSIPY units | ERA5 name | ERA5 units | Conversion |
|----------|-------------|-------------|-----------|------------|------------|
| Air temperature | T2 | K | t2m | K | none (already K) |
| Relative humidity | RH2 | % (0-100) | d2m | K (dewpoint) | Magnus formula |
| Wind speed | U2 | m/s at 2m | u10, v10 | m/s at 10m | log profile correction |
| Shortwave radiation | G | W/m2 | ssrd | J/m2 accumulated | / dt_seconds |
| Air pressure | PRES | hPa | sp | Pa | / 100 |
| Total precipitation | RRR | mm/timestep | tp | m accumulated | * 1000 |
| Cloud cover | N | fraction (0-1) | tcc | fraction (0-1) | none |
| Longwave radiation | LWin | W/m2 | strd | J/m2 accumulated | / dt_seconds |
| Snowfall | SNOWFALL | m snow height | sf | m w.e. | * 1000 / density |

## Outputs

| Output | Path | Format |
|--------|------|--------|
| COSIPY input netCDF | `data/input/<name>.nc` | netCDF4 |

### Output structure
- Dimensions: `(time, lat, lon)`
- Time coordinate: `hours since <reference date>`
- All forcing variables on the same grid as static file

## Procedure

### Using aws2cosipy (built-in)

```bash
cosipy-aws2cosipy \
    -i data/input/Zhadang/Zhadang_ERA5_2009_2018.csv \
    -o data/input/Zhadang/Zhadang_ERA5_2009.nc \
    -s data/static/Zhadang_static.nc \
    -u utilities_config.toml \
    -b "2009-01-01" -e "2009-12-31"
```

### Using KI tool

```bash
python ki/tools/convert_forcing.py \
    --input raw_data.csv \
    --output data/input/forcing.nc \
    --static data/static/static.nc \
    --source era5 \
    --start "2009-01-01" --end "2009-12-31" \
    --lat 30.47 --lon 90.64
```

### Manual conversion steps

1. Read raw data (CSV or netCDF)
2. Apply unit conversions (see table above)
3. Apply lapse rate corrections for elevation difference
4. Resample to hourly if needed
5. Write COSIPY-format netCDF
6. Validate bounds

## Verification

```bash
# Check input file
python -c "
import xarray as xr
ds = xr.open_dataset('data/input/Zhadang/Zhadang_ERA5_2009.nc')
print('Variables:', list(ds.data_vars))
for v in ['T2', 'RH2', 'U2', 'G', 'PRES', 'RRR']:
    if v in ds:
        print(f'{v}: min={float(ds[v].min()):.2f}, max={float(ds[v].max()):.2f}')
ds.close()
"
```

### Expected ranges
| Variable | Min | Max | Red flag |
|----------|-----|-----|----------|
| T2 | 223 K | 316 K | < 100 = likely Celsius |
| RH2 | 0 % | 100 % | < 1.5 = likely fraction |
| U2 | 0 m/s | 50 m/s | > 30 = check height |
| G | 0 W/m2 | 1600 W/m2 | > 2000 = likely J/m2 |
| PRES | 200 hPa | 1080 hPa | > 2000 = likely Pa |
| RRR | 0 mm | 20 mm | > 50 = check temporal unit |
| N | 0 | 1 | > 1.5 = likely % |
| SNOWFALL | 0 m | 0.05 m | > 0.1 = check units |

## Traps

1. **ERA5 radiation is ACCUMULATED J/m2, not instantaneous W/m2**: The most common unit error. ssrd and strd are accumulated over the forecast period. To get W/m2: `W_m2 = J_m2 / dt_seconds`. For hourly ERA5: `W_m2 = J_m2 / 3600`.

2. **ERA5 precipitation is ACCUMULATED meters**: tp is accumulated m of water. For hourly data: `mm/hr = tp * 1000`. For 3-hourly: `mm/hr = tp * 1000 / 3`.

3. **ERA5 wind at 10m, COSIPY expects 2m**: Apply log wind profile: `U2 = U10 * ln(2/z0) / ln(10/z0)`. With z0=0.001m: U2 ~ 0.75 * U10. Skipping this overestimates turbulent fluxes by 30-50%.

4. **Temperature in Celsius causes zero snowfall**: If T2 is -5C instead of 268K, the tanh snow partition function returns 100% rain. No error message — just no snow.

5. **Cloud cover N is fraction (0-1) but RH2 is percentage (0-100)**: This inconsistency is a common source of confusion. N>1 causes extreme longwave radiation.

6. **NaN in glacier cells crashes the model**: COSIPY checks for NaN in every masked grid cell before processing. Fill NaN values before running.

## Example

ERA5 to COSIPY conversion for Zhadang Glacier:
```python
import xarray as xr
import numpy as np

# Read ERA5
era = xr.open_dataset('era5_raw.nc')

# Convert
T2 = era['t2m']                          # already K
RH2 = compute_rh_from_dewpoint(era)      # dewpoint -> %
U2 = compute_u2_from_u10v10(era)         # 10m -> 2m
G = np.maximum(era['ssrd'] / 3600, 0)    # J/m2 -> W/m2
PRES = era['sp'] / 100                   # Pa -> hPa
RRR = np.maximum(era['tp'] * 1000, 0)    # m -> mm
N = np.clip(era['tcc'], 0, 1)            # fraction
```
