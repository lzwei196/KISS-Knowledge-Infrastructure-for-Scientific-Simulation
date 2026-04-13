# Stage 3: Data Interpolation to FEM Space

## Purpose

Interpolate gridded raster data (velocity, thickness, bed, surface) from their
native grids onto the unstructured finite element mesh. This is the bridge between
remote sensing data and the icepack solver — the step where continuous fields are
projected onto discrete function spaces.

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| Raster datasets | rasterio DatasetReader or xarray DataArray | Gridded fields in projected CRS |
| Firedrake mesh | firedrake.Mesh | Target FEM mesh |
| Function space | firedrake.FunctionSpace | CG degree ≥ 1 for scalars, VectorFunctionSpace for velocity |

## Outputs

| Output | Type | Description |
|--------|------|-------------|
| h | firedrake.Function | Ice thickness on FEM mesh |
| u | firedrake.Function | Ice velocity on FEM mesh |
| s | firedrake.Function | Surface elevation on FEM mesh |
| b | firedrake.Function | Bed elevation on FEM mesh |
| A | firedrake.Function | Fluidity (from temperature via rate_factor) |

## Procedure

1. **Create function spaces**:
   ```python
   Q = firedrake.FunctionSpace(mesh, "CG", 2)      # scalars
   V = firedrake.VectorFunctionSpace(mesh, "CG", 2)  # vectors
   ```

2. **Interpolate scalar fields** (thickness, bed, surface):
   ```python
   import rasterio
   import icepack

   with rasterio.open("thickness_m.tif") as src:
       h = icepack.interpolate(src, Q)
   ```

3. **Interpolate vector fields** (velocity):
   ```python
   vx_data = rasterio.open("vx_myr.tif")
   vy_data = rasterio.open("vy_myr.tif")
   u = icepack.interpolate((vx_data, vy_data), V)
   ```

4. **Compute derived fields**:
   ```python
   # Surface from thickness + bed (hydrostatic balance)
   s = icepack.compute_surface(thickness=h, bed=b)

   # Fluidity from temperature
   T = 254.15  # Kelvin
   A = firedrake.Function(Q)
   A.interpolate(firedrake.Constant(icepack.rate_factor(T)))
   ```

5. **Handle missing data**: icepack.interpolate uses scipy's RegularGridInterpolator
   internally. NaN values in the raster will propagate. Ensure the raster covers
   the entire mesh domain or fill gaps before interpolation.

## Verification

- [ ] h.dat.data.min() > 0 (positive thickness everywhere)
- [ ] No NaN values in any interpolated field
- [ ] Velocity magnitude range matches source data
- [ ] Surface elevation consistent with flotation: s ≥ (1-ρ_i/ρ_w)×h
- [ ] CRS of raster matches mesh coordinates

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Raster CRS ≠ mesh CRS | Fields shifted/distorted | Reproject raster to match mesh CRS |
| NaN in interpolated field | Solver crash with "NaN in residual" | Fill raster gaps or clip mesh to data extent |
| Velocity (vx,vy) swapped | Flow direction wrong | Check raster band order vs x,y convention |
| Thickness = 0 on boundary | Zero-thickness → division by zero | Enforce min thickness before interpolation |
| Wrong interpolation method | Blocky artifacts | Use method="linear" (default) or "cubic" |
| Raster smaller than mesh | Extrapolation → garbage values | Ensure raster extent fully covers mesh |

## Example

```python
import firedrake
import rasterio
import icepack

# Set up mesh and function spaces
mesh = firedrake.Mesh("glacier.msh")
Q = firedrake.FunctionSpace(mesh, "CG", 2)
V = firedrake.VectorFunctionSpace(mesh, "CG", 2)

# Interpolate thickness
with rasterio.open("thickness_m.tif") as src:
    h = icepack.interpolate(src, Q)

# Interpolate velocity
vx = rasterio.open("vx_myr.tif")
vy = rasterio.open("vy_myr.tif")
u = icepack.interpolate((vx, vy), V)

# Verify
import numpy as np
print(f"h: [{h.dat.data.min():.0f}, {h.dat.data.max():.0f}] m")
speed = np.sqrt(np.sum(u.dat.data**2, axis=1))
print(f"|u|: [{speed.min():.0f}, {speed.max():.0f}] m/yr")
```
