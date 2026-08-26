# S0: Data Preparation Skill Document

## Purpose

Convert raw forcing data (CMFD, MSWX, TerraClimate) and soil databases (HWSD) into
PyAEZ-compatible format: NumPy 3D arrays for climate, GeoTIFF rasters for spatial data,
and Excel sheets for crop/soil/terrain parameters.

## Inputs

| Data | Source | Raw Format | Raw Unit |
|------|--------|-----------|----------|
| Temperature | CMFD/MSWX | NetCDF, 3-hourly/daily | Kelvin |
| Precipitation | CMFD/MSWX | NetCDF | mm/day or mm/3hr |
| Solar radiation | CMFD/MSWX | NetCDF | W/m² |
| Wind speed | CMFD/MSWX | NetCDF | m/s (10m height) |
| Relative humidity | CMFD | NetCDF | 0–100% |
| Specific humidity | MSWX | NetCDF | kg/kg |
| Pressure | MSWX | NetCDF | Pa |
| Elevation | SRTM/ASTER | GeoTIFF | meters |
| Soil mapping units | HWSD | Raster + MDB | integer codes |
| Slope | DEM-derived | GeoTIFF | percent |
| Land cover | AVHRR/Globcover | GeoTIFF | class codes |

## Outputs

All stored as NumPy (.npy) files in `data_input/climate/`:

| File | Shape | Unit | Description |
|------|-------|------|-------------|
| `max_temp.npy` | (H, W, 12) or (H, W, 365) | °C | Daily maximum temperature |
| `min_temp.npy` | (H, W, 12) or (H, W, 365) | °C | Daily minimum temperature |
| `precipitation.npy` | (H, W, 12) or (H, W, 365) | mm/day | Daily precipitation |
| `short_rad.npy` | (H, W, 12) or (H, W, 365) | W/m² | Shortwave radiation |
| `wind_speed.npy` | (H, W, 12) or (H, W, 365) | m/s at 2m | Wind speed |
| `relative_humidity.npy` | (H, W, 12) or (H, W, 365) | 0–1 fraction | Relative humidity |

GeoTIFF rasters in `data_input/`:

| File | Type | Unit |
|------|------|------|
| `admin_mask.tif` | int (0/1) | Binary study area mask |
| `elevation.tif` | float | meters above sea level |
| `slope.tif` | float | percent slope |
| `soil_map.tif` | int | HWSD mapping unit codes |

## Procedure

### Step 1: Clip to study area
```python
# Extract bounding box from source data
# lat_min, lat_max, lon_min, lon_max define the spatial extent
```

### Step 2: Temperature conversion (K → °C)
```python
temp_C = temp_K - 273.15
# CRITICAL: PyAEZ expects Celsius. Feeding Kelvin gives ~300°C mean.
```

### Step 3: Humidity conversion
```python
# CMFD: percentage → fraction
rh_frac = rh_pct / 100.0

# MSWX: specific humidity + pressure → relative humidity
# es = 0.6108 * exp(17.27 * T / (T + 237.3))  [kPa]
# rh = (q * P_Pa / 1000) / (0.622 * es)
```

### Step 4: Wind height correction
```python
# If wind is at 10m, convert to 2m:
u2 = u10 * 4.87 / np.log(67.8 * 10 - 5.42)
```

### Step 5: Precipitation aggregation
```python
# MSWX 3-hourly: sum 8 steps per day
precip_daily = precip_3hr.reshape(..., 8).sum(axis=-1)
# Monthly: divide by days in month
precip_daily = precip_monthly / days_per_month
```

### Step 6: Array axis ordering
```python
# Source (time, lat, lon) → PyAEZ (lat, lon, time)
data_pyaez = np.transpose(data_source, (1, 2, 0))
```

### Step 7: Save as NumPy
```python
np.save('climate/max_temp.npy', max_temp)  # shape (H, W, 12) or (H, W, 365)
```

## Verification

1. Check array shapes: all climate arrays must have identical (H, W) and same time dim
2. Temperature range: -50 to +50 °C (not 200–350 which indicates Kelvin)
3. Humidity range: 0 to 1.0 (not 0–100 which indicates percentage)
4. Precipitation: 0 to ~100 mm/day max (not >500 which indicates mm/month)
5. Radiation: 0 to ~400 W/m² (not >1000 which indicates wrong units)
6. Wind: 0 to ~15 m/s at 2m (>20 suggests 10m height)
7. No NaN/Inf in arrays (replace with 0 or interpolate)

## Traps

| # | Trap | Symptom | Fix |
|---|------|---------|-----|
| 1 | Temperature in Kelvin | Mean ~290 K, all yields NaN | Subtract 273.15 |
| 2 | Humidity as percentage | ETo explodes, LGP=0 everywhere | Divide by 100 |
| 3 | Precipitation as mm/month | P/PET >10, perhumid everywhere | Divide by days_in_month |
| 4 | Wrong array axis order | Wrong values per pixel, no error | Transpose to (H,W,T) |
| 5 | Wind at 10m not 2m | ETo ~20% too high | Apply height correction |
| 6 | Missing mask alignment | Shapes don't match, index error | Resample to same grid |

## Example

```bash
python ki/tools/convert_forcing.py \
    --source cmfd \
    --input-dir KISSPATH_FORCING/Data_forcing_01dy_010deg/ \
    --lat-min 13.87 --lat-max 22.59 --lon-min 100.0 --lon-max 108.0 \
    --year 2010 --output-dir ./data_input/climate
```
