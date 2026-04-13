# S6: Initial and Boundary Conditions — Skill Document

## Purpose

Set the initial pressure head field and boundary conditions. The initial condition determines how quickly the simulation reaches physical equilibrium.

## Critical Concept: Pressure Head Semantics

- **Negative pressure** = unsaturated zone (soil suction/tension)
- **Positive pressure** = saturated zone (positive pore water pressure)
- **Zero pressure** = water table surface
- **Units**: meters of water (NOT Pa, NOT kPa) -- see dt_pf_004

## Initialization Methods

| Method | When to Use | Spinup Needed? |
|--------|-------------|----------------|
| Hydrostatic (uniform WTD) | Quick start, no prior information | Yes (10-50 yr) |
| Reinecke WTD | Best for new basins (global data) | Moderate (5-20 yr) |
| MODFLOW steady-state | If MODFLOW run exists | Minimal (1-5 yr) |
| Previous ParFlow restart | Continuing a run | None |

## Procedure

1. **Choose method** based on available data.
2. **Run** `generate_initial_conditions.py`.
3. **Verify** saturation_fraction: 0.3-0.7 is typical for most basins.
4. **Check** no extreme values (pressure < -200m or > +100m).

## Boundary Conditions

| Face | Default | When to Change |
|------|---------|----------------|
| Bottom | No-flow (impermeable bedrock) | Rarely -- default is usually correct |
| Sides | No-flow | Through-flow basins need constant head or flux |
| Top | OverlandFlow | Always -- this is where precip and ET interact |

## Spinup Strategy

ParFlow needs spinup to equilibrate the water table to the climate and topography.
- **Recommended**: 10-100 years of recycled forcing (repeat one year's forcing).
- **Shortcut**: Use MODFLOW steady-state water table as initial condition.
- **Sign of equilibrium**: Inter-annual water balance residual < 1% of precipitation.
