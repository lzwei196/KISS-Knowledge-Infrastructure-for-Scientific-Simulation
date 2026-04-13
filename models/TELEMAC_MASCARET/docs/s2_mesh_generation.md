# S2: Mesh Generation

## Purpose

Create the unstructured triangular mesh (SELAFIN geometry file) and boundary
conditions file (.cli) required by TELEMAC. The mesh quality directly controls
simulation accuracy, stability, and runtime.

## Inputs

| Input                | Format      | Description                               |
|----------------------|-------------|-------------------------------------------|
| Domain boundary      | Polygon     | From Stage 1                              |
| Resolution map       | Text/config | Target element sizes by zone              |
| Bathymetry data      | XYZ/GeoTIFF | Bottom elevation or depth                 |
| Boundary definitions | Polylines   | Open/closed boundary segments             |

## Outputs

| Output               | Format  | Description                                |
|----------------------|---------|--------------------------------------------|
| Geometry file        | .slf    | SELAFIN mesh with coordinates + topology   |
| Boundary file        | .cli    | Boundary condition types per edge node     |
| Mesh quality report  | Text    | Statistics on element quality              |

## Procedure

1. **Generate mesh** using one of:
   - **BlueKenue** (free, NRC Canada): GUI-based mesh generation
   - **SALOME-MECA**: Open-source CAD/mesh platform
   - **SMS** (commercial): Surface-water Modeling System
   - **stbtel**: TELEMAC's built-in mesh converter

2. **Import bathymetry** onto mesh nodes:
   ```bash
   python convert_bathymetry.py --mesh geo.slf --bathy bathy.xyz \
       --output geo_with_bathy.slf --negate  # if source is depth
   ```

3. **Assign boundary conditions** in the .cli file:
   - LIHBOR = 4 (prescribed elevation) or 5 (prescribed discharge)
   - LIUBOR = 4 (prescribed velocity) or 6 (velocity from elevation)
   - LIVBOR = matching LIUBOR

4. **Check mesh quality**:
   - Minimum angle > 15 degrees
   - Maximum aspect ratio < 5
   - No degenerate (zero-area) elements
   - Smooth size transitions

## Verification

- [ ] Mesh covers the entire study domain
- [ ] Boundary nodes are correctly typed in .cli
- [ ] Bottom elevation (BOTTOM variable) has realistic values
- [ ] No orphan nodes or disconnected elements
- [ ] Element count is manageable for target hardware

## Traps

- **dt_007**: Bathymetry sign convention. TELEMAC uses bottom elevation
  (positive upward). Nautical charts provide depth (positive downward).
  Use `--negate` flag in convert_bathymetry.py.

- **dt_006**: Mesh coordinates must be metric. A mesh in degrees will have
  elements of ~0.001 m and require dt < 0.001 s.

- **dt_013**: SELAFIN files are big-endian. Custom mesh generators must write
  big-endian binary or the file will be unreadable.

## Example

```bash
# Typical mesh generation workflow with BlueKenue
# 1. Create boundary in BlueKenue
# 2. Set mesh density constraints
# 3. Generate mesh -> export as .slf
# 4. Add bathymetry
python convert_bathymetry.py --mesh geo_raw.slf --bathy survey.xyz \
    --output geo.slf --negate --method linear

# Verify mesh stats
python parse_selafin.py geo.slf --info
# Expected: npoin > 1000, nelem > 2000, reasonable coordinate ranges
```
