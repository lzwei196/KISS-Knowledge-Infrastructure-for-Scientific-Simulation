# Skill: Meteorological Forcing Data Preparation

## Purpose

Convert raw meteorological station data or gridded reanalysis products into the format
required by openAMUNDSEN. This is the most error-prone stage because of unit conversions.
Seven of the eighteen diagnostic triplets (dt_001–dt_007) relate to this stage.

## Inputs

| Input | Format | Unit | Required |
|-------|--------|------|----------|
| Air temperature | Time series | **K** (Kelvin) | Yes |
| Precipitation | Time series | **kg m⁻²** per timestep | Yes |
| Relative humidity | Time series | **%** (0–100) | Yes |
| Shortwave radiation | Time series | **W m⁻²** | Yes |
| Wind speed | Time series | **m s⁻¹** | Yes |
| Wind direction | Time series | degrees | No |
| Wind gust speed | Time series | m s⁻¹ | No |
| Cloud fraction | Time series | % (0–100) | No |
| Station metadata | CSV or NetCDF attrs | lon, lat (°), alt (m) | Yes |

## Outputs

### CSV Format
Per-station CSV files + `stations.csv` metadata:

**Station data CSV** (e.g., `station_A.csv`):
```csv
date,temp,precip,rel_hum,sw_in,wind_speed
2020-10-01 00:00,271.5,0.0,85.2,0.0,2.1
2020-10-01 01:00,271.2,0.3,87.1,0.0,1.8
```

**stations.csv**:
```csv
id,name,x,y,alt
station_A,Station Alpha,11.0765,47.1234,2100
```

Note: x/y in stations.csv are in the CRS specified by `input_data.meteo.crs` (typically WGS84 lon/lat).

### NetCDF Format
Per-station NetCDF with CF-1.6 conventions:
- Variables: `tas` (K), `pr` (kg m⁻² s⁻¹), `hurs` (%), `rsds` (W m⁻²), `wss` (m s⁻¹)
- Attributes: `alt`, `lat`, `lon`, `station_name`

**CRITICAL**: NetCDF `pr` units are kg m⁻² s⁻¹ (rate), auto-converted by the model.
CSV `precip` units are kg m⁻² per timestep (accumulation). Mixing these up is dt_002.

## Procedure

### Step 1: Identify Source Data Units

Before any processing, document the native units of your data source:

| Source | Temp | Precip | RH | SW | Wind |
|--------|------|--------|-----|-----|------|
| ERA5 | K | m (accum) | % | J m⁻² (accum) | m/s |
| MSWX | °C | mm/day | % | W m⁻² | m/s |
| CMFD | K | mm/hr | % | W m⁻² | m/s |
| Local station | °C | mm/h | % | W m⁻² | m/s |

### Step 2: Apply Unit Conversions

Use `convert_meteo_forcing.py` or apply manually:

| Variable | From | To | Conversion |
|----------|------|----|------------|
| temp | °C | K | + 273.15 |
| temp | °F | K | (°F - 32) × 5/9 + 273.15 |
| precip | mm/day | kg m⁻² per hour | ÷ 24 |
| precip | mm/3h | kg m⁻² per 3h | No change (mm = kg m⁻²) |
| precip | kg m⁻² s⁻¹ | kg m⁻² per hour | × 3600 |
| precip | m (ERA5) | kg m⁻² per step | × 1000 |
| rel_hum | fraction (0-1) | % | × 100 |
| sw_in | J m⁻² (ERA5 accum) | W m⁻² | ÷ timestep_seconds |
| sw_in | MJ m⁻² day⁻¹ | W m⁻² | ÷ 0.0864 |
| sw_in | kJ m⁻² h⁻¹ | W m⁻² | ÷ 3.6 |
| wind | km/h | m/s | ÷ 3.6 |

### Step 3: Quality Control

openAMUNDSEN applies default input filters that **silently replace** out-of-range values with NaN:

| Variable | Min | Max | Effect of NaN |
|----------|-----|-----|---------------|
| temp | 200 K | 330 K | Interpolation fails |
| rel_hum | 1% | 100% | Vapor pressure wrong |
| precip | 0 | ∞ | Negative precip removed |
| wind_speed | 0 m/s | 50 m/s | Calm wind clipped (min 0.1 at runtime) |
| sw_in | 0 | 1500 W m⁻² | Excess radiation removed |

**If your Celsius temperatures are -40 to +35°C, they will ALL be set to NaN by the
200–330 K filter!** This is the #1 silent error (dt_001).

### Step 4: Validate Converted Data

Run the validation checks:
```python
python convert_meteo_forcing.py --input-dir ./raw/ --output-dir ./input/meteo/ \
  --source station_csv --temp-unit celsius --precip-unit mm_per_day --rh-unit percent
```

Check the validation output for warnings about unrealistic ranges.

### Step 5: Configure Meteo Input in YAML

```yaml
input_data:
  meteo:
    dir: ./input/meteo
    format: csv          # or netcdf
    crs: "epsg:4326"     # CRS of station coordinates in stations.csv
    bounds: grid          # use only stations within grid extent
```

## Verification

1. Plot each variable for each station — look for sudden jumps or flat lines
2. Check temperature range: should be ~240–310 K for alpine sites
3. Check precipitation: hourly values rarely exceed 20 kg m⁻² (mm)
4. Check wind speed: values > 30 m/s are rare outside hurricanes
5. Check shortwave: daytime peaks ~800–1100 W m⁻², must be 0 at night
6. Verify stations.csv coordinates plot on the DEM

## Traps

| Trap | Symptom | Fix | Diagnostic |
|------|---------|-----|------------|
| Celsius instead of Kelvin | All temp NaN after filter | Add 273.15 | dt_001 |
| Precip rate vs accumulation | 24x or 3600x over/under snow | Match timestep | dt_002 |
| RH as fraction | All humidity NaN (filter min=1%) | Multiply by 100 | dt_003 |
| SW in energy not power | Radiation way too high/low | Divide by seconds | dt_004 |
| Wind in km/h | Precip correction 3.6x off | Divide by 3.6 | dt_005 |
| Cloud fraction 0-1 | Auto-conversion fragile | Multiply by 100 manually | dt_006 |
| NetCDF precip missing units attr | No auto-conversion of rate | Set units="kg m-2 s-1" | dt_007 |
| Station coords in wrong CRS | Stations outside grid | Set meteo.crs correctly | dt_014 |

## Example

Converting MSWX daily data (°C, mm/day) to openAMUNDSEN hourly format:

```python
python convert_meteo_forcing.py \
  --input-dir ./mswx_data/ \
  --output-dir ./input/meteo/ \
  --source station_csv \
  --timestep h \
  --temp-unit celsius \
  --precip-unit mm_per_day \
  --rh-unit percent \
  --sw-unit wm2 \
  --wind-unit ms
```
