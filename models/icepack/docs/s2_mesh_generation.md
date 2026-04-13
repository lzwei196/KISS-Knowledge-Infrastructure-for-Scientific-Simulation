# Stage 2: Mesh Generation

## Purpose

Convert a glacier outline (GeoJSON FeatureCollection) into an unstructured
triangular finite element mesh suitable for icepack simulations. The mesh must
respect boundary segment labeling for Dirichlet and Neumann boundary conditions.

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| Glacier outline | GeoJSON FeatureCollection | LineString/MultiLineString features with boundary labels |
| lcar / max_volume | float | Characteristic element size (m) or max triangle area (m²) |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| mesh | Firedrake Mesh | Unstructured triangular mesh with labeled boundaries |
| .msh file | gmsh format | Optional: disk-cached mesh file |

## Procedure

1. **Prepare GeoJSON**: The outline must be a FeatureCollection of LineString features.
   Each feature can have a boundary ID property for labeling inflow, outflow, walls.

2. **Normalize** the collection:
   ```python
   import icepack.meshing
   collection = icepack.meshing.normalize(collection)
   ```
   This applies: flatten → snap → reorient → topologize → reorder.

3. **Generate mesh** using one of three backends:

   **gmsh (recommended):**
   ```python
   mesh_geo = icepack.meshing.collection_to_gmsh(collection, lcar=5000)
   mesh_geo.write("glacier.msh")
   mesh = firedrake.Mesh("glacier.msh")
   ```

   **Triangle (MeshPy):**
   ```python
   tri_mesh = icepack.meshing.collection_to_triangle(collection, max_volume=1e8)
   mesh = icepack.meshing.triangle_to_firedrake(tri_mesh)
   ```

   **Simple rectangle (for testing):**
   ```python
   mesh = firedrake.RectangleMesh(nx=64, ny=64, Lx=50e3, Ly=50e3)
   ```

4. **For hybrid/3D models**, extrude the mesh:
   ```python
   mesh3d = firedrake.ExtrudedMesh(mesh, layers=5)
   ```

5. **Verify boundary IDs**:
   ```python
   print(mesh.exterior_facets.unique_markers)
   # e.g., [1, 2, 3, 4] for a rectangle
   ```

## Verification

- [ ] Mesh has expected number of boundary segments
- [ ] Boundary markers match expected IDs for dirichlet_ids, side_wall_ids
- [ ] Element quality: no degenerate triangles (area > 0)
- [ ] Mesh resolution appropriate for glacier scale
- [ ] Coordinates are in projected CRS (meters)

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| GeoJSON not closed loop | Mesh generation fails | Ensure features form closed loops |
| Features not head-to-tail | normalize() fails with ValueError | Check endpoint connectivity |
| lcar too small | Millions of elements, out of memory | Start with lcar=10000, refine |
| lcar too large | Poor geometry representation | Use lcar ~1/20 of smallest glacier dimension |
| Lat/lon coordinates | Elements have ~1° size, solver fails | Reproject to meters first |
| Missing gmsh initialization | "gmsh not initialized" error | Ensure gmsh.initialize() called |
| Wrong boundary IDs | BC applied to wrong boundary | Print mesh.exterior_facets.unique_markers |

## Example

```python
import geojson
import firedrake
import icepack.meshing, icepack.datasets

# Fetch glacier outline
outline_path = icepack.datasets.fetch_outline("pine-island")
with open(outline_path) as f:
    outline = geojson.load(f)

# Generate mesh
mesh_geo = icepack.meshing.collection_to_gmsh(outline, lcar=2000)
mesh_geo.write("pine-island.msh")
mesh = firedrake.Mesh("pine-island.msh")

print(f"Cells: {mesh.num_cells()}, Vertices: {mesh.num_vertices()}")
print(f"Boundary IDs: {mesh.exterior_facets.unique_markers}")
```
