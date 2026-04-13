# Stage 1: DEM and Basic Grid Preparation

## Purpose

Prepare the three fundamental grids required by EF5: Digital Elevation Model (DEM), Drainage Direction Map (DDM), and Flow Accumulation Map (FAM). These grids define the hydrological topology of the basin and control all routing computations in CREST.

## Inputs

| Input | Format | Unit | Source |
|-------|--------|------|--------|
| Raw DEM | GeoTIFF (.tif) or ESRI ASCII (.asc) | meters | SRTM 90m, ASTER GDEM, local survey |
| Basin boundary | Shapefile or bounding box | degrees (WGS84) | Manual delineation or HydroSHEDS |
| Outlet coordinates | lon, lat | degrees (WGS84) | Gauge location |

## Outputs

| Output | Format | Unit | Description |
|--------|--------|------|-------------|
| DEM.asc / DEM.tif | ESRI ASCII or Float32 GeoTIFF | meters | Clipped, pit-filled DEM |
| DDM.asc / DDM.tif | ESRI ASCII or Float32 GeoTIFF | direction code | Drainage direction map |
| FAM.asc / FAM.tif | ESRI ASCII or Float32 GeoTIFF | cell count | Flow accumulation map |

## Procedure

### Step 1: Obtain and clip DEM

```bash
# Using GDAL to clip DEM to bounding box
gdalwarp -te lon_min lat_min lon_max lat_max \
         -tr 0.01 0.01 \
         input_dem.tif clipped_dem.tif
```

Or use EF5's built-in DEM processor:
```bash
ef5 -z dem.tif -d ddm.tif -a fam.tif -p
```

### Step 2: Fill sinks and generate DDM

If not using EF5's built-in tool, use TauDEM or ArcGIS Hydrology tools:
```bash
# TauDEM workflow
pitremove dem.tif -z dem_filled.tif
d8flowdir -p ddm.tif -sd8 slope.tif -fel dem_filled.tif
aread8 -p ddm.tif -ad8 fam.tif
```

### Step 3: Set DDM encoding

EF5 supports two DDM encoding schemes. Configure via `ESRIDDM` in control.txt:

**ESRI encoding (ESRIDDM=true):**
```
 32  64  128
 16   •    1
  8   4    2
```

**TauDEM encoding (ESRIDDM=false):**
```
  4   3   2
  5   •   1
  6   7   8
```

### Step 4: Set FAM self-inclusion

Configure `SELFFAM` in control.txt:
- `SELFFAM=true`: Cell counts itself (minimum FAM = 1)
- `SELFFAM=false`: Cell does not count itself (minimum FAM = 0)

### Step 5: Set projection

Configure `PROJ` in control.txt:
- `geographic`: Standard lat/lon (WGS84) — most common for global datasets
- `laea`: Lambert Azimuthal Equal Area (centered at 45°N, 100°W) — for CONUS applications

## Verification

1. **Visual inspection**: Open DEM, DDM, FAM in QGIS or similar
2. **Grid alignment**: All three grids must have identical extent, resolution, and projection
3. **DDM sanity**: Check that flow directions follow topographic gradient
4. **FAM sanity**: Outlet cell should have maximum FAM value
5. **No-data consistency**: All three grids should use the same nodata value

```python
# Quick check
from osgeo import gdal
for f in ["DEM.tif", "DDM.tif", "FAM.tif"]:
    ds = gdal.Open(f)
    print(f"{f}: {ds.RasterXSize}x{ds.RasterYSize}, GT={ds.GetGeoTransform()}")
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| DEM in feet not meters | Slopes too large, routing crashes | Convert: `gdal_calc.py -A dem.tif --calc="A*0.3048"` |
| Wrong DDM encoding | Flow routes in wrong direction | Check ESRIDDM flag matches your DDM source |
| FAM self-inclusion mismatch | Off-by-one in basin area | Check SELFFAM flag matches your FAM tool |
| Grid misalignment | Model crashes at startup | Ensure DEM/DDM/FAM have identical extent and cellsize |
| Unresolved sinks in DEM | Disconnected drainage network | Pit-fill the DEM before generating DDM |
| Wrong projection | Gauge snapping fails | Ensure grids match PROJ setting in config |

## Example

```ini
[Basic]
DEM=/data/bengbu/DEM_90m.asc
DDM=/data/bengbu/DDM_90m.asc
FAM=/data/bengbu/FAM_90m.asc
PROJ=geographic
ESRIDDM=true
SELFFAM=true
```
