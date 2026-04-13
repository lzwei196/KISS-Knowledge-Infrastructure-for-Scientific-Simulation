# Stage 1: Domain Setup — DEM and D8 Flow Grid Preparation

## Purpose

Prepare the spatial domain for TopoFlow by processing a Digital Elevation Model
(DEM) into the required D8 flow direction grid, slope grid, and contributing
area grid.  These grids define how water routes through the landscape and are
prerequisites for all other components.

## Inputs

| File / Data           | Format          | Units         | Source                    |
|-----------------------|-----------------|---------------|---------------------------|
| DEM raster            | GeoTIFF / ASCII | meters (m)    | SRTM, ASTER, MERIT, LiDAR|
| Basin outlet location | lat/lon         | degrees        | Manual or GIS             |
| Target resolution     | scalar          | meters         | User choice (10–1000 m)   |

## Outputs

| File                   | Format     | Units / Content                          |
|------------------------|------------|------------------------------------------|
| `*_DEM.rtg`            | RTG binary | Elevation in meters                      |
| `*_DEM.rti`            | RTI text   | Grid header (nrows, ncols, dx, dy, etc.) |
| `*_flow.rtg`           | RTG binary | D8 flow direction codes (0–128)          |
| `*_slope.rtg`          | RTG binary | Slope (m/m, dimensionless)               |
| `*_area.rtg`           | RTG binary | Contributing area (km² or # cells)       |
| `*_outlets.txt`        | Text       | Outlet pixel row/col coordinates         |

## Procedure

### Step 1: Obtain and clip the DEM

Download a DEM covering the target watershed plus a buffer zone (at least 5 cells
on each side).  For global coverage:

- **SRTM** (30 m / 90 m): Available from USGS EarthExplorer
- **MERIT Hydro** (90 m, hydrologically conditioned): Recommended for large basins
- **LiDAR** (1–5 m): Best for small research catchments

Clip to the study area using GDAL:

```bash
gdalwarp -te xmin ymin xmax ymax -tr 30 30 raw_dem.tif clipped_dem.tif
```

### Step 2: Reproject to UTM (if needed)

TopoFlow works with projected coordinates (meters).  If the DEM is in geographic
coordinates (degrees), reproject:

```bash
gdalwarp -t_srs EPSG:32615 clipped_dem.tif dem_utm.tif
```

### Step 3: Convert to RTG format

TopoFlow reads RTG (binary float32) with an accompanying RTI header.  Use the
TopoFlow utility or a custom script:

```python
import numpy as np
from osgeo import gdal

ds = gdal.Open('dem_utm.tif')
dem = ds.ReadAsArray().astype(np.float32)
dem.tofile('Treynor_DEM.rtg')

# Write RTI header
with open('Treynor_DEM.rti', 'w') as f:
    f.write(f"ncols           | {dem.shape[1]}\n")
    f.write(f"nrows           | {dem.shape[0]}\n")
    f.write(f"data_type       | FLOAT\n")
    f.write(f"byte_order      | LSB\n")
    f.write(f"pixel_geom      | 1\n")
    f.write(f"xres            | 30.0\n")
    f.write(f"yres            | 30.0\n")
```

### Step 4: Fill pits and compute D8 grids

```python
from topoflow.components.d8_global import d8_component

d8 = d8_component()
d8.initialize(cfg_file='my_d8.cfg')
d8.update()   # computes flow codes, slopes, areas
d8.finalize()
```

Alternatively, use the fill_pits utility first:

```python
from topoflow.utils import fill_pits
fill_pits.fill_pits(DEM_file='Treynor_DEM.rtg', ...)
```

### Step 5: Create outlet file

Identify the outlet pixel (row, col) from the D8 area grid (largest contributing
area cell at the basin boundary):

```
# Treynor_outlets.txt
# col  row
14   28
```

## Verification

1. **DEM range check:** Verify elevation range matches expected topography.
2. **D8 connectivity:** All cells should drain to the outlet; no orphan cells.
3. **Slope check:** No zero slopes (minimum floor ≥ 1e-6 m/m).
4. **Area at outlet:** Contributing area should match known basin area.
5. **RTG file size:** Must equal `nrows × ncols × 4` bytes.

```python
import numpy as np
dem = np.fromfile('Treynor_DEM.rtg', dtype=np.float32).reshape(nrows, ncols)
assert dem.min() > 0, "Elevation should be positive"
slope = np.fromfile('Treynor_slope.rtg', dtype=np.float32).reshape(nrows, ncols)
assert slope.min() > 0, "Zero slope will cause division-by-zero in Manning's eq"
```

## Traps

| Trap                           | Symptom                                | Fix                                  |
|--------------------------------|----------------------------------------|--------------------------------------|
| DEM not pit-filled             | Water pools in flat areas, no outflow  | Run fill_pits before D8 computation  |
| Zero slope cells               | Division by zero in channel routing    | Impose minimum slope of 1e-6 m/m     |
| RTG/RTI dimension mismatch     | Silent data corruption, shifted grids  | Verify file size = nrows×ncols×4     |
| Geographic vs. projected CRS   | Cell size in degrees, not meters       | Reproject to UTM before processing   |
| Stale D8 after DEM edit        | Incorrect flow routing                 | Recompute D8 codes after any DEM mod |
| Outlet pixel outside domain    | Zero or NaN discharge at outlet        | Verify outlet is within D8 flow grid |

## Example

For the Treynor Iowa test case (bundled with TopoFlow):
- DEM: 29 rows × 44 cols at 30 m resolution
- Elevation range: ~320–390 m
- Basin area: ~0.7 km²
- Outlet at approximately col=14, row=28 (adjust per actual D8 grid)
