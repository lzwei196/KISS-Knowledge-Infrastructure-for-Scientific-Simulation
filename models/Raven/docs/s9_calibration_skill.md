# s9: Calibration Strategy

## Purpose

Optimize model parameters using DDS (Dynamically Dimensioned Search) to match observed discharge. Calibrate ONLY the best-performing template from the ensemble comparison.

## Prerequisites

- Completed ensemble comparison (s8) to identify best template
- Observed discharge data in .rvt file
- At least 5 years of data (3 calibration + 2 validation minimum)

## DDS Algorithm

DDS (Tolson & Shoemaker, 2007) is a single-solution global optimization algorithm designed for expensive model evaluations. Key properties:
- Starts with global search, automatically narrows to local refinement
- Perturbation probability decreases with iteration: p = 1 - log(i)/log(N)
- Works well with limited budget (100-500 evaluations)
- No population — single candidate per iteration

## Parameter Ranges by Template

### GR4J (4 parameters — recommended for calibration)
| Parameter | Min | Max | Default | Description |
|-----------|-----|-----|---------|-------------|
| GR4J_X1 | 1 | 1500 | 350 | Production store capacity (mm) |
| GR4J_X2 | -10 | 5 | 0 | GW exchange coefficient (mm/d) |
| GR4J_X3 | 1 | 500 | 90 | Routing store capacity (mm) |
| GR4J_X4 | 0.5 | 10 | 1.5 | Unit hydrograph time base (d) |

### HBV-EC (calibrate 5 of 21 parameters)
| Parameter | Min | Max | Default | Description |
|-----------|-----|-----|---------|-------------|
| MELT_FACTOR | 1 | 8 | 4 | Degree-day snowmelt |
| HBV_BETA | 0.5 | 6 | 2 | Soil moisture nonlinearity |
| MAX_PERC_RATE | 0.1 | 10 | 2 | Max percolation (mm/d) |
| BASEFLOW_COEFF | 0.001 | 0.5 | 0.05 | Baseflow recession (1/d) |
| FIELD_CAPACITY | 0.1 | 0.5 | 0.31 | Field capacity (fraction) |

### HYMOD (5 parameters)
| Parameter | Min | Max | Default | Description |
|-----------|-----|-----|---------|-------------|
| HYMOD_CMAX | 1 | 1000 | 200 | Max soil moisture (mm) |
| HYMOD_B | 0 | 2 | 0.5 | Spatial variability |
| HYMOD_ALPHA | 0 | 1 | 0.7 | Quick/slow partition |
| HYMOD_KS | 0.001 | 0.1 | 0.01 | Slow reservoir rate |
| HYMOD_KQ | 0.1 | 0.99 | 0.3 | Quick reservoir rate |

## Procedure

1. **Split data**: 70% calibration, 30% validation
2. **Start calibration**:
```bash
python calibrate_raven_dds.py \
    --run_dir <path> --basin_name <name> \
    --template hbv_ec --n_iterations 100 \
    --objective NSE
```
3. **Evaluate**: Check both calibration and validation period metrics
4. **Report**: Best parameters + NSE/KGE for both periods

## Rules of Thumb

- **GR4J**: 50-100 iterations sufficient (only 4 params)
- **HBV-EC**: 200-500 iterations (5 calibrated of 21 total)
- **SAC-SMA**: 500-1000 iterations (6+ params)
- **Data length**: Need at least 3 years per calibrated parameter
- **Warmup**: Discard first 1-2 years from calibration objective

## Validation Checks

- [ ] Calibration NSE > validation NSE (expected)
- [ ] Calibration NSE - validation NSE < 0.15 (no overfitting)
- [ ] Parameters within physical bounds
- [ ] Water balance closed (total P ~ total Q + total ET)

## Common Pitfalls

- **dt_015**: Wrong template for basin — no improvement possible
- **dt_016**: Overfitting with too many params vs data length
- Calibrating to wrong objective (RMSE biases toward peak matching; NSE biases toward mean flow)
