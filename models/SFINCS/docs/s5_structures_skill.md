# S5: Hydraulic Structures — Skill Document

## Purpose

Add thin dams (levees, embankments), weirs, and drainage structures to the SFINCS model. This stage is OPTIONAL — only needed for domains with significant hydraulic infrastructure that affects flood routing.

## Prerequisites

- sfincs.dep and sfincs.msk from s2_topobathy
- GIS data for levees, weirs, or drainage structures (shapefiles or coordinates)
- Knowledge of structure dimensions (height, crest width, discharge capacity)

## Inputs

| Input | Type | Required |
|-------|------|----------|
| Levee polylines | .shp or coordinates | No |
| Weir locations | coordinates + params | No |
| Drainage points | coordinates + capacity | No |

## Procedure

1. **Thin dams (sfincs.thd)**: Represent levees, embankments, sea walls as infinitely thin barriers at cell edges. Format: one line per dam segment with start/end coordinates and crest elevation.

2. **Weirs (sfincs.weir)**: Represent spillways, overflow structures. Include location, crest elevation, discharge coefficient.

3. **Drainage (sfincs.drn)**: Represent drainage outfalls, pump stations. Include location and capacity (m3/s).

4. **When structures matter**:
   - Urban areas with levee protection: YES, critical
   - Rural floodplains without embankments: NO, skip this stage
   - Coastal areas with sea walls: YES
   - Mountain valleys: Usually NO (natural terrain dominates)

## Expected Outputs

| Output | Path | Verification |
|--------|------|-------------|
| sfincs.thd | `{output_dir}/sfincs.thd` | Valid coordinates and elevations |
| sfincs.weir | `{output_dir}/sfincs.weir` | Valid parameters |
| sfincs.drn | `{output_dir}/sfincs.drn` | Valid capacity values |

## Validation Checks

1. Structure coordinates fall within the computational domain
2. Crest elevations are above surrounding terrain (otherwise useless)
3. Drainage capacity is reasonable (typical pump: 1-50 m3/s)

## Common Pitfalls

- Thin dam crest elevation lower than surrounding DEM — structure has no effect
- Drainage capacity too high — artificially prevents flooding
- Missing gaps in levee representation — water cannot enter protected area during overtopping
