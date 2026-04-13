# Stage 1: DEM Preparation

## Purpose

Prepare a Digital Elevation Model (DEM) in ESRI ASCII Grid format (.asc) suitable for HAIL-CAESAR simulation. The DEM defines the terrain surface, grid resolution, and model domain extents.

## Inputs

| Input | Format | Units | Source |
|-------|--------|-------|--------|
| Raw DEM | GeoTIFF, ASCII, or other raster | metres (elevation) | SRTM, ASTER, LiDAR, national surveys |
| Catchment boundary | Shapefile/GeoJSON (optional) | - | HydroSHEDS, manual delineation |

## Outputs

| Output | Format | Units | Description |
|--------|--------|-------|-------------|
| Clipped DEM | `.asc` (ESRI ASCII Grid) | metres | Catchment DEM with outlet at edge |

## Procedure

### Step 1: Obtain DEM data

Download or extract DEM covering the catchment of interest. Resolution determines model speed and accuracy:
- **50m**: Fast, suitable for large catchments (>100 km2)
- **10m**: Moderate, suitable for medium catchments
- **5m or finer**: Slow, required for detailed flood inundation

### Step 2: Reproject to local coordinate system

HAIL-CAESAR requires the DEM cellsize in **metres**. If the DEM is in geographic coordinates (WGS84, degrees), reproject to a local projected CRS (e.g., UTM).

```python
# Using GDAL
gdalwarp -t_srs EPSG:32650 -tr 50 50 -r bilinear input.tif reprojected.tif
```

### Step 3: Clip to catchment extent

Clip the DEM to the catchment boundary plus a small buffer. The DEM should be rectangular.

```python
gdalwarp -cutline catchment.shp -crop_to_cutline reprojected.tif clipped.tif
```

### Step 4: Ensure outlet touches DEM edge

**This is the most critical requirement.** Water must be able to exit the model domain through cells at the DEM edge. There must be no NODATA values between the catchment outlet and the DEM boundary.

Options:
- Rotate the DEM so the outlet is on the bottom/left/right edge
- Extend the channel from the outlet to the nearest edge
- Pad the DEM with a narrow strip of low-elevation cells leading to the edge

### Step 5: Convert to ASCII format

```bash
gdal_translate -of AAIGrid -a_nodata -9999 clipped.tif output_dem.asc
```

### Step 6: Verify header format

The ASCII file must have this exact header format:
```
ncols        120
nrows        60
xllcorner    209000.000000
yllcorner    89000.000000
cellsize     50.000000
NODATA_value -9999
```

Followed by space-delimited elevation values (one row per line).

## Verification

1. Open in QGIS and visually check:
   - Outlet is at the edge of the DEM
   - No internal sinks that would trap water unrealistically
   - NODATA pattern is correct (outside catchment = NODATA, inside = real elevations)
2. Check that the lowest elevation point is near the edge (outlet)
3. Verify cellsize is in metres, not degrees
4. Verify NODATA_value matches what HAIL-CAESAR expects (-9999)

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| DEM in degrees (WGS84) | Model crashes or gives huge cellsize warnings | Reproject to UTM |
| Outlet not at edge | Water pools, catchment floods completely | Extend channel to edge or rotate DEM |
| Wrong NODATA value | Model reads NODATA as real elevation (-9999m) | Set NODATA_value to -9999 in header |
| Elevation in feet/cm | All values incorrect, erosion/flow wrong | Convert to metres |
| Extra header lines | Model fails to read DEM | Ensure exactly 6 header lines |
| Windows line endings | Parser may fail on some systems | Convert to Unix line endings (`dos2unix`) |

## Example

Boscastle catchment (50m resolution):
```
ncols        120
nrows        60
xllcorner    209000.000000000000
yllcorner    89000.000000000000
cellsize     50.000000000000
NODATA_value -9999
 0 0 0 0 ... 40 53 53 56 58 69 85 101 108 ...
```

- 120 x 60 cells = 7,200 grid cells (6km x 3km domain)
- Elevation range: 0-212m
- Outlet: left side of DEM (cells with value 0 connecting to edge)
