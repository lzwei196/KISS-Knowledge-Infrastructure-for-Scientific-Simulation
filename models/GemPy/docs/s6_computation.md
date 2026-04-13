# S6: Interpolation Computation

## Purpose

Execute the GemPy interpolation engine to compute the 3D geological model.
This stage evaluates the potential-field interpolation at every grid point
and extracts formation boundaries as iso-surfaces.

## Inputs

| Input              | Format    | Source                                |
|--------------------|-----------|---------------------------------------|
| Configured model   | GeoModel  | S3–S5 outputs (structural + grid)     |
| Engine config      | optional  | Backend choice (NumPy/PyTorch)        |

## Outputs

| Output            | Type               | Description                       |
|-------------------|--------------------|-----------------------------------|
| solutions         | Solutions object   | Scalar fields, block model, meshes|

### Solutions Object Contents

| Attribute       | Type            | Description                          |
|-----------------|-----------------|--------------------------------------|
| scalar_field    | ndarray float64 | Continuous potential values per cell  |
| block           | ndarray int32   | Discrete formation IDs per cell      |
| vertices        | list[ndarray]   | Mesh vertices per surface boundary   |
| edges           | list[ndarray]   | Mesh triangles per surface boundary  |

## Procedure

### Step 1: Choose backend

| Backend  | Strengths                                   | When to Use              |
|----------|---------------------------------------------|--------------------------|
| NumPy    | No extra deps, stable, CPU-only             | Default, small models    |
| PyTorch  | GPU, autodiff for probabilistic modeling    | Large models, inference  |

### Step 2: Compute the model

```python
import gempy as gp

# Default computation (NumPy backend)
solutions = gp.compute_model(model)

# PyTorch backend with GPU
from gempy_engine.core.data import GemPyEngineConfig
config = GemPyEngineConfig(
    backend=gp.data.AvailableBackends.PYTORCH,
    use_gpu=True
)
solutions = gp.compute_model(model, engine_config=config)
```

### Step 3: Optimize nuggets (optional)

If the covariance matrix is ill-conditioned (computation fails or results
are unstable), optimize the nugget parameters:

```python
# Requires PyTorch backend
gp.optimize_nuggets(model)
solutions = gp.compute_model(model)
```

### Step 4: Access results

```python
# Block model (formation IDs at each grid point)
block = model.solutions.raw_arrays.block

# Scalar field (continuous values)
scalar = model.solutions.raw_arrays.scalar_field

# Mesh vertices for each surface
for i, verts in enumerate(model.solutions.raw_arrays.vertices):
    print(f"Surface {i}: {len(verts)} vertices")
```

### Step 5: Compute at specific points

```python
import numpy as np
custom_points = np.array([[500, 500, -100], [500, 500, -500]])
solutions_at = gp.compute_model_at(model, at=custom_points)
```

## Verification

- [ ] `compute_model()` completes without error
- [ ] Block model has more than 1 unique formation ID
- [ ] Scalar field contains no NaN or Inf values
- [ ] Mesh vertices exist for each expected surface boundary
- [ ] Computation time is reasonable (< 5 min for typical models)

## Traps

| Trap    | Description                                          | Severity |
|---------|------------------------------------------------------|----------|
| dt_007  | Nugget too large — surfaces don't pass through data  | degraded |
| dt_008  | Nugget too small — singular matrix, crash            | fatal    |
| dt_013  | Octree too coarse — thin layers missed               | degraded |
| dt_014  | Grid too large — out of memory                       | fatal    |

## Example

Compute a model and check the results:

```python
import gempy as gp
import numpy as np

solutions = gp.compute_model(model)

# Check block model
block = model.solutions.raw_arrays.block
unique_ids = np.unique(block)
print(f"Formations found: {len(unique_ids)}")
print(f"Formation IDs: {unique_ids}")

# Check scalar field range
sf = model.solutions.raw_arrays.scalar_field
print(f"Scalar field range: [{np.nanmin(sf):.4f}, {np.nanmax(sf):.4f}]")
print(f"NaN count: {np.isnan(sf).sum()}")

# Check meshes
for i, verts in enumerate(model.solutions.raw_arrays.vertices):
    if verts is not None:
        print(f"Surface {i}: {len(verts)} vertices, "
              f"Z range [{verts[:,2].min():.1f}, {verts[:,2].max():.1f}]")
```

Expected: multiple formations, finite scalar values, vertices at geologically
sensible depths.
