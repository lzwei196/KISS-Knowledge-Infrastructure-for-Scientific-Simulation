# S9: Output Processing — Skill Document

## Purpose

Extract hydrological variables from ParFlow PFB output and convert to standard formats.

## Key Variables

| Variable | Source | Units | Extraction Method |
|----------|--------|-------|-------------------|
| Water table depth | saturation field | m below surface | Saturation >= 0.99 threshold (NOT pressure=0) |
| Overland flow depth | pressure at surface | m | Positive pressure at top layer |
| Soil moisture | saturation * porosity | m3/m3 | Per layer |
| Discharge at outlet | overland flow velocity * depth | m3/s | Sum at outlet cells |
| Subsurface storage | saturation * porosity * volume | m3 | Integrate over domain |

## Procedure

1. **Run** `parse_parflow_output.py` with run directory and domain JSON.
2. **Check** timeseries.json for reasonable values.
3. **Check** water balance: P - ET - Q - dS/dt should be < 1% of P.

## Critical Knowledge

- **Water table** (dt_pf_041): Use saturation >= 0.99, NOT pressure = 0. The pressure=0 contour may not align with cell centers in coarse grids.
- **Discharge extraction** (dt_pf_042): The outlet cell must be on the overland flow path (determined by slopes), not just the shapefile pour point.
- **Distributed PFB** (dt_pf_040): Combine before reading, or use `dist=True`.
- **CLM output**: `*.out.clm_output.NNNNN.C.pfb` contains 11 CLM diagnostic variables in layers. See ParFlow manual for variable ordering.
- **Coupling** (dt_pf_050): Do NOT send both ParFlow AND VIC runoff to CaMa-Flood.
- **Temporal aggregation** (dt_pf_052): Use MEAN for fluxes, instantaneous for states.

## Validation Checks

1. Water table depth is positive (0 to total_depth range)
2. Discharge is non-negative
3. Storage change matches water balance
4. Final state is physically reasonable (no saturated columns in dry basins)
