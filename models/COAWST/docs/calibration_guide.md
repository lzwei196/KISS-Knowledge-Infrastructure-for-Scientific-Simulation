# Calibration Guide

## Purpose
Systematic guide for tuning COAWST/ROMS parameters to improve agreement with observations. Calibration is performed iteratively, adjusting one parameter group at a time, from most to least sensitive.

## Parameter Priority

Parameters are ordered by sensitivity — calibrate high-sensitivity parameters first.

### Priority 1: Timestep and Stability (MUST get right first)
| Parameter   | Keyword    | Range        | Effect                                     |
|-------------|------------|--------------|---------------------------------------------|
| DT          | DT         | 1–300 s      | Baroclinic timestep. Too large → BLOWUP     |
| NDTFAST     | NDTFAST    | 10–60        | Barotropic ratio. Too small → instability    |

**Procedure**: Start with a conservative DT (small value) and NDTFAST=30. If stable, gradually increase DT. If blowup, reduce DT by 50%.

CFL criterion: `DT_baro = DT/NDTFAST < dx_min / sqrt(g × h_max)`

### Priority 2: Vertical Coordinate
| Parameter   | Keyword      | Range      | Effect                                    |
|-------------|-------------|------------|-------------------------------------------|
| Vtransform  | Vtransform  | 1 or 2     | V2 recommended (avoids shallow issues)    |
| Vstretching | Vstretching | 1–5        | V4 recommended (better resolution control)|
| theta_s     | THETA_S     | 0.1–10.0   | Surface resolution. Higher = more surface |
| theta_b     | THETA_B     | 0.0–4.0    | Bottom resolution. Higher = more bottom   |
| Tcline      | TCLINE      | 10–300 m   | Thermocline tracking depth                |

**Procedure**: Use Vtransform=2, Vstretching=4 for most applications. Set theta_s=7.0 for strong surface processes (SST, mixing). Set theta_b=2.0 for bottom boundary layer. Tcline should be near the thermocline depth.

Verify with S-coordinate plots:
```python
# Visualize vertical levels
import numpy as np
# Use ROMS stretching functions to compute Cs_r, Cs_w
# Plot z-levels vs depth for h = [10, 100, 1000, 5000] m
```

### Priority 3: Horizontal Mixing
| Parameter   | Keyword | Range           | Effect                                    |
|-------------|---------|-----------------|-------------------------------------------|
| VISC2       | VISC2   | 1–100 m²/s     | Laplacian viscosity. Higher = smoother     |
| TNU2        | TNU2    | 0–50 m²/s      | Tracer diffusion. Higher = less gradients  |
| VISC4       | VISC4   | 1e6–1e10 m⁴/s  | Biharmonic viscosity (if VISC4 enabled)    |

**Procedure**: Start with VISC2=5.0, TNU2=5.0 for ~1 km grids. Scale roughly linearly with grid spacing. If noisy patterns appear, increase viscosity. If features are too smooth, decrease.

### Priority 4: Bottom Friction
| Parameter   | Keyword | Range           | Effect                                    |
|-------------|---------|-----------------|-------------------------------------------|
| RDRG2       | RDRG2   | 1e-4–1e-2      | Quadratic drag coefficient                |
| Zob         | ZOB     | 0.001–0.1 m    | Bottom roughness length (if LOG_PROFILE)  |

**Procedure**: Default RDRG2=3.0e-3 works for most open ocean. Increase for shallow/estuarine (up to 0.01). Decrease for deep ocean (down to 3e-4).

### Priority 5: Boundary Conditions
| Parameter   | Keyword | Range           | Effect                                    |
|-------------|---------|-----------------|-------------------------------------------|
| TNUDG       | TNUDG   | 1–360 days      | Tracer nudging. Shorter = follows BC more |
| ZNUDG       | ZNUDG   | 0.01–30 days    | SSH nudging timescale                     |
| M2NUDG      | M2NUDG  | 0.01–10 days    | 2D momentum nudging                       |
| obcfac      | OBCFAC  | 0–10            | Increased nudging at boundary             |

**Procedure**: Start with moderate nudging (TNUDG=10 days). If boundary artifacts propagate inward, reduce to 3 days. If interior is over-constrained, increase to 30+ days. Use stronger nudging for 2D fields (ZNUDG=1 day).

### Priority 6: Wave Coupling (SWAN Parameters)
| Parameter            | Range        | Effect                                    |
|---------------------|--------------|-------------------------------------------|
| Direction bins       | 24–72        | More bins = better directional resolution |
| Frequency range      | 0.03–1.0 Hz | Must cover swell to wind-sea              |
| Frequency bins       | 25–40        | Logarithmic spacing                       |
| Breaking constant    | 0.65–0.85    | Higher = more dissipation at coast        |
| Friction (JONSWAP)   | 0.038–0.100  | Higher = more bottom dissipation          |

## Calibration Workflow

1. **Baseline run**: Default parameters, check stability (no BLOWUP)
2. **SSH calibration**: Compare sea level to tide gauge data. Adjust TNUDG, tidal forcing
3. **SST calibration**: Compare surface temperature to satellite/buoy. Adjust theta_s, mixing
4. **Current calibration**: Compare to ADCP/drifter data. Adjust VISC2, RDRG2
5. **Wave calibration** (if coupled): Compare Hsig to buoy data. Adjust SWAN parameters
6. **Sensitivity analysis**: Vary one parameter ±50%, check metric response

## Automated Calibration

For systematic calibration, run parameter sweeps:
```bash
for rdrg in 0.001 0.003 0.005 0.01; do
  sed "s/RDRG2 ==.*/RDRG2 == ${rdrg}d0/" ocean_base.in > ocean_rdrg${rdrg}.in
  mpirun -np 4 ./coawstM ocean_rdrg${rdrg}.in > log_${rdrg}.txt 2>&1
  python3 ki/tools/parse_output.py \
    --history his_rdrg${rdrg}.nc --variable zeta --level surface \
    --observations obs.csv --output metrics_${rdrg}.csv --metrics
done
```

## Common Calibration Pitfalls

- **Over-tuning**: Don't match one station perfectly at the expense of others
- **Compensating errors**: A wrong SST + wrong currents can accidentally give correct sea level
- **Non-physical parameters**: VISC2 > 100 m²/s at 1 km resolution is non-physical
- **Forgetting spin-up**: Always exclude the first 3-7 days from metric calculations
- **Resolution dependence**: Parameters calibrated for 10 km grid do NOT transfer to 1 km grid
