# s0 — Configuration Skill Document

## Purpose

Set basin identity, simulation period, resolution, model variant, routing method, sediment toggle, and forcing dataset. This is the HydroCraft orchestration config that drives all downstream stages. Skipping this stage means all subsequent tools lack required parameters.

## Prerequisites

- Basin location (lat/lon or shapefile path)
- Desired simulation period (start/end year)
- Knowledge of which forcing dataset covers the region

## Inputs

| Name | Type | Source | Description |
|------|------|--------|-------------|
| basin_name | string | user | Short identifier (e.g., "chaohe") |
| lat, lon | float | user or shapefile | Basin outlet or centroid coordinates |
| start_year, end_year | int | user | Simulation period |
| resolution | float | user | Grid resolution in degrees (0.25 or 0.1) |
| forcing | string | user | "cmfd" (China), "mswx" (global), or "nasa_power" |
| routing | string | user | "kinematic" (default) or "local_inertial" (flood) |
| sediment | bool | user | Enable wflow_sediment post-processor |
| glacier | bool | user | Enable glacier module (mountain basins only) |

## Procedure

1. Ask user for basin location and period
2. Determine forcing dataset: CMFD for China (1979-2018), MSWX for global/post-2018
3. Choose resolution: 0.25 deg default, 0.1 deg for small basins (<500 km2)
4. Choose routing: kinematic wave (fast, default) or local inertial (flood inundation)
5. Ask about sediment: enable if erosion/sediment transport is needed
6. Run `setup_wflow_config.py` to generate wflow_config.yaml
7. Verify config YAML contains all required fields

## Expected Outputs

| Output | Path | Verification |
|--------|------|-------------|
| wflow_config.yaml | outputs/<run>/wflow_config.yaml | YAML loads without error, all fields present |

## Validation Checks

1. lat/lon are within valid range (-90/90, -180/180)
2. start_year < end_year
3. Forcing dataset matches basin location (CMFD only for China)
4. Resolution is 0.25 or 0.1 (nothing finer)

## Common Pitfalls

- **dt_w001**: Using CMFD for basins outside China produces silent errors
- Using 0.05 deg resolution wastes computation (forcing is 0.1 deg native)
- Enabling glacier for non-glaciated basins adds computation for zero benefit (dt_w016)
