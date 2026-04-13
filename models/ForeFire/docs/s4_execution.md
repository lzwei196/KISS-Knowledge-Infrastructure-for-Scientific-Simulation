# Stage 4: Execution and Runtime

## Purpose

Run the ForeFire binary with proper environment setup, monitor execution, and validate that output files are produced correctly.

## Inputs

| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| ForeFire binary | Executable | Build stage | `bin/forefire` |
| Simulation script | `.ff` file | Stage 3 | Complete simulation script |
| Data files | NetCDF + CSV | Stages 1-2 | `data.nc`, `fuels.csv` |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Fire perimeters | KML/GeoJSON/FF | Fire front positions over time |
| State dump | NetCDF | `ForeFire.0.nc` — full simulation state |
| Console output | Text | Simulation progress and diagnostics |

## Procedure

### 1. Environment Setup

```bash
# Ensure binary is accessible
export PATH=/path/to/forefire/bin:$PATH
export FOREFIREHOME=/path/to/forefire

# Verify library linkage
ldd bin/forefire | grep -i netcdf
# Should show: libnetcdf.so.X and libnetcdf_c++4.so.X
```

### 2. Execution Modes

**Script mode** (recommended for automation):
```bash
forefire -i simulation.ff
```

**Interactive console**:
```bash
forefire
# Then type commands interactively
forefire> setParameter[propagationModel=Iso]
forefire> ...
```

**HTTP server mode** (web interface):
```bash
forefire -l
# Access at http://localhost:8000
```

**Python bindings**:
```python
import pyforefire as pyff
ff = pyff.ForeFire()
ff.execute("FireDomain[sw=(0,0,0);ne=(10000,10000,0);t=0]")
ff.addLayer("propagation", "Iso", "propagationModel")
ff.execute("startFire[loc=(5000,5000,0)]")
ff.execute("step[dt=1000]")
print(ff.execute("print[]"))
```

### 3. Runtime Expectations

| Scenario | Grid Size | Duration | Expected Time |
|----------|-----------|----------|---------------|
| Small test (Iso) | 300×200 | 1000s | < 1 second |
| Medium (Rothermel) | 1000×1000 | 3600s | 5-30 seconds |
| Real case (Corsica) | 5000×5000 | 7200s | 1-5 minutes |
| Large coupled (MesoNH) | 10000×10000 | 86400s | Hours (MPI) |

### 4. Monitoring

ForeFire prints progress to stdout. Key messages:
- `Domain string created:` — domain successfully initialized
- `ForeFire HTTP command server listening` — HTTP mode active
- Error messages are printed to stderr

### 5. Output Collection

After execution, collect outputs from the working directory:
```bash
ls -la *.nc *.kml *.geojson *.ff
```

## Verification

- Exit code 0 = success
- Output files exist and are non-empty
- `ForeFire.0.nc` should be > 60KB for typical simulations
- KML/GeoJSON should contain fire perimeter coordinates
- No "segfault" or "SIGSEGV" in stderr

## Traps

### Trap 1: Missing libnetcdf
**Symptom**: `error while loading shared libraries: libnetcdf_c++4.so`
**Cause**: NetCDF C++ library not installed or not in library path.
**Fix**: `apt install libnetcdf-c++4-dev` or set `LD_LIBRARY_PATH`.

### Trap 2: Git LFS data not downloaded
**Symptom**: `NetCDF: Unknown file format` when running built-in tests.
**Cause**: data.nc is a Git LFS pointer file (ASCII text, ~130 bytes).
**Fix**: Install Git LFS (`apt install git-lfs`) and run `git lfs pull`.

### Trap 3: Build without NetCDF headers
**Symptom**: Compilation error: `fatal error: netcdf: No such file or directory`
**Cause**: NetCDF development headers not installed.
**Fix**: `apt install libnetcdf-c++4-dev`

### Trap 4: Segfault on missing fuel type
**Symptom**: Segmentation fault during simulation.
**Cause**: Fuel map contains index values not present in fuels.csv.
**Fix**: Ensure all fuel indices in data.nc have corresponding rows in fuels.csv.

### Trap 5: Infinite loop in Balbi2020
**Symptom**: Simulation hangs, never completes.
**Cause**: Balbi2020 iterative solver doesn't converge (max 40 iterations).
**Fix**: Check fuel parameters for physical reasonableness. Extreme values can prevent convergence.

## Example

```bash
# Using the execution wrapper tool
python tools/run_forefire.py \
    --binary /path/to/forefire/bin/forefire \
    --script real_case.ff \
    --workdir /path/to/tests/runff \
    --timeout 300 \
    --expected_outputs ForeFire.0.nc real_case.kml
```
