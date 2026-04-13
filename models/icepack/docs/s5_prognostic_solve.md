# Stage 5: Prognostic Thickness Evolution

## Purpose

Advance the ice thickness forward in time by solving the mass continuity equation.
Given a velocity field (from the diagnostic solve) and surface mass balance, compute
the new thickness after a time step dt.

## Inputs

| Input | Type | Unit | Description |
|-------|------|------|-------------|
| dt | float | years | Time step |
| thickness | firedrake.Function (Q) | m | Current ice thickness |
| velocity | firedrake.Function (V) | m/yr | Current velocity field |
| accumulation | firedrake.Function (Q) | m/yr | Surface mass balance (positive = accumulation) |
| thickness_inflow | firedrake.Function (Q) | m | Optional: inflow thickness at boundaries |

## Outputs

| Output | Type | Unit | Description |
|--------|------|------|-------------|
| thickness_new | firedrake.Function (Q) | m | Updated ice thickness |

## Procedure

1. **Set accumulation rate**:
   ```python
   a = firedrake.Function(Q)
   a.interpolate(firedrake.Constant(0.3))  # 0.3 m/yr accumulation
   ```

2. **Run prognostic solve**:
   ```python
   h_new = solver.prognostic_solve(
       dt=0.5,           # 0.5 year timestep
       thickness=h,
       velocity=u,
       accumulation=a,
   )
   ```

3. **Update surface** (for grounded models):
   ```python
   s = icepack.compute_surface(thickness=h_new, bed=b)
   ```

4. **Time-stepping loop**:
   ```python
   for step in range(num_steps):
       u = solver.diagnostic_solve(velocity=u, thickness=h, fluidity=A)
       h = solver.prognostic_solve(dt, thickness=h, velocity=u, accumulation=a)
   ```

5. **Timestepping schemes**:
   - **Lax-Wendroff** (default): 2nd-order, adds streamline diffusion to reduce oscillations
   - **Implicit Euler**: 1st-order, more diffusive, included for backward compatibility

## Verification

- [ ] h_new > 0 everywhere (mass conservation must not produce negative thickness)
- [ ] Total ice volume change ≈ integral of accumulation × dt (mass budget)
- [ ] No spurious oscillations at boundaries
- [ ] Thickness change is smooth and physically reasonable

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| dt too large | Negative thickness, oscillations | Reduce dt; CFL-like constraint |
| Accumulation in wrong units | Mass gain/loss too fast | Must be in m ice/yr; convert from m w.e./yr if needed |
| Zero accumulation when thinning | Glacier thins to zero and crashes | Check sign convention: positive = gain |
| Missing velocity update | Thickness drifts unrealistically | Must re-solve diagnostic each step |
| Lax-Wendroff oscillations | Small thickness oscillations at fronts | Try implicit-euler or smaller dt |
| Not updating surface | Surface desyncs from thickness | Recompute s after each prognostic step |

## Example

```python
import firedrake
import icepack

mesh = firedrake.RectangleMesh(64, 64, 50e3, 50e3)
Q = firedrake.FunctionSpace(mesh, "CG", 2)
V = firedrake.VectorFunctionSpace(mesh, "CG", 2)

# Initialize
x, y = firedrake.SpatialCoordinate(mesh)
h = firedrake.Function(Q).interpolate(500 - 100 * x / 50e3)
A = firedrake.Function(Q).interpolate(firedrake.Constant(icepack.rate_factor(254.15)))
a = firedrake.Function(Q).interpolate(firedrake.Constant(0.3))  # 30 cm/yr
u = firedrake.Function(V)

model = icepack.models.IceShelf()
solver = icepack.solvers.FlowSolver(model, dirichlet_ids=[1])

# Time stepping
dt = 0.5  # years
for step in range(200):
    u = solver.diagnostic_solve(velocity=u, thickness=h, fluidity=A)
    h = solver.prognostic_solve(dt, thickness=h, velocity=u, accumulation=a)

    if (step + 1) % 50 == 0:
        print(f"Step {step+1}: <h> = {h.dat.data.mean():.1f} m")
```
