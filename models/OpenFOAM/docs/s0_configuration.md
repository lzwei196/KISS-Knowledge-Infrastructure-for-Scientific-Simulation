# S0: Case Configuration

## Purpose

Set up an OpenFOAM case directory with properly configured solver control,
discretization schemes, and linear solver settings. This stage establishes
the simulation parameters that govern time stepping, output frequency, and
numerical algorithm selection.

## Inputs

| Input | Source | Format | Units |
|-------|--------|--------|-------|
| Simulation end time | User specification | Scalar | seconds |
| Time step (deltaT) | Stability analysis (Co < 1) | Scalar | seconds |
| Solver type | Physics selection | String | - |
| Algorithm | Steady/transient choice | SIMPLE/PISO/PIMPLE | - |
| Write interval | Output requirements | Scalar | seconds or steps |

## Outputs

| Output | Location | Format |
|--------|----------|--------|
| controlDict | system/controlDict | OpenFOAM dictionary |
| fvSchemes | system/fvSchemes | OpenFOAM dictionary |
| fvSolution | system/fvSolution | OpenFOAM dictionary |

## Procedure

1. **Select solver module**: Choose based on physics (incompressibleFluid for
   water flow, incompressibleVoF for free surface, fluid for thermal).

2. **Choose algorithm**:
   - SIMPLE: steady-state problems (large pseudo-time step, relaxation < 1)
   - PISO: transient with small time steps (Co < 1, no outer correctors)
   - PIMPLE: transient with larger time steps (Co > 1 possible, outer correctors)

3. **Set time stepping**:
   - Estimate deltaT from mesh spacing and expected velocity: dt = dx / U_max
   - For adaptive: set `adjustTimeStep yes` and `maxCo 1`
   - For steady-state: deltaT = 1 (arbitrary, no physical meaning)

4. **Configure discretization** (fvSchemes):
   - Time: `Euler` (1st order, stable), `backward` (2nd order), `steadyState`
   - Convection: `linearUpwind` (2nd order + stability), `linear` (central, 2nd order)
   - Gradient: `Gauss linear` (standard), `cellLimited Gauss linear 1` (bounded)

5. **Configure linear solvers** (fvSolution):
   - Pressure: GAMG (multigrid, fast for large meshes)
   - Velocity/turbulence: smoothSolver with symGaussSeidel
   - Set relaxation factors: 0.7 for U, 0.3 for p (SIMPLE/PIMPLE)

6. **Run tool**:
   ```bash
   python configure_case.py \
       --case-dir ./myCase \
       --solver incompressibleFluid \
       --end-time 10 \
       --delta-t 0.001 \
       --write-interval 1.0 \
       --algorithm PIMPLE
   ```

## Verification

- Open controlDict and verify solver name matches intended physics
- Check deltaT is appropriate for mesh and velocity (Co estimate)
- Verify writeInterval produces reasonable number of output files
- Confirm fvSchemes has entries for all terms in governing equations
- Run `check_case.py` to validate overall consistency

## Traps

| Trap | Symptom | Prevention |
|------|---------|------------|
| SIMPLE with small deltaT | Extremely slow convergence | Use deltaT >= 1 for steady-state |
| PISO with Co > 1 | Divergence in first iterations | Reduce deltaT or switch to PIMPLE |
| Missing div scheme | Fatal error "div scheme not specified" | Add explicit entry for each div term |
| writeControl mismatch | Too many or too few output files | Match writeControl mode with writeInterval units |
| relaxation = 1 with SIMPLE | Oscillatory residuals | Use 0.3-0.7 for SIMPLE |

## Example

Configure a transient pipe flow simulation:
```bash
python configure_case.py \
    --case-dir ./pipeFlow \
    --solver incompressibleFluid \
    --end-time 5.0 \
    --delta-t 0.0005 \
    --write-interval 0.5 \
    --algorithm PIMPLE \
    --adaptive-dt \
    --max-courant 1.0 \
    --n-outer-correctors 3
```

This creates controlDict with adaptive time stepping (maxCo=1), PIMPLE algorithm
with 3 outer correctors, and output every 0.5 seconds of simulation time.
