# S1: Forcing Data Preparation

## Purpose

Convert raw meteorological observations or reanalysis data (ERA5, station CSV)
into SNOWPACK's SMET 1.1 ASCII format with correct SI units. This is the most
error-prone stage because unit mismatches produce silent failures — the model
runs but gives physically meaningless results.

## Inputs

| Field    | Description                    | Expected unit   | Common source units         |
|----------|--------------------------------|----------------|-----------------------------|
| datetime | Timestamp                      | ISO 8601        | various                     |
| TA       | Air temperature                | K               | °C, °F                      |
| RH       | Relative humidity              | 0–1 fraction    | 0–100 %                     |
| VW       | Wind velocity                  | m/s             | km/h, knots, mph            |
| DW       | Wind direction                 | degrees (0–360) | degrees                     |
| ISWR     | Incoming shortwave radiation   | W/m²            | MJ/m²/day, kJ/m²/hr        |
| ILWR     | Incoming longwave radiation    | W/m²            | MJ/m²/day                   |
| PSUM     | Precipitation (rain+snow)      | kg/m² per step  | mm/hr, mm/day, m            |
| HS       | Snow depth (optional)          | m               | cm, mm                      |
| TSG      | Ground surface temp (optional) | K               | °C                          |
| TSS      | Snow surface temp (optional)   | K               | °C                          |
| P        | Atmospheric pressure (optional)| Pa              | hPa, kPa, mbar              |
| RSWR     | Reflected SW (optional)        | W/m²            | W/m²                        |

## Outputs

A single `.smet` file per station with:
- SMET 1.1 ASCII header (station metadata, coordinate system, nodata value)
- Tab/space-separated data block with timestamp and meteorological fields

## Procedure

1. **Load source data** — Read CSV/NetCDF. Identify column mappings.
2. **Apply unit conversions** — Use `convert_forcing.py` with `--source_*_unit` flags.
3. **Handle missing data** — Replace gaps with the configured nodata sentinel (-999).
4. **Sort chronologically** — SNOWPACK requires monotonically increasing timestamps.
5. **Write SMET** — Header + data block.
6. **Verify** — Spot-check first/last 5 rows. Confirm TA > 200 K, 0 ≤ RH ≤ 1.0.

## Verification

```bash
# Check temperature range (should be ~230-320 K)
head -20 input/station.smet
# Verify no Celsius values slipped through
awk '/^[0-9]/ {if ($2 < 200) print "CELSIUS DETECTED line", NR, $2}' input/station.smet
# Check RH range
awk '/^[0-9]/ {if ($3 > 1.1) print "RH PERCENT DETECTED line", NR, $3}' input/station.smet
```

## Traps

### Temperature in Celsius (dt_001) — SILENT
If TA is in Celsius, SNOWPACK interprets 20 as 20 K (−253°C). The surface energy
balance produces extreme outgoing longwave (~0.3 W/m²), zero melt, and the
snowpack grows indefinitely. No error is raised.

**Detection:** Any TA value below 200 in the SMET file.

### Relative humidity as percentage (dt_002) — SILENT
If RH is 0–100 instead of 0–1, values >1 are clamped. The latent heat flux
is computed using saturated conditions, systematically overestimating
sublimation/condensation.

**Detection:** RH values exceeding 1.05 in the SMET file.

### Precipitation rate mismatch (dt_003) — SILENT
PSUM must be kg/m² per timestep interval. If the source provides mm/day but
the timestep is 1 hour, each timestep gets 24× too much precipitation, leading
to runaway SWE accumulation.

**Detection:** Single-timestep PSUM values >50 kg/m² are suspicious for hourly data.

### Radiation in energy units (dt_010) — SILENT
ERA5 and some datasets provide radiation as MJ/m²/day or J/m² accumulated.
SNOWPACK needs instantaneous W/m². Forgetting the conversion causes radiation
values 1000× too large or too small.

**Conversion:** MJ/m²/day × 10⁶ / 86400 = W/m²

## Example

```bash
python tools/convert_forcing.py \
    --input era5_wfj_2020.csv \
    --output input/WFJ2.smet \
    --station_id WFJ2 \
    --latitude 46.831 --longitude 9.810 --altitude 2540 \
    --source_temp_unit C \
    --source_rh_unit percent \
    --source_precip_unit mm_per_hour \
    --source_rad_unit W_per_m2 \
    --timezone 1
```
