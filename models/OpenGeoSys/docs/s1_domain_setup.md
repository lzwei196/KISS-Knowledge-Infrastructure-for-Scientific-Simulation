# Stage 1: Domain Setup — Mesh and Geometry

## Purpose

Create or import the computational mesh (VTU format) and define geometric entities for boundary condition application. OGS-6 requires separate submeshes for boundary conditions — this is the most common setup pitfall.

## Inputs

- **Domain geometry**: Coordinates, extents, geological layers
- **Boundary definitions**: Which surfaces/edges receive which BCs
- **Element type preferences**: Triangles/quads (2D), tetrahedra/hexahedra (3D)
- **Resolution requirements**: Element size (meters)

## Outputs

- `domain.vtu` — Bulk mesh (VTK Unstructured Grid)
- `boundary_*.vtu` — One submesh per boundary condition surface/edge
- `geometry.gml` — Optional GML geometry file (points, polylines, surfaces)

## Procedure

### Step 1: Generate or import mesh

**Using Gmsh** (recommended for complex geometries):
```bash
gmsh -2 domain.geo -format msh2 -o domain.msh
# Convert to VTU:
python -c "import meshio; m=meshio.read('domain.msh'); meshio.write('domain.vtu', m)"
```

**Using OGS MeshLib utilities** (for simple geometries):
```bash
generateStructuredMesh -e tri --lx 100 --ly 50 --nx 100 --ny 50 -o domain.vtu
```

**VTU requirements**:
- Nodes: 3D coordinates (x, y, z) even for 2D problems (z=0)
- Elements: Standard VTK types (triangle=5, quad=9, tetrahedron=10, hexahedron=12)
- Material IDs: Cell data array "MaterialIDs" (integer, 0-based) for multi-material domains

### Step 2: Extract boundary submeshes

OGS-6 applies BCs on **submeshes**, not on geometry+mesh intersections. Each BC needs its own submesh VTU file containing the boundary faces/edges.

```python
# Example: extract left boundary (x=0) from 2D mesh
import meshio
mesh = meshio.read("domain.vtu")
# Find nodes on left boundary
left_nodes = [i for i, p in enumerate(mesh.points) if abs(p[0]) < 1e-6]
# Create submesh with boundary edges/faces
# (In practice, use Gmsh physical groups or OGS ExtractBoundary utility)
```

**Using OGS utilities**:
```bash
ExtractBoundary -i domain.vtu -o boundary_all.vtu
# Then filter by position/name
```

### Step 3: Verify mesh quality

Check for:
- No degenerate elements (zero area/volume)
- No duplicate nodes
- Boundary submeshes are subsets of bulk mesh nodes
- MaterialIDs cover all elements (no gaps)

## Verification

- [ ] `domain.vtu` loads in ParaView without errors
- [ ] Boundary submeshes contain only face/edge elements
- [ ] MaterialIDs assigned for multi-material domains
- [ ] Node coordinates are in meters (SI)
- [ ] Element count is reasonable for problem complexity

## Traps

| Trap | Consequence | Prevention |
|------|-------------|------------|
| No boundary submeshes | BCs cannot be applied, crash | Always extract submeshes |
| Coordinates in km instead of m | All lengths wrong by 1000× | Convert to meters |
| Missing MaterialIDs | Default material for all elements | Assign IDs in mesh generator |
| 2D mesh with non-zero z | May confuse body force direction | Set z=0 for 2D plan-view |
| Duplicate nodes at interfaces | Non-conforming mesh → solver failure | Use mesh merge tools |
| Boundary mesh has volume elements | BC applied to volumes instead of surfaces | Extract faces only |

## Example

For a 100m × 50m rectangular 2D aquifer with left/right Dirichlet BCs:

```
Files needed:
  domain.vtu           # 100×50 triangular mesh, ~2000 elements
  boundary_left.vtu    # Left edge (x=0), ~50 line elements
  boundary_right.vtu   # Right edge (x=100), ~50 line elements

MaterialIDs: 0 for entire domain (single material)
Node count: ~1100 nodes
Element type: Triangle (VTK type 5)
```
