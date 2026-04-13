# Stage 1: Mesh Generation — Skill Document

## Purpose

Generate the hexagonal (or other polygonal) mesh with DEM-derived elevation values
in the JSON format consumed by HexWatershed. This stage bridges raw geospatial data
(GeoTIFF DEMs) to the model's cell-based representation.

The mesh JSON is the single most critical input to HexWatershed. Every subsequent
computation depends on correct cell geometry, neighbor relationships, and elevation values.

## Inputs

| Input              | Source              | Format   | Unit/Notes                          |
|-------------------|---------------------|----------|--------------------------------------|
| DEM raster        | SRTM / MERIT / NED  | GeoTIFF  | EPSG:4326, elevation in meters       |
| Mesh resolution   | Configuration        | float    | Cell edge length in meters           |
| Mesh type         | Configuration        | string   | hexagon, square, latlon, mpas, etc.  |
| Study area bounds | Configuration        | lat/lon  | west, south, east, north in degrees  |

## Outputs

| Output                        | Format | Description                               |
|-------------------------------|--------|-------------------------------------------|
| `{mesh_type}_mesh_info.json`  | JSON   | Complete mesh with cells, topology, elev  |

### Output JSON Structure

```json
{
  "sMesh_type": "hexagon",
  "nCell": 12345,
  "dResolution": 5000.0,
  "aCells": [
    {
      "lCellID": 1,
      "dLongitude_center_degree": -76.5,
      "dLatitude_center_degree": 39.2,
      "dElevation_mean": 152.3,
      "dElevation_raw": 152.3,
      "dArea": 21650000.0,
      "nVertex": 6,
      "vVertex": [{"dLongitude_degree": -76.48, "dLatitude_degree": 39.22}, ...],
      "aNeighbor": [2, 3, 4, 5, 6, 7],
      "aNeighbor_distance": [5000.0, 5000.0, 5000.0, 5000.0, 5000.0, 5000.0]
    }
  ]
}
```

## Procedure

1. **Obtain DEM** in GCS (EPSG:4326) with meters elevation:
   ```bash
   # Reproject if needed
   gdalwarp -t_srs EPSG:4326 -r bilinear input_utm.tif output_gcs.tif
   ```

2. **Verify DEM CRS and units**:
   ```bash
   gdalinfo dem.tif | grep -E "AUTHORITY|Unit|NoData"
   # Must show: EPSG:4326, degree units, elevation in meters
   ```

3. **Generate mesh** using PyFlowline (recommended):
   ```python
   from pyflowline.formats.convert_mesh import pyflowline_generate_mesh
   pyflowline_generate_mesh(
       sDEM='/data/dem.tif',
       sMesh_type='hexagon',
       dResolution=5000,
       sOutput='/data/mesh/'
   )
   ```

   Or use the KI mesh_converter tool:
   ```bash
   python mesh_converter.py --dem /data/dem.tif --resolution 5000 \
       --mesh-type hexagon --output /data/mesh/hexagon_mesh_info.json
   ```

4. **Validate mesh**:
   - Check all cells have valid elevation (not nodata)
   - Check neighbor relationships are symmetric (if A neighbors B, B neighbors A)
   - Check cell areas are physically reasonable for the resolution

## Verification

```bash
# Check mesh JSON is valid and has cells
python3 -c "
import json
mesh = json.load(open('hexagon_mesh_info.json'))
print(f'Cells: {mesh[\"nCell\"]}')
cells = mesh['aCells']
elev = [c['dElevation_mean'] for c in cells]
print(f'Elevation range: {min(elev):.1f} to {max(elev):.1f} m')
nodata = [c for c in cells if c['dElevation_mean'] <= -9999]
print(f'Nodata cells: {len(nodata)}')"

# Check coordinate system (values should be in degree range)
python3 -c "
import json
mesh = json.load(open('hexagon_mesh_info.json'))
lons = [c['dLongitude_center_degree'] for c in mesh['aCells']]
lats = [c['dLatitude_center_degree'] for c in mesh['aCells']]
print(f'Lon range: {min(lons):.4f} to {max(lons):.4f}')
print(f'Lat range: {min(lats):.4f} to {max(lats):.4f}')
assert max(abs(l) for l in lons) <= 180, 'PROJECTED CRS DETECTED'
assert max(abs(l) for l in lats) <= 90, 'PROJECTED CRS DETECTED'"
```

## Traps

### TRAP: DEM in projected CRS (dt_006)
If the DEM is in UTM or State Plane (coordinates in meters, not degrees), the mesh
will have coordinates like (500000, 4000000) instead of (-76.5, 39.2). The model
will compute nonsensical distances because it expects geographic degrees for its
internal spherical geometry calculations. **Always check bounds before proceeding.**

### TRAP: DEM elevation in feet (dt_013)
USGS NED tiles may have elevation in feet. Since all HexWatershed internal calculations
assume meters, slopes will be inflated by a factor of 3.28, and depression filling will
behave incorrectly. **Verify**: `gdalinfo dem.tif` should show meters or check max values.

### TRAP: Cell area units (dt_011)
Cell area (`dArea`) must be in m² (square meters). If a GIS tool exports area in km²,
the value will be 10⁶ times too small, causing drainage density and all area-based
metrics to be wildly wrong. A 5km hex cell should have area ~21.65 × 10⁶ m², not 21.65.

### TRAP: Neighbor distance units (dt_012)
`aNeighbor_distance` must be in meters. If distances are in km or degrees, slope
calculations (Δz / distance) will be off by orders of magnitude.

### TRAP: Mesh type mismatch (dt_005)
The `sMesh_type` in the config must match the structure of the mesh JSON. A hexagon
mesh has 6 neighbors per cell; an MPAS mesh has variable connectivity. Using the wrong
parser silently produces garbage topology.

## Example

For a 5km hexagonal mesh over the Chesapeake Bay watershed:

```bash
# DEM: MERIT Hydro, already in EPSG:4326, meters
python mesh_converter.py \
    --dem /data/merit_hydro_chesapeake.tif \
    --resolution 5000 \
    --mesh-type hexagon \
    --output /data/mesh/hexagon_mesh_info.json

# Expected: ~2000-5000 cells depending on watershed size
```
