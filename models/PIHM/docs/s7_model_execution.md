# S7: Model Execution Skill

## Purpose

Build and execute the MM-PIHM binary for a configured watershed project.
Includes compilation of CVODE library, model building, environment setup,
spin-up workflow, and runtime troubleshooting.

## Prerequisites

- GCC compiler with OpenMP support
- CMake >= 3.18 (auto-downloaded if not available)
- All input files prepared and validated (S1–S6)
- Sufficient disk space for output files

## Inputs

| Input | Description |
|-------|-------------|
| Source code | MM-PIHM repository |
| Input files | Complete set in `input/<project>/` |
| Configuration | `.para` and `.calib` files |

## Outputs

| Output | Path | Description |
|--------|------|-------------|
| Binary output files | `output/<run>/` | `.dat` files for each variable |
| CVODE log | `output/<run>/` | Debug information (if -d flag) |
| IC file | `output/<run>/` | Final state for restart |

## Procedure

### Step 1: Build CVODE Library

```bash
cd MM-PIHM/
make cvode
```

This compiles the SUNDIALS CVODE v7.3.0 implicit ODE solver. The library is
installed to `cvode/instdir/`. This step only needs to be done once.

### Step 2: Compile PIHM

```bash
# Choose one model variant:
make pihm           # Core hydrology only
make flux-pihm      # With Noah LSM (energy balance, snow)
make flux-pihm-bgc  # With biogeochemistry

# Always clean before switching variants:
make clean
make flux-pihm
```

Compilation flags:
- `make DEBUG=off pihm` — optimized build (-O2), faster but harder to debug
- `make CVODE_OMP=on pihm` — OpenMP for CVODE (only for >30000 elements)
- `make WARNING=on pihm` — enable all compiler warnings

### Step 3: Set OpenMP Environment

```bash
export OMP_NUM_THREADS=4   # Match your CPU cores
```

Guideline: Use physical cores, not hyperthreads. For small domains (<1000
elements), 4 threads is sufficient. For large domains (>10000 elements),
use 8–16 threads.

### Step 4: Spin-up (Recommended)

Spin-up runs the model repeatedly until groundwater reaches dynamic
equilibrium. Without spin-up, groundwater initialization is arbitrary
and early results are unreliable (dt_012).

```bash
# 1. Set .para: SIMULATION_MODE=1
# 2. Run spin-up
./pihm -o spinup ShaleHills

# 3. Copy output IC to input directory
cp output/spinup/ShaleHills.ic input/ShaleHills/ShaleHills.ic

# 4. Set .para: SIMULATION_MODE=0, INIT_MODE=1
```

Spin-up terminates when subsurface storage change < 0.01 m between cycles,
or after MAX_SPINUP_YEAR. Typical spin-up: 20–100 cycles for small catchments.

### Step 5: Production Run

```bash
./pihm [-b] [-c] [-d] [-v] [-o output_dir] <project>
```

| Flag | Use Case |
|------|----------|
| `-b` | Long simulations (reduce screen output) |
| `-c` | First run on new mesh (fix surface sinks) |
| `-d` | Debugging solver issues (creates CVODE log) |
| `-v` | Detailed progress (development/testing) |
| `-o name` | Custom output directory |

### Step 6: Using run_pihm.py Wrapper

```bash
python ki/tools/run_pihm.py \
    --binary ./pihm \
    --project ShaleHills \
    --input-dir input/ShaleHills \
    --output-dir test_run \
    --threads 4
```

The wrapper performs pre-flight validation:
- Checks all required input files exist
- Validates solver tolerance values
- Warns about calibration multiplier issues
- Checks disk space

## Verification

1. **Simulation completes**: "Simulation completed." message appears
2. **Output files exist**: Check `output/` directory for `.dat` files
3. **File sizes reasonable**: GW output for 535 elements × 365 days ≈ 1.2 MB
4. **Water balance**: If `WATBAL_OUTPUT=1`, check `.watbal.plt` for residuals < 1%
5. **No solver warnings**: CVODE convergence messages indicate problems

## Traps

| Trap | Triplet | Severity |
|------|---------|----------|
| CVODE convergence failure | dt_015 | Fatal — crash |
| No spin-up for groundwater | dt_012 | Degraded — bad baseflow |
| CVODE tolerance too loose | dt_013 | Degraded — mass imbalance |
| Negative state variable | dt_020 | Fatal — FPE crash |

## Troubleshooting CVODE Failures

**CV_TOO_MUCH_WORK** — solver hit max internal steps:
1. Enable debug: `./pihm -d ShaleHills`
2. Find the failing time in CVODE log
3. Check forcing data at that time for spikes
4. Try reducing MODEL_STEPSIZE to 30
5. Try increasing MAX_NONLIN_ITER to 5

**Floating point exception** — negative state variable:
1. Check `.ic` file for negative values
2. Reduce ABSTOL to 1e-5
3. Check soil Ksat — very high values cause instability
4. Check mesh for degenerate elements

**Simulation too slow**:
1. Increase OMP_NUM_THREADS
2. Try `make DEBUG=off` for optimized build
3. Increase ABSTOL to 1e-3 (at cost of mass conservation)
4. Reduce output frequency (use -3 instead of -4)

## Example

Complete workflow for Shale Hills:

```bash
# Build
cd MM-PIHM/
make cvode
make pihm
export OMP_NUM_THREADS=4

# Spin-up
./pihm -b -o spinup ShaleHills
cp output/spinup/ShaleHills.ic input/ShaleHills/ShaleHills.ic

# Production
./pihm -b -o production ShaleHills

# Check output
ls -la output/production/*.dat
```
