# Skill: Input Preparation — DEM and Forcing Data (Stage 2)

## Purpose

Load real-world topographic data (DEM) and, optionally, rainfall/climate forcing
into a Landlab grid. This stage converts external geospatial data into the field
arrays that Landlab components consume. Unit mismatches at this stage propagate
silently through every subsequent calculation.

## Inputs

| Input | Format | Units | Source |
|-------|--------|-------|--------|
| DEM file | ESRI ASCII (.asc), GeoTIFF (.tif), NetCDF (.nc) | meters | SRTM, ASTER, LiDAR |
| Rainfall data | CSV or NetCDF time series | varies (mm/hr, mm/day, m/s) | CMFD, ERA5, MSWX |
| Grid spacing override | float | meters | User (if DEM header is inaccurate) |
| NoData value | float | — | DEM metadata (commonly -9999) |

## Outputs

| Output | Format | Location | Description |
|--------|--------|----------|-------------|
| `topographic__elevation` | float array | at_node | Elevation from DEM (m) |
| `water__unit_flux_in` | float array | at_node | Rainfall rate (m/s) |
| Boundary status | int array | at_node | Closed at nodata, open at outlets |

## Procedure

### Loading a DEM

1. **ESRI ASCII** (simplest, no extra dependencies):
   ```python
   from landlab.io.esri_ascii import load
   with open("dem.asc") as f:
       mg = load(f, name="topographic__elevation", at="node")
   ```

2. **GeoTIFF** (requires rasterio):
   ```python
   import rasterio
   import numpy as np
   from landlab import RasterModelGrid

   with rasterio.open("dem.tif") as src:
       data = src.read(1)
       dx = abs(src.transform.a)

   mg = RasterModelGrid(data.shape, xy_spacing=dx)
   z = mg.add_field("topographic__elevation", data[::-1].flatten(), at="node")
   ```
   TRAP: Rasterio reads top-to-bottom; Landlab stores bottom-to-top. You MUST
   flip with `[::-1]` or the landscape will be upside-down (dt_010).

3. **NetCDF**:
   ```python
   from landlab.io.netcdf import from_netcdf
   mg = from_netcdf("dem.nc")
   ```

### Handling NoData

```python
nodata_mask = np.isclose(z, -9999, atol=0.1)
z[nodata_mask] = np.nan
mg.status_at_node[nodata_mask] = mg.BC_NODE_IS_CLOSED
```

NoData nodes MUST be closed. Otherwise FlowAccumulator routes flow through them,
creating artificial drainage paths (dt_010).

### Adding Rainfall

Landlab's `water__unit_flux_in` expects **m/s** (depth per unit time per unit area):

```python
# Convert mm/hr to m/s
rainfall_mm_hr = 10.0
rainfall_m_s = rainfall_mm_hr / (1000.0 * 3600.0)  # = 2.78e-6 m/s

mg.add_field("water__unit_flux_in", np.full(mg.number_of_nodes, rainfall_m_s), at="node")
```

TRAP: If you pass mm/hr directly as m/s, discharge will be 3.6 million times
too large (dt_001). The FlowAccumulator will produce enormous drainage areas
and the stream power eroder will erode mountains in a single timestep.

### Unit Conversion Reference

| Source Units | Target (Landlab) | Conversion |
|-------------|-------------------|------------|
| mm/hr → m/s | `water__unit_flux_in` | ÷ 3,600,000 |
| mm/day → m/s | `water__unit_flux_in` | ÷ 86,400,000 |
| m/yr → m/s | `water__unit_flux_in` | ÷ 31,557,600 |
| feet → m | `topographic__elevation` | × 0.3048 |
| cm → m | `soil__depth` | ÷ 100 |
| degrees → meters | `xy_spacing` | Reproject DEM |

## Verification

- `mg.at_node["topographic__elevation"]` has no unexpected NaN values
- Elevation range is physically reasonable (0–9000 m)
- At least one open boundary node exists
- `water__unit_flux_in` is in m/s (typical range: 1e-8 to 1e-4)
- NoData regions are closed boundary nodes

## Traps

| Trap | Symptom | Fix | Triplet |
|------|---------|-----|---------|
| Rainfall in mm/hr as m/s | Discharge 3.6M× too high | Divide by 3.6e6 | dt_001 |
| GeoTIFF not flipped | Landscape upside-down | Use `data[::-1]` | dt_010 |
| NoData not masked | Flow into void cells | Set BC_NODE_IS_CLOSED | dt_010 |
| DEM in degrees | Slopes ~100,000× wrong | Reproject to UTM meters | dt_004 |
| Elevation in feet | Slopes 3.28× wrong | Multiply by 0.3048 | dt_007 |

## Example

```python
import numpy as np
from landlab.io.esri_ascii import load

# Load DEM
with open("study_area.asc") as f:
    mg = load(f, name="topographic__elevation", at="node")

z = mg.at_node["topographic__elevation"]

# Handle nodata
nodata_mask = z < -9000
z[nodata_mask] = np.nan
mg.status_at_node[nodata_mask] = mg.BC_NODE_IS_CLOSED

# Add uniform rainfall: 50 mm/hr → m/s
rain_m_s = 50.0 / (1000.0 * 3600.0)
mg.add_field("water__unit_flux_in",
             np.full(mg.number_of_nodes, rain_m_s), at="node")

# Verify
print(f"Elevation: {np.nanmin(z):.1f} – {np.nanmax(z):.1f} m")
print(f"Rainfall: {rain_m_s:.2e} m/s")
print(f"Open BC nodes: {np.sum(mg.status_at_node == mg.BC_NODE_IS_FIXED_VALUE)}")
```
