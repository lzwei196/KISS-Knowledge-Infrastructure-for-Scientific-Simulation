# S8: Validation

## Purpose

Validate Elmer/Ice simulation results against analytical solutions, benchmark
intercomparisons, or observational data. This stage confirms that the model
setup is correct and the results are physically meaningful.

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| Simulation output | Stage s7 | CSV time series and snapshots |
| Analytical solution | Literature | Exact solutions for idealized problems |
| Benchmark data | ISMIP-HOM, MISMIP | Community intercomparison results |
| Observations | MEaSUREs, GRACE | Surface velocity, mass change |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Validation figure | PNG | Observed vs simulated comparison plot |
| Metrics | JSON | Quantitative error statistics |
| Findings | Text | Key observations about model performance |

## Procedure

### Benchmark Validation (ISMIP-HOM)

ISMIP-HOM (Ice Sheet Model Intercomparison Project — Higher-Order Models)
provides standard test cases with community consensus results.

**Experiment A**: Ice flow over a sinusoidal bed with periodic boundary conditions.
- Domain: L = 5, 10, 20, 40, 80, 160 km
- Surface: `s(x) = -x * tan(α)` with α = 0.5°
- Bed: `b(x) = s(x) - 1000 + 500 * sin(2πx/L) * sin(2πy/L)`
- Expected: velocity profile at y=L/4

**Verification steps**:
1. Run SSA and/or Stokes solver for each domain length
2. Extract velocity along centerline
3. Compare to published Pattyn et al. (2008) results
4. Compute RMS error relative to full-Stokes consensus

### Observational Validation

For real-world simulations (e.g., Greenland outlet glacier):

1. **Surface velocity**: Compare simulated SSAVelocity with MEaSUREs/ITS_LIVE
2. **Ice thickness change**: Compare dH/dt with CryoSat-2/ICESat-2
3. **Grounding line position**: Compare GroundedMask with InSAR observations
4. **Mass balance**: Compare integrated flux with GRACE/GRACE-FO

### Metrics

| Metric | Formula | Good Value | Use Case |
|--------|---------|------------|----------|
| RMSE | sqrt(mean((sim-obs)^2)) | < 20% of obs range | Velocity, thickness |
| Mean Bias | mean(sim-obs) | < 5% of obs mean | Systematic error check |
| Correlation (r) | pearson(sim, obs) | > 0.9 | Spatial pattern match |
| Relative Error | |sim-obs|/|obs| * 100 | < 10% | Per-point accuracy |
| Volume Error | (V_sim-V_obs)/V_obs * 100 | < 5% | Integrated check |

### Analytical Solutions

For simple geometries, compare to exact solutions:

**Vialov Profile** (SIA, dome geometry):
```
H(r) = H0 * (1 - (r/R)^((n+1)/n))^(n/(2n+2))
```

**Slab on slope** (SIA, uniform thickness):
```
u_surface = 2A/(n+1) * (ρg sin α)^n * H^(n+1)
```

## Verification

- RMSE should decrease with mesh refinement (convergence check)
- Velocity patterns should be physically plausible:
  - Fast flow near margins/outlet glaciers
  - Slow flow at ice divides
  - Velocity increases toward calving front
- Thickness should remain positive
- Grounding line should be at flotation

## Traps

| Trap | Effect | Prevention |
|------|--------|-----------|
| Comparing m/s (model) to m/a (obs) | 10^7x apparent error | Always convert units first |
| Wrong benchmark parameters | Validation fails falsely | Double-check L, α, n values |
| Insufficient mesh resolution | Poor benchmark scores | Use ≥100 elements per wavelength |
| Steady state not reached | Comparing transient to equilibrium | Run until convergence |

## Example

```bash
# ISMIP-HOM Experiment A validation
ElmerGrid 1 2 rectangle
ElmerSolver ismip_SSA_1D.sif

# Extract and compare
python parse_vtu_output.py --vtu_dir . --pattern "test_SSA*.vtu" \
    --variables SSAVelocity --output ismip_results.csv \
    --convert_velocity_to_ma

# Plot comparison
python -c "
import pandas as pd
import matplotlib.pyplot as plt
df = pd.read_csv('ismip_results.csv')
plt.plot(df['x']/1000, df['SSAVelocity_m_per_a'], 'b-', label='Elmer/Ice')
plt.xlabel('x (km)')
plt.ylabel('Velocity (m/a)')
plt.legend()
plt.savefig('validation.png')
"
```
