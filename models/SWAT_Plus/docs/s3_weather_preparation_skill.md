# Weather Data Preparation — Skill Document

> **Stage ID**: s3_weather_preparation
> **Pipeline order**: 3 of 9
> **Depends on**: s1_watershed_delineation (for station locations)

## Purpose

SWAT+ requires daily meteorological forcing as the primary driver of hydrological processes. Weather data must be provided in a specific multi-file format: five variable types, each with individual station files and a .cli index file, plus a weather-sta.cli mapping and a weather generator (wgn.wgn). Incorrect weather preparation is the most common source of silent errors in SWAT+ simulations, because the model will run with wrong data without any error message.

## Prerequisites

Before starting this stage, verify:

- [ ] Subbasin centroids computed from S1 (for nearest-station assignment)
- [ ] Source forcing data covers the simulation period plus warmup years
- [ ] Source data contains all 5 variables: precipitation, temperature (max+min), solar radiation, relative humidity, wind speed
- [ ] For CMFD: data directory at `data/forcing/Data_forcing_03hr_010deg/`
- [ ] For MSWX: data directory at `/mnt/disk3/msxw/`
- [ ] Python environment with xarray, netCDF4, pandas

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| Forcing data | directory | CMFD / MSWX / CSV / NASA POWER | Raw meteorological data |
| Station coordinates | config | Grid cell centers or real station locations | Lat/lon pairs for weather stations |
| Start/end dates | string | User | Simulation period (YYYY-MM-DD) |
| Subbasin centroids | config | From S1 | For nearest-station assignment in weather-sta.cli |

## Procedure

### Step 1: Determine station locations

Define weather station locations. Options:
- **Gridded data** (CMFD, MSWX): Use grid cell centers within/near the basin as station locations
- **Real stations**: Use actual meteorological station coordinates
- **Single station**: One station for the entire basin (acceptable for small basins <500 km2)

**Expected result**: List of station coordinates with unique names.

### Step 2: Extract and convert weather data

```bash
python tools/s3/prepare_weather_files.py
```

For each station, extract daily values from the source and write SWAT+ format files.

**SWAT+ weather file format** (all 5 types follow this pattern):

```
Station precipitation data          <-- Line 1: title (free text)
nbyr       tstep      lat         lon         elev       <-- Line 2: column headers
10         0          32.500      116.800     45.0       <-- Line 3: metadata
2000       1          0.00                               <-- Line 4+: year jday value(s)
2000       2          5.20
```

Variable-specific formats:
- **.pcp**: year, jday, precip (mm)
- **.tmp**: year, jday, tmp_max (C), tmp_min (C)
- **.slr**: year, jday, solar radiation (MJ/m2)
- **.hmd**: year, jday, relative humidity (fraction 0-1)
- **.wnd**: year, jday, wind speed (m/s)

**Critical unit conversions from CMFD/MSWX**:
| Variable | Source Unit (CMFD) | SWAT+ Unit | Conversion |
|----------|-------------------|------------|------------|
| Temperature | K | C | subtract 273.15 |
| Precipitation | mm/3hr | mm/day | sum 8 timesteps |
| Solar radiation | W/m2 | MJ/m2/day | multiply by 0.0864 (avg W/m2 -> MJ/m2/day) |
| Relative humidity | specific humidity (kg/kg) | fraction (0-1) | compute from q, T, P |
| Wind speed | m/s | m/s | no conversion needed |

**If this fails**: See diagnostic triplet dt_002 (format error) or dt_012 (unit error).

### Step 3: Generate .cli index files

For each variable, create a .cli file listing all station file names:

```
Precipitation station files
filename
p000001.pcp
p000002.pcp
```

**Expected result**: pcp.cli, tmp.cli, slr.cli, hmd.cli, wnd.cli in TxtInOut.

### Step 4: Generate weather-sta.cli

```bash
python tools/s3/generate_weather_stations.py
```

Map station combinations to spatial objects. Each record in weather-sta.cli has:
- Station name
- pcp station name (from pcp.cli)
- tmp station name (from tmp.cli)
- slr station name (from slr.cli)
- hmd station name (from hmd.cli)
- wnd station name (from wnd.cli)

SWAT+ assigns the nearest weather-sta.cli record to each spatial object centroid.

**Expected result**: weather-sta.cli with one record per unique station combination.

### Step 5: Generate weather generator (wgn.wgn)

Compute monthly climate statistics for each station:
- Monthly mean max/min temperature, standard deviation
- Monthly mean precipitation, number of wet days, skew coefficient
- Monthly mean solar radiation, dew point temperature
- Probability of wet day following wet/dry day

**Expected result**: wgn.wgn with 12 monthly rows per station. Even if observed data is complete, SWAT+ reads wgn.wgn at startup.

### Step 6: Validate weather data

```bash
python tools/s3/validate_weather_data.py
```

**Expected result**: All files pass QC checks (no Tmax < Tmin, no negative precip, no values outside physical ranges).

**If this fails**: See diagnostic triplet dt_003 (Tmax < Tmin).

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| *.pcp files | `TxtInOut/*.pcp` | 3-line header + daily rows; precip >= 0; no NaN |
| *.tmp files | `TxtInOut/*.tmp` | 3-line header + daily rows; Tmax >= Tmin |
| *.slr files | `TxtInOut/*.slr` | 3-line header + daily rows; 0 <= solar <= 40 MJ/m2 |
| *.hmd files | `TxtInOut/*.hmd` | 3-line header + daily rows; 0 <= RH <= 1 |
| *.wnd files | `TxtInOut/*.wnd` | 3-line header + daily rows; wind >= 0 |
| pcp.cli | `TxtInOut/pcp.cli` | Lists all .pcp files |
| weather-sta.cli | `TxtInOut/weather-sta.cli` | Maps stations to spatial objects |
| wgn.wgn | `TxtInOut/wgn.wgn` | 12 monthly rows per station |

## Validation Checks

1. **Header line count**: Each weather file must have exactly 3 header lines, then data.
   - Command: `head -5 TxtInOut/p000001.pcp` — line 4 should be first data row
   - If wrong: See diagnostic triplet dt_002

2. **Temperature consistency**: Tmax >= Tmin for every row in every .tmp file.
   - If violated: See diagnostic triplet dt_003

3. **Precipitation non-negative**: All precip values >= 0.
   - Negative precipitation causes mass balance errors

4. **Solar radiation range**: 0 to ~40 MJ/m2/day (varies by latitude and season).
   - If values >50: Wrong units (likely W/m2 instead of MJ/m2). See dt_012.

5. **Date continuity**: No gaps in daily sequence (year, jday).

6. **Station count consistency**: Number of files listed in pcp.cli = number of .pcp files in TxtInOut.

## Common Pitfalls

> **PITFALL**: Solar radiation in W/m2 instead of MJ/m2/day
> CMFD provides instantaneous W/m2. SWAT+ expects daily total MJ/m2/day. Forgetting the conversion (multiply by 0.0864 for daily average) gives radiation ~12x too high. The model still runs but ET is massively overestimated.
> **Do this instead**: Convert W/m2 to MJ/m2/day: daily_MJ = daily_mean_W * 86400 / 1e6.
> See diagnostic triplet dt_012.

> **PITFALL**: Relative humidity as percentage instead of fraction
> SWAT+ expects RH as a fraction (0-1). Providing percentage values (0-100) makes RH = 60.0, which SWAT+ may interpret as 6000%. Silent error.
> **Do this instead**: Divide percentage values by 100.

> **PITFALL**: Missing wgn.wgn weather generator file
> Even with complete observed weather data, SWAT+ reads wgn.wgn at initialization. If missing, the simulation crashes immediately.
> **Do this instead**: Always generate wgn.wgn, even if weather data has no gaps.

> **PITFALL**: Wrong number of header lines in weather files
> SWAT+ expects exactly 3 header lines. Extra blank lines or missing headers cause data parsing to shift by N rows, reading header text as numbers.
> See diagnostic triplet dt_002.

---

*This skill document is part of the SWAT+ knowledge infrastructure.*
*Stage 3 of 9 | Tools used: prepare_weather_files, generate_weather_stations, validate_weather_data | Related triplets: dt_002, dt_003, dt_012*
