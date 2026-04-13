# Stage 2: Flowline Preparation — Skill Document

## Purpose

Convert raw stream network data (NHDPlus, HydroSHEDS, or custom flowlines) into the
basin configuration JSON format required by HexWatershed for stream burning. This stage
is ONLY required when `iFlag_flowline = 1` (stream burning enabled).

Stream burning forces flow directions along known channels, preventing the model from
routing flow across ridges due to DEM errors or mesh resolution limitations.

## Inputs

| Input                  | Source              | Format      | Unit/Notes                        |
|-----------------------|---------------------|-------------|-----------------------------------|
| Flowline network      | NHDPlus / HydroSHEDS| Shapefile or GeoJSON | GCS degrees (EPSG:4326) |
| Outlet coordinates    | User-defined        | lat/lon     | Decimal degrees                   |
| Mesh JSON             | Stage 1 output      | JSON        | For outlet cell ID lookup         |
| Accumulation threshold| User decision       | float       | Ratio (0–1) or cell count (≥1)   |

## Outputs

| Output          | Format | Description                                        |
|----------------|--------|----------------------------------------------------|
| `basins.json`  | JSON   | Basin definitions with outlet + flowline references |

### Output JSON Structure

```json
[
  {
    "lBasinID": 1,
    "lCellID_outlet": 42567,
    "dLatitude_outlet_degree": 39.52,
    "dLongitude_outlet_degree": -76.18,
    "dAccumulation_threshold_ratio": 0.01,
    "dThreshold_small_river": 0.0,
    "iFlag_dam": 0,
    "iFlag_disconnected": 0,
    "sFilename_flowline_raw": "/data/flowlines/nhd_raw.shp",
    "sFilename_flowline_filter": "/data/flowlines/nhd_filtered.shp",
    "sFilename_flowline_topo": "/data/flowlines/nhd_topo.shp"
  }
]
```

## Procedure

1. **Obtain flowline data** in GCS:
   ```bash
   # Download NHDPlus flowlines for HUC
   # Or use HydroSHEDS for global coverage
   # CRITICAL: Must be in EPSG:4326
   ogr2ogr -t_srs EPSG:4326 flowlines_gcs.shp flowlines_utm.shp
   ```

2. **Preprocess with PyFlowline** (recommended):
   PyFlowline handles the complex topology extraction, flowline simplification,
   and cell-to-stream mapping that HexWatershed requires.
   ```python
   from pyflowline.flowline import pyflowline_prepare
   pyflowline_prepare(
       sFilename_flowline='/data/nhd.shp',
       sFilename_mesh='/data/mesh/hexagon_mesh_info.json',
       sOutput='/data/flowlines/'
   )
   ```

3. **Identify outlet cell**:
   The `lCellID_outlet` must correspond to an actual cell in the mesh. Use the
   flowline_converter tool:
   ```bash
   python flowline_converter.py \
       --flowline /data/nhd.shp \
       --outlet-lat 39.52 --outlet-lon -76.18 \
       --mesh-json /data/mesh/hexagon_mesh_info.json \
       --output /data/basins.json
   ```

4. **Set breach threshold**:
   - `dBreach_threshold = 0.0`: No breaching (flow follows strict elevation)
   - `dBreach_threshold = 0.1`: Allow 0.1m jumps at crossings (recommended)
   - Higher values accommodate road crossings and mesh artifacts

5. **Validate basin config** references valid mesh cells and existing files.

## Verification

```bash
# Check basin JSON is valid
python3 -c "
import json
basins = json.load(open('basins.json'))
for b in basins:
    print(f'Basin {b[\"lBasinID\"]}: outlet cell {b[\"lCellID_outlet\"]}')
    print(f'  Lat/Lon: {b[\"dLatitude_outlet_degree\"]}, {b[\"dLongitude_outlet_degree\"]}')
"

# Verify outlet cell exists in mesh
python3 -c "
import json
mesh = json.load(open('hexagon_mesh_info.json'))
basins = json.load(open('basins.json'))
cell_ids = {c['lCellID'] for c in mesh['aCells']}
for b in basins:
    oid = b['lCellID_outlet']
    print(f'Basin {b[\"lBasinID\"]}: outlet {oid} -> {\"FOUND\" if oid in cell_ids else \"MISSING\"}')"

# Verify flowline files exist
python3 -c "
import json, os
basins = json.load(open('basins.json'))
for b in basins:
    for key in ['sFilename_flowline_raw', 'sFilename_flowline_filter', 'sFilename_flowline_topo']:
        path = b.get(key, '')
        if path:
            print(f'{key}: {\"EXISTS\" if os.path.isfile(path) else \"MISSING\"}')"
```

## Traps

### TRAP: Flowline in projected CRS (dt_015)
If flowline coordinates are in UTM (e.g., x=500000, y=4000000), they will NOT
intersect any mesh cells (which are in degrees). Stream burning will silently produce
NO effect — the model runs but flow directions ignore the streams entirely.
**Always check**: `ogrinfo flowlines.shp -al -so | grep AUTHORITY`

### TRAP: Wrong outlet cell ID (dt_008)
If `lCellID_outlet` does not match any cell in the mesh JSON, the entire watershed
is silently skipped. The model produces no error message. **Always verify** the cell
ID exists in the mesh before running.

### TRAP: Stream burning without PyFlowline preprocessing (dt_004)
HexWatershed expects topologically ordered flowlines with cell-to-stream mapping.
Raw NHDPlus shapefiles lack this mapping. If you provide raw shapefiles directly,
stream burning may fail silently or produce incorrect flow directions.

### TRAP: Breach threshold = 0 (dt_017)
With `dBreach_threshold = 0.0`, the breaching algorithm is effectively disabled.
This means artificial dams at road crossings or mesh artifacts will block flow,
creating disconnected stream segments. A value of 0.05–0.1 m is recommended.

## Example

```bash
# Convert NHDPlus flowlines for Susquehanna Basin
python flowline_converter.py \
    --flowline /data/NHDPlus/NHDFlowline_02050306.shp \
    --outlet-lat 39.52 --outlet-lon -76.18 \
    --basin-id 1 \
    --mesh-json /data/mesh/hexagon_mesh_info.json \
    --threshold-ratio 0.01 \
    --output /data/basins.json

# Verify
cat /data/basins.json | python3 -m json.tool
```
