# Stage 0: Configuration — Skill Document

## Purpose

Prepare the HexWatershed JSON configuration file and basin definitions.
This stage produces the two primary input files that control all model behavior:
the main configuration JSON and the optional basin configuration JSON.

## Inputs

| Input                    | Source                | Format      | Unit/Notes                     |
|-------------------------|-----------------------|-------------|--------------------------------|
| Study area extent       | User-defined          | Lat/lon box | Decimal degrees (GCS)          |
| Mesh type selection     | User decision         | String      | hexagon, square, latlon, mpas, dggrid, tin |
| Mesh resolution         | User decision         | meters      | Edge length of hex cells       |
| DEM path                | Preprocessed raster   | GeoTIFF     | EPSG:4326, meters elevation    |
| Outlet coordinates      | User-defined          | lat/lon     | Decimal degrees                |
| Flowline data (optional)| NHDPlus / HydroSHEDS  | Shapefile   | GCS coordinates                |

## Outputs

| Output                              | Format | Description                             |
|-------------------------------------|--------|-----------------------------------------|
| `hexwatershed_config.json`          | JSON   | Main configuration with all parameters  |
| `basins.json` (if stream burning)   | JSON   | Basin definitions with outlet + flowline paths |

## Procedure

1. **Select mesh type** based on domain:
   - Regional watershed: `hexagon` (eliminates directional bias)
   - Global simulation: `mpas` or `dggrid`
   - Comparison study: `square` (for D8 benchmarking)

2. **Set workspace paths** — all paths MUST be absolute:
   ```json
   {
     "sWorkspace_input": "/absolute/path/to/mesh",
     "sWorkspace_output": "/absolute/path/to/output",
     "sWorkspace_output_hexwatershed": "/absolute/path/to/output/hexwatershed"
   }
   ```

3. **Set stream definition method**:
   - `iFlag_stream_grid_option = 1`: Use burned-in streams (requires flowlines)
   - `iFlag_stream_grid_option = 2`: Use accumulation threshold (no flowlines needed)

4. **Set accumulation threshold** carefully:
   - Value < 1.0 → treated as **ratio** of maximum accumulation (e.g., 0.01 = top 1%)
   - Value ≥ 1.0 → treated as **absolute cell count**
   - Typical regional: 0.01 – 0.05
   - Typical global: 0.001 – 0.01

5. **Set missing value** to match DEM nodata exactly:
   ```json
   {"dMissing_value_dem": -9999.0}
   ```

6. **Configure optional features**:
   - `iFlag_hillslope = 1` for hillslope decomposition
   - `iFlag_vtk = 1` for 3D visualization
   - `iFlag_elevation_profile = 1` for elevation profiles

7. **If using stream burning** (`iFlag_flowline = 1`):
   - Create `basins.json` with outlet cell IDs matching actual mesh cells
   - Set `dBreach_threshold` (meters) to allow stream crossing corrections
   - Provide flowline file paths in basin config

## Verification

```bash
# Validate JSON syntax
python3 -c "import json; json.load(open('hexwatershed_config.json'))"

# Check all paths exist
python3 -c "
import json, os
cfg = json.load(open('hexwatershed_config.json'))
for key in ['sWorkspace_input', 'sWorkspace_output']:
    path = cfg.get(key, '')
    print(f'{key}: {path} -> {\"EXISTS\" if os.path.exists(path) else \"MISSING\"}')"

# Validate missing value matches DEM
# (requires GDAL)
python3 -c "
from osgeo import gdal
ds = gdal.Open('/path/to/dem.tif')
print('DEM nodata:', ds.GetRasterBand(1).GetNoDataValue())"
```

## Traps

### TRAP: Accumulation threshold dual interpretation (dt_007)
A threshold of 100 means "100 cells" (absolute), while 0.01 means "top 1%" (ratio).
Accidentally swapping these produces either zero streams or every-cell-is-a-stream.
**Always verify** which interpretation applies by checking if value < 1.0.

### TRAP: Missing value mismatch (dt_014)
If `dMissing_value_dem` is -9999.0 but DEM nodata is -3.4e38 (float min), valid cells
near nodata will be silently excluded. Always check: `gdalinfo dem.tif | grep NoData`.

### TRAP: Relative vs absolute paths
All `sWorkspace_*` and `sFilename_*` values must be absolute paths. Relative paths
cause "file not found" errors at runtime with unhelpful messages.

### TRAP: Wrong outlet cell ID (dt_008)
`lCellID_outlet` must exactly match a cell in the mesh JSON. If no cell has that ID,
the entire watershed is silently skipped with no error message. Use the flowline_converter
tool with `--mesh-json` to auto-detect the nearest cell.

## Example

```json
{
  "sMesh_type": "hexagon",
  "iFlag_global": 0,
  "iFlag_flowline": 0,
  "iFlag_multiple_outlet": 0,
  "iFlag_stream_grid_option": 2,
  "iFlag_hillslope": 1,
  "iFlag_vtk": 0,
  "iFlag_debug": 0,
  "nOutlet": 1,
  "iCase_index": 1,
  "dMissing_value_dem": -9999.0,
  "dAccumulation_threshold": 0.01,
  "dBreach_threshold": 0.0,
  "sWorkspace_input": "/data/hexwatershed/mesh",
  "sWorkspace_output": "/data/hexwatershed/output",
  "sWorkspace_output_hexwatershed": "/data/hexwatershed/output/hexwatershed",
  "sDate": "2026-03-26"
}
```
