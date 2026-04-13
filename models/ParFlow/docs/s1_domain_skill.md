# S1: Domain and Grid Definition — Skill Document

## Purpose

Define the 3D computational domain covering the basin in a UTM-projected Cartesian grid. This is the foundation for all subsequent stages -- every ParFlow file (subsurface, slopes, forcing, mask) must match the grid dimensions exactly.

**If skipped**: No simulation can run.

## Prerequisites

- Basin boundary shapefile (.shp) with valid geometry
- DEM raster (China DEM 90m or Copernicus GLO-30)
- Desired horizontal resolution (typically 500m-2000m for basin-scale)
- Number of vertical layers (typically 5-20)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| shp_path | file | Basin delineation | Basin boundary shapefile |
| dem_path | file | data/dem/ | DEM raster for elevation stats |
| resolution | float (m) | User choice | Horizontal grid cell size |
| nz | int | User choice | Number of vertical layers |
| dz_layers | list[float] | User/default | Layer thicknesses bottom-to-top (m) |

## Procedure

1. **Run** `define_parflow_domain.py` with shapefile and resolution.
   - The tool auto-detects UTM zone from basin centroid.
   - Output: `domain_definition.json` with NX, NY, NZ, dx, dy, dz, origin, CRS.
   - **Expected**: origin_x and origin_y > 100,000 (UTM meters). If they look like lat/lon (< 200), CRS is wrong (dt_pf_013).

2. **Run** `build_domain_mask.py` to create the 3D mask.
   - Output: `domain_mask.npy` (3D), `surface_mask.npy` (2D).
   - **Expected**: active_fraction 0.3-0.9 (depends on basin shape vs rectangular grid).
   - If active_fraction < 0.1: domain is much larger than basin, consider tighter extent.

3. **Verify** grid dimensions are compatible with MPI decomposition:
   - NX must be divisible by P, NY by Q, NZ by R.
   - If using 4 cores: P=2, Q=2, R=1 requires NX and NY to be even.
   - The tool suggests valid MPI topologies.

4. **Verify** terrain-following grid fractions sum to 1.0:
   - If terrain_following=True, dz_fractions must sum to ~1.0.
   - Tolerance: |sum - 1.0| < 0.001.
   - If wrong, see dt_pf_014.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| domain_definition.json | output_dir/ | NX>0, NY>0, NZ>0, origin in UTM meters |
| domain_mask.npy | output_dir/ | 3D array shape (NZ, NY, NX) with 0/1 values |
| surface_mask.npy | output_dir/ | 2D array shape (NY, NX) with 0/1 values |

## Validation Checks

1. origin_x and origin_y are in meters (> 100,000) not degrees
2. NX * NY * NZ is reasonable (< 10 million for basin-scale)
3. active_fraction > 0.1
4. If terrain_following: sum(dz_fractions) approximately equals 1.0
5. At least one valid MPI topology exists for the grid dimensions

## Common Pitfalls

- **CRS mismatch** (dt_pf_013): Using lat/lon as origin instead of UTM meters
- **TFG fractions** (dt_pf_014): Passing absolute thicknesses as fractions
- **Too fine resolution**: 100m with a 10,000 km2 basin = 10 million cells = very slow
- **MPI incompatibility** (dt_pf_023): Grid not divisible by chosen P/Q/R
