# S1: Grid Discretization — Building the MODFLOW Spatial Grid

## Purpose

Create the spatial grid (DIS package) that defines the model domain: number of rows, columns, and layers; cell sizes; surface elevation; and layer bottom elevations. This is the foundation of every MODFLOW model.

## Inputs

| Input | Format | Source | Units |
|-------|--------|--------|-------|
| DEM raster | GeoTIFF (.tif) or ASCII (.asc) | SRTM, ASTER, LiDAR | meters ASL |
| Domain boundary | Shapefile or bbox (xmin,ymin,xmax,ymax) | User-defined | meters (projected CRS) |
| Target cell size | Scalar | User decision | meters |
| Number of layers | Integer | Conceptual model | — |
| Layer thickness(es) | List of floats or total depth | Borehole logs, geology | meters |

## Outputs

| Output | Format | Consumed by |
|--------|--------|-------------|
| `top.npy` | NumPy array (nrow, ncol) | DIS package |
| `botm.npy` | NumPy array (nlay, nrow, ncol) | DIS package |
| `delr.npy` | NumPy array (ncol,) | DIS package |
| `delc.npy` | NumPy array (nrow,) | DIS package |
| `grid_metadata.json` | JSON | All downstream tools |

## Procedure

1. **Load DEM**: Read raster with rasterio or as ASCII grid
2. **Define extent**: Clip to bounding box or shapefile boundary
3. **Resample**: Resample DEM to target cell size (nearest neighbor for elevation)
4. **Compute layers**: Subtract layer thicknesses from top to get bottoms
5. **Validate**: Check for NaN, negative thickness, reasonable elevation range
6. **Save**: Write arrays and metadata

### MODFLOW 6 (FloPy)

```python
import flopy
import numpy as np

dis = flopy.mf6.ModflowGwfdis(
    gwf,
    nlay=3, nrow=40, ncol=20,
    delr=250.0,        # Row spacing (m) — can be array
    delc=250.0,        # Column spacing (m) — can be array
    top=top_array,      # (nrow, ncol) surface elevation
    botm=botm_array,    # (nlay, nrow, ncol) layer bottoms
    length_units='METERS'
)
```

### MODFLOW-2005 (FloPy)

```python
dis = flopy.modflow.ModflowDis(
    model,
    nlay=3, nrow=40, ncol=20, nper=1,
    delr=250.0, delc=250.0,
    top=top_array, botm=botm_array,
    itmuni=4,   # days
    lenuni=2,   # meters
    perlen=365, nstp=1, tsmult=1.0, steady=True
)
```

## Verification

- [ ] Grid dimensions match expected area: nrow × delc ≈ domain height, ncol × delr ≈ domain width
- [ ] Top elevation range matches DEM range
- [ ] All layer thicknesses > 0 (no zero-thickness cells)
- [ ] Bottom of layer k is above bottom of layer k+1
- [ ] No NaN values in top or botm arrays
- [ ] Total cells (nlay × nrow × ncol) is computationally tractable (< 5M recommended)

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| DEM in feet, model in meters | Heads too high by 3x | Convert: `top_m = top_ft * 0.3048` |
| Cell size too small | Model takes hours/days | Increase cell size; start with 250-500m |
| Zero-thickness layers | MODFLOW crash or dry cells | Ensure min thickness > 0.1m |
| DEM nodata not masked | Extreme elevations in grid | Mask nodata before resampling |
| Wrong CRS projection | Grid offset from real world | Ensure DEM and model use same projected CRS |

## Example

```bash
python tools/build_grid_from_dem.py \
    --dem data/dem_30m.tif \
    --cell_size 250 \
    --nlay 3 \
    --layer_thickness 10,20,30 \
    --bbox "500000,3500000,510000,3510000" \
    --output_dir grid_output/
```
