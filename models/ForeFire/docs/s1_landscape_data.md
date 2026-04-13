# Stage 1: Landscape Data Preparation

## Purpose

Convert geospatial raster data (elevation, fuel type, wind field) into the ForeFire NetCDF input format (`data.nc`). This stage bridges GIS data sources with ForeFire's internal grid representation.

## Inputs

| Input | Format | Source | Units |
|-------|--------|--------|-------|
| Digital Elevation Model | GeoTIFF | SRTM, Copernicus DEM, LiDAR | meters |
| Fuel type map | GeoTIFF (integer) | CORINE, NLCD, Prometheus, custom | fuel index (0-N) |
| Wind field (optional) | NetCDF or constant | ERA5, WRF, manual | m/s |
| Domain timestamp | ISO 8601 string | User-specified | UTC |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `data.nc` | NetCDF4 | Gridded landscape data with variables: altitude, fuel, windU, windV |

### NetCDF Structure

```
dimensions:
  DIMX = <ncols>
  DIMY = <nrows>
  DIMZ = 1
  DIMT = 2  (two time steps for interpolation)

variables:
  XHAT(DIMX)      — UTM easting coordinates (m)
  YHAT(DIMY)      — UTM northing coordinates (m)
  altitude(DIMT, DIMZ, DIMY, DIMX) — elevation (m)
  fuel(DIMT, DIMZ, DIMY, DIMX)     — fuel type index
  windU(DIMT, DIMZ, DIMY, DIMX)    — eastward wind (m/s)
  windV(DIMT, DIMZ, DIMY, DIMX)    — northward wind (m/s)
```

## Procedure

1. **Load DEM**: Read elevation GeoTIFF. Verify units are meters (not feet).
2. **Load fuel map**: Read fuel classification raster. Ensure integer indices matching fuels.csv.
3. **Reproject to UTM**: Both rasters must be in UTM projection (meters). ForeFire does not work in lon/lat.
4. **Align grids**: Resample fuel map to match DEM resolution if they differ.
5. **Prepare wind**: Either load from NetCDF wind field or set uniform U/V components.
6. **Write NetCDF**: Create data.nc with XHAT/YHAT coordinate variables and 4D data arrays.
7. **Validate**: Check altitude range, fuel index range, wind magnitude.

## Verification

- `altitude` min/max should be physically reasonable (0-9000m)
- `fuel` values should be non-negative integers within fuels.csv range
- `windU`/`windV` magnitudes should be < 80 m/s
- No NaN values in any variable
- `XHAT`/`YHAT` should be monotonically increasing
- The `FireDomain[sw=(...);ne=(...)]` command in the .ff script must match the data.nc extent

## Traps

### Trap 1: Coordinates in lon/lat instead of UTM
**Symptom**: Fire starts but doesn't spread, or domain is microscopic.
**Cause**: DEM/fuel in geographic coordinates (degrees) instead of projected (meters).
**Fix**: Reproject to UTM before creating data.nc. Use `gdalwarp -t_srs EPSG:326XX`.

### Trap 2: Git LFS pointer instead of actual data
**Symptom**: `NetCDF: Unknown file format` error when loading data.nc.
**Cause**: The data.nc is a Git LFS pointer file (small text file) rather than actual binary.
**Fix**: Run `git lfs pull` or download data files manually from GitHub.

### Trap 3: Wind units not in m/s
**Symptom**: Fire spreads much too fast or too slow compared to expectations.
**Cause**: Wind provided in km/h, mph, or knots without conversion.
**Fix**: Convert: km/h ÷ 3.6, mph × 0.44704, knots × 0.5144 to get m/s.

### Trap 4: Fuel index mismatch
**Symptom**: Fire doesn't spread in areas that should burn, or crashes.
**Cause**: Fuel map indices don't match rows in fuels.csv.
**Fix**: Ensure fuel raster values are 0..N where N is the last row index in fuels.csv.

## Example

```bash
python tools/convert_landscape_to_nc.py \
    --dem_tif corsica_srtm.tif \
    --fuel_tif corsica_corine_fuel.tif \
    --wind_u 10.0 --wind_v 5.0 \
    --timestamp 2025-02-10T17:35:54Z \
    --output data.nc
```

Then in the .ff script:
```
loadData[data.nc;2025-02-10T17:35:54Z]
```

The timestamp in `loadData` must match the timestamp used when creating data.nc.
