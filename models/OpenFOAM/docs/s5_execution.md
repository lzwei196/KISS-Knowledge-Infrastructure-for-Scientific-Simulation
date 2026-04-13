# S5: Execution

## Purpose

Run the OpenFOAM solver with proper environment, monitor convergence,
and handle serial and parallel execution modes.

## Inputs

| Input | Source | Format |
|-------|--------|--------|
| Complete case directory | Stages s0-s4 | OpenFOAM case structure |
| Solver name | controlDict | incompressibleFluid, fluid, etc. |
| Number of processors | Resource allocation | Integer |
| OpenFOAM environment | Installation | etc/bashrc |

## Outputs

| Output | Location | Format |
|--------|----------|--------|
| Time directories | caseDir/0.1/, 0.2/, ... | Field files per time step |
| Solver log | stdout or log file | Text with residuals |
| postProcessing | caseDir/postProcessing/ | Function object results |

## Procedure

### 1. Pre-flight check

```bash
python check_case.py --case-dir ./myCase
```

Must return status: "pass" with 0 fatal issues.

### 2. Serial execution

```bash
# Source OpenFOAM environment
source $WM_PROJECT_DIR/etc/bashrc

# Generate mesh (if not done)
blockMesh -case ./myCase

# Run solver
foamRun -case ./myCase 2>&1 | tee log.foamRun

# Or legacy solver name
simpleFoam -case ./myCase 2>&1 | tee log.simpleFoam
```

### 3. Parallel execution

```bash
# Source environment
source $WM_PROJECT_DIR/etc/bashrc

# Decompose domain
decomposePar -case ./myCase

# Run in parallel
mpirun -np 4 foamRun -case ./myCase -parallel 2>&1 | tee log.foamRun

# Reconstruct results
reconstructPar -case ./myCase
```

### 4. Using run_openfoam.py

```bash
python run_openfoam.py \
    --case-dir ./myCase \
    --solver incompressibleFluid \
    --np 1 \
    --foam-bashrc /opt/OpenFOAM/etc/bashrc \
    --output result.json
```

### 5. Monitor convergence

During execution, watch for:
- **Residuals**: Should decrease over iterations. Plot with `foamMonitor`
- **Courant number**: Should remain < 1 for explicit schemes
- **Execution time**: Compare to estimated wall clock time
- **Divergence**: "FOAM FATAL ERROR" or residuals increasing unboundedly

### 6. Common log patterns

**Healthy run:**
```
Time = 0.001
smoothSolver:  Solving for Ux, Initial residual = 0.234, Final residual = 1.2e-07
GAMG:  Solving for p, Initial residual = 0.0156, Final residual = 4.5e-07
Courant Number mean: 0.12 max: 0.45
```

**Diverging run:**
```
smoothSolver:  Solving for Ux, Initial residual = 1e+20, Final residual = nan
#0  Foam::error::printStack(Foam::Ostream&)
FOAM FATAL ERROR: Floating point exception
```

## Verification

1. Solver exits with code 0 (success)
2. Final residuals below convergence criteria (typically < 1e-4)
3. Output time directories exist with expected field files
4. Mass balance is conserved (check continuity residual)
5. Solution looks physically reasonable in ParaView

## Traps

| Trap | Symptom | Prevention |
|------|---------|------------|
| Missing etc/bashrc source | "foamRun: command not found" | Source bashrc before running |
| MPI np mismatch | Immediate crash with MPI error | Match -np with numberOfSubdomains |
| No processor directories | "processor directory does not exist" | Run decomposePar first |
| Courant > 1 with PISO | Divergence | Reduce deltaT or use PIMPLE |
| Log not captured | No record of convergence | Always tee to log file |
| Running in wrong directory | Case not found error | Use -case flag or cd to case dir |

## Example

Full execution workflow for cavity tutorial:

```bash
# 1. Source environment
source /opt/OpenFOAM/etc/bashrc

# 2. Copy tutorial
cp -r $FOAM_TUTORIALS/incompressibleFluid/cavity ./cavity
cd cavity

# 3. Generate mesh
blockMesh

# 4. Validate case
python check_case.py --case-dir .

# 5. Run solver
foamRun 2>&1 | tee log.foamRun

# 6. Check result
python parse_openfoam_output.py \
    --case-dir . \
    --log-file log.foamRun \
    --extract-residuals \
    --extract-fields U,p \
    --csv-dir ./csv_output
```
