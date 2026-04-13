# Stage 6: Validation and Metrics

## Purpose

Validate CISM simulation results against analytical solutions, published
benchmarks (EISMINT, ISMIP-HOM), or observational data. Compute domain-
appropriate metrics and generate comparison plots.

## Inputs

| Input | Source | Required |
|-------|--------|----------|
| Simulation results | s5 (CSV or NetCDF) | Yes |
| Reference data | Analytical, benchmark, or observations | Yes |
| Test case type | User (dome, halfar, EISMINT, real) | Yes |

## Outputs

| Output | Format | Used by |
|--------|--------|---------|
| Validation metrics | JSON/dict | Reporting |
| Comparison figures | PNG (matplotlib) | Documentation |
| Pass/fail assessment | Text | Decision |

## Procedure

### 1. Analytical Solutions

**Halfar dome** (SIA benchmark):
```
h(r, t) = H0 * (t0/t)^(1/9) * max(0, [1 - ((t0/t)^(1/18) * r/R0)^(4/3)])^(3/7)
```
Where H0=3600m, R0=750km, t0 depends on H0, R0, and flow parameters.

**Vialov profile** (steady-state SIA):
```
h(r) = h0 * (1 - (r/R)^((n+1)/n))^(n/(2n+2))
```
Where n=3 (Glen's flow law), h0 is divide thickness.

### 2. EISMINT Benchmarks

Compare against published EISMINT-1/2 results:
- Divide thickness (m): expect ~3000m for EISMINT-2a
- Divide basal temperature (deg C): expect ~-8.6C for EISMINT-2a
- Ice volume evolution to steady state

### 3. Metrics for Real Ice Sheets

**Geometric metrics**:
- Ice volume bias: (V_sim - V_obs) / V_obs * 100 (%)
- Ice area bias: (A_sim - A_obs) / A_obs * 100 (%)
- RMSE of ice thickness: sqrt(mean((thk_sim - thk_obs)^2))
- Max thickness error

**Velocity metrics**:
- Log-space RMSE: sqrt(mean((log10(v_sim) - log10(v_obs))^2))
- Velocity ratio: median(v_sim / v_obs)
- Pattern correlation: r(v_sim, v_obs)

**Temperature metrics**:
- Basal temperature RMSE
- Temperate ice fraction bias

### 4. Plotting

- **Time series**: ice volume, area, max thickness vs time
- **Spatial maps**: thk, velnorm, btemp at final time
- **Profiles**: thickness and velocity along transects
- **Scatter**: simulated vs observed velocity

Conventions:
- Observed/reference: black
- Simulated: #2563EB (blue)
- Metrics box: top-right, white background

## Verification

- [ ] Metrics computed and reported
- [ ] Figures generated at specified paths
- [ ] Values are physically reasonable
- [ ] Dome: center thickness within 5% of analytical
- [ ] EISMINT: divide thickness within 50m of published

## Traps

| ID | Trap | Prevention |
|----|------|-----------|
| dt_013 | Compare m/s velocity to m/yr reference | Ensure consistent units |
| dt_001 | SMB error propagates to volume bias | Check SMB units first |
| dt_002 | Zero velocity -> zero metrics | Verify flow is occurring |

## Example

```python
import numpy as np

# Dome benchmark: compare max thickness
simulated_thk = 2856.0  # m (from output)
analytical_thk = 2900.0  # m (Vialov solution)
error_pct = abs(simulated_thk - analytical_thk) / analytical_thk * 100
print(f"Thickness error: {error_pct:.1f}%")  # Should be < 5%

# Ice volume time series correlation
from scipy.stats import pearsonr
r, p = pearsonr(vol_sim, vol_obs)
print(f"Volume correlation: r={r:.3f}, p={p:.2e}")
```
