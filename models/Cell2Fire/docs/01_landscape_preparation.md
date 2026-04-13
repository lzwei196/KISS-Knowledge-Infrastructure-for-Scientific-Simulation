# Stage 1: Landscape Preparation

## Purpose

Prepare the spatial landscape data (fuel types, elevation, slope, slope aspect) as ESRI ASCII Grid (`.asc`) or GeoTIFF (`.tif`) rasters that Cell2Fire can read. All rasters must be co-registered with identical dimensions, cell size, and corner coordinates.

## Inputs

| File | Format | Units | Description |
|------|--------|-------|-------------|
| Fuel type map | Raster (any CRS) | Integer codes | Vegetation classification matching the chosen fire model |
| DEM (elevation) | Raster | Meters ASL | Digital elevation model |
| Slope | Raster (optional) | Degrees (0-90) | Terrain slope; can be computed from DEM |
| Aspect | Raster (optional) | Degrees (0-360, north=0) | Slope aspect (compass convention) |
| CBH | Raster (optional) | Meters | Crown base height (needed for crown fire in S&B) |
| CBD | Raster (optional) | kg/m³ | Crown bulk density (needed for crown fire in S&B) |
| CCF | Raster (optional) | Percent (0-100) | Crown closure fraction |

## Outputs

All files go into the **instance folder**:

| File | Format | Description |
|------|--------|-------------|
| `fuels.asc` | ESRI ASCII Grid | Fuel type codes matching lookup table |
| `elevation.asc` | ESRI ASCII Grid | Elevation in meters |
| `slope.asc` | ESRI ASCII Grid | Slope in degrees |
| `saz.asc` | ESRI ASCII Grid | Slope aspect in degrees (compass) |
| `cbh.asc` | ESRI ASCII Grid | Crown base height in meters (optional) |
| `cbd.asc` | ESRI ASCII Grid | Crown bulk density in kg/m³ (optional) |

## Procedure

### Step 1: Choose cell size and extent

- Cell size determines spatial resolution. Common choices: 20m, 30m, 100m.
- Larger cells = faster simulation but less detail.
- All rasters must share the same cell size.

### Step 2: Prepare fuel type raster

1. Obtain land cover / vegetation classification for your area.
2. Reclassify vegetation types to Cell2Fire fuel codes:
   - **Scott & Burgan (--sim S)**: Codes 101-204 (40 fuel models). See `spain_lookup_table.csv`.
   - **Canadian FBP (--sim C)**: Codes 1-20. See `fbp_lookup_table.csv`.
   - **Kitral (--sim K)**: Chilean fuel types.
3. Set non-burnable areas (water, rock, urban) to code 0 or 91-99.
4. Set NODATA areas to -9999.

### Step 3: Prepare elevation raster

1. Obtain DEM (e.g., SRTM, ASTER, LiDAR).
2. Reproject to match fuel raster CRS and extent.
3. Resample to same cell size.
4. **Unit trap**: DEM must be in meters. If source is in feet, multiply by 0.3048.

### Step 4: Compute slope and aspect (if not provided)

Use `convert_fuel_params.py --elevation elevation.asc --output-dir ./instance`:

```python
from convert_fuel_params import compute_slope_aspect
slope_path, saz_path = compute_slope_aspect("elevation.asc", "./instance")
```

Or compute in GIS:
- Slope: degrees (not percent). **Trap**: If source gives percent rise, convert: `degrees = atan(pct/100) × 180/π`
- Aspect: compass convention (north=0, clockwise). **Trap**: Math convention (east=0, counter-clockwise) is common in GIS outputs.

### Step 5: Export as ASC

All ASC files must have identical headers:
```
ncols         508
nrows         610
xllcorner     494272.38261041
yllcorner     4652115.6527613
cellsize      20
NODATA_value  -9999
```

## Verification

1. **Dimension check**: All `.asc` files have same ncols, nrows, cellsize.
2. **Fuel codes check**: All unique fuel codes appear in the lookup table.
3. **Elevation range**: Values should be physically plausible (not in feet, not in km).
4. **Slope range**: Values should be 0-90 degrees (not percent).
5. **Aspect range**: Values should be 0-360 degrees.
6. **NODATA consistency**: NODATA cells in fuel raster should also be NODATA in other rasters.

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Elevation in feet | Slope calculation wrong, fire spread too slow uphill | Multiply by 0.3048 |
| Slope in percent | Unrealistic slope factors, fire spreads too fast uphill | Convert: `atan(pct/100) × 180/π` |
| Aspect in math convention | Fire spread direction wrong relative to slope | Convert: `(90 - deg) % 360` |
| Misaligned rasters | Segfault or wrong cell adjacency | Ensure identical headers |
| Missing NODATA | Non-burnable areas treated as fuel | Set -9999 consistently |

## Example

Using the built-in Vilopriu 2013 instance (Scott & Burgan):
```
data/ScottAndBurgan/Vilopriu_2013-asc/
├── fuels.asc         # 508×610 cells, 20m resolution, S&B fuel codes
├── elevation.asc     # Matching DEM in meters
├── slope.asc         # Slope in degrees
├── saz.asc           # Aspect in compass degrees
├── cbh.asc           # Crown base height (m)
├── cbd.asc           # Crown bulk density (kg/m³)
├── ccf.asc           # Crown closure fraction (%)
└── fcc.asc           # Foliar canopy cover (%)
```
