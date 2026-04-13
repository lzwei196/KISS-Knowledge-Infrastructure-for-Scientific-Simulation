# S1: Terrain Preparation

## Purpose

Prepare terrain input files for DHSVM: DEM, basin mask, slope, and aspect maps
in flat binary format. These files define the spatial domain, flow directions,
and topographic characteristics that drive the distributed water and energy balance.

## Inputs

| Input | Format | Units | Source |
|-------|--------|-------|--------|
| Raw DEM | GeoTIFF or ASCII grid | meters above sea level | SRTM, ASTER, LiDAR |
| Basin boundary | Shapefile or raster | polygon/mask | Watershed delineation |
| Stream network | Shapefile (optional) | line geometry | NHD, manual delineation |

## Outputs

| Output | Format | Units | Description |
|--------|--------|-------|-------------|
| `dem.bin` | Flat binary, float32, row-major | meters | Elevation grid |
| `mask.bin` | Flat binary, int32, row-major | 0/1 | Basin boundary (1=inside) |
| `slope.bin` | Flat binary, float32 | radians | Surface gradient |
| `aspect.bin` | Flat binary, float32 | degrees (0=N) | Flow direction |

## Procedure

1. **Reproject DEM** to the target coordinate system (typically UTM).
   DHSVM uses a regular Cartesian grid; the DEM must be projected, not geographic.

2. **Resample** to the desired grid spacing (e.g., 90 m). DHSVM supports any
   regular grid size but 30-150 m is typical. Coarser grids lose topographic detail;
   finer grids increase computation time quadratically.

3. **Clip** the DEM to the basin boundary. The mask file marks cells inside (1)
   and outside (0) the basin. DHSVM only computes cells where mask=1.

4. **Compute slope and aspect** from the DEM.
   - Slope must be in **radians** (common trap: degrees).
   - Aspect uses compass convention: 0=North, 90=East, 180=South, 270=West.

5. **Write binary files**. DHSVM reads flat binary, row-major order:
   ```python
   import numpy as np
   dem_array = np.loadtxt("dem.asc", skiprows=6)  # skip header
   dem_array.astype(np.float32).tofile("dem.bin")
   mask_array.astype(np.int32).tofile("mask.bin")
   ```

6. **Verify dimensions** match the config file:
   ```
   Number of Rows = 425
   Number of Columns = 300
   ```
   The binary file must contain exactly `nrows * ncols` values.

## Verification

- Check file sizes: `dem.bin` should be `nrows * ncols * 4` bytes (float32).
- Verify `mask.bin` has the expected number of active cells.
- Plot the DEM and mask to ensure alignment.
- Confirm Extreme North/West coordinates in config match the DEM extent.

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| DEM in feet instead of meters | Elevation-dependent processes (lapse rates, snow line) are wrong | Multiply by 0.3048 |
| Slope in degrees instead of radians | Radiation and flow calculations incorrect | Multiply by pi/180 |
| Binary file wrong endianness | Random-looking values, possible crash | Use native byte order or set `Format = BYTESWAP` |
| Missing nodata fill | NaN propagation through energy balance | Fill nodata cells before writing binary |
| Grid dimensions mismatch | All pixel values shifted; wrong results with no error | Verify binary size = nrows * ncols * 4 |

## Example

```bash
# Using GDAL to prepare DEM
gdalwarp -t_srs EPSG:32610 -tr 90 90 -r bilinear raw_dem.tif dem_utm.tif
gdal_calc.py -A dem_utm.tif --outfile=dem.bin --format=EHdr --calc="A"

# Using Python
import numpy as np
from osgeo import gdal

ds = gdal.Open("dem_utm.tif")
dem = ds.ReadAsArray().astype(np.float32)
dem.tofile("dem.bin")
print(f"Shape: {dem.shape}, Size: {dem.nbytes} bytes")
```
