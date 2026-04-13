# S2 — Meteorological Forcing Preparation

## Purpose

Convert meteorological observations or reanalysis data into SMET format files
that Alpine3D/MeteoIO can read. This is the most error-prone stage because
unit mismatches cause silent model failures.

## Inputs

| Item | Format | Source | Required |
|------|--------|--------|----------|
| Meteorological time series | CSV, NetCDF, database | Weather stations, ERA5, MERRA-2 | Yes |
| Station metadata | lat, lon, altitude | Station registry, DEM extraction | Yes |
| Time zone | UTC offset | Project definition | Yes |

### Required Meteorological Variables

| Variable | SMET Field | Unit | Minimum for Basic Run |
|----------|-----------|------|----------------------|
| Air temperature | TA | K | Yes |
| Relative humidity | RH | 0–1 | Yes |
| Wind speed | VW | m/s | Yes |
| Wind direction | DW | degrees | Yes (for spatial interpolation) |
| Precipitation | PSUM | mm | Yes |
| Incoming shortwave radiation | ISWR | W/m² | Recommended |
| Incoming longwave radiation | ILWR | W/m² | Can be generated |
| Snow height | HS | m | Optional (validation) |
| Atmospheric pressure | P | Pa | Optional (can use STD_PRESS) |
| Snow surface temperature | TSS | K | Optional |
| Ground temperature | TSG | K | Optional |

## Outputs

| File | Format | Path |
|------|--------|------|
| One SMET file per station | SMET 1.1 ASCII | `input/meteo/{STATION_ID}.smet` |

## Procedure

### 1. Identify Data Sources and Units

**CRITICAL**: Determine the units of each variable in your source data BEFORE conversion.
The #1 cause of Alpine3D failure is wrong units.

| Source | TA | RH | VW | PSUM | ISWR | P |
|--------|----|----|----|----|------|---|
| ERA5 | K | 0–1 | m/s | m(!) | J/m² | Pa |
| MERRA-2 | K | 0–1 | m/s | kg/m²/s | W/m² | Pa |
| Swiss IDAWEB | °C | % | km/h | mm | W/m² | hPa |
| Generic AWS | °C | % | m/s | mm | W/m² | hPa |

### 2. Run the Conversion Tool

```bash
python tools/convert_forcing_to_smet.py \
    --input station_data.csv \
    --output ./input/meteo/ \
    --station-id WFJ2 \
    --latitude 46.83 --longitude 9.81 --altitude 2540 \
    --timezone 1 \
    --temp-unit C \
    --rh-unit percent \
    --wind-unit m/s \
    --pressure-unit hPa \
    --precip-unit mm \
    --radiation-unit W/m2
```

### 3. Configure Station List in io.ini

```ini
[Input]
METEO = SMET
METEOPATH = ./input/meteo
STATION1 = WFJ2
STATION2 = DAV
STATION3 = STB2
```

### 4. Configure Input Filters

Filters protect against bad data. Add to io.ini [Filters]:

```ini
[Filters]
TA::filter1 = min_max
TA::arg1::min = 240        ; reject < -33°C
TA::arg1::max = 320        ; reject > 47°C

RH::filter1 = min_max
RH::arg1::min = 0.01
RH::arg1::max = 1.2        ; allow slight oversaturation
RH::filter2 = min_max
RH::arg2::soft = true       ; soft clip to [0.05, 1.0]
RH::arg2::min = 0.05
RH::arg2::max = 1.0

PSUM::filter1 = min_max
PSUM::arg1::min = -0.1
PSUM::arg1::max = 100.0
PSUM::filter2 = undercatch_wmo
PSUM::arg2::type = Hellmannsh

VW::filter1 = min_max
VW::arg1::min = -2
VW::arg1::max = 70
VW::filter2 = min_max
VW::arg2::soft = true
VW::arg2::min = 0.2
VW::arg2::max = 50.0

ISWR::filter1 = min_max
ISWR::arg1::min = -10
ISWR::arg1::max = 1500

ILWR::filter1 = min_max
ILWR::arg1::min = 180
ILWR::arg1::max = 600
```

### 5. Configure Generators for Missing Variables

```ini
[GENERATORS]
ILWR::generator1 = ALLSKY_LW
ILWR::arg1::type = Unsworth
ILWR::generator2 = CLEARSKY_LW
ILWR::arg2::type = Dilley
```

### 6. Configure Temporal Interpolation

```ini
[Interpolations1D]
MAX_GAP_SIZE = 86400          ; max 1 day gap
PSUM::RESAMPLE1 = ACCUMULATE
PSUM::ARG1::PERIOD = 900     ; must match CALCULATION_STEP_LENGTH × 60
```

## Verification

```bash
# Check SMET file format
head -15 input/meteo/WFJ2.smet
# Verify: latitude/longitude/altitude look reasonable
# Verify: fields line contains expected variables

# Quick unit check
python3 -c "
import sys
with open('input/meteo/WFJ2.smet') as f:
    for line in f:
        if line.startswith('[DATA]'):
            break
    vals = f.readline().split()
    print('First data line:', ' '.join(vals[:5]))
    # TA should be 230-320 K
    ta = float(vals[1])
    print(f'TA = {ta} K ({ta-273.15:.1f} °C) — ' + ('OK' if 230<ta<320 else 'WRONG UNIT!'))
"

# Count records and check for gaps
wc -l input/meteo/*.smet
```

## Traps

| Trap ID | Variable | Wrong Unit | Symptom | Fix |
|---------|----------|-----------|---------|-----|
| dt_001 | TA | °C → K | Crash or T near 0 K | Add 273.15 |
| dt_002 | RH | % → 0–1 | Always saturated, excess snow | Divide by 100 |
| dt_003 | VW | km/h → m/s | Extreme turbulent fluxes | Divide by 3.6 |
| dt_004 | DW | rad → deg | Wrong wind patterns | Multiply by 180/π |
| dt_005 | PSUM | m → mm | 1000× too much precip | Multiply by 1000 |
| dt_006 | P | hPa → Pa | Low air density | Multiply by 100 |
| dt_007 | ISWR | MJ/m²/d → W/m² | No snowmelt | Multiply by 11.574 |
| dt_008 | ILWR | MJ/m²/d → W/m² | Cold surface temps | Multiply by 11.574 |
| dt_009 | HS | cm → m | 100× too much snow | Divide by 100 |

## Example

Converting an ERA5 single-level download:

```bash
# ERA5 units: TA=K, PSUM=m, ISWR=J/m² (accumulated)
# Need: PSUM in mm (×1000), ISWR needs de-accumulation then conversion

python tools/convert_forcing_to_smet.py \
    --input era5_weissfluhjoch.csv \
    --output ./input/meteo/ \
    --station-id ERA5_WFJ \
    --latitude 46.83 --longitude 9.81 --altitude 2540 \
    --timezone 0 \
    --temp-unit K \
    --rh-unit fraction \
    --wind-unit m/s \
    --pressure-unit Pa \
    --precip-unit m \
    --radiation-unit W/m2
```
