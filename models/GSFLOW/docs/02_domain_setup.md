# Stage 1: Domain / Grid Setup

## Purpose
Define the computational domain by delineating Hydrologic Response Units (HRUs)
from a DEM and basin shapefile, and optionally creating a MODFLOW finite-difference
grid for the groundwater component.

## Inputs
- DEM raster (e.g., SRTM 90m: `china_dem_90m.tif`)
- Basin boundary shapefile (e.g., `bengbu_clip.shp`)
- Target number of HRUs (or sub-basin delineation criteria)
- MODFLOW grid resolution (e.g., 1000m cells)

## Outputs
- PRMS parameter file with HRU definitions:
  - `nhru`, `hru_area` (acres), `hru_elev` (model units), `hru_lat`, `hru_lon`
  - `hru_slope`, `hru_aspect`, `hru_type`
- Cascade parameters: `hru_up_id`, `hru_down_id`, `hru_pct_up`
- MODFLOW discretization file (`.dis`): grid dimensions, cell sizes, layer elevations
- GVR parameters: `gvr_cell_id`, `gvr_hru_id`, `gvr_cell_pct` (HRU↔MODFLOW cell mapping)
- GIS parameter file: `hru_x`, `hru_y`, `gis_params`

## Procedure

1. **Clip DEM to basin:**
   ```python
   import rasterio
   from rasterio.mask import mask
   basin = gpd.read_file("basin.shp")
   with rasterio.open("dem.tif") as src:
       clipped, transform = mask(src, basin.geometry, crop=True)
   ```

2. **Delineate sub-basins / HRUs:**
   - Use pygsflow or GIS tools to subdivide basin into HRUs
   - For lumped model: 1 HRU = entire basin
   - For semi-distributed: use sub-watershed delineation
   - Calculate per-HRU: area, mean elevation, slope, aspect, centroid

3. **Build cascade network:**
   - Determine flow direction from DEM
   - Connect upslope HRUs to downslope HRUs
   - Final HRU drains to stream segment

4. **Create MODFLOW grid (GSFLOW mode):**
   - Define regular grid covering basin extent
   - Set active/inactive cells based on basin boundary
   - Assign layer elevations from DEM
   - Create BAS6, DIS packages

5. **Map HRUs to MODFLOW cells:**
   - Create GVR (Gravity Reservoir) mapping
   - Each MODFLOW cell maps to one HRU
   - Area-weight fractions for partial overlaps

## Verification
- Sum of `hru_area` ≈ basin area from shapefile
- All HRUs have valid slope (> 0) and elevation
- Cascade network is connected — no isolated HRUs
- MODFLOW grid covers entire basin (no gaps)
- GVR cell count ≈ number of active MODFLOW cells

## Traps
- **Area units:** PRMS `hru_area` is in ACRES, not km² or m².
  1 km² = 247.105 acres. Wrong units → wrong water balance.
- **Elevation units:** Must match between DEM, PRMS, and MODFLOW.
  If DEM is meters, set `elev_units = 1` (meters). Mixing feet and meters
  corrupts temperature lapse rate calculations.
- **Cascade completeness:** Every HRU must cascade to another HRU or a stream
  segment. Orphan HRUs accumulate water indefinitely → unrealistic soil moisture.
- **MODFLOW cell size:** Too coarse → poor representation; too fine → slow convergence.
  Rule of thumb: 500m–2000m for basin-scale studies.
- **CRS mismatch:** Basin shapefile and DEM must be in the same coordinate system.

## Example
```python
import gsflow
from gsflow.builder import GenerateFishnet, FlowAccumulation

# Create MODFLOW grid
fishnet = GenerateFishnet(basin_shp="basin.shp", dx=1000, dy=1000)
grid = fishnet.build()

# Create PRMS parameters
builder = gsflow.builder.PrmsBuilder(dem="dem.tif", basin="basin.shp")
params = builder.build_parameters(nhru=50)
```
