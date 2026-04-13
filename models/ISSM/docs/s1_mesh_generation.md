# Stage 1: Mesh Generation and Refinement

## Purpose

Create a 2D unstructured triangular mesh over the ice sheet domain. The mesh is the foundation of all ISSM simulations — it defines the spatial discretization for the finite element solver. Mesh quality directly controls solution accuracy, convergence speed, and computational cost.

## Inputs

| Input | Format | Units | Description |
|-------|--------|-------|-------------|
| Domain outline | `.exp` (Argus) | m (projected) | Closed polygon defining ice sheet boundary |
| Resolution | scalar | m | Target element edge length |
| Velocity field (optional) | array[nv] | m/yr | For adaptive refinement with `bamg()` |
| hmin (optional) | scalar | m | Minimum element size for adaptive mesh |
| hmax (optional) | scalar | m | Maximum element size for adaptive mesh |

### .exp File Format

```
## Name:domainoutline
## Icon:0
# Points Count  Value
5 1.
# X pos Y pos
0 0
1000000 0
1000000 1000000
0 1000000
0 0
```

**CRITICAL**: Coordinates must be in **meters** using a projected coordinate system (e.g., polar stereographic EPSG:3031 for Antarctica, EPSG:3413 for Greenland). Using lat/lon degrees produces a mesh 111,000× too small (dt_004).

## Outputs

| Output | Type | Description |
|--------|------|-------------|
| `md.mesh.x` | array[nv] | Vertex x-coordinates (m) |
| `md.mesh.y` | array[nv] | Vertex y-coordinates (m) |
| `md.mesh.elements` | array[ne×3] | Element connectivity (1-indexed) |
| `md.mesh.numberofvertices` | int | Vertex count |
| `md.mesh.numberofelements` | int | Element count |
| `md.mesh.vertexonboundary` | array[nv] | 1 if vertex is on boundary |
| `md.mesh.segments` | array[ns×3] | Boundary segments |

## Procedure

### Simple Uniform Mesh

```python
from model import model
from triangle import triangle

md = triangle(model(), 'DomainOutline.exp', 100000)  # 100 km resolution
```

### Adaptive Mesh (BAMG)

```python
from bamg import bamg

# Step 1: Coarse initial mesh
md = bamg(model(), 'domain', 'DomainOutline.exp', 'hmax', 100000)

# Step 2: Load velocity for refinement metric
vel = np.sqrt(vx**2 + vy**2)

# Step 3: Refine based on velocity gradients
md = bamg(md, 'hmax', 100000, 'hmin', 5000, 'gradation', 1.7,
          'field', vel, 'err', 8)
```

BAMG adapts the mesh to resolve high-gradient regions (fast-flowing outlet glaciers) with small elements while using coarse elements in slow interior regions.

### 3D Extrusion (for HO/FS)

```python
md = extrude(md, 15, 1.3)  # 15 vertical layers, exponent 1.3
```

Extrusion converts 2D triangles to 3D pentahedral prisms. The exponent controls vertical layer spacing (>1 concentrates layers near the base where shear is strongest).

## Verification

1. **Element count**: Check `md.mesh.numberofelements` is reasonable for domain size
2. **Vertex count**: Typically 3× fewer vertices than elements for triangles
3. **No degenerate elements**: All element areas > 0 (dt_013)
4. **Connected mesh**: Single connected component (dt_014)
5. **Resolution**: Verify minimum/maximum element sizes match expectations

```python
# Quick mesh quality check
areas = compute_element_areas(md)
assert np.all(areas > 0), "Degenerate elements detected (dt_013)"
print(f"Elements: {md.mesh.numberofelements}")
print(f"Vertices: {md.mesh.numberofvertices}")
print(f"Min element size: {np.sqrt(np.min(areas)):.0f} m")
print(f"Max element size: {np.sqrt(np.max(areas)):.0f} m")
```

## Traps

| Trap | Symptom | Cause | Fix |
|------|---------|-------|-----|
| dt_004 | Mesh is tiny (~1 m domain) | Coordinates in degrees, not meters | Use projected coordinates (EPSG:3031/3413) |
| dt_010 | Mesh too coarse/fine | Resolution in km instead of m | Multiply resolution by 1000 |
| dt_013 | Solver crashes immediately | Zero-area degenerate triangles | Reduce resolution or fix domain outline |
| dt_014 | Partial domain solved | Disconnected mesh regions | Ensure domain outline is a single closed polygon |

## Example

```python
# Pine Island Glacier: adaptive mesh from 5-100 km
md = bamg(model(), 'domain', 'Pig.exp', 'hmax', 100000)
vel = np.sqrt(vx_obs**2 + vy_obs**2)
md = bamg(md, 'hmax', 100000, 'hmin', 5000, 'gradation', 1.7,
          'field', vel, 'err', 8)
# Result: ~3000 elements, ~1600 vertices
# Fast-flowing trunk: 5-10 km elements
# Slow interior: 50-100 km elements
```
