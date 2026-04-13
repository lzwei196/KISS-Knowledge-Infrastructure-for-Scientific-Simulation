# Parameter Configuration -- Skill Document

> **Stage ID**: s4_parameter_config
> **Pipeline order**: 4 of 6
> **Depends on**: s1_basin_setup, s3_module_selection

## Purpose

Set module parameters in the .prj project file for each HRU. CRHM parameters control the physics of every module: blowing snow fetch distances, soil hydraulic conductivity, vegetation height, infiltration state, and routing coefficients. Each parameter has a declared valid range (e.g., `<0.001 to 100.0>`). Parameters outside this range are silently clamped to the boundary value -- CRHM does NOT warn you. This is a dangerous silent error: you think you set fetch=50000m but CRHM uses max=10000m.

## Prerequisites

- [ ] HRU configuration complete (hru_config.json from s1)
- [ ] Module chain selected (modules.json from s3)
- [ ] Observation file created (basin.obs from s2)
- [ ] Python environment activated

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| hru_config | file | s1_basin_setup | HRU definitions |
| module_chain | file | s3_module_selection | Module chain JSON |
| obs_path | file | s2_observation_data | Observation file |
| start_date | string | User configuration | Start date "YYYY M D" |
| end_date | string | User configuration | End date "YYYY M D" |

## Procedure

### Step 1: Generate initial .prj file

```bash
python tools/s4_parameter_config/create_prj_file.py \
  --hru_config outputs/<run>/crhm/hru/hru_config.json \
  --module_chain outputs/<run>/crhm/modules.json \
  --obs_path outputs/<run>/crhm/obs/basin.obs \
  --start_date "<YYYY> <M> <D>" \
  --end_date "<YYYY> <M> <D>" \
  --output_path outputs/<run>/crhm/basin.prj
```

**Expected result**: .prj file with all sections populated.

**If this fails**: See dt_005 (parameter format error) or dt_013 (section delimiter error).

### Step 2: Review critical parameters

These parameters have the highest impact on cold regions simulation quality:

**PBSM (Blowing Snow)**:
| Parameter | Description | Typical Range | Critical Because |
|-----------|-------------|---------------|------------------|
| fetch | Fetch distance (m) | 300-3000 | Controls snow transport rate. Too high = too much drift |
| Ht | Vegetation height (m) | 0.01-20 | Traps blowing snow. Stubble vs forest |
| distrib | Distribution factor | 0-5 | Controls drift pattern |

**SnobalCRHM (Energy Balance Melt)**:
| Parameter | Description | Typical Range | Critical Because |
|-----------|-------------|---------------|------------------|
| T_g | Ground temperature (C) | -4 to 0 | Bottom boundary of snowpack energy balance |
| z_u | Wind measurement height (m) | 2-10 | Turbulent exchange coefficient |
| max_z_s_0 | Max active layer depth (m) | 0.05-0.5 | Snowpack thermal layering |

**PrairieInfil (Frozen Soil)**:
| Parameter | Description | Values | Critical Because |
|-----------|-------------|--------|------------------|
| fallstat | Fall moisture condition | 0-3 (dry to saturated) | Determines how much water can infiltrate frozen soil |
| major | Major melt event index | 0-5 | Controls infiltration during peak melt |

**Soil**:
| Parameter | Description | Typical Range | Critical Because |
|-----------|-------------|---------------|------------------|
| soil_Depth | Total soil depth (m) | 0.5-5 | Total water storage capacity |
| soil_rechr_max | Recharge zone max (mm) | 20-200 | Shallow soil responsiveness |
| soil_moist_max | Total moisture max (mm) | 50-1000 | Overall storage |

### Step 3: Adjust HRU-specific parameters

For parameters marked `per_hru: true`, provide one value per HRU. The order MUST match the HRU order in hru_config.json. Values are space-separated, with line breaks every 16 values for readability.

Example for nhru=5:
```
PBSM fetch <10 to 10000>
1500.0 1500.0 200.0 50.0 30.0
```
Here: HRU 1-2 are open prairie (1500m fetch), HRU 3 is shrub (200m), HRU 4-5 are forest (50-30m).

### Step 4: Validate the .prj file

```bash
python tools/s4_parameter_config/validate_prj.py \
  --prj_path outputs/<run>/crhm/basin.prj
```

**Expected result**: Status "PASS", no errors.

**If this fails**: See dt_005 (range violation), dt_013 (format error).

### Step 5: Set output variables (Display_Variable section)

Choose which variables to output. Critical cold regions diagnostics:
- **SWE**: Snow water equivalent (mm) -- the primary state variable
- **snowmelt**: Daily snowmelt depth (mm)
- **Subl**: Sublimation (mm) -- canopy + surface
- **drift_in, drift_out**: Blowing snow transport between HRUs (mm)
- **infil**: Infiltration into soil (mm)
- **runoff**: Surface runoff (mm)
- **soil_moist**: Soil moisture storage (mm)
- **WS_outflow**: Watershed outlet discharge (m3/s)

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| .prj file | `outputs/{run}/crhm/basin.prj` | validate_prj passes, all sections present |

## Validation Checks

1. **All required sections present**: Dimensions, Observations, Dates, Modules, Parameters
   - Command: `validate_prj.py --prj_path basin.prj`
   - Expected: PASS
   - If missing sections: See dt_013.

2. **Parameter values within ranges**: No value outside declared <min to max>
   - Command: validate_prj reports n_param_range_errors
   - Expected: 0
   - If violations: Fix values. CRHM silently clamps. See dt_006.

3. **Parameter count matches nhru**: Per-HRU params must have exactly nhru values
   - If mismatch: CRHM reads wrong values for HRUs. See dt_005.

4. **Observation file accessible**: Path in Observations section resolves
   - If not found: Use absolute path or --obs_file_directory. See dt_007.

5. **Date range within observation period**: Start/end must be covered by .obs file
   - If outside: CRHM may crash or read garbage data.

## Common Pitfalls

> **PITFALL**: Parameter values silently clamped to range boundaries
> CRHM clamps parameter values to the declared <min to max> range WITHOUT warning. If you set fetch=50000 but the max is 10000, CRHM uses 10000. Your parameter file looks correct but the model runs with different values than you intended.
> **Do this instead**: Always run validate_prj.py which checks all values against declared ranges. Treat any range violation as an error.
> See diagnostic triplet dt_006.

> **PITFALL**: Wrong number of parameter values for nhru
> If nhru=10 but you provide only 5 values for a per-HRU parameter, CRHM may read into the next parameter's values or crash with a cryptic error.
> **Do this instead**: Always provide exactly nhru values for per-HRU parameters. Use create_prj_file.py which auto-generates the correct count from hru_config.json.
> See diagnostic triplet dt_005.

> **PITFALL**: Section delimiter "######" must be exact
> The .prj format uses exactly 6 hash characters "######" as section delimiters. Using "#####" (5) or "#######" (7) causes CRHM to misparse the file. Section names must be on the line AFTER the delimiter, not the same line.
> **Do this instead**: Use create_prj_file.py which generates correct delimiters. If editing manually, count the hashes.
> See diagnostic triplet dt_013.

> **PITFALL**: Fetch distance wrong for landscape type
> Prairie fetch should be 300-3000m (wind travels far). Forest fetch should be 10-100m (trees block wind). Using prairie fetch values in forest HRUs produces massive unrealistic blowing snow transport.
> **Do this instead**: Set fetch based on land cover class. create_prj_file.py uses hru_config.json land cover to set appropriate defaults.

---

*This skill document is part of the hydrocraft-crhm knowledge infrastructure.*
*Stage 4 of 6 | Tools used: create_prj_file, validate_prj | Related triplets: dt_005, dt_006, dt_007, dt_013*
