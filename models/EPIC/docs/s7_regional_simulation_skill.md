# Stage 7: Regional Simulation and Spatial Analysis

## Purpose

Scale EPIC from single-site to regional simulations covering states, counties,
or arbitrary areas of interest. This stage uses Geo-EPIC's spatial modules to
automatically generate inputs for hundreds to thousands of sites from remote
sensing and national databases, run them in parallel, and aggregate results
into spatial maps.

## Prerequisites

- All previous stages mastered for single-site
- GIS tools (geopandas, rasterio, shapely)
- Data access: SSURGO, Daymet/GridMET, CDL (Cropland Data Layer)
- Google Earth Engine account (optional, for satellite-based management)

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| AOI shapefile | .shp / .geojson | Study area boundary |
| CDL raster | .tif | Crop type classification |
| SSURGO geodatabase | .gdb | Soil map units |
| Daymet/GridMET tiles | NetCDF | Weather data |
| DEM | .tif | Elevation for slope |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| info.csv | CSV | Complete site list with all file references |
| weather/*.DLY | Text | One DLY per unique weather grid cell |
| soil/*.SOL | Text | One SOL per unique soil map unit |
| output/*.ACY | Text | One ACY per site |
| Yield map | GeoTIFF / Shapefile | Spatial yield estimates |

## Procedure

### Step 1: Define Area of Interest

```python
import geopandas as gpd

# Load study area
aoi = gpd.read_file('data/iowa_counties.shp')
# or
aoi = gpd.GeoDataFrame(geometry=[box(-94, 41, -93, 42)], crs='EPSG:4326')
```

### Step 2: Generate Site Points

```python
from geoEpic.spatial import generate_sites

# Create grid of simulation points
sites = generate_sites(aoi, resolution=0.1)  # ~10 km grid
# or from CDL crop mask
sites = generate_sites(aoi, crop_type='corn', resolution=0.05)
```

### Step 3: Fetch Data Automatically

```python
from geoEpic.spatial import ssurgo, daymet

# Fetch soil data for all sites
for site in sites:
    ssurgo.fetch_and_write(site.lat, site.lon, f'soil/{site.id}.SOL')

# Fetch weather
for site in sites:
    daymet.fetch_and_write(site.lat, site.lon,
                           start='2015-01-01', end='2020-12-31',
                           path=f'weather/{site.id}.DLY')
```

### Step 4: Generate info.csv

```python
import pandas as pd

info = pd.DataFrame({
    'SiteID': [s.id for s in sites],
    'soil': [f'{s.id}.SOL' for s in sites],
    'dly': [f'{s.id}.DLY' for s in sites],
    'opc': ['CORN.OPC'] * len(sites),  # Same management for all
    'lat': [s.lat for s in sites],
    'lon': [s.lon for s in sites],
})
info.to_csv('info.csv', index=False)
```

### Step 5: Run All Sites

```python
from geoEpic.core import Workspace

ws = Workspace('config.yml')
ws.run(num_workers=16)  # Parallel execution
```

### Step 6: Aggregate Results

```python
import geopandas as gpd
from geoEpic.io import ACY

yields = []
for site in sites:
    acy = ACY(f'output/{site.id}.ACY')
    mean_yield = acy.get_var('YLDG')['YLDG'].mean()
    yields.append({'SiteID': site.id, 'lat': site.lat,
                   'lon': site.lon, 'yield_tha': mean_yield})

results = gpd.GeoDataFrame(
    pd.DataFrame(yields),
    geometry=gpd.points_from_xy([y['lon'] for y in yields],
                                 [y['lat'] for y in yields]),
    crs='EPSG:4326'
)
results.to_file('output/yield_map.shp')
```

## Verification

1. **Coverage**: info.csv has entries for all AOI grid cells
2. **Completeness**: All sites produced output files
3. **Spatial patterns**: Yield map shows reasonable gradients
4. **Statistics**: Mean/std yield across region matches expectations
5. **No edge effects**: Sites near AOI boundary have valid data

## Traps

| Trap | Symptom | Root Cause | Fix |
|------|---------|------------|-----|
| Memory exhaustion | OOM during parallel runs | Too many workers | Reduce num_workers |
| /dev/shm full | Disk space error | Cache not cleaned | Clean old temp dirs |
| Missing soil for sites | Null SOL files | Sites outside SSURGO coverage | Use ISRIC/SoilGrids instead |
| Wrong CDL year | Crop types don't match | CDL year != simulation year | Match CDL year to study period |
| Coordinate system mismatch | Sites in wrong location | WGS84 vs projected CRS | Ensure all data in EPSG:4326 |

## Example

```python
# Quick check: how many sites completed?
import os
acy_files = [f for f in os.listdir('output/') if f.endswith('.ACY')]
print(f"Completed: {len(acy_files)} / {len(sites)} sites")
```
