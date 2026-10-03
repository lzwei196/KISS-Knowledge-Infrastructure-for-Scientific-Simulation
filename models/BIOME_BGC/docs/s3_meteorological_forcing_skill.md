# S3: Meteorological Forcing -- Skill Document

## Purpose

Build the BIOME-BGC daily meteorological input file straight from the data source: CMFD, MSWX or NASA POWER (read by the tool through the shared loader `ki_tools_common.load_forcing.load_daily_forcing`) or a FLUXNET2015 tower file. The met file is never made from another model's input files (dt_028). This stage contains the most dangerous unit conversion traps in the entire pipeline.

**If skipped**: Model cannot run (no meteorological driver).

**If done incorrectly**: the forcing triplets (dt_007 through dt_011, dt_027) are related to forcing conversion errors, and ALL are silent -- the model runs to completion but produces wrong results.

## Prerequisites

- [ ] A weather source covers the site and the WHOLE period: `cmfd` (China, 70-140E 15-55N), `mswx` (global, local store `KISSPATH_FORCING`), `nasa_power` (global, network, daily from 1981), or a FLUXNET tower file
- [ ] Site longitude known (cmfd / mswx / nasa_power)
- [ ] Site latitude known (needed for day length computation)
- [ ] Year range matches the intended simulation period

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| source | choice | User | REQUIRED, no default: `cmfd`, `mswx`, `nasa_power` or `fluxnet` |
| lat | float | Site/grid | Latitude (point to read; also day length) |
| lon | float | Site/grid | Longitude east (cmfd / mswx / nasa_power) |
| forcing_dir | path | Store | cmfd / mswx store root (always give it for cmfd) |
| forcing_file | path | FLUXNET2015 | fluxnet only: `<site>/FULLSET_DD.csv` (the sibling `FULLSET_HH.csv` is used when present) |
| start_year | int | User | First year to extract |
| end_year | int | User | Last year to extract |

## BIOME-BGC Met File Format

Space-separated, one row per day, with header lines:

```
year  yday  Tmax(C)  Tmin(C)  Tday(C)  prcp(cm)  VPD(Pa)  srad(W/m2)  daylen(s)
```

### CRITICAL UNIT TABLE

| Column | Variable | BIOME-BGC Unit | Unit from the shared loader | Conversion | Silent Error If Wrong |
|--------|----------|---------------|---------------|------------|----------------------|
| 1 | Year | integer | -- | from date | -- |
| 2 | Year-day | 1-365 | -- | from date | -- |
| 3 | Tmax | deg C | deg C (`temp_max_c`) | none | dt_010: wrong phenology/respiration |
| 4 | Tmin | deg C | deg C (`temp_min_c`) | none | dt_010 |
| 5 | Tday | deg C | NOT in input | Tmin + 0.45*(Tmax-Tmin) | -- |
| 6 | Precipitation | **cm/day** | **mm in the day** (`precip_mm`) | **DIVIDE BY 10** | dt_007: 10x GPP/NPP |
| 7 | VPD | **Pa** | specific humidity (`shum_kgkg`) + the source's surface pressure (`pres_pa`) | see below | dt_008: stomata always open; dt_031: fixed pressure |
| 8 | Shortwave | **W/m2 DAYLIGHT average** (`metv.swavgfd`) | W/m2 **24-h mean** (`srad_wm2`; CMFD/MSWX/NASA POWER/FLUXNET) | **MULTIPLY BY 86400/daylen** (tool does it; `--srad_is_daylight_avg` only for MTCLIM input) | dt_027: GPP/LAI/ET 30-60% low, timing intact |
| 9 | Day length | **seconds** | NOT in input | **MUST COMPUTE** | dt_009: GPP = 0 |

### VPD Computation

VPD is NOT directly available from CMFD/MSWX. It must be computed:

1. Saturated vapor pressure: `es = 611 * exp(17.27 * Tday / (Tday + 237.3))` (Pa)
2. Actual vapor pressure: `ea = q * P / (0.622 + 0.378 * q)` (Pa)
   where q = specific humidity (kg/kg), P = the source's own surface pressure of that day (Pa) -- not a fixed 101325 Pa (dt_031)
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
# gridded / point product at the site
python tools/convert_forcing_to_bgc.py \
  --source nasa_power \
  --lat <latitude> --lon <longitude> \
  --start_year <start> --end_year <end> \
  --output <met_output_path>
#   --source cmfd  --forcing_dir KISSPATH_DATA/forcing/Data_forcing_03hr_010deg   (China; ~50 s per year)
#   --source mswx  --forcing_dir KISSPATH_FORCING   (global; ~15 min per year: 5 variables, ~3 min each, read one file at a time)

# flux tower with its own weather
python tools/convert_forcing_to_bgc.py \
  --source fluxnet --forcing_file <site>/FULLSET_DD.csv \
  --lat <latitude> --start_year <start> --end_year <end> \
  --output <met_output_path>
```

**Expected result**: JSON with status=success, mean_annual_precip_cm < 300. For cmfd / mswx / nasa_power the tool also writes `<met_output_path>.summary.json` (source, point, period, mean annual precipitation, mean temperature).

**The tool refuses instead of filling** (exit 2, nothing written) when the source has a missing or non-finite value, an uneven time axis, does not cover every day of `start_year`..`end_year`, or gives a value outside the physical range of its unit (dt_029). Choose another source or period; do not patch the series by hand.

**Never start more than one MSWX read at a time**: the store is on an exfat disk that wedges under parallel reads. The tool already reads its MSWX files one after another (dt_033).

### Step 2: Validate the output

Check the JSON output for:
- `mean_annual_precip_cm`: Should be 20-200 cm for most climates. If >300, precipitation units are wrong (still mm).
- `tmax_range`: Should be -40 to +50 C. If >100, temperature is in Kelvin.
- `<met>.summary.json` (cmfd / mswx / nasa_power): `mean_annual_precip_mm` and `mean_temperature_c` must fit the site's known climate; a gridded product can differ a lot from a tower gauge (DK-Sor 2004-2012: NASA POWER 736 mm/yr and 8.7 C, tower file 970 mm/yr and 8.5 C).
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
