# S0 — Domain Setup and DEM Preparation

## Purpose

Prepare the spatial domain for an Alpine3D simulation: create or obtain the DEM
(Digital Elevation Model) and land-use grids in ARC ASCII format, define the
coordinate system, and set up the directory structure.

## Inputs

| Item | Format | Source | Required |
|------|--------|--------|----------|
| DEM raster | GeoTIFF, NetCDF, or ARC ASCII | SRTM, ASTER, SwissALTI3D, national surveys | Yes |
| Land-use map | GeoTIFF, NetCDF, or ARC ASCII | CORINE, national landcover, custom | Yes |
| Coordinate system | EPSG code or MeteoIO name | Project definition | Yes |
| Target resolution | meters | User choice | Yes |

## Outputs

| File | Format | Path |
|------|--------|------|
| DEM grid | ARC ASCII (.asc/.dem) | `input/surface-grids/{name}.dem` |
| Land-use grid | ARC ASCII (.asc/.lus) | `input/surface-grids/{name}.lus` |
| POI file | SMET | `input/surface-grids/{name}.poi` |

## Procedure

### 1. Create Directory Structure

```bash
mkdir -p ${SIM_DIR}/{input/{meteo,surface-grids,snowfiles},output/{grids,snowfiles},setup}
```

### 2. Prepare DEM

Alpine3D requires an ARC ASCII grid. If starting from GeoTIFF:

```bash
# Using GDAL to convert and reproject
gdal_translate -of AAIGrid -a_srs EPSG:21781 input.tif output.dem
# Or resample to desired resolution
gdalwarp -tr 25 25 -r bilinear -of AAIGrid input.tif output.dem
```

**ARC ASCII format:**
```
ncols         100
nrows         80
xllcorner     782000
yllcorner     180000
cellsize      25
NODATA_value  -9999
1500 1502 1510 ...
```

### 3. Prepare Land-Use Grid

The land-use grid must have **identical** header values (ncols, nrows, xllcorner,
yllcorner, cellsize) as the DEM. Values encode surface type.

Common land-use codes used by Alpine3D:
- 0: Water
- 1–99: Vegetation types
- 100+: Rock/ice/glacier

### 4. Create POI File

Points of Interest receive full snow profile output (time-consuming). Place POIs
at locations where you have validation data:

```
SMET 1.1 ASCII
[HEADER]
fields = easting northing altitude
[DATA]
785360  182255  2520
786100  181900  2350
```

### 5. Configure Coordinate System

Set `COORDSYS` in io.ini [Input] and [Output] sections to match the DEM:

| DEM Coordinates | COORDSYS Value |
|----------------|----------------|
| Swiss CH1903 (LV03) | CH1903 |
| Swiss CH1903+ (LV95) | CH1903+ |
| UTM zone 32N | UTM32N |
| WGS84 lat/lon | LATLON |

## Verification

```bash
# Check DEM and land-use grid headers match
head -6 input/surface-grids/*.dem
head -6 input/surface-grids/*.lus
# Headers must be identical for ncols, nrows, xllcorner, yllcorner, cellsize

# Check for reasonable elevation range
awk 'NR>6 {for(i=1;i<=NF;i++) if($i!=-9999){if($i<min||NR==7&&i==1)min=$i; if($i>max)max=$i}} END{print "Elevation range:", min, "to", max, "m"}' input/surface-grids/*.dem

# Verify POI coordinates are within DEM extent
python3 -c "
with open('input/surface-grids/dischma.dem') as f:
    h = {}
    for _ in range(6):
        k, v = f.readline().split()
        h[k.lower()] = float(v)
    print(f'DEM extent: x=[{h[\"xllcorner\"]}, {h[\"xllcorner\"]+h[\"ncols\"]*h[\"cellsize\"]}]')
    print(f'            y=[{h[\"yllcorner\"]}, {h[\"yllcorner\"]+h[\"nrows\"]*h[\"cellsize\"]}]')
"
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| DEM/LUS header mismatch (dt_017) | Segfault at startup | Regenerate LUS from DEM extent |
| COORDSYS mismatch (dt_018) | Silent wrong interpolation | Verify coordinate ranges |
| NODATA in DEM | Pixels with -9999 altitude | Fill or mask NODATA pixels |
| Resolution too fine | Excessive runtime | Start with 100m, refine later |
| Mixed coordinate units | Wrong station placement | Use consistent CRS everywhere |

## Example

```bash
# Setup for Dischma catchment (Swiss Alps)
cd ~/sim/Dischma

# Convert SRTM DEM to Swiss coordinates at 25m resolution
gdalwarp -t_srs EPSG:21781 -tr 25 25 -of AAIGrid srtm_n46e009.tif input/surface-grids/dischma.dem

# Create matching land-use grid
gdal_translate -of AAIGrid -projwin 782000 185000 785000 180000 corine.tif input/surface-grids/dischma.lus

# Verify headers match
diff <(head -5 input/surface-grids/dischma.dem) <(head -5 input/surface-grids/dischma.lus)
```
