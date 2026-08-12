# Stage 1: Basic Grid Preparation

## Purpose

Prepare the three foundational geospatial grids that EF5 requires: Digital Elevation Model (DEM), Drainage Direction Map (DDM), and Flow Accumulation Map (FAM). These grids define the terrain, flow routing network, and upstream contributing area for every cell in the modeling domain.

## Inputs

| Input | Format | Units | Source |
|-------|--------|-------|--------|
| Raw DEM | GeoTIFF or ESRI ASCII | meters | SRTM 90m, HydroSHEDS, MERIT DEM, local survey |
| Basin boundary | Shapefile (optional) | — | HydroBASINS, manual delineation |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `DEM.asc` or `DEM.tif` | ESRI ASCII / float32 GeoTIFF | Elevation in meters |
| `DDM.asc` or `DDM.tif` | ESRI ASCII / float32 GeoTIFF | Drainage direction codes (ESRI or TauDEM) |
| `FAM.asc` or `FAM.tif` | ESRI ASCII / float32 GeoTIFF | Flow accumulation (cell count) |

## Procedure

### Option A (Recommended, KDT 5.1.2): KI's `prepare_basic_grids` tool

```bash
python tools/prepare_basic_grids.py \
    --dem raw_DEM.tif \
    --out-dir basin/grids/ \
    --bbox 113.0 31.5 117.5 33.5 \
    --method breach \
    --out-format asc \
    --expected-outlet 117.35 33.05
```

The tool runs WhiteboxTools `BreachDepressionsLeastCost` → `D8Pointer (ESRI)` →
`D8FlowAccumulation (cells, +1 for SELFFAM=true)`, writes ASC outputs (EF5's
TIF reader has known bugs with rasterio-generated GeoTIFFs), and verifies:
- DDM unique values are subset of {0, 1, 2, 4, 8, 16, 32, 64, 128}
- DDM sinks < 1% of basin
- DEM/DDM/FAM share extent, transform, CRS
- FAM at expected outlet is non-trivial (not 1)

If `--expected-outlet` is supplied, the tool reports FAM at that cell (and
its 3×3 max), so you can confirm the upstream basin connects to the gauge
**before running EF5**.

### Option B: HydroSHEDS pre-processed grids

1. Download HydroSHEDS DEM, flow direction, and flow accumulation at desired resolution
2. Clip to basin extent
3. **Verify** flow direction is ESRI 8-direction encoding (1, 2, 4, 8, 16, 32, 64, 128)
   — HydroSHEDS uses ESRI by default, but always check: `gdalinfo -mm flow_dir.tif`
4. Write as ASC. Confirm SELFFAM convention matches your `[Basic]` setting.

### Option C: External D8 tools (TauDEM / ArcGIS / QGIS)

1. Fill sinks in DEM (do NOT skip — unfilled sinks are the #1 cause of
   "Walked N out of M" routing failures)
2. Compute flow direction (D8 algorithm) → export as ESRI grid (NOT TauDEM 1-8!)
3. Compute flow accumulation → export as ESRI grid; **add +1 if SELFFAM=true**
4. Verify direction encoding matches `ESRIDDM` setting in control.txt

### `ef5 -p` is not a working option in v1.2.3

EF5 v1.2.3's argument parser accepts `-p` (process DEM from scratch), and prior
versions of this KI documented it as a fallback. **`-p` is not implemented in
this build** — `src/DEMProcessor.cpp:23` only handles mode=2 (`-s`, FAM from
existing DDM). Mode=1 falls through silently with no output.

```bash
# This DOES work (recompute FAM from a known-good DDM):
ef5 -z DEM.tif -d DDM.tif -a FAM.tif -s

# This does NOT (silently exits with no output):
# ef5 -z DEM.tif -d DDM.tif -a FAM.tif -p
```

### Configuration in control.txt

```ini
[Basic]
DEM=/path/to/DEM.asc
DDM=/path/to/DDM.asc
FAM=/path/to/FAM.asc
PROJ=geographic          # or laea
ESRIDDM=true             # true for ESRI encoding, false for TauDEM
SELFFAM=true             # true if FAM includes current cell (min value=1)
```

## Verification

1. **Grid dimensions match**: DEM, DDM, and FAM must have identical ncols, nrows, cellsize, xllcorner, yllcorner
2. **DEM values reasonable**: Elevation should match expected terrain (e.g., 0-5000m for most basins)
3. **DDM values valid**: All values must be valid direction codes (1,2,4,8,16,32,64,128 for ESRI; 1-8 for TauDEM)
4. **FAM monotonically increasing**: The outlet cell should have the highest FAM value
5. **Outlet cell exists**: FAM maximum should correspond to the basin outlet
6. **No flat areas**: DDM should have no undefined (0 or nodata) cells within the basin

```python
# Quick validation
import numpy as np
dem = np.loadtxt("DEM.asc", skiprows=6)
ddm = np.loadtxt("DDM.asc", skiprows=6)
fam = np.loadtxt("FAM.asc", skiprows=6)

# Check ESRI direction codes
valid_dirs = {1, 2, 4, 8, 16, 32, 64, 128}
ddm_valid = ddm[ddm > 0]
invalid = set(ddm_valid.astype(int)) - valid_dirs
assert len(invalid) == 0, f"Invalid DDM codes: {invalid}"

# Check FAM max at expected outlet
outlet_idx = np.unravel_index(np.argmax(fam), fam.shape)
print(f"Outlet at row={outlet_idx[0]}, col={outlet_idx[1]}, FAM={fam[outlet_idx]:.0f}")
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| DEM in feet instead of meters | Routing speeds wildly wrong, slopes too steep or flat | Convert: `DEM_m = DEM_ft * 0.3048` |
| Wrong DDM encoding (ESRI vs TauDEM) | Water flows in wrong direction, disconnected network | Toggle `ESRIDDM=true/false` |
| SELFFAM mismatch | Gauge snaps to wrong cell (off by one in contributing area) | Toggle `SELFFAM=true/false` |
| Grids not aligned | EF5 crash or silent spatial mismatch | Re-derive all three from same DEM |
| GeoTIFF not float32 | Read error or truncated values | Convert: `gdal_translate -ot Float32` |
| Projection mismatch | Area/distance calculations wrong | Ensure all grids in same CRS as PROJ setting |

## Example

```bash
# Using MERIT DEM for a basin in China
# 1. Clip MERIT DEM to bounding box
gdalwarp -te 116.5 32.0 118.5 34.0 merit_dem.tif DEM_clip.tif

# 2. Generate DDM and FAM with EF5
ef5 -z DEM_clip.tif -d DDM.tif -a FAM.tif -p

# 3. Verify
gdalinfo DEM_clip.tif | grep "Size is"
gdalinfo DDM.tif | grep "Size is"
gdalinfo FAM.tif | grep "Size is"
```
