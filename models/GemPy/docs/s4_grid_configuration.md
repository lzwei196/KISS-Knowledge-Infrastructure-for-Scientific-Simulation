# S4: Grid Configuration

## Purpose

Configure the computational grid for GemPy model evaluation. The grid
determines where the interpolation function is evaluated, affecting both
model resolution and computational cost.

## Inputs

| Input             | Format    | Source                                |
|-------------------|-----------|---------------------------------------|
| Initialized model | GeoModel  | S2 output                             |
| Grid type choice  | string    | OCTREE, DENSE, CUSTOM, TOPOGRAPHY     |
| Topography data   | array/file| Optional: DEM file or random surface  |
| Section specs     | dict      | Optional: cross-section definitions   |

## Outputs

| Output          | Type      | Description                            |
|-----------------|-----------|----------------------------------------|
| Configured grid | GeoModel  | Model with active grid set             |

## Procedure

### Grid Types

GemPy supports multiple grid types that can be used simultaneously:

| Type       | Use Case                              | Memory     |
|------------|---------------------------------------|------------|
| OCTREE     | Default 3D evaluation, adaptive       | Low–Medium |
| DENSE      | Regular grid, uniform resolution      | High       |
| CUSTOM     | Arbitrary point cloud                 | Variable   |
| TOPOGRAPHY | Surface elevation grid                | Low        |
| SECTIONS   | 2D cross-section slices               | Low        |
| CENTERED   | Spherical grids for geophysics        | Low        |

### Setting the Primary Grid

```python
import gempy as gp

# OCTREE (recommended) — set during model creation
model = gp.create_geomodel(
    project_name="test",
    extent=[0, 2000, 0, 2000, -1000, 0],
    refinement=6,
    importer_helper=importer
)

# DENSE — use resolution parameter
model = gp.create_geomodel(
    project_name="test",
    extent=[0, 2000, 0, 2000, -1000, 0],
    resolution=[80, 80, 80],
    importer_helper=importer
)
```

### Adding Topography

```python
# From random fractal surface
gp.set_topography_from_random(
    grid=model.grid,
    fractal_dimension=1.2,
    d_z=[0, 200],
    topography_resolution=[50, 50]
)

# From file (GeoTIFF, ASCII grid)
gp.set_topography_from_file(
    grid=model.grid,
    filepath="dem.tif",
    crop_to_extent=[xmin, xmax, ymin, ymax]
)
```

### Adding Cross-Sections

```python
gp.set_section_grid(
    grid=model.grid,
    section_dict={
        "NS_section": ([1000, 0], [1000, 2000], [200, 200]),
        "EW_section": ([0, 1000], [2000, 1000], [200, 200])
    }
)
```

### Custom Grid (e.g., borehole locations)

```python
import numpy as np
custom_points = np.array([
    [500, 500, -100],
    [500, 500, -200],
    [500, 500, -300],
])
gp.set_custom_grid(model.grid, custom_points)
```

### Activating Grid Types

```python
# Activate multiple grids simultaneously
gp.set_active_grid(model.grid, gp.data.Grid.GridTypes.DENSE)
gp.set_active_grid(model.grid, gp.data.Grid.GridTypes.TOPOGRAPHY)
```

## Verification

- [ ] Grid type matches the analysis need
- [ ] Total grid points are manageable (< 10M for DENSE)
- [ ] Topography covers the model extent
- [ ] Cross-sections pass through areas of interest
- [ ] Grid resolves thin layers and narrow fault zones

## Traps

| Trap    | Description                                          | Severity |
|---------|------------------------------------------------------|----------|
| dt_010  | Topography elevation units differ from model units   | silent   |
| dt_013  | Octree refinement too low — misses thin layers       | degraded |
| dt_014  | Dense grid too large — out of memory                 | fatal    |

## Example

Configure a model with OCTREE grid, topography, and two cross-sections:

```python
model = gp.create_geomodel(
    project_name="basin_model",
    extent=[0, 5000, 0, 5000, -2000, 500],
    refinement=7,
    importer_helper=importer
)

# Add topography
gp.set_topography_from_random(
    grid=model.grid,
    fractal_dimension=1.5,
    d_z=[0, 500],
    topography_resolution=[80, 80]
)

# Add cross-sections
gp.set_section_grid(
    grid=model.grid,
    section_dict={
        "A-A'": ([0, 2500], [5000, 2500], [300, 200]),
        "B-B'": ([2500, 0], [2500, 5000], [300, 200])
    }
)
```
