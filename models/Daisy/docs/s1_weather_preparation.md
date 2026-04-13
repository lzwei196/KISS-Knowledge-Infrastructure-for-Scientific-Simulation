# S1: Weather Data Preparation

## Purpose

Convert global or station meteorological data into Daisy's `.dwf` (Daisy Weather File) format. This is the most error-prone stage because silent unit conversion mistakes produce plausible but wrong simulations.

## Inputs

| Input | Source | Format | Required |
|-------|--------|--------|----------|
| Air temperature | Station / ERA5 / CMFD | °C or K | Yes |
| Global radiation | Station / ERA5 / CMFD | W/m² or MJ/m²/d | Yes |
| Precipitation | Station / ERA5 / CMFD | mm/d, mm/3h, or kg/m²/s | Yes |
| Reference ET | Station / calculated | mm/d | Optional |
| Wind speed | Station / ERA5 | m/s | Optional |
| Relative humidity | Station / ERA5 | % or fraction | Optional |
| Station metadata | — | lat, lon, elevation | Yes |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `<site>.dwf` | Daisy Weather File | Tab-separated with metadata header |

## Procedure

1. **Read source data** — Load CSV or NetCDF meteorological data
2. **Map columns** — Identify which source columns correspond to GlobRad, AirTemp, Precip
3. **Convert units**:
   - Radiation: MJ/m²/d → W/m² by dividing by 0.0864
   - Temperature: K → °C by subtracting 273.15
   - Precipitation: mm/3h → mm/d by multiplying by 8; or kg/m²/s → mm/d by multiplying by 86400
   - Humidity: fraction → % by multiplying by 100
4. **Compute metadata**:
   - TAverage: annual mean temperature
   - TAmplitude: half the range of monthly means
   - MaxTDay: Julian day of warmest period (default ~209 for N. hemisphere)
   - TimeZone: nearest 15° meridian east of Greenwich
5. **Write DWF file** with header and tab-separated data
6. **Validate output**: check temperature range (−60 to +60°C), radiation ≥ 0, precip ≥ 0

## Verification

- [ ] First line starts with `dwf-0.0`
- [ ] Temperature range is physically plausible (−40 to +45°C for temperate)
- [ ] Daily mean radiation is 0–400 W/m² (not 0–40 MJ/m²/d)
- [ ] Precipitation is 0–200 mm/d (not 0–200 mm/3h)
- [ ] Begin/End dates match data range
- [ ] No negative radiation values
- [ ] File can be previewed in any text editor

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Radiation in MJ/m²/d used as W/m² | Unrealistically low radiation, stunted crops | Divide by 0.0864 |
| Temperature in Kelvin used as °C | Temperature ~300°C, immediate crash or extreme ET | Subtract 273.15 |
| Precip in mm/3h used as mm/d | 8x too much precipitation, waterlogged soil | Multiply by 8 for daily total |
| Precip in kg/m²/s used as mm/d | ~86400x too much water | Multiply by 86400 |
| RelHum as fraction (0–1) used as % | Extreme evaporation, soil dries instantly | Multiply by 100 |
| Missing RefEvap column | Daisy falls back to Makkink estimation | Provide RefEvap for better accuracy |
| Tab vs space delimiter | Daisy fails to parse columns | Use tab separators |
| Timezone wrong | Radiation timing offset | Set TimeZone to nearest 15° multiple |

## Example

```bash
python ki/tools/convert_weather_to_dwf.py \
    --input era5_daily.csv \
    --output my-site.dwf \
    --station "Taastrup" \
    --lat 55.67 --lon 12.30 --elev 30 \
    --rad-unit "MJ/m2/d" \
    --temp-unit "degC" \
    --precip-unit "mm/d" \
    --date-col "time" \
    --rad-col "ssrd" \
    --temp-col "t2m" \
    --precip-col "tp"
```

Expected output: `my-site.dwf` with header + tab-separated daily data.
