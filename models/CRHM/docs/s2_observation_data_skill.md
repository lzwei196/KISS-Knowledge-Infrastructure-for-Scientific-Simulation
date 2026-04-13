# Observation Data Preparation -- Skill Document

> **Stage ID**: s2_observation_data
> **Pipeline order**: 2 of 6
> **Depends on**: none (can run in parallel with s1)

## Purpose

Prepare meteorological observation files in CRHM's `.obs` format. This is the model's sole input for weather data. If the .obs file has wrong units, missing timesteps, or incorrect variable declarations, CRHM will either crash or -- more dangerously -- run to completion with scientifically meaningless results. The most critical conversion is humidity: VIC uses specific humidity (kg/kg, values ~0.001-0.02) while CRHM expects relative humidity (%, values 0-100). Passing specific humidity as relative humidity makes the atmosphere appear essentially dry, suppressing all sublimation and evaporation.

## Prerequisites

- [ ] Weather station data OR VIC forcing files available
- [ ] Time period and timestep determined
- [ ] Python environment activated

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| forcing_dir | directory | VIC forcing pipeline or station data | Meteorological data files |
| grid_nc | file | VIC grid generation (Step 1) | VIC basin grid for coordinate lookup |
| start_year | number | User configuration | Start of simulation period |
| end_year | number | User configuration | End of simulation period |

## Procedure

### Step 1: Determine data source

CRHM can use data from:
- **Weather stations** (native .obs files): Best quality. One station per `nobs` declaration.
- **VIC forcing files** (converted): For VIC-CRHM coupling. Must convert format and units.
- **Reanalysis products** (e.g., ERA5): Global coverage but requires formatting.

For VIC coupling, use `convert_vic_to_obs.py`.

### Step 2: Convert VIC forcing to CRHM .obs

```bash
python tools/s2_observation_data/convert_vic_to_obs.py \
  --forcing_dir outputs/<run>/vic_temp/forcing/forcing_final \
  --grid_nc outputs/<run>/vic_temp/grid/basin_grid.nc \
  --output_path outputs/<run>/crhm/obs/basin.obs \
  --start_year <start> --end_year <end> \
  --timestep 3
```

**Expected result**: .obs file with header variables and continuous data rows.

**If this fails**: See dt_001 (unit conversion error) or dt_003 (obs format error).

### Step 3: Validate the observation file

```bash
python tools/s2_observation_data/validate_obs_file.py \
  --obs_path outputs/<run>/crhm/obs/basin.obs
```

**Expected result**: JSON report with status "PASS", no errors.

**If validation fails**: See dt_003 (format), dt_011 (winter gaps), dt_018 (timestep mismatch).

### Step 4: Verify unit conversion table

Before proceeding, manually verify this unit table:

| Variable | Source unit (VIC) | Target unit (CRHM) | Conversion | Silent if wrong? |
|----------|-------------------|---------------------|------------|------------------|
| Temperature (t) | degrees C | degrees C | None | No |
| Rel. humidity (rh) | kg/kg (specific) | % (relative) | Formula: RH = e/es*100 | **YES** -- dt_001 |
| Wind speed (u) | m/s | m/s | None | No |
| Precipitation (ppt) | mm/timestep | mm/d | *24/timestep_hours | **YES** -- dt_002 |
| Shortwave (Qsi) | W/m2 | W/m2 | None | No |
| Longwave (Qli) | W/m2 | W/m2 | None | No |
| Pressure (p) | kPa | kPa | None | No |

**If humidity is passed as specific humidity (0.001-0.02) instead of relative humidity (0-100%), CRHM interprets the atmosphere as having 0.001-0.02% RH. All sublimation and evaporation go to near-zero. SWE accumulates without limit. This is the #1 silent error in VIC-CRHM coupling.**

### Step 5: Check computed variables

CRHM .obs files can declare computed variables with `$` prefix:
- `$ea ea(t, rh) (kPa) vapour pressure` -- computes vapor pressure from t and rh
- `$Qsi mul(Qsi, 277.8)` -- unit conversion multiplier

Verify computed variable formulas reference variables declared earlier in the header.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| .obs file | `outputs/{run}/crhm/obs/basin.obs` | File > 0 bytes, validate_obs_file passes |

## Validation Checks

1. **Variable declarations present**: At minimum `t` and `ppt`
   - Command: `head -10 basin.obs | grep -c "^t \|^ppt "`
   - Expected: 2 (both found)
   - If missing: .obs header is malformed. See dt_003.

2. **No datetime gaps**: Continuous timestep sequence
   - Command: validate_obs_file.py reports n_gaps
   - Expected: 0 gaps
   - If gaps: Winter station outages are common in cold regions. See dt_011.

3. **Values within physical bounds**:
   - Temperature: -80 to 60 C
   - RH: 0 to 100% (NOT 0 to 1 -- if max is ~0.02, units are wrong!)
   - Wind: 0 to 80 m/s
   - Precip: 0 to 500 mm/d

4. **Column count matches declarations**:
   - Count data columns = sum of all declared variable column counts
   - If mismatch: Extra or missing columns. CRHM reads by column position.

## Common Pitfalls

> **PITFALL**: Specific humidity passed as relative humidity (SILENT ERROR)
> VIC forcing may provide specific humidity (kg/kg, values ~0.001-0.02). CRHM expects relative humidity (%, values 0-100). If you pass specific humidity directly, CRHM interprets the atmosphere as 0.001-0.02% RH (bone dry). Sublimation drops to zero. SWE accumulates indefinitely.
> **Do this instead**: Use convert_vic_to_obs.py which applies the Tetens formula conversion. Always check that RH values are 0-100%, not 0-1 or 0-0.02.
> See diagnostic triplet dt_001.

> **PITFALL**: Precipitation rate vs accumulation (SILENT ERROR)
> VIC forcing gives precipitation per timestep (mm/3h). CRHM expects mm/d rate. If 3-hourly precip is passed directly, CRHM receives 8x too much precipitation daily, producing unrealistic flood peaks.
> **Do this instead**: convert_vic_to_obs.py multiplies by 24/timestep_hours. Verify by comparing daily total against known values.
> See diagnostic triplet dt_002.

> **PITFALL**: Winter observation gaps in station data
> Cold-region weather stations often fail during extreme cold (-40C), blizzards, or rime icing. Gap-filled data may have artificial constant values during these periods. CRHM does not interpolate -- it reads whatever is in the file.
> **Do this instead**: Use validate_obs_file.py to detect gaps. Fill short gaps (<3 days) with linear interpolation. For longer gaps, use nearby station data or reanalysis.
> See diagnostic triplet dt_011.

> **PITFALL**: Observation file path in .prj is relative to working directory
> CRHM resolves observation file paths relative to the current working directory, NOT the .prj file location. If you run CRHM from a different directory, it cannot find the .obs file.
> **Do this instead**: Use absolute paths in the .prj Observations section, or use --obs_file_directory CLI flag.
> See diagnostic triplet dt_007.

---

*This skill document is part of the hydrocraft-crhm knowledge infrastructure.*
*Stage 2 of 6 | Tools used: convert_vic_to_obs, validate_obs_file | Related triplets: dt_001, dt_002, dt_003, dt_011, dt_018*
