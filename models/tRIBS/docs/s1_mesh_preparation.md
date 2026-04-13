# S1: Mesh Preparation

## Purpose

Prepare a Triangulated Irregular Network (TIN) mesh that represents the watershed
topography for tRIBS. The mesh defines the computational domain: nodes store
hydrologic variables, edges connect adjacent nodes, and triangles form the
Delaunay triangulation with corresponding Voronoi polygons.

## Inputs

| Input | Format | Units | Source |
|-------|--------|-------|--------|
| Digital Elevation Model (DEM) | GeoTIFF / ASCII grid | meters (MSL) | SRTM, ASTER, LiDAR |
| Watershed boundary | Shapefile / points | UTM meters | GIS delineation |
| Stream network (optional) | Shapefile | UTM meters | NHD, delineated |
| Soil/land-use grids (for resampling) | Raster | varies | HWSD, NLCD |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `.nodes` file | Text (ID X Y Z BND) | Node coordinates and boundary codes |
| `.edges` file | Text (ID N1 N2 TL TR) | Edge connectivity |
| `.tri` file | Text (ID N1 N2 N3 E1 E2 E3) | Triangle connectivity |
| `.z` file | Text (ID Elev) | Elevation at each node |

## Procedure

### Step 1: Obtain and preprocess DEM
1. Download DEM covering the watershed extent plus a buffer (~10%)
2. Reproject to **UTM coordinates (meters)** — tRIBS requires metric coordinates
3. Fill sinks to ensure hydrologic connectivity
4. Clip to watershed boundary

### Step 2: Choose mesh generation option
tRIBS supports multiple mesh input options via `OPTMESHINPUT`:

| Option | Description | When to use |
|--------|-------------|-------------|
| 0 | Generate from scratch | Small test cases |
| 1 | From point cloud | Custom point sets |
| 2 | From rectangular grid | Regular DEM |
| 8 | From tRIBS-format files | Pre-built mesh |
| 9 | From meshbuilder files | Parallel runs |

### Step 3: Generate TIN mesh
For most applications, use external tools (e.g., GRASS GIS `v.surf.rst` or
custom triangulation) to create the mesh, then convert to tRIBS format:
- Simplify the DEM to reduce node count while preserving terrain features
- Ensure higher resolution near channels and steep slopes
- Typical mesh: 1,000–100,000 nodes depending on basin size

### Step 4: Assign soil and land-use classes
Each node requires soil type and land-use class IDs that reference the
soil (.sdt) and land-use (.ldt) tables.

## Verification

- [ ] All coordinates are in **UTM meters** (not lat/lon degrees)
- [ ] Elevation units are **meters** (not feet)
- [ ] No orphan nodes (every node connected to at least one edge)
- [ ] Boundary codes correctly set (0=interior, 1=closed, 2=open, 3=stream)
- [ ] Stream nodes have boundary code 3
- [ ] Outlet node identified correctly
- [ ] Node count is appropriate for basin size (100–1000 nodes/km²)

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Coordinates in degrees instead of meters | Domain is ~0.001 km², unrealistic results | Reproject DEM to UTM |
| Elevation in feet | Slopes are 3× too low, wrong routing | Convert: elev_m = elev_ft × 0.3048 |
| Unfilled sinks in DEM | Flow routing fails at depression nodes | Fill sinks before mesh generation |
| Too few nodes | Poor representation of terrain | Increase node density |
| OPTMESHINPUT mismatch | File-not-found crash on startup | Match option to available file format |

## Example

```bash
# Generate mesh from DEM using external tool, then set in .in file:
OPTMESHINPUT
8
INPUTDATAFILE
/path/to/mesh/basin
# This expects basin.nodes, basin.edges, basin.tri, basin.z
```
