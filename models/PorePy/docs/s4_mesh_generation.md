# S4: Mesh Generation and Mixed-Dimensional Grids

## Purpose

Create the computational mesh (mixed-dimensional grid, MDG) from the domain
definition and fracture network. PorePy uses Gmsh for unstructured meshing and
has built-in support for Cartesian/tensor grids. The MDG couples higher-dimensional
matrix cells with lower-dimensional fracture cells and interface mortars.

## Inputs

| Input                | Type            | Unit | Description                               |
|----------------------|-----------------|------|-------------------------------------------|
| Domain               | `pp.Domain`     | m    | Bounding box of simulation domain         |
| Fractures            | `List[Fracture]`| m    | Fracture geometries                       |
| Grid type            | `str`           | —    | "cartesian", "simplex", or "tensor_grid"  |
| Cell size            | `float`         | m    | Target cell size for matrix               |
| Cell size (fracture) | `float`         | m    | Target cell size near fractures           |
| Cell size (boundary) | `float`         | m    | Target cell size at boundaries            |

## Outputs

| Output                   | Type                        | Description                     |
|--------------------------|-----------------------------|---------------------------------|
| Mixed-dimensional grid   | `pp.MixedDimensionalGrid`   | Complete MDG with all entities  |
| Subdomains               | `List[pp.Grid]`             | Matrix + fracture + intersection grids |
| Interfaces               | `List[pp.MortarGrid]`       | Coupling interfaces             |

## Procedure

### Step 1: Configure meshing arguments

```python
meshing_args = {
    "cell_size": 0.1,            # Main cell size (meters)
    "cell_size_fracture": 0.05,  # Finer near fractures
    "cell_size_boundary": 0.1,   # Boundary cell size
    "cell_size_min": 0.02,       # Minimum allowed cell size
}
```

### Step 2: Select grid type

| Grid Type   | Use Case                          | Mesh Generator |
|-------------|-----------------------------------|----------------|
| `cartesian` | Regular domains, no fractures     | Built-in       |
| `simplex`   | Fractured domains, complex geometry | Gmsh          |
| `tensor_grid` | Structured with variable spacing | Built-in       |

### Step 3: Create MDG (automatic via model)

```python
class MyModel(pp.SinglePhaseFlow):
    def set_domain(self):
        self._domain = pp.Domain({"xmin": 0, "xmax": 1, "ymin": 0, "ymax": 1})

    def set_fractures(self):
        self._fractures = [
            pp.LineFracture(np.array([[0.2, 0.8], [0.5, 0.5]])),
        ]

model = MyModel({
    "grid_type": "simplex",
    "meshing_arguments": meshing_args,
})
model.prepare_simulation()
mdg = model.mdg
```

### Step 4: Inspect the MDG

```python
# Grid hierarchy
for sd in mdg.subdomains():
    print(f"Dim {sd.dim}: {sd.num_cells} cells, {sd.num_faces} faces")

# Interfaces
for intf in mdg.interfaces():
    print(f"Interface: {intf.num_cells} mortar cells")
```

## Verification

- `len(mdg.subdomains(dim=nd))` should be 1 (single matrix)
- `len(mdg.subdomains(dim=nd-1))` should equal number of fractures
- Cell sizes should approximate the requested `cell_size`
- No cells with zero volume: `np.all(sd.cell_volumes > 0)`
- Fracture cells should have lower dimension than matrix cells

## Traps

| ID     | Trap                                      | Consequence                              |
|--------|-------------------------------------------|------------------------------------------|
| dt_008 | Cell size too large for domain            | Under-resolved flow field                |
| dt_014 | Degenerate fracture (zero-area polygon)   | Gmsh crash                               |
| dt_018 | Fracture extends outside domain           | Gmsh failure or incorrect topology       |
| dt_008 | Cell size too small                       | Millions of cells, out of memory         |

## Example

```python
import numpy as np
import porepy as pp

# Create MDG directly (without model class)
domain = pp.Domain({"xmin": 0, "xmax": 1, "ymin": 0, "ymax": 1})
fractures = [pp.LineFracture(np.array([[0.25, 0.75], [0.5, 0.5]]))]
network = pp.create_fracture_network(fracs=fractures, domain=domain)
mdg = pp.create_mdg(
    grid_type="simplex",
    meshing_args={"cell_size": 0.1},
    fracture_network=network,
)

# Summary
print(f"Total subdomains: {len(mdg.subdomains())}")
print(f"  Matrix (2D): {len(mdg.subdomains(dim=2))} grids")
print(f"  Fractures (1D): {len(mdg.subdomains(dim=1))} grids")
print(f"  Intersections (0D): {len(mdg.subdomains(dim=0))} grids")
print(f"Interfaces: {len(mdg.interfaces())}")
```
