# s1: Mesh Generation — Creating FEM Meshes for Inversion

## Purpose

Generate an unstructured finite-element mesh suitable for forward modelling or
inversion. The mesh must resolve the electrode/sensor positions, honour
topography, and extend far enough to avoid boundary effects.

## Inputs

| Input               | Format              | Unit        | Source             |
|---------------------|---------------------|-------------|--------------------|
| DataContainer       | `.ohm` / `.sgt`     | m (coords)  | s0 output          |
| Topography          | CSV (x, z)          | m           | Survey/DEM         |
| Region constraints  | JSON                | —           | s2 output          |
| Quality parameter   | float               | degrees     | User config        |

## Outputs

| Output              | Format              | Unit        | Destination        |
|---------------------|---------------------|-------------|--------------------|
| Para mesh           | `.bms` / Mesh obj   | m           | s3 inversion       |
| Region markers      | Mesh attributes     | —           | s3 inversion       |
| Mesh statistics     | JSON                | —           | QC                 |

## Procedure

### Step 1: Create parametric mesh from sensor positions
```python
import pygimli as pg

# For ERT
data = pg.load("survey.ohm")
mesh = pg.meshtools.createParaMesh(data, quality=34, paraMaxCellSize=5.0,
                                    paraDepth=0.3, paraDX=0.5, boundary=2)

# For structured grid (simpler, good for initial tests)
mesh = pg.meshtools.createParaMesh2DGrid(data.sensors())
```

### Step 2: Configure mesh parameters

| Parameter         | Default | Typical Range | Effect                             |
|-------------------|---------|---------------|------------------------------------|
| `quality`         | 34      | 30–34         | Min angle constraint (degrees)     |
| `paraMaxCellSize` | auto    | 1–50 m²       | Max cell area in parameter domain  |
| `paraDepth`       | 0.3     | 0.2–0.5       | Depth factor × electrode spread    |
| `paraDX`          | 0.5     | 0.3–1.0       | Horizontal cell width factor       |
| `boundary`        | 2       | 1–5           | Boundary extension factor          |
| `paraBoundary`    | 2       | 1–5           | Extra boundary for para domain     |

### Step 3: Incorporate topography
```python
# If electrodes have z-coordinates
# They are automatically included in the PLC

# For additional topography points between electrodes
import numpy as np
topo = np.loadtxt("topography.csv", delimiter=",")  # x, z columns
for point in topo:
    # Add as additional nodes to PLC before meshing
    pass
```

### Step 4: Add geological boundaries (optional)
```python
# Create PLC with internal boundaries
world = pg.meshtools.createWorld(start=[-50, 0], end=[90, -30])
layer = pg.meshtools.createRectangle(start=[-50, -5], end=[90, -15], marker=2)
geom = world + layer
mesh = pg.meshtools.createMesh(geom, quality=34)
```

### Step 5: Validate mesh quality
```python
print(f"Cells: {mesh.cellCount()}")
print(f"Nodes: {mesh.nodeCount()}")
print(f"Boundaries: {mesh.boundaryCount()}")

# Check minimum angle
angles = [cell.attribute() for cell in mesh.cells()]
print(f"Cell quality range: {min(angles):.1f} – {max(angles):.1f}")

# Visualize
pg.show(mesh, markers=True)
```

## Verification

1. **Cell count**: 500–50000 for 2D (too few → resolution loss; too many → slow)
2. **Minimum angle**: > 20° (ideally > 28°)
3. **Boundary extent**: 2–5× electrode spread on each side
4. **Electrode positions**: all electrodes are mesh nodes
5. **No degenerate cells**: zero-area or extremely elongated triangles
6. **Depth**: parametric domain extends to expected investigation depth

## Traps

| Trap | Symptom | Cause | Fix |
|------|---------|-------|-----|
| dt_006 | "Mesh generation failed" | Overlapping electrodes | Remove duplicates, snap to grid |
| dt_007 | Poor resolution at depth | paraDepth too small | Increase to 0.4–0.5 |
| dt_008 | Boundary artifacts | Boundary too small | Increase boundary factor to 3–5 |
| dt_009 | Slow inversion | Too many cells | Increase paraMaxCellSize |
| dt_010 | Electrode not on mesh | Non-planar PLC | Check topography consistency |

## Example

```python
import pygimli as pg
from pygimli.physics import ert

# Load data with topography
data = ert.load("survey.ohm")

# Create high-quality inversion mesh
mesh = pg.meshtools.createParaMesh(
    data,
    quality=34,           # min angle = 34° (good quality)
    paraMaxCellSize=5.0,  # max cell area 5 m²
    paraDepth=0.4,        # depth = 40% of spread
    paraDX=0.5,           # horizontal refinement factor
    boundary=3,           # boundary = 3× spread
)

print(f"Created mesh: {mesh.cellCount()} cells, {mesh.nodeCount()} nodes")
mesh.save("inversion_mesh.bms")
```
