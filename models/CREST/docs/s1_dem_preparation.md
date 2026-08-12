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

### Recommended (KDT 5.1.2): use the KI's `prepare_basic_grids` tool

The Stage-1 tool wraps WhiteboxTools and produces EF5-compatible
DEM/DDM/FAM in one command:

```bash
python tools/prepare_basic_grids.py \
    --dem raw_dem.tif \
    --out-dir basin/grids/ \
    --bbox 82.0 27.8 95.3 31.5 \
    --method breach \
    --out-format asc \
    --expected-outlet 94.583 29.466
```

The tool:
1. Clips the DEM to `--bbox` (optional)
2. Fills sinks via `BreachDepressionsLeastCost` (preferred — preserves more
   terrain than fill; falls back to `FillDepressions` with `--method fill`)
3. Computes D8 drainage direction with **ESRI encoding** (EF5 expects this)
4. Computes D8 flow accumulation as **cell count, self-inclusive**
   (EF5 `SELFFAM=true` convention)
5. Writes ASC by default (EF5's TIF reader has known bugs with
   rasterio-generated GeoTIFFs — see known_issues in `format_spec.yaml`)
6. Verifies the output and writes a diagnostic JSON. Fails loudly if:
   - DEM/DDM/FAM grids don't share extent/transform/CRS
   - DDM contains non-ESRI values (anything outside {0, 1, 2, 4, 8, 16, 32, 64, 128})
   - More than 1% of valid cells are unfilled sinks (DDM=0)
   - The expected-outlet check shows FAM=1 (gauge isolated)

If `--expected-outlet` is supplied, the tool reports FAM at that cell and
its 3×3 max — so you can confirm the upstream basin connects to the gauge
before running EF5.

#### Why a custom tool (and not `ef5 -p`)

The EF5 v1.2.3 binary's argument parser accepts a `-p` flag (mode=1) that
SKILL.md historically advertised as a fallback DEM processor. That flag is
**not implemented in this build of EF5** — `ProcessDEM(mode=1)` falls
through and exits silently with no output (verified at
`source/repo/src/DEMProcessor.cpp`). The only working EF5 mode is `-s`
(mode=2), which recomputes FAM from a *pre-existing* DDM:

```bash
# Recompute FAM from a known-good DDM (rare; only useful for re-prepping)
ef5 -z dem.tif -d ddm.tif -a fam.tif -s
```

Do not use `ef5 -p`. Use `prepare_basic_grids.py`.

### Alternative: external D8 tools

If WhiteboxTools is unavailable, you can produce the same outputs with
TauDEM or ArcGIS Hydrology — but you must enforce the same conventions:

```bash
# TauDEM workflow (then set ESRIDDM=false in control.txt — TauDEM uses 1-8 codes!)
pitremove dem.tif -z dem_filled.tif
d8flowdir -p ddm.tif -sd8 slope.tif -fel dem_filled.tif
aread8 -p ddm.tif -ad8 fam.tif      # WARNING: this is 0-based; add +1 for SELFFAM=true
```

Critical conventions (whichever tool you use):
- ESRI encoding for DDM (1, 2, 4, 8, 16, 32, 64, 128) — set `ESRIDDM=true` in control.txt
- Self-inclusive FAM (minimum value = 1) — set `SELFFAM=true` in control.txt
- Nodata = -9999 in all three grids
- All three grids on identical extent, cellsize, and CRS

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
