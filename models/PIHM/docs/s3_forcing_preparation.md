# S3: Forcing Preparation Skill

## Purpose

Convert meteorological forcing data from global reanalysis products (ERA5, NLDAS,
GLDAS) or station observations into the PIHM `.meteo` file format with correct
units. This is the most error-prone stage because unit mismatches produce **silent
failures** — the model runs without errors but produces physically meaningless results.

## Prerequisites

- Mesh generation (S1) completed — need to know the number of forcing zones
- Raw meteorological data covering the simulation period
- Knowledge of source data units (check dataset documentation carefully)

## Inputs

| Input | Source | Format |
|-------|--------|--------|
| Meteorological data | ERA5/NLDAS/station | CSV or NetCDF |
| Time period | User specification | Start/end dates |
| Spatial extent | Mesh centroid | Lat/lon coordinates |

### Required Forcing Variables

| # | Variable | PIHM Name | PIHM Unit | Common Sources |
|---|----------|-----------|-----------|----------------|
| 1 | Precipitation | PRCP | kg/m²/s | ERA5: m/hr, NLDAS: kg/m²/s |
| 2 | Air temperature | SFCTMP | K | ERA5: K, stations: °C |
| 3 | Relative humidity | RH | % | ERA5: %, some provide q (kg/kg) |
| 4 | Wind speed | SFCSPD | m/s | ERA5: m/s, stations: km/hr |
| 5 | Shortwave radiation | SOLAR | W/m² | ERA5: J/m² (accumulated), NLDAS: W/m² |
| 6 | Longwave radiation | LONGWV | W/m² | ERA5: J/m² (accumulated), NLDAS: W/m² |
| 7 | Surface pressure | PRES | Pa | ERA5: Pa, some provide hPa |

### Wind Level

The `.meteo` file header requires `WIND_LVL` — the height above ground (meters) at
which wind speed was measured. ERA5 uses 10 m; tower stations vary. This affects
the aerodynamic resistance calculation in the land surface model.

## Outputs

| Output | Path | Format |
|--------|------|--------|
| PIHM forcing file | `input/<project>/<project>.meteo` | PIHM text format |

## Procedure

### Step 1: Identify Source Units

**This is the most critical step.** Read the source dataset documentation to
identify the exact units for each variable. Common pitfalls:

- ERA5 accumulates radiation over the forecast step (J/m²), not instantaneous W/m²
- ERA5 provides dewpoint temperature, not RH
- NLDAS provides specific humidity, not RH
- Station data may use °F, inches, or mph

### Step 2: Run the Converter

```bash
python ki/tools/forcing_converter.py \
    --input raw_forcing.csv \
    --output input/MyProject/MyProject.meteo \
    --prcp-unit mm/hr \
    --temp-unit C \
    --pres-unit hPa \
    --wind-unit m/s \
    --rad-unit W/m2 \
    --humidity-type RH \
    --wind-level 10.0
```

### Step 3: Validate Converted Values

Check that converted values fall in physically reasonable ranges:

| Variable | Typical Range | Extreme Range |
|----------|--------------|---------------|
| PRCP | 0–0.005 kg/m²/s | 0–0.03 kg/m²/s |
| SFCTMP | 250–310 K | 200–330 K |
| RH | 20–100% | 5–100% |
| SFCSPD | 0.5–10 m/s | 0–40 m/s |
| SOLAR | 0–800 W/m² | 0–1361 W/m² |
| LONGWV | 150–450 W/m² | 50–550 W/m² |
| PRES | 80000–105000 Pa | 50000–110000 Pa |

### Step 4: Check Temporal Continuity

- No gaps longer than the output interval
- No sentinel values (-999, NaN, -9999)
- Consistent timestep throughout (hourly for most applications)
- Time format: `YYYY-MM-DD HH:MM`

## Verification

1. **Range check**: All values within expected physical ranges
2. **Diurnal cycle**: Solar radiation shows clear day/night pattern
3. **Seasonal cycle**: Temperature and radiation follow expected seasonality
4. **Precipitation total**: Annual total matches regional climatology (mm/yr)
5. **Time coverage**: Forcing period covers simulation period in `.para` file

## Traps

| Trap | Triplet | Severity |
|------|---------|----------|
| Precipitation in mm/hr not kg/m²/s | dt_001 | Silent — flooding |
| Temperature in °C not K | dt_002 | Silent — permanent snow |
| Pressure in hPa not Pa | dt_003 | Silent — wrong ET |
| Specific humidity vs RH | dt_004 | Degraded — wrong ET |
| Radiation in MJ/m²/day not W/m² | dt_005 | Silent — no energy |
| Wind in km/hr not m/s | dt_006 | Degraded — wrong ET |
| Missing/gap timesteps | dt_017 | Degraded — interpolation artifacts |

## Example

Converting ERA5 hourly data for Shale Hills watershed:

```bash
# ERA5 provides: total precipitation (m), T2m (K), dewpoint (K),
# u10/v10 (m/s), ssrd/strd (J/m²), sp (Pa)

# Pre-process ERA5 to CSV with proper column names
# Then convert:
python ki/tools/forcing_converter.py \
    --input era5_shale_hills_2009.csv \
    --output input/ShaleHills/ShaleHills.meteo \
    --prcp-unit mm/hr \
    --temp-unit K \
    --pres-unit Pa \
    --wind-unit m/s \
    --rad-unit W/m2 \
    --humidity-type RH \
    --wind-level 10.0
```

Expected output: ~8760 hourly records for one year, file size ~2 MB.
