# s3: Meteorological Forcing — Skill Document

## Purpose

Build the CE-QUAL-W2 met file straight from a forcing source (CMFD, MSWX or NASA POWER). The tool reads the source itself through the shared loader (`ki_tools_common.load_forcing.load_hourly_forcing`). CE-QUAL-W2 input is never made from another model's input files (dt_026).

This stage holds the most dangerous conversions of the pipeline. A wrong one gives NO error, only wrong water temperatures.

## Prerequisites

- [ ] Reservoir latitude and longitude
- [ ] Start and end year
- [ ] The met file name the control file expects (`w2_con.csv`, file-name block; `met.npt` in the DeGray example)

## Procedure

### Step 1: Pick the source

| Where | `--source` | `--forcing_dir` | Step |
|-------|-----------|-----------------|------|
| China | `cmfd` | `KISSPATH_DATA/forcing/Data_forcing_03hr_010deg` | 3 h |
| Anywhere, 1979 onward | `mswx` | `KISSPATH_FORCING` | 3 h |
| Anywhere, 2001 onward, no local store | `nasa_power` | (none; network) | 1 h |

`KISSPATH_DATA` is exfat: run ONE reader at a time, never in parallel. MSWX 1979 and 2011 are known faulty years.

### Step 2: Run the tool

```bash
python tools/s3_met_forcing/convert_met_to_w2.py \
    --source mswx --forcing_dir KISSPATH_FORCING \
    --lat <lat> --lon <lon> \
    --start_year <start> --end_year <end> \
    --output <run_dir>/<met file name>
```

`--source` has no default. Optional: `--wind_dir_deg` (default 270), `--utc_offset_hours` (default `int(lon/15)`).

### What the tool writes

The v5 CSV form (the binary reads the first character: `$` = CSV): three header lines, then rows

`JDAY,TAIR,TDEW,WIND,PHI,CLOUD,SRO`

| Column | Unit | From the source | How |
|--------|------|-----------------|-----|
| JDAY | decimal day, 1.0 = 00:00 on 1 Jan of the start year, LOCAL STANDARD time | UTC time | add `int(lon/15)` hours; values do not change |
| TAIR | deg C | `temp_c` | as it is |
| TDEW | deg C | `shum_kgkg`, `pres_pa` | `e = q p / (0.622 + 0.378 q)`, inverse Tetens; set to TAIR where above saturation |
| WIND | m/s | `wind_ms` | as it is (no height change; set WINDH to the source height) |
| PHI | **radians** | none | constant `--wind_dir_deg` as radians (270 deg = 4.712). The sources have no wind direction |
| CLOUD | **tenths 0-10** | `srad_wm2` | one value per local day with the model's own relation `SRO = (1 - 0.0065 CLOUD^2) SRO_clear`; a day with no daylight in the series takes the nearest day's value |
| SRO | W/m^2 | `srad_wm2` | as it is. Used by the model only when SROC is ON |

A summary is written to `<output>.summary.json` (source, point, step, period, means, what was estimated).

### No made-up values

A missing or non-finite value, an uneven time axis, a value outside its physical range (wrong unit upstream) or a period the source does not fully cover stops the tool with a clear error. Nothing is written. Do not repair this by hand-writing a met file: fix the period or pick another source.

### Step 3: Check the met file

- `head -4`: line 1 starts with `$`, line 3 is the column line, line 4 is the first data row.
- CLOUD between 0 and 10 with overcast days near 8-10 (dt_001).
- TDEW never above TAIR; not near -40 (dt_002).
- PHI between 0 and 6.29 (dt_031).
- First JDAY at or before TMSTRT and last JDAY at or after TMEND (dt_009). The tool moves the UTC stamps to local standard time and reads the neighbouring UTC year (the year before, east of Greenwich; the year after, west) so the file covers the local years fully, JDAY 1.0 to the end. If the source does not have that extra year the tool stops; `--no_edge_padding` skips it, and the file then misses the first or last local hours (start and end the run inside the JDAY range in `<output>.summary.json`).
- The summary's annual mean air temperature is believable for the place.

## Expected Outputs

| Output | Path | Verification |
|--------|------|-------------|
| Met file | name given by `--output` | checks above |
| Summary | `<output>.summary.json` | `status` = success |

## Proven case (2026-10-03)

DeGray Lake, Arkansas (34.2, -93.1), 1980, `--source mswx`: TAIR, WIND and SRO in the file equal the loader's values step by step; the met file replaced the example's `met.npt` and the v5 binary ran to the end with the control file unchanged. The numbers are in the run's `result.json`.

## Common Pitfalls

| Pitfall | Triplet | How to detect |
|---------|---------|--------------|
| Cloud as fraction 0-1 (3-5 C warm) | dt_001 | Max cloud < 2 |
| Dew point from a wrong vapour-pressure unit | dt_002 | TDEW always < -30 C |
| Integer Julian days | dt_005 | All JDAY are whole numbers |
| Wind direction in degrees | dt_031 | PHI above 6.29 |
| UTC stamps written as local time | dt_031 | daily maximum of SRO not near JDAY x.5 |
| Met file shorter than the run | dt_009 | Last JDAY < TMEND |
| Constant columns from a made-up fill | dt_027 | a column that never changes (PHI is the one allowed constant) |
| Met file from VIC forcing files | dt_026 | `--vic_forcing_dir` no longer exists |
