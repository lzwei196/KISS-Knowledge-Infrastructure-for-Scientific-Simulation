# Stage 1: Bathymetry / Topography Preparation

## Purpose

Prepare topography and bathymetry data files in GeoClaw-compatible format.
This is the foundation of any GeoClaw simulation — incorrect bathymetry
causes every downstream result to be wrong.  The main challenges are unit
conversion, sign convention, coordinate system consistency, and ensuring
complete domain coverage.

## Prerequisites

- Raw bathymetry/topography data from a source such as:
  - ETOPO1/ETOPO2 (global, 1–2 arc-minute resolution)
  - GEBCO (global, 15 arc-second)
  - SRTM (land, 30m or 90m)
  - Local survey data (variable formats)
- Knowledge of the target domain bounds and coordinate system
- Python with NumPy installed; optionally rasterio (GeoTIFF) or netCDF4

## Inputs

| Input | Format | Units | Source |
|-------|--------|-------|--------|
| Raw DEM / bathymetry | GeoTIFF, ESRI ASCII, NetCDF, CSV, XYZ | varies | NOAA, GEBCO, local survey |
| Domain bounds | 4 floats (xlower, xupper, ylower, yupper) | meters or degrees | User-defined |
| Coordinate system | integer (1 or 2) | — | 1 = Cartesian/meters, 2 = lat-lon/degrees |
| Vertical datum | string | — | MSL, NAVD88, EGM96, etc. |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `*.topotype2` or `*.tt2` | GeoClaw Type 2 ASCII grid | Header + grid of elevation values |
| `*.topotype3` or `*.tt3` | ESRI ASCII grid | Standard GIS format with header |
| `conversion_report.json` | JSON | Metadata, statistics, warnings |

## Procedure

1. **Identify data source and format.**  Determine the raw data format
   (GeoTIFF, ASCII, NetCDF) and its coordinate reference system (CRS).

2. **Check sign convention.**  GeoClaw uses the convention that ocean
   bathymetry is **negative** (below datum) and land elevation is **positive**
   (above datum).  ETOPO follows this convention.  GEBCO pre-2019 and many
   sonar surveys use positive-down for ocean depth.  If all ocean values
   are positive, negate them with `--flip-sign`.

3. **Convert units.**  GeoClaw expects elevation in **meters**.  Convert
   from feet (×0.3048), fathoms (×1.8288), or centimeters (×0.01) as needed.

4. **Ensure coordinate consistency.**  If `coordinate_system=2` (lat-lon),
   all spatial data must be in decimal degrees.  If `coordinate_system=1`
   (Cartesian), all data must be in meters.  Mixing produces silent errors.

5. **Run the converter tool:**
   ```bash
   python convert_bathymetry.py \
     --input gebco_2023.nc \
     --output domain_bathy.tt2 \
     --format netcdf \
     --topo-type 2 \
     --coordinate-system 2 \
     --flip-sign    # if source uses positive-down
   ```

6. **Verify the output.**  Check that:
   - z_min is negative (ocean) and z_max is positive (land), or
     all negative for a purely oceanic domain
   - The grid dimensions match expectations
   - No excessive NODATA cells

7. **Register in setrun.py.**  Add the topo file to the configuration:
   ```python
   topo_data.topofiles.append([2, 'domain_bathy.tt2'])
   ```

## Verification

- [ ] Elevation range is physically plausible (ocean: −11,000 to 0 m; land: 0 to 8,849 m)
- [ ] Sign convention matches GeoClaw (negative = below sea level)
- [ ] Coordinate system matches `geo_data.coordinate_system`
- [ ] Grid covers the entire computational domain (no gaps at boundaries)
- [ ] NODATA fraction is < 10% of total cells
- [ ] File can be loaded by GeoClaw without error

## Traps

| Trap | Triplet | Impact |
|------|---------|--------|
| Positive-down ocean depth | dt_001 | Ocean appears as mountain, zero flow |
| Coordinate system mismatch | dt_002 | Domain mismatch, nonsensical results |
| Elevation in feet/fathoms | dt_001 | Depth 3× or 6× wrong → wrong wave speed |
| Topo doesn't cover domain | dt_014 | Artificial walls at topo boundary |
| ESRI xllcenter vs xllcorner | dt_001 | Half-cell shift in bathymetry |

## Example

Converting GEBCO NetCDF (positive-down ocean) to GeoClaw Type 2:

```bash
python ki/tools/convert_bathymetry.py \
  --input GEBCO_2023_sub_ice.nc \
  --output chile_bathy.tt2 \
  --format netcdf \
  --topo-type 2 \
  --coordinate-system 2 \
  --flip-sign \
  --z-var elevation \
  --json-output bathy_report.json

# Check result
python -c "
import json
r = json.load(open('bathy_report.json'))
print(f'Elevation range: {r[\"z_min\"]:.1f} to {r[\"z_max\"]:.1f} m')
print(f'Grid: {r[\"ncols\"]}x{r[\"nrows\"]}')
print(f'Warnings: {r[\"warnings\"]}')
"
```
