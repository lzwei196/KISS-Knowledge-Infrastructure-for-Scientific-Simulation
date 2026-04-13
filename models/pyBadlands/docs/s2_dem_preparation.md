# S2 — DEM Preparation

## Purpose

Process and validate the Digital Elevation Model (DEM) before ingestion by pyBadlands.
The model requires a regular-grid elevation dataset with values in metres. This stage
handles reprojection, resampling, unit conversion, and quality checks.

## Inputs

| Input | Format | Units | Source |
|-------|--------|-------|--------|
| Raw DEM | GeoTIFF, netCDF | varies | SRTM, ALOS, LiDAR |
| Target CRS | EPSG code | — | User-defined (projected CRS preferred) |
| Target resolution | grid spacing | m | User-defined |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Processed DEM | CSV or raster | Regular grid, units=metres, clean edges |
| DEM metadata | JSON | Extent, resolution, z-range, CRS |

## Procedure

1. **Reproject to projected CRS** — pyBadlands works in Cartesian coordinates (metres).
   If the DEM is in geographic coordinates (lat/lon), reproject to a suitable projected
   CRS (e.g., UTM zone). Use `gdalwarp` or `rasterio`:

   ```bash
   gdalwarp -t_srs EPSG:32650 -tr 500 500 raw_dem.tif dem_projected.tif
   ```

2. **Verify elevation units** — Check the z-value range:
   - Typical land elevation: -500 to +8000 m
   - If values are in cm: divide by 100
   - If values are in feet: multiply by 0.3048
   - If values are in mm: divide by 1000

3. **Fill NoData values** — pyBadlands does not handle NoData gracefully. Fill gaps
   using interpolation:

   ```bash
   gdal_fillnodata.py dem_projected.tif dem_filled.tif
   ```

4. **Resample to target resolution** — For geological-scale simulations, coarser grids
   (250 m – 5 km) are appropriate. Finer grids increase computation time quadratically.

5. **Export to CSV format** — pyBadlands can read regular-grid CSV with columns
   `x y z` (space-separated). Export using GDAL or numpy:

   ```python
   import rasterio
   import numpy as np
   with rasterio.open("dem_filled.tif") as src:
       z = src.read(1)
       transform = src.transform
       rows, cols = z.shape
       x = np.array([transform * (c, 0) for c in range(cols)])[:, 0]
       y = np.array([transform * (0, r) for r in range(rows)])[:, 1]
       xx, yy = np.meshgrid(x, y)
       data = np.column_stack([xx.ravel(), yy.ravel(), z.ravel()])
       np.savetxt("dem.csv", data, fmt="%.2f", header="x y z")
   ```

6. **Validate processed DEM**:
   - Check min/max elevation are reasonable
   - Verify no NaN or extreme outlier values
   - Confirm grid spacing is uniform
   - Ensure boundary rows/columns are clean

## Verification

- [ ] Elevation values are in metres (dt_003)
- [ ] No NaN or NoData values remain
- [ ] Grid is regular (uniform spacing in x and y)
- [ ] CRS is projected (not geographic lat/lon)
- [ ] Resolution matches simulation requirements
- [ ] File format matches `<demfile>` expectation (CSV or raster)

## Traps

| ID | Trap | Consequence |
|----|------|-------------|
| dt_003 | Wrong elevation units | Erosion rates scaled incorrectly |
| dt_012 | NaN values in DEM | Model crash with NaN propagation |
| dt_013 | Resolution too coarse after resfactor | Features below grid scale lost |

## Example

Converting a 90 m SRTM tile to 500 m for a 5 Myr simulation:

```bash
# Reproject to UTM zone 50N, resample to 500 m
gdalwarp -t_srs EPSG:32650 -tr 500 500 -r bilinear \
    srtm_tile.tif dem_500m.tif

# Fill NoData
gdal_fillnodata.py dem_500m.tif dem_500m_filled.tif

# Check elevation range
gdalinfo -stats dem_500m_filled.tif | grep "STATISTICS_M"
# Should show: STATISTICS_MINIMUM=0, STATISTICS_MAXIMUM=~5000 (metres)
```
