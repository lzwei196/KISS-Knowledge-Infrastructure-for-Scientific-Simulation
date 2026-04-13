# Stage 5: Flow Equations and Solver Configuration

## Purpose

Select the ice flow physics formulation and configure the nonlinear solver. The flow equation determines which momentum conservation approximation is used — from simple 2D depth-integrated (SSA) to full 3D Stokes (FS). This choice profoundly affects accuracy, computational cost, and required mesh dimensionality.

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| Model with parameterization | `md` object | From Stages 1-4 |
| Flow equation type | string | `'SSA'`, `'SIA'`, `'HO'`, `'FS'`, `'L1L2'`, `'MOLHO'` |
| Domain specification | string | `'all'` or `.exp` file for per-region assignment |

## Outputs

| Output | Type | Description |
|--------|------|-------------|
| `md.flowequation.element_equation` | array[ne] | Flow equation ID per element |
| `md.flowequation.vertex_equation` | array[nv] | Flow equation ID per vertex |
| `md.flowequation.isSIA` | array[ne] | Boolean: SIA active |
| `md.flowequation.isSSA` | array[ne] | Boolean: SSA active |
| `md.flowequation.isHO` | array[ne] | Boolean: HO active |
| `md.flowequation.isFS` | array[ne] | Boolean: FS active |

## Procedure

### Setting the Flow Equation

```python
from setflowequation import setflowequation

# Uniform SSA everywhere (most common for 2D)
md = setflowequation(md, 'SSA', 'all')

# SIA for grounded ice sheets
md = setflowequation(md, 'SIA', 'all')

# Higher-Order for 3D simulations (requires extrusion first)
md = extrude(md, 15, 1.3)
md = setflowequation(md, 'HO', 'all')

# Full Stokes (most expensive, most accurate)
md = extrude(md, 15, 1.3)
md = setflowequation(md, 'FS', 'all')
```

### Flow Equation Selection Guide

| Equation | Dimensions | DOFs/node | Cost | Accuracy | Use When |
|----------|-----------|-----------|------|----------|----------|
| **SSA** | 2D | 2 (vx, vy) | Low | Good for shelves/streams | Ice shelves, fast ice streams, large ice sheets |
| **SIA** | 2D | 2 (vx, vy) | Very low | Good for interior | Slow grounded ice, paleo simulations |
| **L1L2** | 2D | 2 (vx, vy) | Low | Better than SSA | Fast alternative to HO |
| **MOLHO** | 2D+3D | 2+ | Medium | Good hybrid | When SSA is too simple but HO too expensive |
| **HO** | 3D | 2 (vx, vy) | High | Very good | Outlet glaciers, transition zones |
| **FS** | 3D | 4 (vx, vy, vz, p) | Very high | Exact | Ice divides, grounding lines, benchmarks |

**Rule of thumb**: Start with SSA. Only move to HO/FS if SSA results are clearly inadequate for your study region.

### Solver Configuration

```python
# Stress balance solver settings
md.stressbalance.maxiter = 100          # Max nonlinear iterations
md.stressbalance.restol = 0.001         # Residual tolerance (relative)
md.stressbalance.reltol = 0.01          # Relative tolerance
md.stressbalance.abstol = 10            # Absolute tolerance (N)
md.stressbalance.isnewton = 0           # 0=Picard, 1=Newton, 2=hybrid

# Cluster configuration
md.cluster = generic('name', gethostname(), 'np', 4)  # 4 processors

# Toolkit (PETSc solver options)
md.toolkits.DefaultAnalysis = bcgslbjacobioptions()  # BiCGStab + block Jacobi
```

### Timestepping (for Transient)

```python
md.timestepping.time_step = 0.1          # years
md.timestepping.final_time = 100         # years
md.timestepping.start_time = 0           # years

# Transient configuration
md.transient.isstressbalance = 1         # Solve velocity
md.transient.ismasstransport = 1         # Solve thickness evolution
md.transient.isthermal = 0               # Skip temperature (faster)
md.transient.isgroundingline = 1         # Track grounding line migration
md.transient.requested_outputs = ['default', 'IceVolume', 'TotalSmb']
```

## Verification

1. **2D vs 3D match**: SSA/SIA/L1L2 need 2D mesh; HO/FS need 3D (extruded)
2. **Newton convergence**: If Newton fails, try Picard first (isnewton=0)
3. **Time step CFL**: For transient, ensure `dt < dx / max(vel)` roughly

```python
# Check flow equation assignment
print(f"SSA elements: {np.sum(md.flowequation.isSSA)}")
print(f"SIA elements: {np.sum(md.flowequation.isSIA)}")
print(f"HO elements: {np.sum(md.flowequation.isHO)}")
print(f"FS elements: {np.sum(md.flowequation.isFS)}")

# Verify mesh dimensionality matches
if md.flowequation.isHO.any() or md.flowequation.isFS.any():
    assert hasattr(md.mesh, 'numberoflayers'), "HO/FS requires 3D mesh (use extrude first)"
```

## Traps

| Trap | Symptom | Cause | Fix |
|------|---------|-------|-----|
| dt_015 | Wrong velocities, especially at margins | SSA on domain where SIA is needed (or vice versa) | Match flow eq to physics regime |
| dt_017 | Transient blows up after few steps | Time step too large for CFL | Reduce `md.timestepping.time_step` |
| - | Solver never converges | Newton method fails on poorly conditioned problem | Set `isnewton=0` (Picard iteration) |
| - | Crash: "need 3D mesh" | HO/FS on 2D mesh | Call `extrude()` before `setflowequation()` |
| - | Extremely slow solve | FS on large mesh | Use SSA or HO instead |

## Example

```python
# Pine Island Glacier: SSA with inversion
md = setflowequation(md, 'SSA', 'all')

# Configure inversion for friction coefficient
md.inversion.iscontrol = 1
md.inversion.control_parameters = ['FrictionCoefficient']
md.inversion.maxsteps = 20
md.inversion.cost_functions = [101, 103, 501]  # AbsVelMisfit, LogVelMisfit, DragCoeff
md.inversion.cost_functions_coefficients = np.ones((md.mesh.numberofvertices, 3))
md.inversion.cost_functions_coefficients[:, 0] = 1
md.inversion.cost_functions_coefficients[:, 1] = 1
md.inversion.cost_functions_coefficients[:, 2] = 1e-12

# Solve with control method
md.cluster = generic('name', gethostname(), 'np', 4)
md = solve(md, 'Stressbalance')
```
