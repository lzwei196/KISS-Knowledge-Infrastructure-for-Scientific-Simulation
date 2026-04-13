# Stage 1: Grid Generation

## Purpose

Create the computational mesh (grid) that defines the model domain. Delft3D supports
two grid types: structured (curvilinear, for Delft3D-FLOW) and unstructured (flexible
mesh, for D-Flow FM). The grid determines spatial resolution, domain extent, and
computational cost.

## Inputs

| Input | Format | Source | Required |
|-------|--------|--------|----------|
| Domain boundary | Polygon / coordinates | User definition | Yes |
| Coastline data | Shapefile / .ldb | GSHHS / OpenStreetMap | Recommended |
| Bathymetry hint | NetCDF / .dep | GEBCO / survey | Optional |
| Target resolution | Meters | User specification | Yes |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Grid file (structured) | .grd + .enc | Curvilinear grid + enclosure |
| Grid file (unstructured) | _net.nc | UGRID NetCDF mesh |
| Grid quality report | Text | Orthogonality, aspect ratio, smoothness |

## Procedure

### D-Flow FM (Unstructured Grid)

1. **Define domain polygon** — outline the computational area as a closed polygon
2. **Set resolution** — specify target cell size (can vary spatially: fine near coast, coarse offshore)
3. **Generate mesh** using MeshKernel or RGFGRID:
   ```python
   # Using MeshKernel Python API
   import meshkernel
   mk = meshkernel.MeshKernel()
   mk.mesh2d_make_triangular_mesh_from_polygon(polygon_x, polygon_y)
   ```
4. **Refine locally** — increase resolution in areas of interest (harbors, channels)
5. **Orthogonalize** — improve cell quality for numerical accuracy
6. **Add bathymetry** — interpolate depth values onto grid nodes (see Stage 2)
7. **Export** — save as _net.nc (UGRID NetCDF format)

### Delft3D-FLOW (Structured Grid)

1. **Define enclosure** — rectangular domain outline
2. **Generate curvilinear grid** using RGFGRID
3. **Set M×N dimensions** — number of cells in each direction
4. **Smooth** — ensure cell size transitions gradually
5. **Export** — save as .grd (coordinates) + .enc (enclosure)

## Verification

- **Orthogonality**: cell angles should be close to 90° (deviation < 20°)
- **Aspect ratio**: length/width of cells should be < 5:1
- **Smoothness**: adjacent cell size ratio should be < 1.4
- **Courant number**: verify that DtMax is small enough for the finest cells
  ```
  CFL = sqrt(g * h_max) * dt / dx_min < 1.0
  ```

## Traps

1. **Geographic vs projected coordinates**: If using lat/lon degrees, Delft3D
   interprets distances in degrees — a cell of 0.01° × 0.01° is NOT 1 km × 1 km.
   Use UTM or other projected coordinates for proper area/volume computations.

2. **Grid too coarse at boundaries**: Open boundaries need sufficient resolution
   to resolve tidal wavelengths. Rule of thumb: at least 20 cells per wavelength.

3. **Dry cells at domain edge**: Ensure the grid extends slightly beyond the
   actual water domain to avoid boundary artifacts.

## Example

```bash
# Inspect an existing grid
ncdump -h domain_net.nc | grep -E "node|elem|edge"

# Check grid dimensions
python3 -c "
import netCDF4 as nc
ds = nc.Dataset('domain_net.nc')
print(f'Nodes: {len(ds.dimensions[\"nNetNode\"])}')
print(f'Elements: {len(ds.dimensions[\"nNetElem\"])}')
print(f'Edges: {len(ds.dimensions[\"nNetLink\"])}')
ds.close()
"
```
