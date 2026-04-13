# WRF-Hydro Calibration Guide

## Calibration Parameters by Priority

### Tier 1 — Adjust First
| Param | File | Default | Range | Controls |
|-------|------|:-------:|-------|----------|
| **REFKDT** | soil_properties.nc / GENPARM.TBL | 3.0 | 0.1-10 | Peak magnitude (infiltration vs runoff) |
| **MannN** | CHANPARM.TBL (per stream order) | 0.02-0.09 | ×0.5-3.0 | Peak timing + attenuation |
| **OVROUGHRTFAC** | Fulldom_hires.nc | 1.0 | 0.1-10 | Overland flow speed → peak delay |
| **GW Coeff** | GWBUCKPARM.nc | 0.04 | 0.001-0.5 | Baseflow magnitude |
| **GW Zmax** | GWBUCKPARM.nc | 50 mm | 10-500 | Baseflow memory/recession |

### Tier 2 — Fine-tune
| Param | File | Default | Range | Controls |
|-------|------|:-------:|-------|----------|
| **SLOPE** | GENPARM.TBL | 0.1-1.0 | 0-1 | Subsurface drainage rate |
| **RETDEPRTFAC** | Fulldom_hires.nc | 1.0 | 0.1-10 | Ponding → peak dampening |
| **GW Expon** | GWBUCKPARM.nc | 3.0 | 1-8 | Baseflow nonlinearity |
| **LKSATFAC** | Fulldom_hires.nc | 1000 | 10-10000 | Lateral subsurface flow |

### Tier 3 — Seasonal/Volume
| Param | File | Default | Range | Controls |
|-------|------|:-------:|-------|----------|
| FRZK | GENPARM.TBL | 0.15 | 0.05-0.5 | Frozen soil infiltration |
| CZIL | GENPARM.TBL | 0.1 | 0.01-1.0 | ET → total volume |
| BEXP | soil_properties.nc | soil-dep | ×0.5-2.0 | Soil moisture retention |
| DKSAT | soil_properties.nc | soil-dep | ×0.1-10 | Infiltration + drainage |

## Schaake Infiltration Formula (RUNOFF_OPTION=3)
```
KDT = REFKDT × DKSAT(layer1) / REFDK
VAL = 1 - exp(-KDT × dt/86400)
DD = Σ(layer_depth × (SMCMAX-SMCWLT) × (1 - (SH2O-SMCWLT)/(SMCMAX-SMCWLT)))
INFMAX = (P × DD×VAL) / (P + DD×VAL) / dt
RUNSRF = max(0, QINSUR - INFMAX)
```

## Calibration Strategy
1. **REFKDT first** — controls 80% of peak magnitude
2. **MannN + OVROUGHRTFAC** — attenuate remaining peak overshoot
3. **SLOPE + GW params** — match baseflow recession
4. **CZIL** — adjust total water balance if needed

## Chaohe Results
- REFKDT=3.0 (default): r=-0.08, flat baseflow, no storm peaks
- REFKDT=0.1: r=0.50, peaks 5× too high (1750 vs 340 m³/s)
- **Optimal: ~0.3-0.5 + routing attenuation**
