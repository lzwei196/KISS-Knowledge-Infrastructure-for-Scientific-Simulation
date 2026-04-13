# s4: Process Algorithm Reference

## Purpose

Reference guide for Raven's 120+ process algorithms. Each hydrological process has multiple interchangeable algorithms. The .rvi file selects one algorithm per process.

## Process Categories

### Infiltration (19 algorithms)
| Algorithm | Model Family | Description |
|-----------|-------------|-------------|
| INF_RATIONAL | Generic | Rational method |
| INF_SCS | Generic | SCS curve number |
| INF_GREEN_AMPT | Generic | Green-Ampt |
| INF_VIC | VIC | VIC variable infiltration curve |
| INF_HBV | HBV | HBV beta-function |
| INF_GR4J | GR4J | GR4J production store |
| INF_HMETS | HMETS | HMETS specific |
| INF_PRMS | PRMS | USGS PRMS |
| INF_UBC | UBC | UBC model |
| INF_TOPMODEL | TOPMODEL | TOPMODEL saturation excess |
| INF_PDM | PDM/HYMOD | Probability Distributed Model |
| INF_XINANXIANG | Xinanjiang | Chinese Xinanjiang model |

### Evapotranspiration (24 algorithms)
| Algorithm | Data Needed | Description |
|-----------|------------|-------------|
| PET_OUDIN | T_AVE | Oudin (temperature-only, simplest) |
| PET_HARGREAVES_1985 | T_MIN, T_MAX | Hargreaves-Samani 1985 |
| PET_PENMAN_MONTEITH | T, WIND, RH, SW, PRESS | Full Penman-Monteith |
| PET_PRIESTLEY_TAYLOR | T, SW | Priestley-Taylor |
| PET_HAMON | T_AVE | Hamon method |
| PET_MOHYSE | T | MOHYSE specific |
| PET_DATA | PET data | User-provided PET time series |

### Snow Balance (9 algorithms)
| Algorithm | Complexity | Model Family |
|-----------|-----------|-------------|
| SNOBAL_SIMPLE_MELT | Low | Generic degree-day |
| SNOBAL_HBV | Medium | HBV snow routine |
| SNOBAL_UBCWM | Medium | UBC model |
| SNOBAL_HMETS | Medium | HMETS specific |
| SNOBAL_CEMA_NEIGE | Medium | CemaNeige |
| SNOBAL_TWO_LAYER | High | Energy balance |
| SNOBAL_COLD_CONTENT | Medium | Cold content tracking |

### Baseflow (10 algorithms)
| Algorithm | Description |
|-----------|-------------|
| BASE_LINEAR | Linear reservoir |
| BASE_POWER_LAW | Power law recession |
| BASE_VIC | VIC baseflow |
| BASE_GR4J | GR4J routing store |
| BASE_TOPMODEL | TOPMODEL exponential |
| BASE_THRESH_POWER | Threshold power law |
| BASE_THRESH_STOR | Threshold storage |

### Percolation (12 algorithms)
| Algorithm | Description |
|-----------|-------------|
| PERC_LINEAR | Linear percolation |
| PERC_POWER_LAW | Power law |
| PERC_SACRAMENTO | Sacramento scheme |
| PERC_GR4J | GR4J exchange |
| PERC_PRMS | PRMS scheme |

## Algorithm Compatibility Rules

1. **Emulation templates are always compatible** — use select_model_template.py
2. **Same-family algorithms work together** — GR4J infiltration + GR4J baseflow + GR4J percolation
3. **Cross-family mixing requires care** — verify state variables are compatible
4. **State variable conflicts** cause fatal errors (dt_013)

## .rvi Format

```
:HydrologicProcesses
  :Precipitation    PRECIP_RAVEN
  :SnowBalance      SNOBAL_HBV         MULTIPLE MULTIPLE
  :Infiltration     INF_HBV            PONDED_WATER MULTIPLE
  :SoilEvaporation  SOILEVAP_HBV       SOIL[0] ATMOSPHERE
  :Percolation      PERC_LINEAR        SOIL[0] SOIL[1]
  :Baseflow         BASE_LINEAR        SOIL[0] SURFACE_WATER
  :Baseflow         BASE_LINEAR        SOIL[1] SURFACE_WATER
:EndHydrologicProcesses
```

Each process line: `:ProcessType  ALGORITHM  FROM_STATE  TO_STATE`

## Common Pitfalls

- **dt_013**: Mixing GR4J infiltration with HBV baseflow — incompatible state variables
- **dt_014**: Using PET_PENMAN_MONTEITH without providing wind/humidity/radiation
- Never use more than one algorithm per process type (except Baseflow, which can have multiple for different soil layers)
