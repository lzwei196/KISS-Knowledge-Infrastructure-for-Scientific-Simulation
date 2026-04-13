# Stage 8: Regridding

## Purpose

Interpolate fields between different computational grids. Regridding is
ESMF's core capability — it enables coupling between model components
on different grids (e.g., atmosphere at 1° and ocean at 0.25°). This
stage covers weight generation, application, and validation of the
regridded output.

## Inputs

| Input                  | Format       | Description                          |
|------------------------|--------------|--------------------------------------|
| Source grid             | NetCDF/SCRIP | Grid where data currently lives      |
| Destination grid        | NetCDF/SCRIP | Grid where data is needed            |
| Source field data        | NetCDF       | Data to be regridded                 |
| Mask (optional)         | NetCDF       | Cells to exclude from regridding     |

## Outputs

| Output                 | Format       | Description                          |
|------------------------|--------------|--------------------------------------|
| Weight file             | NetCDF       | Sparse matrix of interpolation weights |
| Regridded field         | NetCDF       | Data on destination grid             |
| Validation report       | JSON         | Conservation checks, error metrics   |

## Procedure

1. **Choose regridding method**:

   | Method | Use When | Conservative? |
   |--------|----------|---------------|
   | bilinear | Smooth fields (T, P, wind) | No |
   | patch | Need accurate gradients | No |
   | conserve | Flux fields (precip, radiation) | Yes |
   | conserve2nd | Flux fields, smoother result | Yes |
   | neareststod | Categorical data (land use) | No |

2. **Generate weight file**:
   ```bash
   # Command-line tool
   ESMF_RegridWeightGen \
       --source atm_grid.nc \
       --destination ocean_grid.nc \
       --weight atm2ocn_weights.nc \
       --method conserve \
       --ignore_unmapped

   # Or Python wrapper
   python generate_regrid_weights.py \
       --source atm_grid.nc \
       --destination ocean_grid.nc \
       --weight atm2ocn_weights.nc \
       --method conserve
   ```

3. **Apply weights**:
   ```bash
   ESMF_Regrid \
       --source atm_temperature.nc \
       --destination ocean_temperature.nc \
       --weight atm2ocn_weights.nc
   ```

4. **Validate conservation** (for conservative methods):
   ```python
   import numpy as np
   from netCDF4 import Dataset

   src = Dataset("atm_precip.nc")
   dst = Dataset("ocean_precip.nc")
   src_grid = Dataset("atm_grid.nc")
   dst_grid = Dataset("ocean_grid.nc")

   # Integral = sum(field * area) over all cells
   src_integral = np.sum(src['precip'][:] * src_grid['grid_area'][:])
   dst_integral = np.sum(dst['precip'][:] * dst_grid['grid_area'][:])

   conservation_error = abs(src_integral - dst_integral) / abs(src_integral)
   print(f"Conservation error: {conservation_error:.2e}")
   # Should be < 1e-10 for 1st order conservative
   ```

5. **Check for unmapped cells**:
   - Unmapped destination cells get fill values
   - Use `--ignore_unmapped` to prevent fatal errors
   - Use extrapolation (`--extrap_method creep_fill`) to fill gaps

## Verification

- Weight file exists and has non-zero S (weight) variable
- For conservative: row sums ≈ 1.0 (within machine precision)
- Global integral preserved (source integral ≈ destination integral)
- No NaN values in regridded output (unless from masked source)
- Visual comparison: no obvious artifacts at grid boundaries

## Traps

| Trap | Description | Severity |
|------|-------------|----------|
| Areas in wrong units | Degrees² instead of steradians → 3000x conservation error | silent |
| Clockwise corners | SCRIP corners must be CCW → negative areas → wrong weights | silent |
| Missing destination areas | Conservative regrid without dst areas → silent violation | silent |
| Fill values interpolated | Source -9999 not masked → interpolated as real data | silent |
| Unmapped cells | Destination cells outside source domain → uninitialized data | silent/fatal |
| Periodic boundary missing | Global grid without periodic → seam artifact at 0°/360° | silent |
| 0-based mesh indices | C convention instead of Fortran 1-based → topology error | silent |
| Weight file reuse | Grid changed but old weights used → dimension mismatch | fatal |

## Example

```python
import esmpy
import numpy as np

# Create source grid (2° global)
srcgrid = esmpy.Grid(np.array([90, 180]),
                     staggerloc=esmpy.StaggerLoc.CENTER,
                     coord_sys=esmpy.CoordSys.SPH_DEG)

# Create destination grid (1° global)
dstgrid = esmpy.Grid(np.array([180, 360]),
                     staggerloc=esmpy.StaggerLoc.CENTER,
                     coord_sys=esmpy.CoordSys.SPH_DEG)

# Create fields
srcfield = esmpy.Field(srcgrid, name="temperature")
dstfield = esmpy.Field(dstgrid, name="temperature")

# Fill source with test pattern
srcfield.data[...] = 300.0  # 300 K uniform

# Create regrid handle
regrid = esmpy.Regrid(srcfield, dstfield,
                       regrid_method=esmpy.RegridMethod.BILINEAR,
                       unmapped_action=esmpy.UnmappedAction.IGNORE)

# Apply regridding
dstfield = regrid(srcfield, dstfield)

# Verify
print(f"Source mean: {np.mean(srcfield.data):.2f} K")
print(f"Dest mean:   {np.mean(dstfield.data):.2f} K")
# Should be approximately equal for uniform field
```
