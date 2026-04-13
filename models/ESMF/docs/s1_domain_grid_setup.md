# Stage 1: Domain / Grid Setup

## Purpose

Define the computational domain as an ESMF Grid (structured) or Mesh (unstructured).
The grid defines the spatial discretization on which Fields are allocated and
regridding operates. This is the foundation of all ESMF spatial operations.

## Inputs

| Input                  | Format            | Units            | Required |
|------------------------|-------------------|------------------|----------|
| Grid definition        | NetCDF/SCRIP/CSV  | Degrees (lat/lon)| Yes      |
| DEM (optional)         | GeoTIFF/NetCDF    | meters           | No       |
| Basin shapefile        | Shapefile/GeoJSON | geographic coords| No       |
| Land-sea mask          | NetCDF            | 0/1 integer      | No       |

## Outputs

| Output                 | Format       | Description                          |
|------------------------|--------------|--------------------------------------|
| ESMF grid file         | NetCDF       | SCRIP-format grid with centers, corners, areas |
| Grid mask              | NetCDF       | Land/ocean/active cell mask          |
| Regrid weight file     | NetCDF       | Pre-computed interpolation weights   |

## Procedure

1. **Choose grid type**:
   - **Regular lat-lon**: Use for global or regional rectangular domains
   - **Curvilinear**: Use for rotated or stretched grids (ocean models)
   - **Unstructured mesh**: Use for irregular domains (river networks, FEM)

2. **Create grid definition file** (SCRIP format):
   ```bash
   python convert_grid_to_esmf.py \
       --format latlon \
       --resolution 0.25 \
       --lat-range 20 50 \
       --lon-range 100 140 \
       --output domain_grid.nc
   ```

3. **Add mask** (if needed):
   - 1 = active cell, 0 = masked/inactive
   - TRAP: Many datasets use opposite convention (1 = masked)!

4. **Verify grid**:
   - Check coordinate ranges are in degrees (not radians)
   - Check corner ordering is counter-clockwise
   - Check cell areas are in steradians for conservative regridding

5. **Pre-compute regrid weights** (if coupling multiple grids):
   ```bash
   python generate_regrid_weights.py \
       --source atm_grid.nc \
       --destination ocean_grid.nc \
       --weight atm_to_ocean.nc \
       --method conserve
   ```

## Verification

- Grid file opens in `ncdump -h` without error
- `grid_dims` matches expected resolution
- Coordinate ranges are physically reasonable (lat ∈ [-90, 90])
- Cell areas sum to expected domain area
- Mask correctly excludes ocean/land cells
- Corner coordinates form valid (non-degenerate) polygons

## Traps

| Trap | Description | Severity |
|------|-------------|----------|
| Coordinates in radians | Lat/lon stored as radians instead of degrees → 57.3x error | silent |
| Areas in degrees² | Cell areas not in steradians → conservation violated by ~3000x | silent |
| Clockwise corners | SCRIP corners in wrong order → negative areas → wrong regridding | silent |
| 0-based connectivity | Mesh node indices 0-based (C) instead of 1-based (Fortran) | silent |
| Missing periodic boundary | Global grid without `ESMF_GRIDCONN_PERIODIC` → seam at 0°/360° | silent |
| Mask convention inverted | 1=masked instead of 0=masked → valid data excluded | silent |

## Example

```python
import esmpy
import numpy as np

# Create a 1° global grid
grid = esmpy.Grid(np.array([180, 360]),
                  staggerloc=[esmpy.StaggerLoc.CENTER, esmpy.StaggerLoc.CORNER],
                  coord_sys=esmpy.CoordSys.SPH_DEG)

# Set center coordinates
gridXCenter = grid.get_coords(0)  # longitude
gridYCenter = grid.get_coords(1)  # latitude

lon = np.linspace(-179.5, 179.5, 360)
lat = np.linspace(-89.5, 89.5, 180)
lon2d, lat2d = np.meshgrid(lon, lat)

gridXCenter[...] = lon2d[grid.lower_bounds[esmpy.StaggerLoc.CENTER][0]:grid.upper_bounds[esmpy.StaggerLoc.CENTER][0],
                          grid.lower_bounds[esmpy.StaggerLoc.CENTER][1]:grid.upper_bounds[esmpy.StaggerLoc.CENTER][1]]
gridYCenter[...] = lat2d[grid.lower_bounds[esmpy.StaggerLoc.CENTER][0]:grid.upper_bounds[esmpy.StaggerLoc.CENTER][0],
                          grid.lower_bounds[esmpy.StaggerLoc.CENTER][1]:grid.upper_bounds[esmpy.StaggerLoc.CENTER][1]]
```
