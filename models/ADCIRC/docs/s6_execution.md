# S6: Execution

## Purpose

Run ADCIRC in serial or parallel mode with proper preflight validation, domain decomposition (for parallel), and postflight output verification. This stage covers the actual model execution and common runtime issues.

## Inputs

| Input | Source | Format | Description |
|-------|--------|--------|-------------|
| Grid file | S1 | `fort.14` | Mesh, bathymetry, boundaries |
| Control file | S2 | `fort.15` | All model parameters |
| Nodal attributes | S3 | `fort.13` | Spatially varying parameters (optional) |
| Met forcing | S4 | `fort.22*` | Wind and pressure (if NWS≠0) |
| Boundary conditions | S5 | `fort.19/20` | Time-varying BCs (optional) |
| ADCIRC binary | Build | `adcirc` or `padcirc` | Compiled executable |

## Outputs

| Output | File | Format | Description |
|--------|------|--------|-------------|
| Elevation | `fort.63` | ASCII/netCDF | Water surface time series |
| Velocity | `fort.64` | ASCII/netCDF | Velocity time series |
| Max elevation | `maxele.63` | ASCII/netCDF | Peak water level at each node |
| Max velocity | `maxvel.63` | ASCII/netCDF | Peak speed at each node |
| Screen log | `fort.6` / stdout | text | Runtime progress and warnings |
| Run summary | `fort.16` | text | Model configuration echo |
| Hot start | `fort.67/68` | binary | Restart files |

## Procedure

### Serial Execution

```bash
# Ensure all input files are in working directory
ls fort.14 fort.15

# Run
./adcirc

# Or with the wrapper tool
python ki/tools/run_adcirc.py \
    --binary ./build/adcirc \
    --work_dir /path/to/run \
    --mode serial
```

### Parallel Execution

```bash
# Step 1: Partition mesh (METIS graph partitioning)
./adcprep --np 8 --partmesh

# Step 2: Prepare per-processor subdomain files
./adcprep --np 8 --prepall

# Step 3: Run with MPI
mpirun -np 8 ./padcirc

# All-in-one with wrapper
python ki/tools/run_adcirc.py \
    --binary ./build/padcirc \
    --adcprep ./build/adcprep \
    --work_dir /path/to/run \
    --mode parallel --np 8
```

### Hot Start (Restart)

```bash
# Set IHOT in fort.15:
# IHOT = 67 or 68 (read fort.67 or fort.68)
# Place the hot start file in the working directory

# CRITICAL: Hot start files are compiler-specific binary (dt_009)
# Do NOT use hot start files from a different compiler
```

### Runtime Monitoring

```bash
# Watch progress (fort.6 output or screen)
tail -f fort.6

# Check if still running
ps aux | grep adcirc

# Typical output pattern:
# TIME STEP =    1000  TIME =  2000.000000
# TIME STEP =    2000  TIME =  4000.000000
```

### Resource Estimation

| Metric | Formula | Example (100k nodes, 30 days, dt=2s) |
|--------|---------|--------------------------------------|
| Total steps | RNDAY × 86400 / DTDP | 1,296,000 |
| Memory (serial) | ~200 bytes × nodes | ~20 MB |
| Memory (parallel) | ~200 bytes × nodes/np + overhead | ~5 MB/proc |
| Runtime | ~0.001s × steps × nodes/1e5 | ~3.6 hours serial |
| Output size | depends on NSPOOLGE | ~1-50 GB |

## Verification

```bash
# Check that output files were created
ls -la fort.63 fort.64 maxele.63

# Quick sanity check on max elevation
python3 -c "
with open('maxele.63') as f:
    f.readline(); f.readline(); f.readline()
    vals = []
    for line in f:
        parts = line.strip().split()
        if len(parts) >= 2:
            v = float(parts[1])
            if v > -99999: vals.append(v)
        if len(vals) > 10000: break
import numpy as np
a = np.array(vals)
print(f'Max elevation: min={a.min():.2f}, max={a.max():.2f}, mean={a.mean():.2f} m')
"

# Check for NaN (indicates instability)
grep -c "NaN\|Inf\|nan" fort.63 maxele.63
```

## Traps

| Trap | ID | Symptom |
|------|----|---------|
| CFL violation | dt_006 | Growing oscillations, NaN after many timesteps |
| Hot start incompatible | dt_009 | Crash at startup with binary read error |
| MPI version mismatch | dt_019 | Segfault or hang during parallel run |
| Disconnected mesh | dt_020 | adcprep crash during domain decomposition |
| ESLM too large | dt_016 | NaN in velocity output |
| fort.14 not found | dt_017 | Immediate crash: "file not found" |
| Output disk full | — | Partial output, corrupt files |

## Example

```bash
# Complete serial run from scratch
cd /path/to/run_dir

# Verify inputs
python ki/tools/run_adcirc.py --binary ./adcirc --work_dir . --dry_run

# Execute
python ki/tools/run_adcirc.py --binary ./adcirc --work_dir . --mode serial

# Parse results
python ki/tools/parse_adcirc_output.py \
    --work_dir . --format ascii \
    --output_csv results.csv \
    --variables elevation,velocity,maxele

# Check summary
cat results_summary.json
```
