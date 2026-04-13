# Stage 5: Output Parsing and Visualization

## Purpose

Extract fire simulation results from ForeFire output files, convert to analysis-ready formats (CSV, GeoJSON), and produce visualization products.

## Inputs

| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| Simulation output | NetCDF/KML/GeoJSON/FF | Stage 4 | ForeFire output files |
| Domain metadata | From .ff script | Stage 3 | Coordinate system, time reference |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `fire_perimeters.csv` | CSV | Perimeter coordinates per timestep |
| `validation_results.json` | JSON | Computed metrics |
| Visualization plots | PNG | Fire spread maps |

## Procedure

### 1. Parse Output Files

#### NetCDF (ForeFire.0.nc)
Contains the burning map (arrival time at each grid cell) and saved state.

```python
import netCDF4
ds = netCDF4.Dataset("ForeFire.0.nc")
# Available variables depend on what was saved
for v in ds.variables:
    print(f"{v}: {ds[v].shape}")
```

#### GeoJSON
Fire front geometries per timestep. Each feature is a fire front polygon.

```python
import json
with open("result.geojson") as f:
    data = json.load(f)
for feat in data["features"]:
    coords = feat["geometry"]["coordinates"]
    print(f"Perimeter: {len(coords)} rings")
```

#### KML
Fire perimeters as KML placemarks. Viewable in Google Earth.

#### ForeFire Text (.ff)
Full node state (position, velocity, front depth). Used for reload/continue.

```
FireFront[id=2;domain=0;t=3600]
    FireNode[domain=0;id=4;fdepth=20;kappa=0;loc=(5100,5200,0);vel=(0.5,0.3,0);t=3600;state=init;frontId=2]
    ...
```

### 2. Extract Perimeters to CSV

```bash
python tools/parse_forefire_output.py \
    --input ForeFire.0.nc \
    --format netcdf \
    --output fire_perimeters.csv
```

CSV format:
```
perimeter_id,timestamp,point_idx,x,y,z
0,0,0,35881.87,28699.67,0
0,0,1,35882.12,28700.01,0
...
```

### 3. Compute Fire Statistics

Key metrics:
- **Burned area** (ha): Area enclosed by final perimeter
- **Rate of spread** (m/s): Fire front advancement per unit time
- **Perimeter length** (m): Total fire boundary length
- **Fire line intensity** (kW/m): ROS × heat yield × fuel load (Byram's equation)

### 4. Visualization

#### Fire Perimeter Time Series
Plot perimeters colored by time over topography.

#### Burning Map
If burning map is available in NetCDF, plot arrival times as heatmap:

```python
import matplotlib.pyplot as plt
import numpy as np
import netCDF4

ds = netCDF4.Dataset("ForeFire.0.nc")
# Find arrival time variable
bmap = ds["arrival_time"][:]  # or similar variable name
plt.imshow(bmap[-1, -1, :, :], cmap='hot', origin='lower')
plt.colorbar(label='Arrival time (s)')
plt.title('Fire Arrival Time Map')
plt.savefig('burning_map.png', dpi=150)
```

#### Wind + Fire Overlay
```python
# Plot wind vectors over fire perimeter
windU = ds["windU"][0, 0, ::10, ::10]
windV = ds["windV"][0, 0, ::10, ::10]
plt.quiver(windU, windV, alpha=0.5)
```

## Verification

- CSV has valid coordinates within domain bounds
- Perimeter coordinates form closed polygons (first point ≈ last point)
- Burned area is positive and physically reasonable
- Time values are monotonically increasing across perimeters
- Coordinate units match the simulation domain (UTM meters)

## Traps

### Trap 1: Confusing UTM meters with lon/lat
**Symptom**: Perimeter coordinates look like (35881, 28699) — not lon/lat.
**Cause**: ForeFire outputs in the same coordinate system as the input domain (UTM meters).
**Fix**: Convert to lon/lat if needed using pyproj or the domain's UTM zone.

### Trap 2: Empty output file
**Symptom**: Output KML/GeoJSON exists but has no perimeter data.
**Cause**: Simulation didn't produce fire spread (fire extinguished, wrong parameters).
**Fix**: Check simulation console output for errors. Verify fuel and wind configuration.

### Trap 3: Time reference confusion
**Symptom**: Fire arrival times are in seconds from domain start, not absolute time.
**Cause**: ForeFire uses relative time internally.
**Fix**: Add the domain start time to arrival times for absolute timestamps.

### Trap 4: Multiple fronts merged
**Symptom**: Single perimeter where multiple fires were expected.
**Cause**: ForeFire merges fire fronts when they meet.
**Fix**: This is correct physical behavior. Track individual ignition times if needed.

## Example

Complete output parsing workflow:

```bash
# Parse NetCDF output
python tools/parse_forefire_output.py \
    --input ForeFire.0.nc --format netcdf \
    --output fire_perimeters.csv

# Parse GeoJSON output
python tools/parse_forefire_output.py \
    --input result.geojson --format geojson \
    --output fire_perimeters_geojson.csv

# Validate against observations
python tools/validate_spread.py \
    --simulated fire_perimeters.csv \
    --observed observed_perimeters.csv \
    --output validation_results.json \
    --figure validation_plot.png
```
