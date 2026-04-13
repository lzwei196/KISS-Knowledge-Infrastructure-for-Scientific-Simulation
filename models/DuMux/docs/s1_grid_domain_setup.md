# Stage 1: Grid and Domain Setup

## Purpose

Define the computational domain and spatial discretization for the DuMux groundwater simulation. This stage creates the grid (mesh) on which the governing PDEs are solved and determines the spatial resolution and geometry of the simulation.

## Inputs

| Input | Format | Source | Unit |
|-------|--------|--------|------|
| Domain extent (LowerLeft, UpperRight) | coordinates | DEM, field survey | meters [m] |
| Grid resolution (Cells) | integer pair/triple | User choice | number of cells |
| Grid file (optional) | `.dgf` or `.msh` | Gmsh, external mesher | - |
| Aquifer thickness | scalar | Geological survey | meters [m] |
| Refinement level | integer | User choice | levels |

## Outputs

| Output | Format | Consumed by |
|--------|--------|-------------|
| `[Grid]` section in `.input` file | INI-style text | DuMux executable |
| Grid file (if unstructured) | `.dgf` or `.msh` | DuMux grid manager |

## Procedure

### Step 1: Choose grid type

| Grid | When to use | DuMux type |
|------|-------------|------------|
| Structured Cartesian | Simple rectangular domains | `Dune::YaspGrid<dim>` |
| Unstructured triangular | Complex boundaries, heterogeneity | `Dune::ALUGrid<dim,dim,simplex,conforming>` |
| 1D network in 3D | Fracture/pipe networks | `Dune::FoamGrid<1,3>` |

### Step 2: Define domain extent

For structured grids, specify in the `.input` file:
```ini
[Grid]
LowerLeft = 0 0           # [m] origin coordinates
UpperRight = 1000 500     # [m] domain extent
Cells = 100 50            # grid resolution
```

For 3D:
```ini
[Grid]
LowerLeft = 0 0 0
UpperRight = 1000 500 50  # [m] including aquifer thickness
Cells = 100 50 10
```

### Step 3: Set refinement (optional)

```ini
[Grid]
Refinement = 1            # uniform refinement levels (doubles resolution)

[Adaptive]
MinLevel = 0
MaxLevel = 3
RefineTolerance = 1e-4
CoarsenTolerance = 1e-5
```

### Step 4: For unstructured grids — create DGF file

Dune Grid Format (DGF) example:
```
DGF
Interval
0 0        % lower-left
1000 500   % upper-right
100 50     % cells per direction
#
```

Or load from a Gmsh `.msh` file:
```ini
[Grid]
File = aquifer_mesh.msh
Refinement = 0
```

## Verification

1. **Cell count**: Verify `Cells` product matches expected resolution. 100x50 = 5,000 cells.
2. **Coordinate units**: All coordinates must be in meters. Not km, not cm.
3. **2D vs 3D**: For plan-view groundwater (Dupuit assumption), use 2D. For full 3D aquifer with vertical variation, use 3D grid.
4. **Aspect ratio**: Cells should not be extremely elongated (aspect ratio < 10:1). High aspect ratios cause poor solver convergence.

## Traps

### TRAP: Gravity direction in 2D
For 2D vertical cross-sections, the second coordinate (y) is vertical. Gravity acts in -y direction. If you set up a 2D plan-view model with gravity enabled, the pressure gradient will be wrong.

**Fix**: For plan-view 2D aquifer models, set `EnableGravity = false` in `[Problem]` and apply hydrostatic correction manually.

### TRAP: Cell size vs. permeability heterogeneity
If the grid is too coarse, heterogeneous permeability features (lenses, faults) may not be resolved. Each distinct geological feature needs at least 3-4 cells across its smallest dimension.

### TRAP: Units must be meters
All Grid coordinates are in meters. Using km produces a domain 1000x too small; using cm produces a domain 100x too large. Both lead to incorrect flow velocities.

## Example

```ini
# 2D plan-view aquifer, 1km x 500m domain, 5m resolution
[Grid]
LowerLeft = 0 0
UpperRight = 1000 500
Cells = 200 100

[Problem]
EnableGravity = false     # plan-view, no vertical gravity

# 2D vertical cross-section, 100m wide x 20m deep
[Grid]
LowerLeft = 0 0
UpperRight = 100 20
Cells = 100 40

[Problem]
EnableGravity = true      # vertical section, gravity matters
```
