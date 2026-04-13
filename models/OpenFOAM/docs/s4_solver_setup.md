# S4: Solver Setup and Scheme Selection

## Purpose

Select appropriate numerical schemes and solver settings for the specific
physics being simulated. The choice of discretization schemes, convergence
criteria, and relaxation factors determines solution accuracy and stability.

## Inputs

| Input | Source | Format |
|-------|--------|--------|
| Solver type | Physics requirements | incompressibleFluid, fluid, etc. |
| Mesh quality | checkMesh report | Non-orthogonality, skewness |
| Expected flow regime | Re analysis | Laminar, turbulent, transitional |
| Accuracy requirements | Project specification | 1st or 2nd order |
| Steady vs transient | Problem type | SIMPLE, PISO, PIMPLE |

## Outputs

| Output | Location | Format |
|--------|----------|--------|
| fvSchemes | system/fvSchemes | OpenFOAM dictionary |
| fvSolution | system/fvSolution | OpenFOAM dictionary |

## Procedure

### 1. Time discretization (ddtSchemes)

| Scheme | Order | Use Case |
|--------|-------|----------|
| `steadyState` | - | SIMPLE algorithm (steady problems) |
| `Euler` | 1st | Transient, maximum stability |
| `backward` | 2nd | Transient, improved accuracy |
| `CrankNicolson 0.9` | 2nd | Transient, good accuracy/stability balance |

### 2. Gradient schemes (gradSchemes)

| Scheme | Notes |
|--------|-------|
| `Gauss linear` | Standard, 2nd order |
| `cellLimited Gauss linear 1` | Bounded, prevents overshoots near walls |
| `leastSquares` | Better for non-orthogonal meshes |

### 3. Convection schemes (divSchemes)

| Scheme | Order | Stability | Use |
|--------|-------|-----------|-----|
| `Gauss upwind` | 1st | Very stable | Initial runs, debugging |
| `Gauss linearUpwind grad(U)` | 2nd | Stable | Production runs |
| `Gauss linear` | 2nd | Less stable | Requires fine mesh |
| `Gauss QUICK` | 3rd | Limited stability | Hex-only meshes |
| `Gauss vanLeer` | 2nd TVD | Stable | VoF alpha equation |

### 4. PIMPLE algorithm settings

| Parameter | SIMPLE | PISO | PIMPLE |
|-----------|--------|------|--------|
| nOuterCorrectors | 1 | 1 | 2-50 |
| nCorrectors | 2 | 2-4 | 1-3 |
| nNonOrthogonalCorrectors | 0-2 | 0-1 | 0-2 |
| Relaxation (U) | 0.7 | 1.0 | 0.7 |
| Relaxation (p) | 0.3 | 1.0 | 0.3 |

### 5. Linear solver selection

| Variable | Recommended Solver | Reason |
|----------|--------------------|--------|
| p, p_rgh | GAMG + DICGaussSeidel | Fast multigrid for pressure Poisson |
| U, k, epsilon, omega | smoothSolver + symGaussSeidel | Efficient for transport equations |
| alpha.water | smoothSolver + symGaussSeidel | Phase fraction transport |

### 6. Mesh-dependent adjustments

| Mesh Quality Issue | Adjustment |
|--------------------|------------|
| Non-orthogonality > 40 | Add nNonOrthogonalCorrectors = 1-2 |
| Non-orthogonality > 70 | Use `limited corrected 0.5` for snGrad and laplacian |
| High skewness > 2 | Reduce relaxation factors |
| High aspect ratio > 20 | Use `cellLimited` gradient scheme |

## Verification

1. Run a few time steps and check:
   - Residuals decrease monotonically (or at least bounded)
   - No "Floating point exception" or NaN values
   - Courant number within expected range
2. Compare 1st order (upwind) vs 2nd order (linearUpwind) results
3. Check solution is mesh-independent (run on coarser/finer mesh)

## Traps

| Trap | Symptom | Prevention |
|------|---------|------------|
| Missing divScheme entry | "div scheme not specified for div(phi,U)" | Add explicit entry for each divergence term |
| `none` default in divSchemes | Fatal error if any div term unmatched | Only use `none` as default if all terms listed |
| linear on coarse mesh | Oscillations, unbounded solution | Use linearUpwind or TVD scheme |
| No non-ortho correctors on bad mesh | Pressure oscillations, divergence | Add nNonOrthogonalCorrectors for non-ortho > 40 |
| Over-relaxation with SIMPLE | Oscillating residuals, no convergence | Reduce relaxation factors to 0.3-0.7 |
| relTol 0 for all solvers | Extremely slow (solves to machine precision) | Use relTol 0 only for "Final" corrector |

## Example

Scheme selection for turbulent pipe flow (PIMPLE):

```
fvSchemes:
  ddt: backward (2nd order transient)
  grad: cellLimited Gauss linear 1 (bounded gradients)
  div(phi,U): Gauss linearUpwind grad(U) (2nd order upwind)
  div(phi,k): bounded Gauss linearUpwind (turbulence, bounded)
  laplacian: Gauss linear corrected (2nd order, orthogonal mesh)

fvSolution:
  p: GAMG, tol=1e-6, relTol=0.01
  U: smoothSolver, tol=1e-6, relTol=0.1
  PIMPLE: nOuter=3, nCorr=2, nNonOrtho=1
  relaxation: U=0.7, p=0.3, k=0.7
```
