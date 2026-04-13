# Model Execution — Skill Document

> **Stage ID**: s8_model_execution
> **Pipeline order**: 8 of 9
> **Depends on**: s7_simulation_config

## Purpose

Execute the SWAT+ Fortran binary to perform the watershed simulation. SWAT+ reads all inputs from the TxtInOut directory (via file.cio) and writes output files to the same directory. The binary must be run from within TxtInOut — it reads file.cio from the current working directory.

## Prerequisites

Before starting this stage, verify:

- [ ] SWAT+ binary exists and is executable (compiled from source or pre-built)
- [ ] validate_txtinout (S7) passed without errors
- [ ] file.cio exists in TxtInOut directory
- [ ] Sufficient disk space for output files (can be GB for daily HRU output)
- [ ] For compilation: gfortran >= 9.0 and cmake >= 3.16 installed

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| SWAT+ binary | file | Pre-compiled or from S8 compilation | Executable |
| TxtInOut directory | directory | S7 output | Complete input file set |

## Procedure

### Step 1: Compile SWAT+ (if needed)

```bash
python tools/s8/compile_swatplus.py
```

Or manually:
```bash
cd model/swatplus
mkdir -p build && cd build
cmake .. -DCMAKE_Fortran_COMPILER=gfortran -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
```

For debugging (slower but catches array bounds errors):
```bash
cmake .. -DCMAKE_Fortran_COMPILER=gfortran -DCMAKE_BUILD_TYPE=Debug \
  -DCMAKE_Fortran_FLAGS="-g -fcheck=all -fbacktrace -Wall"
make -j$(nproc)
```

**Expected result**: `swatplus` binary in build directory.

**If this fails**: See diagnostic triplet dt_007.

### Step 2: Run SWAT+

```bash
python tools/s8/run_swatplus.py
```

Or manually:
```bash
cd TxtInOut/
/path/to/swatplus > swatplus_run.log 2>&1
echo "Exit code: $?"
```

SWAT+ takes no command-line arguments. It reads file.cio from CWD.

**Expected result**: Exit code 0. Output files created in TxtInOut.

Runtime estimates:
- Small basin (<50 HRUs), 10 years: seconds
- Medium basin (50-500 HRUs), 10 years: 1-10 minutes
- Large basin (>500 HRUs), 30 years: 10-60 minutes

**If this fails**: See diagnostic triplets dt_005 (array bounds), dt_014 (runtime crash).

### Step 3: Check for runtime errors

Examine the run log for:
- `STOP` statements: Fatal errors (usually array bounds or missing data)
- `Warning`: Non-fatal issues (may still affect results)
- `NaN` or `Infinity`: Numerical instability (usually from bad soil/weather data)
- Fortran runtime errors: `At line X of file Y`, `Index N out of bounds`

**Expected result**: Clean log with no errors or warnings.

### Step 4: Verify output files exist

Check that expected output files were created:
```bash
ls -la TxtInOut/channel_sd_day.txt
ls -la TxtInOut/basin_wb_day.txt
ls -la TxtInOut/basin_nb_day.txt
```

**Expected result**: All output files enabled in print.prt exist and have non-zero size.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| channel_sd_day.txt | `TxtInOut/channel_sd_day.txt` | Non-empty, has header + data rows |
| basin_wb_day.txt | `TxtInOut/basin_wb_day.txt` | Non-empty, has header + data rows |
| basin_nb_day.txt | `TxtInOut/basin_nb_day.txt` | If enabled; non-empty |
| swatplus_run.log | `TxtInOut/swatplus_run.log` | No STOP, no NaN |

## Validation Checks

1. **Exit code**: Must be 0. Non-zero indicates fatal error.

2. **Output file existence**: All files enabled in print.prt must exist.
   - If missing: Simulation crashed before writing output. Check log.

3. **Log clean**: No STOP, no runtime error, no NaN in log.
   - If STOP: See dt_005 (array bounds) or dt_014 (generic crash)

4. **Output file size**: channel_sd_day.txt should have approximately (nyears - nyskip) * 365 * nchannels data rows.

## Common Pitfalls

> **PITFALL**: Running from wrong directory (file.cio not found)
> SWAT+ reads file.cio from the current working directory. If you run from the parent directory, it fails immediately.
> **Do this instead**: Always `cd` into TxtInOut before running the binary.

> **PITFALL**: Array bounds exceeded (STOP or segfault)
> Hardcoded array dimensions in some SWAT+ versions cannot handle very large basins (>5000 HRUs). The binary crashes with a segfault or Fortran STOP.
> **Do this instead**: Reduce HRU count via thresholds, or recompile with larger array bounds.
> See diagnostic triplet dt_005.

> **PITFALL**: gfortran version incompatibility
> SWAT+ source code uses some non-standard Fortran features. gfortran < 9.0 may fail to compile. Some revisions have bugs that require patches.
> **Do this instead**: Use gfortran >= 9.0. Check GitHub issues for known compilation fixes.
> See diagnostic triplet dt_007.

> **PITFALL**: Disk space exhaustion during run
> Daily HRU output for 1000 HRUs over 30 years generates multi-GB files. If disk fills during run, output is truncated silently.
> **Do this instead**: Enable daily output only for basin_wb and channel_sd. Use monthly or yearly for HRU-level output.

---

*This skill document is part of the SWAT+ knowledge infrastructure.*
*Stage 8 of 9 | Tools used: compile_swatplus, run_swatplus | Related triplets: dt_005, dt_007, dt_014*
