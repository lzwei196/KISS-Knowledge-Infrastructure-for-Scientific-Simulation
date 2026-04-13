# Stage 1: DEM and Slope Grid Preparation

## Purpose

Prepare the foundational topographic grids required by TRIGRS: a Digital Elevation Model (DEM), slope angle grid, and flow direction grid. These grids define the spatial domain and control both the infiltration calculations and the infinite-slope stability analysis. All subsequent grids (zones, depth, water table, rainfall) must be congruent with the DEM.

## Inputs

| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| Raw DEM | GeoTIFF, SRTM, ASTER | USGS, Copernicus | Digital elevation model of study area |
| Basin boundary | Shapefile / GeoJSON | GIS delineation | Study area extent for clipping |

## Outputs

| Output | Format | Unit | Description |
|--------|--------|------|-------------|
| dem.asc | ESRI ASCII grid | meters | Elevation above datum |
| slope.asc | ESRI ASCII grid | **degrees** | Slope angle (NOT percent, NOT radians) |
| directions.asc | ESRI ASCII grid | integer (1-8) | D8 flow direction codes |

## Procedure

1. **Obtain DEM data**
   - Download from USGS National Elevation Dataset, SRTM 30m/90m, ASTER GDEM, or Copernicus DEM
   - Resolution typically 10-30m for regional studies

2. **Clip to study area**
   - Buffer the study area boundary by at least 5 cells to avoid edge effects in flow routing
   - Ensure the DEM covers all areas of interest

3. **Fill sinks** (optional but recommended)
   - Use GIS hydrological tools to fill depressions
   - TRIGRS does not require a hydrologically conditioned DEM, but filled DEMs produce better flow routing

4. **Compute slope angle grid**
   - Calculate slope angle in **degrees** (not percent, not radians)
   - TRAP: ArcGIS defaults to degrees, QGIS/GRASS may output in percent or radians depending on settings

5. **Compute flow direction grid**
   - Use D8 flow direction algorithm
   - TRIGRS uses its own numbering (TopoIndex convention) or ESRI convention
   - TopoIndex can convert ESRI flow direction codes to its own format

6. **Export as ESRI ASCII grids**
   - All grids must have identical: ncols, nrows, xllcorner, yllcorner, cellsize, NODATA_value
   - Use consistent CRS (projected coordinates in meters recommended)
   - NODATA_value must be consistent (typically -9999)

7. **Run GridMatch**
   - Verify all grids are congruent: `./gridmatch < gm_in.txt`
   - Fix any mismatches before proceeding

## Verification

```bash
# Check grid dimensions match
head -6 dem.asc
head -6 slope.asc
head -6 directions.asc

# Verify slope is in degrees (max typically < 90)
python3 -c "
import numpy as np
d = np.loadtxt('slope.asc', skiprows=6)
print(f'Slope range: {d[d!=-9999].min():.1f} to {d[d!=-9999].max():.1f} degrees')
assert d[d!=-9999].max() < 90, 'Slope > 90 degrees -- check units!'
"
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Slope in radians | All FS values near 1.0 or unrealistically high | Multiply by 180/pi |
| Slope in percent | FS values shifted; flat areas show instability | Convert: degrees = atan(percent/100) * 180/pi |
| Grid size mismatch | TRIGRS crash with array bounds error | Run GridMatch; regenerate from same DEM |
| Mixed CRS | Spatial offset in results | Reproject all grids to same CRS |
| Nodata mismatch | Wrong cells processed or skipped | Ensure all grids use same NODATA_value |

## Example

```python
# Generate slope grid from DEM using Python
import numpy as np

def compute_slope_degrees(dem_data, cellsize):
    """Compute slope angle in degrees from DEM."""
    dy, dx = np.gradient(dem_data, cellsize)
    slope_rad = np.arctan(np.sqrt(dx**2 + dy**2))
    return np.degrees(slope_rad)

# Read DEM
dem = np.loadtxt('dem.asc', skiprows=6)
slope_deg = compute_slope_degrees(dem, cellsize=10)
print(f"Max slope: {slope_deg.max():.1f} degrees")
```
