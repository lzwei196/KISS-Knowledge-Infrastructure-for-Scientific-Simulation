# S3: Topography and Slopes — Skill Document

## Purpose

Compute slope_x and slope_y from DEM for overland flow routing. ParFlow uses these slopes with Manning's equation to route surface water.

## Prerequisites

- Domain definition (s1)
- DEM raster
- Surface mask (s1)

## Procedure

1. **Run** `build_slopes.py` with DEM and domain definition.
2. **Verify** sinks were filled (check `sinks_filled` count).
3. **Verify** minimum slope was applied to flat cells.
4. **Check** slope sign convention: positive slope in positive coordinate direction.

## Critical Knowledge

- **Unfilled sinks** (dt_pf_010): Create extreme pressure gradients -> NaN crash. Always fill.
- **Slope signs** (dt_pf_011): Inverted signs make water flow uphill (silent error).
- **Zero slopes** (dt_pf_012): All-zero slopes = no drainage. Set min_slope ~0.0001.
- **Smoothing**: Noisy slopes from high-res DEMs can cause CFL instability. Use --smooth 3 for 30m DEMs.

## Validation

1. Mean |slope| > 0 for active cells
2. No NaN or Inf in slope arrays
3. Elevation range matches DEM (no resampling artifacts)
