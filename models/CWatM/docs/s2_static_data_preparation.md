# Stage 2: Static Data Preparation — Topography, Soil, and Land Cover

## Purpose

Prepare all time-invariant spatial input data required by CWatM: topography, drainage network, soil hydraulic properties, land cover fractions, and channel geometry. These files define the physical structure of the model domain.

## Inputs

| Input | Source | Format | Description |
|-------|--------|--------|-------------|
| DEM | SRTM / MERIT DEM | GeoTIFF / NetCDF | Digital elevation model |
| Flow direction | HydroSHEDS / derived | NetCDF / PCRaster | Local drain direction (LDD) |
| HWSD soil | FAO/IIASA | NetCDF / GeoTIFF | Soil texture and properties |
| SoilGrids | ISRIC | GeoTIFF | Alternative soil data source |
| Land cover | ESA CCI / MODIS | NetCDF | Fractional land cover |
| Channel geometry | Global datasets | NetCDF | Width, depth, gradient, length |
| HydroLAKES | Messager et al. | Shapefile / NetCDF | Lake and reservoir database |
| GRDC gauges | GRDC | CSV / Shapefile | Gauge station locations |

## Outputs

| Output | Settings Key | Unit | Description |
|--------|-------------|------|-------------|
| Ldd.nc | Ldd | 1-9 code | Local drain direction map |
| dem.nc | - | m | Elevation |
| ElevationStD.nc | ElevationStD | m | Elevation standard deviation |
| CellArea.nc | CellArea | m² | Grid cell area |
| KSat1.nc, KSat2.nc, KSat3.nc | KSat1-3 | cm/day | Saturated conductivity |
| alpha1-3.nc | alpha1-3 | 1/cm | van Genuchten alpha |
| lambda1-3.nc | lambda1-3 | - | van Genuchten lambda |
| thetas1-3.nc | thetas1-3 | - | Saturated water content |
| thetar1-3.nc | thetar1-3 | - | Residual water content |
| percolationImp.nc | percolationImp | - | Impermeable fraction |
| chanGrad.nc | chanGrad | - | Channel gradient |
| chanLength.nc | chanLength | m | Channel length |
| chanWidth.nc | chanWidth | m | Channel width |
| chanDepth.nc | chanDepth | m | Bankfull depth |
| chanMan.nc | chanMan | s/m^(1/3) | Manning's roughness |
| landcover.nc | fractionLandcover | - | 6 land cover fractions |

## Procedure

### Topography and Drainage

1. **Resample DEM** to target resolution (30 arcmin or 5 arcmin).
2. **Derive LDD** from DEM or use pre-computed HydroSHEDS. CWatM uses PCRaster convention:
   ```
   7 8 9
   4 5 6    (5 = pit/outlet)
   1 2 3
   ```
   **TRAP**: ArcGIS D8 uses 1=E, 2=SE, ..., 128=NE. Conversion required.
3. **Calculate elevation standard deviation** within each grid cell (for snow elevation zones).
4. **Calculate cell area** in m² (varies with latitude for geographic grids).

### Soil Parameters

1. **Extract soil texture** from HWSD or SoilGrids for the study area.
2. **Apply pedotransfer functions** (Schaap et al. 2001, Rosetta) to derive van Genuchten parameters:
   - From HWSD: texture class → lookup table
   - From SoilGrids: sand/silt/clay fractions → PTF equations
3. **Map to 3 CWatM layers**:
   - Layer 1 (topsoil): 0-5 cm (StorDepth derived from settings)
   - Layer 2 (middle): 5-30 cm
   - Layer 3 (deep): 30-100+ cm
4. **Convert KSat units**:
   - HWSD: already cm/day ✓
   - SoilGrids: mm/hr → cm/day (× 2.4)

### Land Cover

1. **Reclassify** ESA CCI or MODIS land cover into CWatM's 6 classes:
   - Forest, Grassland, Irrigated paddy, Irrigated non-paddy, Sealed, Open water
2. **Calculate fractions** per grid cell.
3. **Ensure fractions sum to 1.0** for each cell.

### Channel Geometry

1. **Channel gradient**: Derived from DEM along flow path (minimum: 0.0001).
2. **Channel length**: Grid cell diagonal or flow path length (m).
3. **Channel width/depth**: From empirical relationships with upstream area or global datasets.
4. **Manning's n**: Typically 0.04 for natural channels (calibration parameter scales this).

## Verification

- All maps should cover the same spatial extent and resolution as the mask map.
- KSat values should be 0.1-1000 cm/day for natural soils.
- van Genuchten alpha should be 0.001-0.5 1/cm.
- Land cover fractions should sum to 1.0 ± 0.001 per cell.
- LDD should have exactly one pit (value=5) at the outlet.
- Channel gradient should be > 0 everywhere (minimum 0.0001).
- Cell area should vary smoothly with latitude.

## Traps

1. **KSat unit trap**: CWatM expects cm/day. SoilGrids gives mm/hr. Factor = 2.4. Using wrong units causes either instant drainage or waterlogging.

2. **LDD coding**: PCRaster convention (5=pit) vs ArcGIS D8 (power-of-2 encoding). Wrong coding creates disconnected drainage network — water accumulates in random cells.

3. **van Genuchten alpha units**: CWatM uses 1/cm. Some databases provide 1/m or 1/kPa. Using 1/m values directly makes alpha 100× too large.

4. **Missing soil data**: Cells with no HWSD data (ocean, glaciers) need reasonable defaults or masking. CWatM will crash on NaN soil parameters.

5. **Channel gradient zero**: Zero gradient causes division by zero in kinematic wave routing. Always enforce minimum gradient (e.g., 0.0001).

## Example

```python
# Convert SoilGrids KSat from mm/hr to CWatM cm/day
import netCDF4 as nc
import numpy as np

ds = nc.Dataset("soilgrids_ksat_0-5cm.nc")
ksat_mm_hr = ds.variables["ksat"][:]  # mm/hr
ksat_cm_day = ksat_mm_hr * 2.4       # cm/day

# Validate
assert np.nanmin(ksat_cm_day) > 0, "KSat must be positive"
assert np.nanmax(ksat_cm_day) < 10000, "KSat unrealistically high"

# Write for CWatM
ds_out = nc.Dataset("KSat1.nc", "w")
# ... write with units="cm/day"
```
