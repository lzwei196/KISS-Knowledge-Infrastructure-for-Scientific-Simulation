# Skill: Grid Setup (DEM and ROI Preparation)

## Purpose

Prepare the spatial grid data required by openAMUNDSEN: a Digital Elevation Model (DEM)
and an optional Region of Interest (ROI) mask. These must be in Arc/Info ASCII Grid format
(.asc) with specific naming conventions and projected coordinate systems.

## Inputs

| Input | Format | Source | Required |
|-------|--------|--------|----------|
| DEM raster | GeoTIFF, SRTM HGT, NetCDF | SRTM, ASTER GDEM, LiDAR | Yes |
| ROI polygon | Shapefile, GeoJSON | Catchment boundary | No |
| Target CRS | EPSG code string | User-defined | Yes |
| Domain name | String | User-defined | Yes |
| Resolution | Integer (meters) | User-defined | Yes |

## Outputs

| Output | Format | Naming Convention |
|--------|--------|-------------------|
| DEM grid | Arc/Info ASCII (.asc) | `dem_{domain}_{resolution}.asc` |
| ROI mask | Arc/Info ASCII (.asc) | `roi_{domain}_{resolution}.asc` |

## Procedure

### Step 1: Obtain DEM Data

Download DEM covering the study area with margin:
- SRTM 30m: Available globally 60°N–56°S
- ASTER GDEM v3: 30m global coverage
- National LiDAR: Higher resolution where available

### Step 2: Reproject to Target CRS

openAMUNDSEN requires a **projected** coordinate system (not geographic WGS84).
Common choices for alpine regions:

| Region | CRS | EPSG |
|--------|-----|------|
| European Alps | UTM Zone 32N | epsg:32632 |
| Scandinavian Alps | UTM Zone 33N | epsg:32633 |
| Rocky Mountains | UTM Zone 12N | epsg:32612 |
| Himalayas | UTM Zone 44N | epsg:32644 |

```bash
gdalwarp -t_srs EPSG:32632 -tr 50 50 -r bilinear input_dem.tif dem_reprojected.tif
```

### Step 3: Clip to Domain Extent

Clip the DEM to the study domain with some buffer (add 5-10 grid cells):

```bash
gdalwarp -te xmin ymin xmax ymax dem_reprojected.tif dem_clipped.tif
```

### Step 4: Convert to Arc/Info ASCII Grid

```bash
gdal_translate -of AAIGrid dem_clipped.tif dem_mydomain_50.asc
```

**CRITICAL**: The filename MUST follow the pattern `dem_{domain}_{resolution}.asc` where
`{domain}` and `{resolution}` exactly match the YAML configuration values.

### Step 5: Create ROI Mask (Optional)

If using a catchment boundary, rasterize to matching grid:

```bash
gdal_rasterize -burn 1 -init 0 -te xmin ymin xmax ymax -tr 50 50 \
  -ot Byte boundary.shp roi_mydomain_50.asc
```

ROI values: 1 = inside region, 0 = outside.

### Step 6: Place Files

```
input/grid/
├── dem_mydomain_50.asc
└── roi_mydomain_50.asc   (optional)
```

## Verification

1. Open the .asc file and check the header:
   ```
   ncols     200
   nrows     150
   xllcorner 620000.0
   yllcorner 5180000.0
   cellsize  50.0
   NODATA_value -9999
   ```
2. Verify `cellsize` matches config `resolution`
3. Verify coordinates are in the projected CRS (large numbers, not degrees)
4. Verify no large NODATA gaps in the domain interior

## Traps

| Trap | Symptom | Fix | Diagnostic |
|------|---------|-----|------------|
| DEM in geographic CRS (degrees) | Cellsize is ~0.0005 instead of 50 | Reproject to UTM | dt_009 |
| Filename mismatch | "DEM not found" error at startup | Match domain/resolution exactly | dt_009 |
| Resolution in km | Grid has 1-2 cells total | Use meters (50, not 0.05) | dt_010 |
| DEM in feet | All elevations ~3x too high | Convert to meters | dt_008 |
| No projected CRS | Coordinate transforms fail | Use EPSG projected code | — |

## Example

For a 50m resolution domain "stubai" in the Austrian Alps:

```bash
# Download SRTM
# Reproject to UTM 32N
gdalwarp -t_srs EPSG:32632 -tr 50 50 -r bilinear srtm_tile.tif dem_tmp.tif
# Clip to domain
gdalwarp -te 680000 5210000 695000 5225000 dem_tmp.tif dem_clipped.tif
# Convert
gdal_translate -of AAIGrid dem_clipped.tif input/grid/dem_stubai_50.asc
```

Config must then specify:
```yaml
domain: stubai
resolution: 50
crs: "epsg:32632"
```
