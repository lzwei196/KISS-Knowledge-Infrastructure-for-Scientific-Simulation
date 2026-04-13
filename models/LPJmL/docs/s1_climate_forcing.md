# Stage 1: Climate Forcing Preparation

## Purpose

Convert global gridded climate datasets (GSWP3-W5E5, CRU TS, ISIMIP, ERA5) into LPJmL's CLM binary format with correct units. This is the most error-prone stage because unit mismatches produce no errors but cause physically impossible results.

## Inputs

| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| Temperature | NetCDF | GSWP3-W5E5 / CRU | Mean daily air temperature |
| Precipitation | NetCDF | GSWP3-W5E5 / CRU | Total precipitation |
| Shortwave radiation | NetCDF | GSWP3-W5E5 / ERA5 | Downward shortwave radiation |
| Net longwave radiation | NetCDF | GSWP3-W5E5 / ERA5 | Net longwave radiation |
| Wind speed | NetCDF | GSWP3-W5E5 / CRU | Surface wind speed |
| Min/Max temperature | NetCDF | GSWP3-W5E5 | Daily extremes (or diurnal range for CRU) |
| Specific humidity | NetCDF | GSWP3-W5E5 | Surface specific humidity |

## Outputs

| Output | Format | Unit | CLM ID | LPJmL Variable |
|--------|--------|------|--------|-----------------|
| Temperature | CLM binary | deg C | 1 | `temp` |
| Precipitation | CLM binary | mm/day or mm/month | 2 | `prec` |
| Shortwave radiation | CLM binary | W/m2 | 3 | `swdown` |
| Net longwave radiation | CLM binary | W/m2 | 4 | `lwnet` |
| Wind speed | CLM binary | m/s | 15 | `wind` |
| Min temperature | CLM binary | deg C | 9 | `tmin` |
| Max temperature | CLM binary | deg C | 10 | `tmax` |
| Specific humidity | CLM binary | kg/kg | 14 | `humid` |

## Procedure

1. **Identify source dataset**: Determine which climate forcing is available (GSWP3-W5E5 is default for LPJmL 6.0)
2. **Check source units**: Read NetCDF attributes (`units` field) — DO NOT assume units
3. **Apply unit conversions**:
   - Temperature: K → deg C (subtract 273.15)
   - Precipitation: kg/m2/s → mm/day (multiply by 86400)
   - Shortwave: J/m2/day → W/m2 (divide by 86400) — many datasets already in W/m2
   - Wind: km/h → m/s (divide by 3.6) — most datasets already in m/s
   - Humidity: g/kg → kg/kg (divide by 1000) — check if already in kg/kg
4. **Write CLM binary**: Use `convert_climate_to_clm.py` with correct CLM ID
5. **Update config**: Set paths in `input.cjson` or `input_netcdf.cjson`

## Verification

- Check value ranges match physical expectations:
  - Temperature: -60 to +50 deg C
  - Precipitation: 0 to 200 mm/day (daily), 0 to 3000 mm/month (monthly)
  - Shortwave: 0 to 450 W/m2
  - Wind: 0 to 30 m/s
- Use `printclm` or `statclm` to inspect CLM file statistics
- Cross-check with `lpjcheck` for configuration consistency

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Temperature in Kelvin | All values ~300, unrealistic warm climate | Subtract 273.15 |
| Precipitation in kg/m2/s | Extremely dry (values < 0.001 mm/day) | Multiply by 86400 |
| Precipitation in mm/month but daily expected | 30x too much rain | Divide by days-in-month |
| Shortwave in J/m2/day | GPP 86400x too high | Divide by 86400 |
| CRU monthly vs daily | Wrong temporal disaggregation | Use `random_prec: true` for CRU |
| Grid mismatch | Wrong spatial coverage | Verify grid.bin matches climate grid |
| Missing leap days | Off-by-one errors accumulating | Use nstep=365 (not 366) |

## Example

```bash
# Convert GSWP3-W5E5 temperature (already in deg C for ISIMIP-processed files)
python tools/convert_climate_to_clm.py \
    --input GSWP3-W5E5/tas_1901-2019.nc \
    --variable tas --clm_id 1 \
    --unit_from degC --unit_to degC \
    --output input/temp.clm \
    --firstyear 1901 --lastyear 2019 --nstep 12

# Convert GSWP3-W5E5 precipitation (kg/m2/s -> mm/day for daily)
python tools/convert_climate_to_clm.py \
    --input GSWP3-W5E5/pr_1901-2019.nc \
    --variable pr --clm_id 2 \
    --unit_from "kg/m2/s" --unit_to "mm/day" \
    --output input/prec.clm \
    --firstyear 1901 --lastyear 2019 --nstep 365
```
