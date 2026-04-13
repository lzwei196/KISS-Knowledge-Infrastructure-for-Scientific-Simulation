# Apply Deltas to VIC Forcing — Skill Document

> **Stage ID**: s3_apply_deltas
> **Pipeline order**: 3 of 4
> **Depends on**: s2_compute_deltas (delta file), VIC baseline forcing (forcing_1d output)

## Purpose

Generate future VIC forcing files by applying CMIP6 monthly climate change deltas to the existing CMFD/MSWX baseline forcing. This preserves the sub-daily variability and all 7 meteorological variables from the baseline while incorporating projected changes in temperature and precipitation.

## Prerequisites

Before starting this stage, verify:

- [ ] Delta file exists: `deltas/{MODEL}_{ssp}_deltas_{basin}_{period}.nc`
- [ ] Baseline forcing_1d files exist: `outputs/{basin}/vic_temp/forcing/forcing_1d/temp_*.nc`, `prec_*.nc`, etc.
- [ ] VIC grid file exists
- [ ] Python environment activated

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| BASELINE_FORCING_DIR | directory | VIC workflow | `outputs/{basin}/vic_temp/forcing/forcing_1d/` |
| DELTA_FILE | file | Stage 2 | Monthly delta NetCDF file |
| GRID_NC | file | VIC grid | Basin grid file |
| TARGET_YEARS | year range | User choice | Years to generate forcing for |

## Procedure

### Step 1: Choose target period

The target period should match the FUTURE_PERIOD used in delta computation. For a 30-year window:

```
FUTURE_PERIOD = 2041-2070
```

The tool cycles through baseline years to fill the target period. For example, if baseline is 1990-2000 (11 years), years 2041-2051 use baseline 1990-2000, years 2052-2062 reuse 1990-2000, etc.

### Step 2: Run delta application

```bash
python skills/climate-projection/tools/s3_apply_deltas/apply_deltas_forcing.py \
  outputs/{basin}/vic_temp/forcing/forcing_1d \
  outputs/{basin}/climate_projection/deltas/{MODEL}_{ssp}_deltas_{basin}_2041-2070.nc \
  outputs/{basin}/vic_temp/grid/basin_grid.nc \
  outputs/{basin}/climate_projection/forcing_{MODEL}_{ssp} \
  {basin} {MODEL} {ssp} \
  2041 2070
```

**Expected result**: 7 variables × 30 years = 210 NetCDF files in `forcing_{MODEL}_{ssp}/`

**Runtime**: 5-15 minutes (reads and rewrites all forcing files).

### Step 3: Convert projected forcing NC → VIC ASCII

Use the dedicated conversion tool (NOT `process_forcing.py`, which requires error-prone config editing):

```bash
python skills/climate-projection/tools/s3_apply_deltas/convert_projected_forcing.py \
  outputs/{basin}/climate_projection/forcing_{MODEL}_{ssp} \
  outputs/{basin}/climate_projection/forcing_final_{MODEL}_{ssp} \
  outputs/{basin}/vic_temp/soil/SOIL_PARAM_COMPLETE.txt \
  "{forcing_prefix}" "{basin_tag}" \
  2041 2070
```

Where:
- `{forcing_prefix}` matches the baseline prefix (e.g., `nuxia_0.25deg_`). Check with: `ls outputs/{basin}/vic_temp/forcing/forcing_final/ | head -1`
- `{basin_tag}` is the suffix used in NC filenames (usually the basin name from config_paths.py)

**Expected result**: One ASCII file per grid cell in `forcing_final_{MODEL}_{ssp}/`, each with 87,664 lines (30 years × 365.25 days × 8 timesteps/day). 7 columns: air_temp, prec, pressure, swdown, lwdown, vp, wind.

**Runtime**: ~2-5 minutes per SSP scenario.

### Step 4: Verify projected forcing

```bash
# Check file count matches grid cells
ls outputs/{basin}/climate_projection/forcing_final_{MODEL}_{ssp}/ | wc -l

# Check line count (should be ~87,664 for 30 years of 3-hourly data)
wc -l outputs/{basin}/climate_projection/forcing_final_{MODEL}_{ssp}/* | tail -1

# Spot-check temperature (should be in Celsius, not Kelvin)
head -3 outputs/{basin}/climate_projection/forcing_final_{MODEL}_{ssp}/*_30.0000_*
```

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| Projected forcing NC | `forcing_{MODEL}_{ssp}/temp_*_{year}.nc` | One per variable per year |
| Projected forcing ASCII | `forcing_final_{MODEL}_{ssp}/` | One per grid cell, matching VIC format |

## Validation Checks

1. **Temperature increase**: Mean annual temperature in projected forcing > baseline
2. **Variable completeness**: All 7 variables present (not just temp and prec)
3. **No NaN values**: Projected forcing should have no gaps
4. **Non-negative precipitation**: All precip values >= 0 after multiplicative scaling

## Common Pitfalls

> **PITFALL**: Using `process_forcing.py` instead of `convert_projected_forcing.py`
> The old approach required editing hardcoded paths in `process_forcing.py` (INPUT_DATA_DIR, START_DATE, etc.) — error-prone and not reusable.
> **Do this instead**: Use `convert_projected_forcing.py` which takes all parameters as CLI arguments.
> See diagnostic triplet dt_cc_006.

> **PITFALL**: Time coordinate mismatch
> When cycling baseline years into future years, leap year handling may differ. The tool adjusts the time coordinate, but Feb 29 may be dropped or added.
> **Do this instead**: Use process_forcing.py with `CALENDAR_AWARE=True` if available.

---

*This skill document is part of the climate-projection knowledge infrastructure.*
*Stage 3 of 4 | Tools used: apply_deltas_forcing | Related triplets: dt_cc_006, dt_cc_007*
