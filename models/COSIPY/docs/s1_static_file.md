# Stage 1: Static File Creation

## Purpose

Create the COSIPY static file (`static.nc`) containing elevation (DEM), terrain slope, aspect, and glacier mask on a regular lat/lon grid. This file defines the model domain and is required for distributed simulations.

## Inputs

| Input | Source | Format |
|-------|--------|--------|
| DEM (Digital Elevation Model) | SRTM / ASTER / TanDEM-X | GeoTIFF (.tif) |
| Glacier outline | RGI / manual digitization | Shapefile (.shp) |
| Domain extent | User specification | Lat/lon bounds |
| Grid resolution | User choice | Degrees |

## Outputs

| Output | Path | Format |
|--------|------|--------|
| `static.nc` | `data/static/` | netCDF |

### Static file variables

| Variable | Dimensions | Units | Description |
|----------|-----------|-------|-------------|
| `HGT` | (lat, lon) | m | Elevation |
| `SLOPE` | (lat, lon) | degrees | Terrain slope angle |
| `ASPECT` | (lat, lon) | degrees | Slope aspect (0=North) |
| `MASK` | (lat, lon) | 0/1 | Glacier mask |

## Procedure

### Using built-in utility

```bash
# Configure in utilities_config.toml [create_static] section
cosipy-create-static -u utilities_config.toml
```

### Using KI tool

```bash
python ki/tools/convert_static.py \
    --dem data/static/DEM/n30_e090_3arc_v2.tif \
    --shapefile data/static/Shapefiles/Zhadang_RGI6.shp \
    --output data/static/Zhadang_static.nc \
    --lon-min 90.62 --lon-max 90.66 \
    --lat-min 30.46 --lat-max 30.48 \
    --resolution 0.003
```

### Key configuration (utilities_config.toml)

```toml
[create_static.paths]
static_folder = "./data/static/"
dem_path = "DEM/n30_e090_3arc_v2.tif"
shape_path = "Shapefiles/Zhadang_RGI6.shp"
output_file = "Zhadang_static.nc"

[create_static.coords]
tile = true
aggregate = true
aggregate_degree = 0.003
longitude_upper_left = 90.62
latitude_upper_left = 30.48
longitude_lower_right = 90.66
latitude_lower_right = 30.46
```

## Verification

```bash
# Check static file contents
python -c "
import xarray as xr
ds = xr.open_dataset('data/static/Zhadang_static.nc')
print('Dimensions:', dict(ds.dims))
print('Variables:', list(ds.data_vars))
print('HGT range:', float(ds.HGT.min()), 'to', float(ds.HGT.max()), 'm')
print('Glacier cells:', int(ds.MASK.sum()))
print('Total cells:', ds.MASK.size)
ds.close()
"
```

## Traps

1. **MASK all zeros**: If the shapefile extent does not overlap with the DEM extent or coordinate bounds, all MASK values will be 0. The model will skip all grid cells and produce empty output without any error message.

2. **DEM nodata values**: Some DEM tiles use -9999 or -32768 for nodata. These must be replaced with NaN before computing slope/aspect, otherwise the gradient calculation produces extreme slopes at tile boundaries.

3. **Coordinate system mismatch**: The DEM and shapefile must be in the same coordinate reference system (typically WGS84, EPSG:4326). If the shapefile uses a projected CRS (UTM), it must be reprojected first.

4. **Resolution too coarse**: If `aggregate_degree` is too large relative to the glacier size, the glacier may fit entirely within one grid cell, losing all spatial detail. For small glaciers (< 1 km2), use resolution <= 0.001 degrees.

5. **GDAL/richdem dependency**: The `create_static_file` utility requires GDAL and richdem (Python < 3.11). Install with: `pip install gdal==\`gdal-config --version\` richdem`.

## Example

For Zhadang Glacier (Tibet, 30.47N, 90.64E):
- DEM: SRTM 3-arc-second (~90m resolution)
- Shapefile: RGI v6.0 glacier outline
- Output grid: 7 x 13 cells at 0.003 degree resolution (~330m)
- Glacier cells: ~15 out of 91 total
