# S1: Domain Definition and Fracture Setup

## Purpose

Define the computational domain geometry, fracture network, and wells for a PorePy
simulation. This is the foundation of the mixed-dimensional grid (MDG) that represents
the fractured porous medium.

## Inputs

| Input             | Type                | Unit   | Description                          |
|-------------------|---------------------|--------|--------------------------------------|
| Domain bounds     | `pp.Domain` dict    | m      | xmin/xmax, ymin/ymax, zmin/zmax     |
| Fractures (2D)    | `pp.LineFracture`   | m      | Start/end point coordinates          |
| Fractures (3D)    | `pp.PlaneFracture`  | m      | Corner point coordinates (convex polygon) |
| Elliptic fracs    | `pp.EllipticFracture` | m    | Center, major/minor axes, angles     |
| Wells             | `pp.WellNetwork3d`  | m      | Well trajectory coordinates          |

## Outputs

| Output            | Type                        | Description                         |
|-------------------|-----------------------------|-------------------------------------|
| Domain object     | `pp.Domain`                 | Bounding box of simulation domain   |
| Fracture list     | `List[pp.PlaneFracture]`    | All fractures for meshing           |
| Fracture network  | `pp.FractureNetwork`        | Processed network with intersections|

## Procedure

### Step 1: Define the domain

```python
import porepy as pp

# 2D domain
domain_2d = pp.Domain({"xmin": 0, "xmax": 1, "ymin": 0, "ymax": 1})

# 3D domain
domain_3d = pp.Domain({
    "xmin": 0, "xmax": 100,
    "ymin": 0, "ymax": 100,
    "zmin": 0, "zmax": 50,
})
```

### Step 2: Define fractures

```python
import numpy as np

# 2D: Line fractures (two endpoints)
frac_2d = pp.LineFracture(np.array([[0.2, 0.8], [0.5, 0.5]]))

# 3D: Planar fractures (corner points as columns)
frac_3d = pp.PlaneFracture(np.array([
    [20, 80, 80, 20],   # x
    [20, 20, 80, 80],   # y
    [25, 25, 25, 25],   # z (planar)
]))

# Elliptic fracture
frac_ell = pp.EllipticFracture(
    center=np.array([50, 50, 25]),
    major_axis=20,
    minor_axis=10,
    major_axis_angle=0,
    strike_angle=0,
    dip_angle=np.pi / 4,
    num_points=16,
)
```

### Step 3: Implement in model class

```python
class MyModel(pp.SinglePhaseFlow):
    def set_domain(self):
        self._domain = pp.Domain({"xmin": 0, "xmax": 1, "ymin": 0, "ymax": 1})

    def set_fractures(self):
        self._fractures = [
            pp.LineFracture(np.array([[0.2, 0.8], [0.5, 0.5]])),
        ]
```

## Verification

- All fracture points must lie within or on the domain boundary
- Fracture planes must be non-degenerate (non-zero area)
- 3D fractures must be planar (all corner points coplanar)
- Check: `len(model._fractures)` matches expected count

## Traps

| ID     | Trap                                      | Consequence                              |
|--------|-------------------------------------------|------------------------------------------|
| dt_018 | Fracture extends outside domain           | Gmsh meshing failure (fatal)             |
| dt_008 | Cell size much larger than fracture length | Fracture not resolved in mesh            |
| dt_012 | Fracture coordinates in mm instead of m   | Fracture too small relative to domain    |

## Example

```python
import numpy as np
import porepy as pp

# Single fracture in unit square
class FracturedDomain(pp.SinglePhaseFlow):
    def set_domain(self):
        self._domain = pp.Domain({"xmin": 0, "xmax": 1, "ymin": 0, "ymax": 1})

    def set_fractures(self):
        self._fractures = [
            pp.LineFracture(np.array([[0.25, 0.75], [0.5, 0.5]])),
        ]

model = FracturedDomain({
    "grid_type": "simplex",
    "meshing_arguments": {"cell_size": 0.1},
})
model.prepare_simulation()
mdg = model.mdg
print(f"Subdomains: {len(mdg.subdomains())}")
print(f"Interfaces: {len(mdg.interfaces())}")
```
