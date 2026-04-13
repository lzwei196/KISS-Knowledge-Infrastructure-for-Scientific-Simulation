# Stage 7: Execution and Post-Processing

## Purpose

Execute the ISSM finite element solver and extract, visualize, and validate the results. ISSM's solver is a compiled C++ code called via MATLAB/Python wrappers. The solve process includes matrix assembly, nonlinear iteration, convergence checking, and result extraction.

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| Fully configured model | `md` object | All fields from Stages 1-6 populated |
| Solution type | string | `'Stressbalance'`, `'Transient'`, etc. |
| Cluster config | `md.cluster` | Number of processors, hostname |

## Outputs

| Output | Location | Description |
|--------|----------|-------------|
| Solution fields | `md.results.<Type>Solution` | Velocity, thickness, temperature, etc. |
| Convergence info | solver stdout | Iteration count, residual norms |
| NetCDF export | `output.nc` | Optional, via `export_netCDF()` |

### Result Fields by Solution Type

**Stressbalance:**
- `md.results.StressbalanceSolution.Vx` — x-velocity (m/yr)
- `md.results.StressbalanceSolution.Vy` — y-velocity (m/yr)
- `md.results.StressbalanceSolution.Vel` — velocity magnitude (m/yr)
- `md.results.StressbalanceSolution.Pressure` — ice pressure (Pa)

**Transient:**
- `md.results.TransientSolution` — array indexed by timestep
- `md.results.TransientSolution[i].Vel` — velocity at timestep i
- `md.results.TransientSolution[i].Thickness` — thickness at timestep i
- `md.results.TransientSolution[i].Surface` — surface at timestep i

**Thermal:**
- `md.results.ThermalSolution.Temperature` — temperature (K)
- `md.results.ThermalSolution.BasalFrictionHeating` — friction heating (W/m^2)

## Procedure

### Basic Execution

```python
from solve import solve
from generic import generic
from socket import gethostname

# Configure cluster
md.cluster = generic('name', gethostname(), 'np', 4)

# Solve
md = solve(md, 'Stressbalance')

# Access results
vel = md.results.StressbalanceSolution.Vel
print(f"Max velocity: {np.max(vel):.1f} m/yr")
print(f"Mean velocity: {np.mean(vel):.1f} m/yr")
```

### Transient Simulation

```python
# Configure time stepping
md.timestepping.time_step = 0.5     # years
md.timestepping.final_time = 100    # years

# Enable physics modules
md.transient.isstressbalance = 1
md.transient.ismasstransport = 1
md.transient.isthermal = 0
md.transient.isgroundingline = 1

# Request specific outputs
md.transient.requested_outputs = ['default', 'IceVolume', 'TotalSmb', 'GroundedArea']

# Solve
md = solve(md, 'Transient')

# Extract time series
n_steps = len(md.results.TransientSolution)
volumes = [md.results.TransientSolution[i].IceVolume for i in range(n_steps)]
```

### Export Results

```python
# Export to NetCDF
from export_netCDF import export_netCDF
export_netCDF(md, 'output.nc')

# Save model (MATLAB format)
from savevars import savevars
savevars('model.mat', md)
```

### Visualization

```python
from plotmodel import plotmodel

# Plot velocity
plotmodel(md, 'data', md.results.StressbalanceSolution.Vel,
          'title', 'Ice Velocity (m/yr)', 'colorbar', 'on')

# Plot thickness
plotmodel(md, 'data', md.geometry.thickness,
          'title', 'Ice Thickness (m)', 'colorbar', 'on')
```

### With matplotlib (outside ISSM)

```python
import matplotlib.pyplot as plt
import matplotlib.tri as tri

# Create triangulation for plotting
triang = tri.Triangulation(md.mesh.x, md.mesh.y,
                           md.mesh.elements - 1)  # Convert to 0-indexed

fig, ax = plt.subplots(1, 1, figsize=(10, 8))
tpc = ax.tripcolor(triang, md.results.StressbalanceSolution.Vel,
                   cmap='viridis', shading='flat')
plt.colorbar(tpc, label='Velocity (m/yr)')
ax.set_aspect('equal')
ax.set_title('Ice Velocity')
plt.savefig('velocity.png', dpi=150, bbox_inches='tight')
```

## Verification

1. **Convergence**: Check solver converged within max iterations
2. **Physical velocity range**: 0-15,000 m/yr for ice sheets
3. **Mass conservation**: Total mass should change only by SMB and calving
4. **Thickness positivity**: No negative thickness in results
5. **Energy conservation**: Temperature bounded by surface T and pressure melting point

```python
# Post-solve checks
vel = md.results.StressbalanceSolution.Vel

# 1. Velocity range
print(f"Velocity: min={np.min(vel):.1f}, max={np.max(vel):.1f}, mean={np.mean(vel):.1f} m/yr")
assert np.max(vel) < 50000, "Unrealistic velocity — check units and parameters"
assert not np.any(np.isnan(vel)), "NaN in velocity — solver did not converge"

# 2. For transient: check mass conservation
if hasattr(md.results, 'TransientSolution'):
    thk_init = md.results.TransientSolution[0].Thickness
    thk_final = md.results.TransientSolution[-1].Thickness
    mass_change = np.mean(thk_final - thk_init) * md.mesh.numberofelements
    print(f"Mean thickness change: {np.mean(thk_final - thk_init):.2f} m")
```

## Traps

| Trap | Symptom | Cause | Fix |
|------|---------|-------|-----|
| dt_016 | "PETSc error" or "library not found" | PETSc not installed or not in PATH | Rebuild with correct PETSc paths |
| dt_019 | Transient starts with wrong velocity | Missing `md.initialization.vx/vy` | Run Stressbalance first, use result as init |
| - | "Mechanical equilibrium not converged" | Problem too stiff or bad initial guess | Increase maxiter, reduce restol, try Picard |
| - | Extremely slow execution | Too many elements or FS on large mesh | Reduce mesh size or use simpler flow equation |
| - | Segmentation fault | Memory exhaustion on large mesh | Increase np (processors) or reduce mesh |
| dt_001 | Velocity near zero everywhere | Velocity data in m/s, not m/yr | Multiply by 3.1536e7 |

## Example

```python
# Complete Pig simulation with inversion + transient
# Step 1: Diagnostic (steady-state velocity)
md = solve(md, 'Stressbalance')
vel_diag = md.results.StressbalanceSolution.Vel
print(f"Diagnostic max velocity: {np.max(vel_diag):.0f} m/yr")

# Step 2: Use diagnostic as initial condition for transient
md.initialization.vx = md.results.StressbalanceSolution.Vx
md.initialization.vy = md.results.StressbalanceSolution.Vy

# Step 3: Run 50-year transient
md.timestepping.time_step = 0.5
md.timestepping.final_time = 50
md.transient.requested_outputs = ['default', 'IceVolume']
md = solve(md, 'Transient')

# Step 4: Analyze volume change
volumes = [md.results.TransientSolution[i].IceVolume
           for i in range(len(md.results.TransientSolution))]
print(f"Volume change: {volumes[-1] - volumes[0]:.2e} m^3")
```
