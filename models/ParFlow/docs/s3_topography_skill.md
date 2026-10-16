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

## Box geometry: every cell gets a real slope

The s7 run script uses Box geometry (no SolidFile mask), so ParFlow routes overland flow over EVERY cell of the rectangle, inside and outside the basin mask. `build_slopes.py` therefore computes DEM slopes, sink filling and the minimum slope for every cell (it used to set outside-mask slopes to 0, which made those simulated cells flat ponds). The basin mask only selects the `inside_basin_mask` statistics. A grid cell with no DEM value stops the tool (`status: error`, count and first 10 cells); DEM gaps are never filled with a neighbour's value. Use a DEM that covers the whole rectangle.

Row order: `elevation.npy`, `slope_x/y` have row j = 0 at the SOUTH edge (cell centre y = origin_y + (j + 0.5) dy), the same as the mask, soil, CLM and forcing tools and ParFlow's PFB layout. Before 2026-10-16 the DEM was not flipped from its north-up raster order, so elevation was mirrored north-south and slope_y had the wrong sign; rebuild s3 (and s6, which reads elevation.npy) for any older run.

## Critical Knowledge

- **Unfilled sinks** (dt_pf_010): Create extreme pressure gradients -> NaN crash. Always fill. `fill_sinks_simple` is a priority-flood fill (epsilon 0.001 m) seeded from the grid edges, so multi-cell and flat-floored pits are filled too and every cell drains to an edge (the old one-cell check left flat pits unchanged).
- **Slope signs** (dt_pf_011): Inverted signs make water flow uphill (silent error).
- **Zero slopes** (dt_pf_012): All-zero slopes = no drainage. Set min_slope ~0.0001.
- **Smoothing**: Noisy slopes from high-res DEMs can cause CFL instability. Use --smooth 3 for 30m DEMs.

## Validation

1. Mean |slope| > 0 in every cell (inside and outside the basin mask)
2. No NaN or Inf in slope arrays
3. Elevation range matches DEM (no resampling artifacts)
