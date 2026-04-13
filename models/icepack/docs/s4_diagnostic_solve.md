# Stage 4: Diagnostic Velocity Solve

## Purpose

Solve for the ice velocity field given the current ice geometry (thickness, surface)
and material properties (fluidity, friction). This is the core physics solve that
finds the velocity satisfying the momentum balance equations as a variational
minimization problem.

## Inputs

| Input | Type | Unit | Required By |
|-------|------|------|-------------|
| velocity (initial guess) | firedrake.Function (V) | m/yr | All models |
| thickness | firedrake.Function (Q) | m | All models |
| fluidity (A) | firedrake.Function (Q) | MPa^-3 yr^-1 | All models |
| surface | firedrake.Function (Q) | m | IceStream, ShallowIce, Hybrid |
| friction (C) | firedrake.Function (Q) | model-specific | IceStream, Hybrid |
| dirichlet_ids | list[int] | — | Where velocity is prescribed |
| side_wall_ids | list[int] | — | Where normal flow = 0 |

## Outputs

| Output | Type | Unit | Description |
|--------|------|------|-------------|
| velocity | firedrake.Function (V) | m/yr | Solved velocity field |

## Procedure

1. **Create model and solver**:
   ```python
   model = icepack.models.IceShelf()  # or IceStream, etc.
   solver = icepack.solvers.FlowSolver(
       model,
       dirichlet_ids=[1],  # inflow boundary
       side_wall_ids=[3, 4],  # wall boundaries
   )
   ```

2. **Run diagnostic solve**:
   ```python
   u = solver.diagnostic_solve(
       velocity=u0,       # initial guess
       thickness=h,
       fluidity=A,
       # surface=s,       # for IceStream/ShallowIce
       # friction=C,      # for IceStream
   )
   ```

3. **Solver internals**:
   - Forms the action functional E(u) = viscosity + friction − gravity − terminus
   - Computes F = dE/du (residual) and J = d²E/du² (Jacobian)
   - Solves F(u) = 0 using PETSc SNES Newton method
   - Default: GMRES + LU preconditioner (MUMPS direct solver)

4. **Check convergence**:
   - PETSc SNES reports convergence reason
   - Typical: 3–10 Newton iterations for well-posed problems
   - Divergence usually means unphysical input data

## Verification

- [ ] Solver converged (no ConvergenceError)
- [ ] Velocity magnitude is physically reasonable (0–4000 m/yr for ice streams)
- [ ] No NaN in velocity field
- [ ] Velocity satisfies boundary conditions (u = u_prescribed on Dirichlet boundaries)
- [ ] Flow direction is physically reasonable (outward for ice shelves)

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Negative thickness | "invalid search direction" ConvergenceError | Enforce h > 0 everywhere |
| Wrong fluidity units | Unrealistic velocities | Use icepack.rate_factor(T) for correct A |
| Missing surface for IceStream | KeyError: 'surface' | Compute s = icepack.compute_surface(thickness=h, bed=b) |
| Bad initial velocity guess | Slow convergence or divergence | Start from observed velocity or zero + small perturbation |
| Dirichlet BC on wrong boundary | Flow direction wrong | Check mesh.exterior_facets.unique_markers |
| Friction too high/low | Solver stalls or unphysical speed | Typical C: 0.01–0.1 MPa yr^(1/m) m^(-1/m) |
| Zero friction coefficient | Division by zero in friction law | Use small positive C instead of 0 |

## Example

```python
import firedrake
import icepack

# Setup
mesh = firedrake.RectangleMesh(64, 64, 50e3, 50e3)
Q = firedrake.FunctionSpace(mesh, "CG", 2)
V = firedrake.VectorFunctionSpace(mesh, "CG", 2)

x, y = firedrake.SpatialCoordinate(mesh)
h = firedrake.Function(Q).interpolate(500 - 100 * x / 50e3)
A = firedrake.Function(Q).interpolate(firedrake.Constant(icepack.rate_factor(254.15)))
u0 = firedrake.Function(V)  # zero initial guess

# Solve
model = icepack.models.IceShelf()
solver = icepack.solvers.FlowSolver(model, dirichlet_ids=[1])
u = solver.diagnostic_solve(velocity=u0, thickness=h, fluidity=A)

# Check
import numpy as np
speed = np.sqrt(np.sum(u.dat.data**2, axis=1))
print(f"Max speed: {speed.max():.1f} m/yr")
```
