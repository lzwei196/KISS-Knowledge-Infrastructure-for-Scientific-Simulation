# s6: Model Execution

## Purpose

Compile and run the GEOtop binary on a prepared simulation directory.
Monitor execution, interpret log output, and detect common runtime failures.

## Inputs

| Input                | Source               | Format    | Notes                |
|----------------------|----------------------|-----------|----------------------|
| geotop binary        | CMake build          | ELF       | C++11 compiled       |
| geotop.inpts         | s5 configuration     | INI-like  | All 455+ keywords    |
| meteo/meteoXXXX.txt  | s4 forcing           | CSV       | One per station      |
| soil/soilXXXX.txt    | s2 soil params       | CSV       | One per point        |
| dem.txt (optional)   | s1 domain            | ASCII Grid| For distributed sims |

## Outputs

| Output               | File                     | Format   | Notes               |
|----------------------|--------------------------|----------|---------------------|
| Basin time series    | output-tabs/basin*.txt   | CSV      | Basin-averaged       |
| Point time series    | output-tabs/point*.txt   | CSV      | Per-point            |
| Soil profiles        | output-tabs/soilTz*.txt  | CSV      | Temperature profiles |
| Snow profiles        | output-tabs/snowT*.txt   | CSV      | Snow layer profiles  |
| Discharge            | output-tabs/discharge*.txt| CSV     | Catchment discharge  |
| Success marker       | _SUCCESSFUL_RUN          | Empty    | Created on completion|
| Log file             | geotop.log               | Text     | Execution details    |

## Procedure

### 1. Build the Binary

```bash
cd /path/to/geotop/source/repo
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=RELEASE
make -j$(nproc)
```

The binary is at `build/geotop`.

### 2. Verify Simulation Directory

Before running, check the directory structure:
```bash
ls sim_folder/
# Expected: geotop.inpts, meteo/, soil/, [dem.txt, slope.txt, ...]
```

### 3. Run the Model

```bash
./geotop /absolute/path/to/sim_folder
```

Or use the wrapper tool:
```bash
python run_geotop.py \
    --binary /path/to/build/geotop \
    --sim-dir /path/to/sim_folder \
    --timeout 3600
```

### 4. Monitor Execution

- Watch `geotop.log` for progress and errors
- The model prints time step progress to stdout
- Typical run time: seconds (point 1-month) to hours (distributed multi-year)
- Memory usage: ~100 MB (point) to several GB (large distributed)

### 5. Verify Completion

```bash
# Check success marker
test -f sim_folder/_SUCCESSFUL_RUN && echo "SUCCESS" || echo "FAILED"

# Check output files exist
ls sim_folder/output-tabs/
```

## Common Runtime Issues

### Richards Equation Divergence
**Symptom**: Model crashes or takes extremely long with small time steps
**Cause**: Unrealistic soil parameters (Dz in meters, alpha in wrong units)
**Fix**: Check dt_001, dt_002, dt_003 in diagnostics

### Segmentation Fault
**Symptom**: Immediate crash with no log output
**Cause**: Missing input files referenced in geotop.inpts
**Fix**: Verify all file paths in geotop.inpts exist

### Infinite Loop / Hanging
**Symptom**: Model runs indefinitely without advancing time
**Cause**: Energy balance not converging (extreme forcing values)
**Fix**: Check forcing units (temperature in Kelvin instead of Celsius)

### Zero Output
**Symptom**: Output files created but all values are 0 or nodata
**Cause**: Forcing file nodata (-9999) not recognized, or wrong header names
**Fix**: Check header names match HeaderXXX keywords in geotop.inpts

## Verification

- [ ] `_SUCCESSFUL_RUN` marker file exists
- [ ] `geotop.log` has no ERROR lines
- [ ] `output-tabs/` contains expected files
- [ ] Output files have data rows (not just headers)
- [ ] Mass balance error is small (< 1 mm cumulative)
- [ ] Execution time is reasonable for the simulation period

## Traps

| Trap ID | Description                                    | Severity |
|---------|------------------------------------------------|----------|
| dt_017  | Binary path not absolute -> working dir issues | fatal    |
| dt_018  | Missing output-tabs directory -> no output     | fatal    |
| dt_009  | Tab characters replaced by spaces in inpts     | fatal    |

## Example

Running the Matsch B2 reference test:
```bash
# Build
cd /path/to/source/repo && mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=RELEASE && make -j4

# Run
./geotop /path/to/source/repo/tests/1D/Matsch_B2_Ref_007

# Check
test -f /path/to/tests/1D/Matsch_B2_Ref_007/_SUCCESSFUL_RUN && echo "OK"
ls /path/to/tests/1D/Matsch_B2_Ref_007/output-tabs/
```

Expected output files for this test:
```
basin0001.txt
point0001.txt
soilTz0001.txt
thetaliq0001.txt
thetaice0001.txt
psiz0001.txt
snowT0001.txt
snowDepth0001.txt
snowIce0001.txt
snowLiq0001.txt
discharge0001.txt
```
