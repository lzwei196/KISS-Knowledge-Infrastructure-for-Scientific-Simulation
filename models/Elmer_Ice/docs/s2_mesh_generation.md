# S2: Mesh Generation

## Purpose

Create a finite element mesh suitable for Elmer/Ice simulations. The mesh defines
the computational domain — its resolution, element types, and boundary definitions
directly affect simulation accuracy, convergence, and runtime.

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| Grid definition | `.grd` (ElmerGrid) | Structured grid specification |
| Gmsh geometry | `.geo` (Gmsh) | Unstructured mesh definition |
| DEM data | GeoTIFF / NetCDF | For glacier outline and surface |
| Domain outline | Shapefile / points | For custom glacier domain |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `mesh.header` | ASCII | Element types, counts |
| `mesh.nodes` | ASCII | Node ID, body ID, x, y, z (meters) |
| `mesh.elements` | ASCII | Element ID, body ID, type, connectivity |
| `mesh.boundary` | ASCII | Boundary element definitions |
| `partitioning.N/` | Directory | Mesh partition files for N MPI processes |

## Procedure

### Option A: Structured Grid (ElmerGrid)

Best for simple geometries, benchmarks (ISMIP-HOM), and flowline models.

1. **Create grid file** (e.g., `rectangle.grd`):
   ```
   #####  rectangle  #####
   Coordinate System = Cartesian 2D
   Subcell Divisions in 2D = 1 1
   Subcell Sizes 1 = 1.0
   Subcell Sizes 2 = 1.0
   Element Divisions 1 = 100
   Element Divisions 2 = 1
   Boundary Conditions
     Target Boundaries(4) = 1 2 3 4
   End
   ```

2. **Generate mesh**:
   ```bash
   ElmerGrid 1 2 rectangle
   ```
   This reads `rectangle.grd` (format 1) and writes Elmer native mesh (format 2)
   in directory `rectangle/`.

3. **For parallel runs**, partition the mesh:
   ```bash
   ElmerGrid 2 2 rectangle -partdual -metis 4
   ```

### Option B: Unstructured Grid (Gmsh)

Best for complex glacier geometries with variable resolution.

1. **Create Gmsh geometry** (`.geo` file) defining the domain outline and mesh
   density fields.

2. **Generate mesh in Gmsh**:
   ```bash
   gmsh -2 glacier.geo -o glacier.msh
   ```

3. **Convert to Elmer format**:
   ```bash
   ElmerGrid 14 2 glacier.msh
   ```
   (Format 14 = Gmsh, format 2 = Elmer native)

### Option C: 3D Extruded Mesh

For full-Stokes or 3D thermomechanical simulations:

1. Create 2D footprint mesh (Option A or B)
2. Use `ExtrudeMesh` to add vertical layers:
   ```bash
   ExtrudeMesh rectangle rectangle_3d 10 1 1 0 0 0 0 0 0 0
   ```
   This extrudes the 2D mesh into 10 vertical layers.

## Verification

- Run `ElmerGrid 2 4 mesh_dir` to export VTU and inspect in ParaView
- Check boundary numbering matches SIF Boundary Condition targets
- Verify node coordinates are in meters
- For grounding line studies: resolution < 1 km at GL
- For ice divides: resolution < 5 km typically sufficient

## Traps

| Trap | Effect | Prevention |
|------|--------|-----------|
| **2D/3D mismatch** (dt_007) | Solver crash | Match mesh dimension to SIF Coordinate System |
| **No partitioning** (dt_011) | MPI crash | Always partition before parallel run |
| **Coarse GL mesh** (dt_010) | Convergence failure | Refine to < 1 km at grounding line |
| **Wrong boundary IDs** | BC applied to wrong edge | Check with `ElmerGrid 2 4` visualization |
| **Degenerate elements** | Poor convergence | Check element quality in Gmsh/ParaView |

## Example

```bash
# Simple 2D benchmark mesh
cat > rectangle.grd << 'EOF'
#####  rectangle  #####
Coordinate System = Cartesian 2D
Subcell Divisions in 2D = 1 1
Subcell Sizes 1 = 1.0
Subcell Sizes 2 = 1.0
Element Divisions 1 = 100
Element Divisions 2 = 1
Boundary Conditions
  Target Boundaries(4) = 1 2 3 4
End
EOF

ElmerGrid 1 2 rectangle
ls rectangle/  # Should contain mesh.header, mesh.nodes, mesh.elements, mesh.boundary

# Partition for 4 processors
ElmerGrid 2 2 rectangle -partdual -metis 4
ls rectangle/partitioning.4/  # Partition files
```
