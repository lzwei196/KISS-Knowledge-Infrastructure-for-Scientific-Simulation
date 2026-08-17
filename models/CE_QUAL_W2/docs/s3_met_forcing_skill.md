# s3: Meteorological Forcing Conversion — Skill Document

## Purpose

Convert HydroCraft forcing data (CMFD/MSWX/VIC) to CE-QUAL-W2 met file format. This stage performs the most dangerous unit conversions in the entire pipeline. Getting these wrong produces NO error message — just silently wrong water temperatures.

## Prerequisites

- [ ] Forcing data available for the simulation period (CMFD, MSWX, or VIC forcing files)
- [ ] Reservoir latitude and longitude known
- [ ] Start and end years defined in s0_config

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| Forcing directory | Directory | CMFD/MSWX/VIC | Raw meteorological data |
| Latitude | Number | s0_config | Reservoir latitude (degrees) |
| Longitude | Number | s0_config | Reservoir longitude (degrees) |
| Start year | Integer | s0_config | First year of simulation |
| End year | Integer | s0_config | Last year of simulation |

## Procedure

### Step 1: Select forcing source

| Condition | Dataset | Path |
|-----------|---------|------|
| China, 1979-2018 | CMFD | `data/forcing/Data_forcing_03hr_010deg/` |
| Global, 1979-2026 | MSWX | `KISSPATH_FORCING/` |
| VIC pre-processed | VIC forcing | `outputs/<run>/vic_temp/forcing/forcing_final/` |

### Step 2: Run convert_met_to_w2

```bash
python tools/s3_met_forcing/convert_met_to_w2.py \
    --vic_forcing_dir outputs/<run>/vic_temp/forcing/forcing_final \
    --lat <lat> --lon <lon> \
    --start_year <start> --end_year <end> \
    --output <run_dir>/met_wb1.npt
```

### Step 3: Validate met file — CRITICAL CHECKS

**Cloud cover range (dt_001)**:
- Read max cloud value: should be 8-10 for overcast days
- If max cloud < 2.0: data is in fraction (0-1) — MULTIPLY BY 10
- If max cloud > 100: data is in percent — DIVIDE BY 10

**Dewpoint sanity (dt_002)**:
- TDEW should always be <= TAIR
- If TDEW is consistently < -30 C: VP units are wrong (Pa instead of kPa)
- Typical range: -20 to +25 C

**Julian day format (dt_005)**:
- JDAY should have 3 decimal places (e.g., 1.000, 1.125, 1.250)
- If all JDAY are integers (1.000, 2.000): only daily resolution (may be acceptable)
- JDAY should start at TMSTRT and end at or beyond TMEND

## Expected Outputs

| Output | Path | Verification |
|--------|------|-------------|
| Met file | `met_wb1.npt` | `head -5 met_wb1.npt` shows JDAY, TAIR, TDEW, WIND, WDIR, CLOUD, SRO |
| JSON result | stdout | Status = success, n_timesteps > 0 |

## Validation Checks

1. Cloud cover max is 8-10 (not 0.8-1.0): `awk '{if(NR>2) print $6}' met_wb1.npt | sort -n | tail -1`
2. TDEW always <= TAIR: `awk '{if(NR>2 && $3>$2+1) print "WARNING TDEW>TAIR at JDAY",$1}' met_wb1.npt`
3. JDAY coverage: first JDAY >= TMSTRT, last JDAY >= TMEND
4. No NaN or blank lines in data section

## Common Pitfalls

| Pitfall | Triplet | How to detect |
|---------|---------|--------------|
| Cloud as fraction 0-1 (3-5 C warm) | dt_001 | Max cloud < 2 |
| VP in Pa instead of kPa | dt_002 | TDEW always < -30 C |
| Integer Julian days | dt_005 | All JDAY are whole numbers |
| Wind direction degrees vs radians | dt_004 | Values > 6.28 = degrees (correct for v4.x) |
| Met file shorter than simulation | dt_009 | Last JDAY < TMEND |

### Unit Conversion Table (MEMORIZE THIS)

| CE-QUAL-W2 Variable | W2 Unit | CMFD/MSWX Source | Conversion |
|---------------------|---------|------------------|------------|
| TAIR | deg C | deg C | Direct |
| TDEW | deg C | VP (kPa) | `TDEW = (237.3*ln(VP/0.6108))/(17.27-ln(VP/0.6108))` |
| WIND | m/s | m/s | Direct |
| WDIR | degrees | Not available | Default 270 (westerly) |
| CLOUD | **TENTHS (0-10)** | Derive from SW | `10 * (1 - SW/SW_clearsky)` |
| SRO | W/m^2 | SW_DOWN (W/m^2) | Direct, clip >= 0 |
