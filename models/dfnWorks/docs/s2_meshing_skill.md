# Stage 2: DFN Meshing with LaGriT

## Purpose

Generate a conforming Delaunay triangulation of the discrete fracture network using LaGriT. The mesh resolves all fracture intersections as triangle edges and creates Voronoi control volumes suitable for finite volume flow solvers (PFLOTRAN, FEHM). This stage is required for full-physics flow simulation but is NOT needed for graph-based mode.

## Prerequisites

- Stage 1 completed: DFN network generated successfully
- LaGriT v3.3 installed and path set in `~/.dfnworksrc`
- For DFM meshing: LaGriT built with Exodus support

## Inputs

| Input | Source | Format | Description |
|-------|--------|--------|-------------|
| Fracture polygons | Stage 1 | DAT files | Vertex coordinates per fracture |
| Intersection segments | Stage 1 | DAT files | Line segments where fractures intersect |
| h parameter | Stage 0 | Float (m) | Target mesh element size |
| params.txt | Stage 1 | Text | Network summary parameters |

## Outputs

| Output | Path | Format | Description |
|--------|------|--------|-------------|
| full_mesh.inp | `<jobname>/` | AVS/UCD | Complete DFN mesh (nodes + elements) |
| full_mesh.uge | `<jobname>/` | UGE | Voronoi control volumes |
| full_mesh.stor | `<jobname>/` | STOR | Sparse matrix storage coefficients |
| materialid.dat | `<jobname>/` | DAT | Fracture ID per mesh element |
| boundary zones | `<jobname>/` | ZONE | 6 boundary face zone files |
| full_mesh.fehmn | `<jobname>/` | FEHM | FEHM-format coordinate file |

## Procedure

### Step 1: Mesh the network

```python
DFN.mesh_network()
# Options:
# DFN.mesh_network(uniform_mesh=True)   # Uniform resolution
# DFN.mesh_network(slope=2.0)           # Adaptive refinement at intersections
```

Internally this:
1. Creates LaGriT parameter files for each fracture
2. Runs parallel LaGriT meshing (one process per fracture, up to ncpu)
3. Merges individual fracture meshes into unified mesh
4. Creates conforming intersection edges
5. Generates Voronoi control volumes (.uge file)
6. Writes boundary zone files

### Step 2: (Optional) Verify mesh quality

```python
DFN.gather_mesh_information()
```

### Step 3: (Optional) Convert mesh formats

```python
DFN.inp2vtk_python()  # Convert to VTK for ParaView visualization
```

## Verification

1. `full_mesh.inp` exists and is non-empty
2. `full_mesh.uge` exists (required for PFLOTRAN)
3. All 6 boundary zone files exist:
   - `boundary_top.zone`, `boundary_bottom.zone`
   - `boundary_left_w.zone`, `boundary_right_e.zone`
   - `boundary_front_n.zone`, `boundary_back_s.zone`
4. `materialid.dat` has one ID per mesh element
5. Mesh log shows no "ERROR" or "degenerate" warnings
6. Number of nodes >> number of fractures (typical ratio: 100-10000 nodes per fracture)

## Traps

| Trap | Symptom | Fix | Triplet |
|------|---------|-----|---------|
| h too large | Degenerate triangles, meshing fails | Reduce h (h < 0.5 * min_radius) | dt_004 |
| Very thin fractures | Zero-volume Voronoi cells | Increase min_radius or reduce h | dt_014 |
| LaGriT not found | Exit with path error | Check LAGRIT_EXE in ~/.dfnworksrc | dt_010 |
| Missing edges after merge | Flow solver crashes | Run check_for_missing_edges() | dt_013 |
| Too many fractures | Memory exhaustion during meshing | Reduce nPoly/p32 or increase h | — |

## Example

```python
# After Stage 1 (create_network)
DFN.mesh_network(uniform_mesh=False)  # Adaptive resolution

# Verify mesh exists
import os
assert os.path.isfile(os.path.join(DFN.jobname, "full_mesh.inp"))
assert os.path.isfile(os.path.join(DFN.jobname, "full_mesh.uge"))

# Convert to VTK for visualization
DFN.inp2vtk_python()
```

## Mesh Resolution Guidelines

| Domain size (m) | Fracture count | Recommended h (m) | Expected nodes |
|-----------------|----------------|-------------------:|---------------:|
| 10 | 10-50 | 0.05-0.1 | 10K-100K |
| 100 | 50-500 | 0.5-1.0 | 100K-1M |
| 1000 | 100-1000 | 2-5 | 500K-5M |

**Rule of thumb**: h should be 5-20% of the smallest fracture radius. Finer meshes increase accuracy but also memory and runtime significantly.
