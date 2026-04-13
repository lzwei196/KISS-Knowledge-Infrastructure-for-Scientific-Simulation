# CRHM Execution -- Skill Document

> **Stage ID**: s5_execution
> **Pipeline order**: 5 of 6
> **Depends on**: s2_observation_data, s4_parameter_config

## Purpose

Run the CRHM executable with the configured .prj file, capture output, and parse results into structured formats for analysis and visualization. CRHM is a C++ executable that reads the .prj file, loads observation data, runs the module chain for each timestep, and writes tab-delimited output. Execution is fast (seconds to minutes for most basins) but errors in .prj or .obs files may cause crashes or silent data corruption.

## Prerequisites

- [ ] CRHM executable built and accessible (`model/crhmcode/crhmcode/build/crhm`)
- [ ] .prj file validated (validate_prj passes)
- [ ] .obs file validated (validate_obs_file passes)
- [ ] Output directory exists

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| crhm_exe | file | CRHM build | Path to crhm executable |
| prj_path | file | s4_parameter_config | Validated .prj project file |
| output_path | file | User choice | Output file path |
| obs_dir | directory | s2_observation_data | Observation file directory (optional) |

## Procedure

### Step 1: Verify executable

```bash
ls -la /mnt/disk1/Hydrocraft_server/model/crhmcode/crhmcode/build/crhm
```

If not built, run `install_crhm.sh` first.

Verify it works:
```bash
/mnt/disk1/Hydrocraft_server/model/crhmcode/crhmcode/build/crhm --help
```

### Step 2: Run CRHM

```bash
python tools/s5_execution/run_crhm.py \
  --crhm_exe /mnt/disk1/Hydrocraft_server/model/crhmcode/crhmcode/build/crhm \
  --prj_path outputs/<run>/crhm/basin.prj \
  --output_path outputs/<run>/crhm/crhm_output.txt \
  --obs_dir outputs/<run>/crhm/obs \
  --progress 100
```

**Expected result**: Exit code 0, non-empty output file.

**If exit code non-zero**: See dt_008 (runtime error), dt_014 (module crash).

### Step 3: Verify output

Check that the output file has:
- Line 1: Tab-separated variable names
- Line 2: Tab-separated units
- Line 3+: Data (date + values)

```bash
head -3 outputs/<run>/crhm/crhm_output.txt
wc -l outputs/<run>/crhm/crhm_output.txt
```

Expected line count: approximately (end_year - start_year + 1) * 365 + 2 (for daily output).

### Step 4: Parse output to CSV/NetCDF

```bash
python tools/s5_execution/parse_crhm_output.py \
  --output_path outputs/<run>/crhm/crhm_output.txt \
  --output_format both \
  --output_dir outputs/<run>/crhm/parsed
```

**Expected result**: `crhm_results.csv` and `crhm_results.nc` in parsed directory.

**If parse fails**: Check date format. CRHM supports 3 formats (ISO, MS, YYYYMMDD). See dt_014.

### Step 5: Generate diagnostic plots

```bash
python tools/s5_execution/plot_crhm_results.py \
  --csv_path outputs/<run>/crhm/parsed/crhm_results.csv \
  --output_dir outputs/<run>/crhm/plots \
  --title "<Basin Name>"
```

**Expected result**: PNG plots for SWE, discharge, water balance, cold regions diagnostics.

### Step 6: Sanity check results

Verify results are physically reasonable:
- **SWE**: Should peak in late winter/early spring, go to zero in summer
- **Discharge**: Should peak during spring snowmelt
- **Sublimation**: Should be 15-40% of snowfall in prairie, 30-50% in boreal forest
- **Soil moisture**: Should increase during snowmelt, decrease during growing season

If SWE never reaches zero in summer, check humidity conversion (dt_001).
If discharge peaks are too sharp, check timestep and infiltration parameters.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| Raw output | `outputs/{run}/crhm/crhm_output.txt` | Non-empty, correct line count |
| Parsed CSV | `outputs/{run}/crhm/parsed/crhm_results.csv` | Has datetime column, numeric data |
| Parsed NetCDF | `outputs/{run}/crhm/parsed/crhm_results.nc` | xarray-readable with time dim |
| SWE plot | `outputs/{run}/crhm/plots/swe_timeseries.png` | SWE peaks in winter |
| Discharge plot | `outputs/{run}/crhm/plots/discharge_timeseries.png` | Spring peak |

## Validation Checks

1. **Non-zero exit code**: CRHM exited successfully
   - If non-zero: Check stderr for module name + error message. See dt_008.

2. **Output file non-empty**: Contains data rows
   - If empty: CRHM ran but produced no output. Check Display_Variable section in .prj. See dt_014.

3. **SWE seasonal cycle**: SWE should go to zero each summer (for non-glaciated basins)
   - If SWE never melts: Humidity or radiation error. See dt_001.
   - If SWE is always zero: No snowfall reaching ground. Check precipitation threshold.

4. **Mass balance**: Over multiple years, P - ET - Q - dS should approximately zero
   - If large imbalance: Module chain may have disconnected components.

## Common Pitfalls

> **PITFALL**: Observation file path not found at runtime
> CRHM resolves .obs paths relative to the WORKING DIRECTORY when the executable is invoked, not relative to the .prj file location. If you run CRHM from a different directory, the obs path in .prj won't resolve.
> **Do this instead**: Use absolute paths in .prj, or use `--obs_file_directory` flag when invoking CRHM.
> See diagnostic triplet dt_007.

> **PITFALL**: Output file is empty despite exit code 0
> If no variables are listed in the Display_Variable section of the .prj file, CRHM runs the simulation but writes an empty output file. This is not treated as an error.
> **Do this instead**: Always specify at least SWE, snowmelt, runoff, WS_outflow in Display_Variable.
> See diagnostic triplet dt_014.

> **PITFALL**: Parsing units row as data
> CRHM STD format has 2 header rows: variable names, then units (e.g., "(mm)", "(W/m^2)"). If you parse starting from row 2 instead of row 3, the units row gets interpreted as data, converting the entire column to object/string dtype.
> **Do this instead**: Use parse_crhm_output.py which correctly skips the units row. If parsing manually, skip rows 0 and 1.

> **PITFALL**: Boost library not found at runtime
> If CRHM was built with static Boost, this is not an issue. But if dynamically linked, the Boost 1.75.0 libraries must be on LD_LIBRARY_PATH.
> **Do this instead**: Build with static linking (CMake default), or set `export LD_LIBRARY_PATH=/path/to/boost/lib:$LD_LIBRARY_PATH`.
> See diagnostic triplet dt_017.

---

*This skill document is part of the hydrocraft-crhm knowledge infrastructure.*
*Stage 5 of 6 | Tools used: run_crhm, parse_crhm_output, plot_crhm_results | Related triplets: dt_007, dt_008, dt_014, dt_017*
