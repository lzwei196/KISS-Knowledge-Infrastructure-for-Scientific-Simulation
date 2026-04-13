# S5: Execution and Output Parsing

## Purpose

Execute the Amanzi/ATS binary with proper MPI configuration, monitor for runtime errors, and parse the resulting output files (HDF5 visualization, observation text files, checkpoints) into analyzable formats (CSV, JSON).

## Inputs

| Input | Source | Format |
|-------|--------|--------|
| XML input file | Stage 4 | .xml |
| Mesh file (if external) | Stage 3 | .exo (Exodus II) |
| Amanzi/ATS binary | Installation | Executable |
| MPI configuration | User | Process count |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Visualization fields | HDF5 + XDMF | Pressure, saturation, velocity on mesh |
| Observation time series | ASCII .out | Point values at observation locations |
| Checkpoint files | HDF5 | Full state for restart |
| Run log | Text | Solver convergence, timing, errors |
| Parsed results | CSV | Extracted time series for analysis |

## Procedure

### 1. Pre-execution Checks

Before running, verify:
- XML file parses without errors
- Mesh file exists (if external)
- Binary is accessible and executable
- MPI launcher is available (for parallel runs)
- Sufficient disk space for output

```bash
# Verify binary
which ats  # or which amanzi

# Verify MPI
mpirun --version
```

### 2. Execute the Model

**Serial (1 process):**
```bash
ats --xml_file=input.xml > run.log 2>&1
```

**Parallel (N processes):**
```bash
mpirun -np 4 ats --xml_file=input.xml > run.log 2>&1
```

**Using the wrapper tool:**
```bash
python ki/tools/run_amanzi.py \
  --xml_file input.xml \
  --np 4 \
  --run_dir ./run \
  --timeout 3600
```

### 3. Monitor Runtime

Key indicators in the log:
- `Cycle N, Time T` — current simulation time
- `Nonlinear solver converged` — successful timestep
- `Nonlinear solver FAILED` — timestep cut required
- `NaN detected` — numerical blowup (fatal)
- `Solver: linear iterations: N` — solver effort per step

Healthy run: linear iterations < 50, timestep growing toward max_dt.
Troubled run: many failed timesteps, iterations near max, timestep stuck at minimum.

### 4. Parse Observation Files

Observation files are ASCII with columns:

```
# "observation: Pressure at Well_1"
# "observation: Head at Well_2"
time_s  pressure_Pa  head_m
0.0     199392.0     10.0
86400.0 198500.0     9.91
...
```

```bash
python ki/tools/parse_amanzi_output.py \
  --obs_file run/observations.out \
  --output results.csv
```

### 5. Parse HDF5 Visualization Files

Visualization files contain field data on the mesh at selected timesteps:

```bash
python ki/tools/parse_amanzi_output.py \
  --vis_file run/plot_data.h5 \
  --variable pressure \
  --output pressure_stats.csv
```

HDF5 structure:
```
/pressure.cell.0        # Pressure at timestep 0
/pressure.cell.1        # Pressure at timestep 1
/saturation_liquid.cell.0  # Saturation at timestep 0
/time                   # Array of output times (seconds)
```

### 6. Post-processing and Visualization

View fields in ParaView:
1. Open the .xmf file (XDMF reader)
2. Select variables to display
3. Apply color map (e.g., pressure → Rainbow)

Convert to head for intuitive interpretation:
```
h [m] = (P [Pa] - P_atm) / (ρ × g) + z
```

## Verification

- Mass balance: total inflow ≈ total outflow + storage change.
- Pressure range: positive (saturated) or negative (unsaturated), not extreme.
- Saturation: 0 ≤ S ≤ 1 everywhere.
- Observation values match expected physical behavior.
- No NaN or Inf in any output field.

## Traps

| Trap | Description | Consequence |
|------|-------------|-------------|
| **dt_007** | Different MPI rank count changes results | Reproducibility issues |
| **dt_013** | NaN from extreme permeability | Simulation crash |
| **dt_014** | Solver non-convergence | Timestep collapse, stall |
| **dt_018** | Timestep collapse from sharp wetting front | Very slow simulation |

## Example

### Complete Execution Workflow

```bash
# 1. Set up run directory
mkdir -p run && cd run
cp ../input.xml .
ln -s ../mesh.exo .  # if external mesh

# 2. Run (4 MPI processes, redirect output)
mpirun -np 4 ats --xml_file=input.xml > run.log 2>&1

# 3. Check for success
tail -5 run.log
# Should show: "Amanzi::SIMULATION_SUCCESSFUL"

# 4. Parse observations
python ../ki/tools/parse_amanzi_output.py \
  --obs_file observations.out \
  --output observations.csv \
  --summary summary.json

# 5. Quick validation
python3 -c "
import csv
with open('observations.csv') as f:
    reader = csv.DictReader(f)
    for row in reader:
        print(row)
"
```

### Runtime Expectations

| Problem Type | Typical Runtime | Notes |
|-------------|----------------|-------|
| 1D steady-state | Seconds | Fast convergence |
| 2D Richards transient (10 yr) | Minutes | Depends on resolution |
| 3D reactive transport | Hours to days | Chemistry is expensive |
| ATS integrated hydrology | Hours | Surface-subsurface coupling |
| Large DFN problems | Days | Many fracture-matrix exchanges |

### Common Error Messages

| Error | Likely Cause | Fix |
|-------|-------------|-----|
| `File not found: mesh.exo` | Wrong mesh path | Check relative/absolute path |
| `NaN detected in residual` | Bad permeability or BC | Reduce init_dt, check units |
| `Nonlinear solver failed to converge` | Stiff problem | Reduce max_dt, adjust vG |
| `MSTK error: invalid mesh` | Corrupted mesh file | Regenerate mesh |
| `Trilinos exception` | Memory or solver failure | Reduce problem size or np |
