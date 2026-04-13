# S7: Calibration Guide

## Purpose

Tune ROMS model parameters to improve agreement with observations. Unlike
data assimilation (which adjusts the state), calibration adjusts the physics
parameters that control mixing, drag, and advection behavior.

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| Baseline simulation | NetCDF | Un-calibrated ROMS output |
| Observations | CSV/NetCDF | Tide gauges, CTD, ARGO, satellite |
| Validation metrics | JSON | From S6 validation |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Calibrated `roms.in` | Text | Updated parameter values |
| Sensitivity table | CSV | Parameter-metric sensitivity matrix |

## Procedure

### Step 1: Identify calibration targets

Based on S6 validation results, determine which model aspects need improvement:

| Problem | Parameters to tune | Priority |
|---------|-------------------|----------|
| SST bias | BULK_FLUXES params, shortwave penetration | High |
| Weak stratification | AKT_BAK, vertical mixing closure | High |
| Tidal amplitude error | Bottom drag (RDRG2, Zob) | High |
| Excessive diffusion | VISC2, TNU2 | Medium |
| Boundary artifacts | Tnudg, sponge layer | Medium |
| Depth-averaged current error | Bottom drag, VISC2 | Medium |

### Step 2: Parameter sensitivity analysis

Run one-at-a-time perturbation experiments:

| Parameter | Low | Default | High | Units | Affects |
|-----------|-----|---------|------|-------|---------|
| VISC2 | 1.0 | 5.0 | 50.0 | m²/s | Horizontal momentum mixing |
| TNU2 | 0.0 | 0.0 | 10.0 | m²/s | Horizontal tracer diffusion |
| AKT_BAK | 1e-7 | 1e-6 | 1e-4 | m²/s | Background vertical diffusivity |
| AKV_BAK | 1e-6 | 1e-5 | 1e-3 | m²/s | Background vertical viscosity |
| RDRG2 | 1e-4 | 3e-3 | 1e-2 | - | Quadratic bottom drag |
| Zob | 0.001 | 0.02 | 0.05 | m | Bottom roughness length |
| THETA_S | 1.0 | 7.0 | 10.0 | - | Surface stretching |
| THETA_B | 0.0 | 2.0 | 4.0 | - | Bottom stretching |
| Tnudg | 1.0 | 10.0 | 180.0 | days | Boundary nudging |

### Step 3: Iterative calibration

1. Run baseline with default parameters
2. Perturb highest-priority parameter (±50%)
3. Compare metrics against observations
4. Select best value
5. Fix that parameter, move to next
6. Repeat until convergence

### Step 4: Final validation

Re-run S6 validation with calibrated parameters. Metrics should improve
across all variables, not just the calibrated target.

## Traps

| Trap | Description | Consequence |
|------|-------------|-------------|
| Over-tuning one metric | Tuning SST at expense of currents | Poor overall skill |
| Compensating errors | Large VISC2 hides grid-scale noise | Unrealistic diffusion |
| Not enough spin-up | Evaluating during adjustment period | Misleading metrics |
| Forgetting recompilation | Changing CPP flags without rebuild | Old binary used |

## Example

```bash
# Sensitivity run: low bottom drag
sed 's/RDRG2 == 3.0d-3/RDRG2 == 1.0d-3/' roms.in > roms_lowdrag.in
mpirun -np 8 ./romsM roms_lowdrag.in > roms_lowdrag.log 2>&1

# Compare tidal amplitudes
python tools/parse_roms_output.py \
  --input roms_lowdrag_his.nc --variable zeta --mode timeseries \
  --lon -74.0 --lat 40.5 --output ssh_lowdrag.csv
```
