# Stage 6: Inverse Problems (Parameter Inference)

## Purpose

Infer unknown model parameters (ice fluidity, basal friction coefficient) from
observed velocity data using adjoint-based optimization. This is critical for
real-world simulations where these parameters cannot be measured directly.

## Inputs

| Input | Type | Unit | Description |
|-------|------|------|-------------|
| Observed velocity | firedrake.Function (V) | m/yr | From satellite data |
| Initial guess for control | firedrake.Function (Q) | varies | Starting point for optimization |
| Model + solver | icepack model + FlowSolver | — | Forward model setup |
| Regularization weight | float | — | Smoothness constraint strength |

## Outputs

| Output | Type | Unit | Description |
|--------|------|------|-------------|
| Optimized control | firedrake.Function | varies | Best-fit parameter field |
| Simulated velocity | firedrake.Function | m/yr | Model velocity at optimum |

## Procedure

1. **Define the simulation function**:
   ```python
   def simulation(A):
       return solver.diagnostic_solve(
           velocity=u_obs, thickness=h, fluidity=A
       )
   ```

2. **Define loss functional** (model-data misfit):
   ```python
   from firedrake import inner, dx, assemble

   def loss(u_sim):
       δu = u_sim - u_obs
       return 0.5 * inner(δu, δu) * dx
   ```

3. **Define regularization** (smoothness prior):
   ```python
   from firedrake import grad

   α = firedrake.Constant(1e-2)  # regularization weight

   def regularization(A):
       return 0.5 * α * inner(grad(A), grad(A)) * dx
   ```

4. **Create and solve the inverse problem**:
   ```python
   problem = icepack.statistics.StatisticsProblem(
       simulation=simulation,
       loss_functional=loss,
       regularization=regularization,
       controls=A_initial,
   )

   estimator = icepack.statistics.MaximumProbabilityEstimator(
       problem,
       algorithm="trust-region",  # or "bfgs"
       max_iterations=50,
       gradient_tolerance=1e-4,
   )
   result = estimator.solve()
   A_opt = estimator.controls
   ```

5. **Post-process**: Compare simulated vs observed velocity.

## Verification

- [ ] Optimizer converged (check iteration count < max_iterations)
- [ ] Misfit reduced significantly from initial guess
- [ ] Optimized parameter field is physically reasonable
- [ ] No overfitting: smooth parameter field, not noisy
- [ ] Regularization weight balances fit vs smoothness

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Regularization too weak | Noisy, overfitted parameter field | Increase α |
| Regularization too strong | Parameters nearly uniform, poor fit | Decrease α |
| Bad initial guess | Optimizer stuck in local minimum | Try multiple starting points |
| Forward solver diverges during optimization | ConvergenceError in iteration | Use ROL wrapper (returns ∞ on crash) |
| Annotation not enabled | Adjoint fails silently | Call firedrake.adjoint.continue_annotation() |
| Wrong observed velocity units | Misfit dominated by unit error | Ensure u_obs in m/yr |

## Example

```python
import firedrake
import icepack

# Setup (assuming mesh, h, u_obs, solver already defined)
Q = h.function_space()

# Initial guess: uniform fluidity
A0 = firedrake.Function(Q)
A0.interpolate(firedrake.Constant(icepack.rate_factor(260.0)))

# Define inverse problem
def simulation(A):
    return solver.diagnostic_solve(velocity=u_obs, thickness=h, fluidity=A)

α = firedrake.Constant(1e-2)
problem = icepack.statistics.StatisticsProblem(
    simulation=simulation,
    loss_functional=lambda u: 0.5 * firedrake.inner(u - u_obs, u - u_obs) * firedrake.dx,
    regularization=lambda A: 0.5 * α * firedrake.inner(firedrake.grad(A), firedrake.grad(A)) * firedrake.dx,
    controls=A0,
)

estimator = icepack.statistics.MaximumProbabilityEstimator(problem, max_iterations=30)
estimator.solve()
A_opt = estimator.controls
```
