# S4: Model Execution

## Purpose

Run the tRIBS binary with a prepared control file (.in), verify successful
initialization and completion, and handle common runtime errors.

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| tRIBS binary | Executable | `tRIBS` (serial) or `tRIBSpar` (parallel) |
| Control file (`.in`) | Text | All parameters and file paths |
| Mesh files | `.nodes`, `.edges`, `.tri`, `.z` | TIN mesh geometry |
| Soil table (`.sdt`) | Tab-delimited | Soil hydraulic parameters |
| Land-use table (`.ldt`) | Tab-delimited | Vegetation parameters |
| Met forcing (`.sdf` + `.mdf`) | Text | Station metadata + time-series |
| Rain data (`.gdf` + `.mdf`) | Text | Rain gauge data |
| Node list (`.nls`) | Text | Node IDs for pixel output |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Pixel files (`.pixel`) | Space-delimited | Per-node time series |
| Outlet file (`.qout`) | Space-delimited | Discharge hydrograph |
| Mean response (`.mrf`) | Space-delimited | Basin-averaged fluxes |
| Spatial snapshots | Text | Distributed variables at intervals |
| Restart file | Binary | Full model state for restarting |
| Console log (stdout) | Text | Runtime progress messages |

## Procedure

### Step 1: Build the binary (if not already done)
```bash
cd /path/to/tRIBS/repo
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --target all
```

### Step 2: Verify all input files exist
Before running, check that every file referenced in the `.in` file is accessible:
```bash
python run_tribs.py --binary ./build/tRIBS --input my_basin.in --flags "-K"
```
The `-K` flag activates input checking mode.

### Step 3: Execute
```bash
# Serial
./build/tRIBS my_basin.in

# With verbose output for node 100
./build/tRIBS my_basin.in -V 100

# Parallel (4 cores)
mpirun -np 4 ./build/tRIBSpar my_basin.in
```

### Step 4: Monitor progress
tRIBS prints progress through 9 parts:
1. **Part 1**: Read input parameters
2. **Part 2**: Preprocess meteorological data
3. **Part 3**: Create mesh and stream network
4. **Part 4**: Create resampling and shelter objects
5. **Part 5**: Create output files
6. **Part 6**: Create hydrologic system (rainfall, ET, interception, snow)
7. **Part 7**: Initialize simulation
8. **Part 8**: Hydrologic simulation loop (main computation)
9. **Part 9**: Cleanup and exit

### Step 5: Verify completion
Check that "Part 9: Deleting Objects and Exiting Program" appears in stdout.

### Step 6: Restart (if needed)
To continue a simulation from a restart file:
```
RESTARTMODE
2
RESTARTFILE
/path/to/restart_file
```

## Verification

- [ ] Binary exists and is executable
- [ ] All file paths in `.in` file are valid
- [ ] METSTEP is in hours (not minutes)
- [ ] Simulation dates are consistent with forcing data period
- [ ] Console output reaches "Part 9"
- [ ] Output files are created and non-empty
- [ ] No NaN values in output files
- [ ] Discharge values are physically plausible for basin size

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Missing input file | Crash at Part 1–3 with "Cannot open" | Check all paths in .in file |
| OPTMESHINPUT mismatch | Crash at Part 2 | Match option to file format |
| Mesh has no outlet | Infinite loop in flow routing | Verify boundary codes |
| METSTEP too large | Forcing gaps, wrong interpolation | Use hours (e.g., 1 for hourly) |
| Memory overflow | Killed by OOM | Reduce mesh size or use parallel |
| NaN in forcing data | NaN propagation through all outputs | Fill gaps before running |
| Wrong coordinate system | Model runs but nonsensical results | Use UTM meters |

## Example

```bash
# Full execution with wrapper
python run_tribs.py \
    --binary ./build/tRIBS \
    --input my_basin.in \
    --timeout 7200 \
    --json-output run_result.json

# Check result
cat run_result.json | python -m json.tool
```
