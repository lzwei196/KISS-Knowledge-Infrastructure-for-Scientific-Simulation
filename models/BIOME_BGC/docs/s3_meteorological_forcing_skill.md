# S3: Meteorological Forcing -- Skill Document

## Purpose

Convert CMFD, MSWX, or VIC forcing data to BIOME-BGC daily meteorological input format. This stage contains the most dangerous unit conversion traps in the entire pipeline.

**If skipped**: Model cannot run (no meteorological driver).

**If done incorrectly**: 7 of the 25 diagnostic triplets (dt_007 through dt_011) are related to forcing conversion errors, and ALL are silent -- the model runs to completion but produces wrong results.

## Prerequisites

- [ ] VIC forcing files exist (from HydroCraft forcing pipeline)
- [ ] Site latitude known (needed for day length computation)
- [ ] Year range matches the intended simulation period

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| forcing_file | path | VIC forcing | 7-column ASCII, 3-hourly (8 steps/day) |
| lat | float | Site/grid | Latitude for day length computation |
| start_year | int | User | First year to extract |
| end_year | int | User | Last year to extract |

## BIOME-BGC Met File Format

Space-separated, one row per day, with header lines:

```
year  yday  Tmax(C)  Tmin(C)  Tday(C)  prcp(cm)  VPD(Pa)  srad(W/m2)  daylen(s)
```

### CRITICAL UNIT TABLE

| Column | Variable | BIOME-BGC Unit | VIC/CMFD Unit | Conversion | Silent Error If Wrong |
|--------|----------|---------------|---------------|------------|----------------------|
| 1 | Year | integer | -- | from date | -- |
| 2 | Year-day | 1-365 | -- | from date | -- |
| 3 | Tmax | deg C | K (CMFD) or C (VIC) | K-273.15 | dt_010: wrong phenology/respiration |
| 4 | Tmin | deg C | K or C | K-273.15 | dt_010 |
| 5 | Tday | deg C | NOT in input | Tmin + 0.45*(Tmax-Tmin) | -- |
| 6 | Precipitation | **cm/day** | **mm** (VIC/CMFD) | **DIVIDE BY 10** | dt_007: 10x GPP/NPP |
| 7 | VPD | **Pa** | specific humidity (kg/kg) | see below | dt_008: stomata always open |
| 8 | Shortwave | W/m2 | W/m2 (VIC/CMFD) | none | -- |
| 9 | Day length | **seconds** | NOT in input | **MUST COMPUTE** | dt_009: GPP = 0 |

### VPD Computation

VPD is NOT directly available from CMFD/MSWX. It must be computed:

1. Saturated vapor pressure: `es = 611 * exp(17.27 * Tday / (Tday + 237.3))` (Pa)
2. Actual vapor pressure: `ea = q * P / (0.622 + 0.378 * q)` (Pa)
   where q = specific humidity (kg/kg), P = surface pressure (Pa)
3. VPD = es - ea (Pa), minimum 0

### Day Length Computation

Day length must be computed from latitude and day-of-year using the CBM formula (Dunn & Mackay 1976):

1. Solar declination: `decl = -23.4856 * cos(2*pi*(yday+10)/365.25)` degrees
2. Hour angle: `cos(ha) = -tan(lat_rad) * tan(decl_rad)`
3. Day length: `dayl = 2 * ha * 86400 / (2*pi)` seconds

### Tday Approximation

Tday is the average temperature during daylight hours, NOT the daily average:
- `Tday = Tmin + 0.45 * (Tmax - Tmin)` (Thornton & Running 1999)
- BIOME-BGC's fscanf reads but discards this column (`%*lf` in metarr_init.c), but it MUST be present in the file for correct column alignment.

## Procedure

### Step 1: Run convert_forcing_to_bgc.py

```bash
python tools/convert_forcing_to_bgc.py \
  --forcing_file <vic_forcing_path> \
  --lat <latitude> \
  --start_year <start> --end_year <end> \
  --output <met_output_path>
```

**Expected result**: JSON with status=success, mean_annual_precip_cm < 300.

### Step 2: Validate the output

Check the JSON output for:
- `mean_annual_precip_cm`: Should be 20-200 cm for most climates. If >300, precipitation units are wrong (still mm).
- `tmax_range`: Should be -40 to +50 C. If >100, temperature is in Kelvin.
- `warnings`: Read all warnings and investigate.

### Step 3: Verify met file header

The output file has 4 header lines (matching MTCLIM format). The .ini file's met_header_lines must be set to 4.

## Expected Outputs

| Output | Path | Verification |
|--------|------|-------------|
| Met file | As specified by --output | 4 header lines + N_days data lines |

## Validation Checks

1. [ ] Annual precipitation is 20-200 cm (200-2000 mm) for most climates
2. [ ] Temperature range is -40 to +50 C (not Kelvin)
3. [ ] VPD values are 0-5000 Pa (not 0-5 kPa)
4. [ ] Day length values are 0-86400 seconds (not 0 everywhere)
5. [ ] Number of data rows = 365 * n_years (no leap years in BIOME-BGC)
6. [ ] No missing or NaN values

## Common Pitfalls

- **dt_007**: Precipitation in mm instead of cm. CHECK: typical daily values should be 0-3 cm, not 0-30.
- **dt_008**: VPD in kPa instead of Pa. CHECK: typical values should be 200-4000 Pa, not 0.2-4.0.
- **dt_009**: Day length = 0. CHECK: column 9 should have values 28000-60000 for mid-latitudes.
- **dt_010**: Temperature in Kelvin. CHECK: values should be -40 to +50, not 233 to 323.
- **dt_011**: Wrong header line count in .ini. The tool produces 4 header lines.
