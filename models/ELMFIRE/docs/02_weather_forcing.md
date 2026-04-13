# Stage 2: Weather Forcing Preparation

## Purpose

Convert weather observations or gridded forecasts into ELMFIRE-compatible GeoTIFF rasters for wind speed, wind direction, and dead fuel moisture content. This stage contains the highest-risk unit conversions in the entire pipeline.

## Inputs

| Input | Source | Format | Units |
|-------|--------|--------|-------|
| Wind speed | RAWS, ASOS, HRRR, GFS | CSV or NetCDF | m/s at 10 m (typical) |
| Wind direction | Same | CSV or NetCDF | degrees (convention varies) |
| 1-hr fuel moisture | Nelson model, NFDRS, observation | Raster or scalar | percent or fraction |
| 10-hr fuel moisture | Nelson model, NFDRS | Raster or scalar | percent or fraction |
| 100-hr fuel moisture | Nelson model, NFDRS | Raster or scalar | percent or fraction |
| Live herbaceous moisture | Observation, NDVI-derived | Scalar | percent |
| Live woody moisture | Observation, seasonal lookup | Scalar | percent |

## Outputs

| Output file | Variable | Type | Units |
|-------------|----------|------|-------|
| `ws.tif` | Wind speed | Float32 | mph at 20 ft |
| `wd.tif` | Wind direction | Float32 | degrees, met convention (FROM) |
| `m1.tif` | 1-hr dead fuel moisture | Float32 | percent (0–30+) |
| `m10.tif` | 10-hr dead fuel moisture | Float32 | percent (0–30+) |
| `m100.tif` | 100-hr dead fuel moisture | Float32 | percent (0–30+) |
| `elmfire.data` | Namelist configuration | Text | Fortran namelist |

For time-varying weather, multi-band rasters are used:
- Band 1 = time step 0, Band 2 = time step DT_METEOROLOGY, etc.

## Procedure

### Step 1: Convert wind speed to mph at 20 ft

```python
# From m/s at 10 m:
ws_mph_20ft = ws_ms_10m * 2.237 * 1.15  # 2.237 m/s→mph, 1.15 height adjustment

# From knots at 10 m:
ws_mph_20ft = ws_knots * 1.151 * 1.15

# Alternatively, set WS_AT_10M = .TRUE. in namelist for auto-conversion
# (but still must be in mph!)
```

### Step 2: Verify wind direction convention

```python
# ELMFIRE: meteorological convention — direction FROM which wind blows
# 0° = wind from North (blows southward)
# 90° = wind from East (blows westward)
# 180° = wind from South (blows northward)

# If source is "blowing TO" (math convention):
wd_met = (wd_math + 180.0) % 360.0

# If source is u,v components:
import numpy as np
ws = np.sqrt(u**2 + v**2)
wd_met = (270 - np.degrees(np.arctan2(v, u))) % 360
```

### Step 3: Convert fuel moisture to percent

```python
# If source is fraction (0-1):
m1_percent = m1_fraction * 100.0

# Typical ranges:
# M1:   2-15% (dead fine fuels, respond to hourly weather)
# M10:  4-20% (respond to daily weather)
# M100: 8-25% (respond to weekly weather)
# MLH:  30-300% (live herbaceous, seasonal)
# MLW:  60-200% (live woody, seasonal)
```

### Step 4: Create weather rasters

```bash
# Constant weather (simplest case):
python convert_weather_to_elmfire.py \
    --ws 15 --wd 0 --m1 3 --m10 4 --m100 5 \
    --lh_moisture 30 --lw_moisture 60 \
    --template_raster ./inputs/dem.tif \
    --out ./inputs
```

### Step 5: Generate namelist

```bash
python convert_weather_to_elmfire.py \
    --generate_namelist \
    --inputs_dir ./inputs --outputs_dir ./outputs \
    --cellsize 30 --epsg 32610 \
    --xll -6000 --yll -6000 \
    --tstop 21600 --dtdump 3600 \
    --x_ign 0.0 --y_ign 3000.0 \
    --lh_moisture 30 --lw_moisture 60 \
    --out ./inputs
```

## Verification

1. **Wind speed range**: `gdalinfo -stats ws.tif` — typical fire weather: 5–40 mph
2. **Wind direction range**: 0–360 degrees, no negative values
3. **Fuel moisture range**: M1 should be 2–25%, not 0.02–0.25
4. **Live moisture range**: MLH = 30–300%, MLW = 60–200%
5. **Spot check**: Compare first weather values against source station data
6. **Temporal continuity**: If multi-band, check bands are in correct time order

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Wind in m/s | Fire too slow | Multiply by 2.237 (and ×1.15 for height) |
| Wind in knots | Fire ~15% too fast | Multiply knots by 1.151 |
| WD "blowing to" | Fire goes opposite direction | Add 180° mod 360 |
| Moisture as fraction | Fire won't start or all crown | Multiply by 100 |
| DT_METEOROLOGY mismatch | Weather jumps or freezes | Match to raster band spacing |
| Wrong time zone | Diurnal cycle shifted | Convert to UTC or local solar time |

## Example

Setting up weather for a moderate-wind grass fire:

```bash
# 15 mph wind from the north, low fuel moisture (fire weather)
python convert_weather_to_elmfire.py \
    --ws 15.0 --wd 0.0 \
    --m1 3.0 --m10 4.0 --m100 5.0 \
    --lh_moisture 30.0 --lw_moisture 60.0 \
    --template_raster ./inputs/dem.tif \
    --generate_namelist \
    --inputs_dir ./inputs --outputs_dir ./outputs \
    --cellsize 30 --epsg 32610 \
    --xll -6000 --yll -6000 \
    --tstop 19800 --dtdump 3600 \
    --x_ign 0.0 --y_ign 3000.0 \
    --out ./inputs
```
