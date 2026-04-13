# SUMMA Execution -- Skill Document

> **Stage ID**: s6_execution
> **Pipeline order**: 6 of 7
> **Depends on**: s1_domain_setup, s2_forcing_prep, s3_decisions, s4_parameters, s5_initial_conditions

## Purpose

Generate the master configuration file (fileManager.txt), validate all file references, run SUMMA, and parse the output. This is the culmination of all preparation stages. fileManager.txt is the single entry point that tells SUMMA where to find everything else.

## Prerequisites

- [ ] All prior stages complete (attributes, forcing, decisions, parameters, initial conditions)
- [ ] SUMMA executable built and tested (`summa.exe --help` prints usage)
- [ ] Output control file exists (defines which variables to write)
- [ ] Parameter lookup tables copied to settings directory (VEGPARM.TBL, etc.)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| settings_path | directory | output dir | Contains all settings files |
| forcing_path | directory | Stage 2 | Contains forcing NetCDF files |
| output_path | directory | output dir | Where SUMMA writes output |
| sim_start | string | user | Start time "YYYY-MM-DD hh:mm" |
| sim_end | string | user | End time "YYYY-MM-DD hh:mm" |
| summa_exe | file | installation | Path to summa.exe |

## Procedure

### Step 1: Create output control file

Create `outputControl.txt` in the settings directory. This defines which variables SUMMA writes to output.

```bash
cat > outputs/<run>/summa_settings/outputControl.txt << 'EOF'
! SUMMA output control file
! Format: varName | outFreq | sum | inst | mean | var | min | max | mode
! outFreq: 1=every timestep, 24=daily for hourly runs, etc.
! Statistics: 0=off, 1=on
! Recommended output set for hydrology:
scalarTotalRunoff      | 1 | 1 | 1 | 1 | 0 | 0 | 0 | 0
scalarTotalET          | 1 | 1 | 1 | 1 | 0 | 0 | 0 | 0
scalarSWE              | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0
scalarSnowDepth        | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0
scalarRainPlusMelt     | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0
scalarSurfaceRunoff    | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0
scalarSoilDrainage     | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0
scalarAquiferRecharge  | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0
scalarAquiferBaseflow  | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0
scalarNetRadiation     | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 0
scalarLatHeatTotal     | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 0
scalarSenHeatTotal     | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 0
mLayerVolFracLiq       | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0
mLayerTemp             | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0
EOF
```

### Step 2: Create fileManager.txt

```bash
python tools/s6_execution/create_file_manager.py \
  --settings_path /absolute/path/to/outputs/<run>/summa_settings/ \
  --forcing_path /absolute/path/to/outputs/<run>/summa_forcing/ \
  --output_path /absolute/path/to/outputs/<run>/summa_output/ \
  --sim_start "2000-01-01 00:00" \
  --sim_end "2010-12-31 23:00" \
  --output_prefix "summa_<basin>" \
  --output_file outputs/<run>/fileManager.txt
```

**CRITICAL**: All paths MUST be absolute. See dt_001.

### Step 3: Validate fileManager

```bash
python tools/s6_execution/validate_file_manager.py \
  --file_manager outputs/<run>/fileManager.txt
```

**Expected result**: "Validation PASSED" with all files found and dimensions consistent.

**If this fails**: See diagnostic triplets dt_001 (missing files), dt_002 (path too long), dt_005/dt_010 (dimension mismatch).

### Step 4: Run SUMMA

```bash
python tools/s6_execution/run_summa.py \
  --summa_exe model/summa/bin/summa.exe \
  --file_manager outputs/<run>/fileManager.txt \
  --log_file outputs/<run>/summa_run.log
```

**Expected runtime**: 1-20 minutes depending on domain size and simulation period.

**Expected result**: Exit code 0, output NetCDF files in output directory.

**If STOP 10**: Missing file. See dt_001.
**If STOP 20**: NetCDF dimension error. See dt_008.
**If STOP 30**: Invalid decision. See dt_009.
**If convergence failure**: See dt_007.

### Step 5: Parse output

```bash
python tools/s6_execution/parse_summa_output.py \
  --output_nc outputs/<run>/summa_output/summa_<basin>_output.nc \
  --variables scalarTotalRunoff scalarTotalET scalarSWE \
  --output_csv outputs/<run>/summa_parsed.csv
```

### Step 6: Quick sanity check

```python
# Mean runoff should be positive and reasonable
# Mean annual runoff ~200-1500 mm/yr for most basins
# scalarTotalRunoff is in m/s -> mm/yr = value * 86400 * 365 * 1000
```

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| fileManager | `outputs/<run>/fileManager.txt` | Passes validation |
| SUMMA output | `outputs/<run>/summa_output/*.nc` | Has time dimension > 0 |
| Run log | `outputs/<run>/summa_run.log` | No STOP codes |
| Parsed CSV | `outputs/<run>/summa_parsed.csv` | Has datetime + variable columns |

## Validation Checks

1. **Exit code is 0**: Non-zero means SUMMA encountered an error.
2. **Output file exists and is non-empty**: `ls -la outputs/<run>/summa_output/*.nc`
3. **Time dimension has expected length**: For 10 years of 3-hourly data = ~29,200 steps.
4. **Runoff is non-zero**: Mean scalarTotalRunoff should be 1e-6 to 1e-4 m/s. See dt_011.
5. **No NaN in output**: Check for NaN values in key variables. See dt_013.

## Common Pitfalls

> **PITFALL**: Using relative paths in fileManager.txt.
> SUMMA resolves paths from the CWD of the executable, NOT from the fileManager location. Always use absolute paths. See dt_001.

> **PITFALL**: Path exceeds 256 characters (Fortran CHARACTER limit).
> Deep directory nesting in outputs/<basin>/<run>/settings/ can exceed this. Use symlinks. See dt_002.

> **PITFALL**: Running SUMMA from a different directory than expected.
> If any paths are relative (despite the rule above), the CWD matters. Always validate with validate_file_manager.py first.

---

*This skill document is part of the hydrocraft-summa knowledge infrastructure.*
*Stage 6 of 7 | Tools used: create_file_manager, validate_file_manager, run_summa, parse_summa_output | Related triplets: dt_001, dt_002, dt_007, dt_008, dt_009, dt_011, dt_013, dt_016*
