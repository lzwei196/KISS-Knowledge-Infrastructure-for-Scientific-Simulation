# Stage 0: Configuration — Routing Method Selection Guide

## Purpose

Select the appropriate routing method, configure basin parameters, and determine whether lake routing is needed. This stage produces the configuration consumed by all downstream stages.

If skipped: downstream tools use default parameters (IRF, no lakes, daily timestep), which may not be appropriate.

## Prerequisites

- Basin shapefile exists (from HydroCraft delineation)
- VIC or WRF-Hydro simulation complete (runoff output available)
- User has specified desired routing method (or use decision tree below)

## Method Selection Decision Tree

```
Is floodplain inundation needed?
  YES -> Use CaMa-Flood (not mizuRoute)
  NO -> Continue

Does basin have significant lakes/reservoirs?
  YES -> mizuRoute with lake routing (route_opt=2 KWE + is_lake_sim=True)
  NO -> Continue

Basin size?
  Small (<1000 km², <50 reaches):
    -> IRF (route_opt=0): fastest, sufficient physics
  Medium (1000-50000 km², 50-1000 reaches):
    -> KWE (route_opt=2): good balance of physics and speed
    -> MC (route_opt=3): if NWM-compatible results desired
  Large (>50000 km², >1000 reaches):
    -> MC (route_opt=3): operationally proven at scale
    -> KWT (route_opt=1): efficient for large networks

Terrain type?
  Flat (coastal, plains): DW (route_opt=4) captures backwater, but needs small dt
  Steep (mountains): IRF or KWT (unconditionally stable, no CFL concern)
  Mixed: KWE or MC (general purpose)

Purpose?
  Quick comparison with Lohmann: IRF (closest physics)
  Research/method intercomparison: All 5 methods via compare_routing_methods.py
  Operational forecasting: MC (used by NOAA National Water Model)
```

## Inputs

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| basin_name | string | Yes | - | Short basin identifier |
| route_opt | int | No | 0 (IRF) | Routing method 0-4 |
| dt | int | No | 3600 | Routing timestep (seconds) |
| start_date | string | Yes | - | YYYY-MM-DD |
| end_date | string | Yes | - | YYYY-MM-DD |
| enable_lakes | bool | No | False | Enable lake routing |
| basin_irf | bool | No | False | Apply hillslope IRF before reach routing |

## Validation Checks

1. Route method is 0-4
2. dt is reasonable: 300-86400 seconds. For DW/KWE on steep basins, use dt=300-900.
3. Time period matches VIC output period
4. If enable_lakes=True, verify lake data is available

## Common Pitfalls

- **Pitfall**: Using DW (route_opt=4) on steep mountain basins -> CFL violation (dt_m009)
  - **Fix**: Use IRF (0) or KWT (1) for steep basins, or reduce dt to 300s
- **Pitfall**: Setting doesBasinRoute=1 when comparing with Lohmann -> double hillslope delay (dt_m014)
  - **Fix**: Set doesBasinRoute=0 for Lohmann comparison
