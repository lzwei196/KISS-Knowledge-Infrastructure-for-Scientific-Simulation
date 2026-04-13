# S1 — Mesh & Survey Setup

## Purpose

Create the computational mesh (spatial discretization) and define survey geometry
(source and receiver locations) for a SimPEG forward or inverse problem.  The mesh
must extend beyond the survey footprint with geometric padding to minimize boundary
effects, and the survey must correctly encode source-receiver relationships for
the chosen geophysical method.

## Inputs

| Input             | Format            | Units           | Required | Notes                        |
|-------------------|-------------------|-----------------|----------|------------------------------|
| Survey locations  | CSV (x,y,z)       | meters (SI)     | Yes      | Elevation, NOT depth         |
| Topography        | CSV (x,y,z)       | meters (elev)   | No       | Defines active/air cells     |
| Method            | string             | —               | Yes      | gravity, magnetics, dc, etc. |
| Core cell counts  | int (nx, ny, nz)  | —               | Yes      | Resolution in each dimension |
| Padding           | int + float        | cells, factor   | Yes      | Geometric growth padding     |

## Outputs

| Output          | Format          | Contents                                      |
|-----------------|-----------------|-----------------------------------------------|
| mesh_config.json| JSON            | Cell widths (hx,hy,hz), origin, survey config |
| Mesh object     | discretize Mesh | TensorMesh, TreeMesh, or CylindricalMesh      |

## Procedure

1. **Load survey locations** from CSV.  Verify units are meters and z is elevation
   (positive up), not depth (positive down).

2. **Compute core cell sizes** from survey extent:
   - `dx = (x_max - x_min) / nx`
   - `dy = (y_max - y_min) / ny`
   - `dz = max(x_extent, y_extent) / nz` (depth ~ horizontal extent)

3. **Add padding cells** with geometric growth:
   ```
   pad_widths = dx * factor^(1..n_pad)
   ```
   Padding must be >= 2× target depth in each horizontal direction.

4. **Build mesh** using `discretize`:
   ```python
   from discretize import TensorMesh
   mesh = TensorMesh([hx, hy, hz], origin=[x0, y0, z0])
   ```

5. **Define active cells** (below topography):
   ```python
   from discretize.utils import active_from_xyz
   active = active_from_xyz(mesh, topo_xyz)
   ```

6. **Build survey** with method-specific sources and receivers:
   ```python
   # Gravity example
   from simpeg.potential_fields import gravity
   rxs = gravity.receivers.Point(locations, components="gz")
   src = gravity.sources.SourceField(receiver_list=[rxs])
   survey = gravity.survey.Survey([src])
   ```

## Verification

- [ ] Total cell count is manageable (< 2M for dense J, < 10M for TreeMesh)
- [ ] Padding extends >= 2× target depth beyond survey footprint
- [ ] Active cells exclude air (above topography)
- [ ] Survey nD matches expected data count
- [ ] Coordinates are in meters, z is elevation

## Traps

| Trap | Description | Consequence |
|------|-------------|-------------|
| **dt_005** | Z coordinate is depth (positive down) instead of elevation | Active cells inverted — model in air, air in ground |
| **dt_011** | Too many cells for dense sensitivity | Out-of-memory crash during Jvec/Jtvec computation |
| **dt_012** | TileMap indices don't match local mesh | Corrupted global sensitivity matrix, wrong inversion |
| Insufficient padding | Mesh doesn't extend far enough | Boundary artifacts in recovered model |
| Non-uniform survey datum | Mixing GPS elevation with geoid | Systematic depth errors in model |

## Example

```python
import numpy as np
from discretize import TensorMesh
from discretize.utils import active_from_xyz

# 1. Define cell widths with padding
dx = 50.0  # 50m core cells
hx = [(dx, 6, -1.3), (dx, 40), (dx, 6, 1.3)]  # pad-core-pad
hy = [(dx, 6, -1.3), (dx, 40), (dx, 6, 1.3)]
hz = [(dx, 6, -1.3), (dx, 20)]                   # pad-core (surface at top)

mesh = TensorMesh([hx, hy, hz], origin="CCN")
print(f"Mesh: {mesh.n_cells:,} cells, shape={mesh.shape_cells}")

# 2. Active cells from topography
topo = np.loadtxt("topography.csv", delimiter=",")
active = active_from_xyz(mesh, topo)
print(f"Active cells: {active.sum():,} / {mesh.n_cells:,}")
```
