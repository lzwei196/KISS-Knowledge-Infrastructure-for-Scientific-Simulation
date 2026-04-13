# s1 — HydroMT Model Setup Skill Document

## Purpose

Build the wflow spatial model: staticmaps.nc containing all grid parameters (DEM, soil, vegetation, river network). This is the foundation — all other stages depend on correct staticmaps. Skipping this stage means no spatial parameters exist and the model cannot run.

## Prerequisites

- Stage s0 complete (wflow_config.yaml exists)
- Basin shapefile (.shp) or coordinates for delineation
- For HydroMT mode: hydromt_wflow Python package installed
- For manual mode: HydroCraft's HWSD soil and AVHRR vegetation data available

## Inputs

| Name | Type | Source | Description |
|------|------|--------|-------------|
| wflow_config.yaml | file | s0 | Configuration with basin, period, resolution |
| shapefile | file | user or delineation | Basin boundary polygon |
| data_catalog.yml | file | build_data_catalog.py | HydroMT data catalog (HydroMT mode) |

## Procedure

### Option A: HydroMT Mode (recommended for first use)

1. Run `build_data_catalog.py` to create catalog pointing to HydroCraft datasets
2. Run `hydromt build wflow` via `run_hydromt_build.py --use_hydromt`
3. Verify staticmaps.nc contains expected variables
4. Check river network looks reasonable (5-20% of cells should be river)

### Option B: Manual Mode (when HydroMT is unavailable)

1. Run `run_hydromt_build.py --shapefile /path/to/basin.shp`
2. This creates staticmaps.nc with placeholder parameters
3. **WARNING**: Placeholder parameters (uniform KsatVer, SoilThickness, etc.) will produce uncalibrated results. Refine with actual HWSD soil data for production runs.
4. River network is set to all cells = river (too coarse — refine from DEM)

### Post-Build Checks

5. Open staticmaps.nc and verify:
   - wflow_subcatch has non-zero values
   - wflow_dem has realistic elevation range
   - KsatVer is in range 10-10000 mm/day
   - SoilThickness is in range 500-5000 mm
   - theta_s > theta_r everywhere

## Expected Outputs

| Output | Path | Verification |
|--------|------|-------------|
| staticmaps.nc | outputs/<run>/wflow_project/staticmaps.nc | ncdump -h shows expected variables |
| data_catalog.yml | outputs/<run>/data_catalog.yml | YAML loads, paths exist |

## Validation Checks

1. staticmaps.nc exists and is >1 MB
2. Grid dimensions match expected resolution
3. Active cells (wflow_subcatch > 0) > 0
4. No NaN values in soil parameters within basin mask
5. River network has proper connectivity (dt_w013)

## Common Pitfalls

- **dt_w013**: If wflow_river is all zeros, routing produces zero flow
- **dt_w014**: Boundary cells with invalid flow direction cause BoundsError
- **dt_w024**: HydroMT-wflow version must match Wflow.jl version
- Manual build uses placeholder params — always state this in results
