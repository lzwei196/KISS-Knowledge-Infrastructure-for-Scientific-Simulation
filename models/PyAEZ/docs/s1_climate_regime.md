# S1: Climate Regime Analysis (Module I) Skill Document

## Purpose

Compute agro-climatic indicators that characterize the thermal and moisture regime
of the study area. These indicators are prerequisite inputs for all subsequent modules
(II–VI). Module I produces: thermal climate classification, thermal zones, Length of
Growing Period (LGP), reference evapotranspiration (ETo), temperature profiles,
permafrost evaluation, and AEZ classification.

## Inputs

| Variable | Type | Shape | Unit | Source |
|----------|------|-------|------|--------|
| `min_temp` | NumPy | (H,W,12/365) | °C | S0 output |
| `max_temp` | NumPy | (H,W,12/365) | °C | S0 output |
| `precipitation` | NumPy | (H,W,12/365) | mm/day | S0 output |
| `short_rad` | NumPy | (H,W,12/365) | W/m² | S0 output |
| `wind_speed` | NumPy | (H,W,12/365) | m/s (2m) | S0 output |
| `rel_humidity` | NumPy | (H,W,12/365) | 0–1 | S0 output |
| `elevation` | NumPy | (H,W) | meters | GeoTIFF |
| `mask` | NumPy | (H,W) | 0/1 | GeoTIFF |
| `lat_min` | float | scalar | degrees | User config |
| `lat_max` | float | scalar | degrees | User config |

### Parameters

| Parameter | Default | Unit | Description |
|-----------|---------|------|-------------|
| `Sa` | 100 | mm/m | Available soil moisture capacity |
| `D` | 1.0 | m | Rooting depth for LGP water balance |
| `mask_value` | 0 | — | Value in mask to exclude from analysis |

## Outputs

| Variable | Shape | Unit | Description |
|----------|-------|------|-------------|
| `thermal_climate` | (H,W) | class 1–12 | Thermal climate classification |
| `thermal_zone` | (H,W) | class 1–12 | Thermal zone |
| `lgpt0` | (H,W) | days | Thermal LGP at T > 0°C |
| `lgpt5` | (H,W) | days | Thermal LGP at T > 5°C |
| `lgpt10` | (H,W) | days | Thermal LGP at T > 10°C |
| `tsum0` | (H,W) | °C·days | Temperature sum above 0°C |
| `tsum5` | (H,W) | °C·days | Temperature sum above 5°C |
| `tsum10` | (H,W) | °C·days | Temperature sum above 10°C |
| `temp_profile` | 18×(H,W) | days | A1–A9 and B1–B9 profiles |
| `lgp` | (H,W) | days | Length of Growing Period |
| `lgp_classified` | (H,W) | class 1–7 | LGP moisture regime class |
| `lgp_equv` | (H,W) | days | LGP equivalent |
| `frost_index` | (H,W) | 0–1 | Air frost index |
| `permafrost` | (H,W) | class 1–4 | Permafrost classification |

## Procedure

### Step 1: Initialize ClimateRegime object
```python
from pyaez import ClimateRegime
clim = ClimateRegime.ClimateRegime()
clim.setStudyAreaMask(mask, 0)
clim.setLocationTerrainData(lat_min, lat_max, elevation)
```

### Step 2: Load climate data
```python
# For monthly data (interpolated to daily via cubic spline):
clim.setMonthlyClimateData(min_temp, max_temp, precipitation,
                           short_rad, wind_speed, rel_humidity)

# For daily data (365 time steps):
clim.setDailyClimateData(min_temp, max_temp, precipitation,
                          short_rad, wind_speed, rel_humidity)
```

### Step 3: Compute thermal indicators (order matters)
```python
thermal_climate = clim.getThermalClimate()
thermal_zone = clim.getThermalZone()
lgpt0 = clim.getThermalLGP0()
lgpt5 = clim.getThermalLGP5()
lgpt10 = clim.getThermalLGP10()
tsum0 = clim.getTemperatureSum0()
tsum5 = clim.getTemperatureSum5()
tsum10 = clim.getTemperatureSum10()
temp_profile = clim.getTemperatureProfile()
```

### Step 4: Compute moisture-dependent LGP
```python
lgp = clim.getLGP(Sa=100, D=1)      # Uses soil water balance
lgp_class = clim.getLGPClassified(lgp)
lgp_equv = clim.getLGPEquivalent()
```

### Step 5: Frost and permafrost evaluation
```python
frost_result = clim.AirFrostIndexandPermafrostEvaluation()
frost_index = frost_result[0]
permafrost_class = frost_result[1]
```

### Step 6: AEZ classification
```python
aez = clim.AEZClassification(thermal_climate, thermal_zone, lgp_class,
                               soil_terrain_lulc_map)
```

## Verification

1. **LGP range**: 0–365 days; tropical lowlands typically 180–365
2. **Thermal LGP**: lgpt0 ≥ lgpt5 ≥ lgpt10 for all pixels (stricter threshold = shorter period)
3. **Temperature sums**: tsum0 ≥ tsum5 ≥ tsum10
4. **ETo**: typically 2–8 mm/day; values >15 indicate unit errors in input
5. **Thermal climate**: classes 1–12 should be spatially coherent
6. **LGP classification**: 1=hyper-arid to 7=per-humid; should correlate with precipitation

## Traps

| Trap | Symptom | Root Cause |
|------|---------|------------|
| LGP = 0 everywhere | Wrong humidity unit (% not fraction) → extreme ETo | Convert RH to 0–1 |
| LGP = 365 everywhere | Precipitation too high (mm/month not mm/day) | Divide by days_in_month |
| All thermal zones identical | Elevation is flat/wrong → no lapse rate variation | Check DEM values |
| Negative ETo values | Negative radiation from cubic spline interpolation | Clamp to 0 |
| NaN in temperature sums | NaN in input temperature arrays | Check for missing data |

## Example

```python
from pyaez import ClimateRegime
import numpy as np
from osgeo import gdal

# Load Laos example data
max_temp = np.load('data_input/climate/max_temp.npy')
min_temp = np.load('data_input/climate/min_temp.npy')
precip = np.load('data_input/climate/precipitation.npy')
srad = np.load('data_input/climate/short_rad.npy')
wind = np.load('data_input/climate/wind_speed.npy')
rhum = np.load('data_input/climate/relative_humidity.npy')
mask = gdal.Open('data_input/LAO_Admin.tif').ReadAsArray()
elev = gdal.Open('data_input/LAO_Elevation.tif').ReadAsArray()

clim = ClimateRegime.ClimateRegime()
clim.setStudyAreaMask(mask, 0)
clim.setLocationTerrainData(13.87, 22.59, elev)
clim.setMonthlyClimateData(min_temp, max_temp, precip, srad, wind, rhum)

lgp = clim.getLGP(Sa=100, D=1)
print(f"LGP range: {lgp[mask>0].min()} – {lgp[mask>0].max()} days")
```
