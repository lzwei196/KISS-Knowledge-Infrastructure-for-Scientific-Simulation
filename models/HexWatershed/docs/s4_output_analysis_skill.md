# Stage 4: Output Analysis — Skill Document

## Purpose

Parse, validate, and analyze HexWatershed outputs to extract watershed characteristics,
generate summary statistics, and verify results against expected ranges. This stage
converts raw JSON outputs into usable CSV tables and computes derived metrics.

## Inputs

| Input                               | Source        | Format  | Notes                          |
|-------------------------------------|---------------|---------|--------------------------------|
| `watershed_NNNNN.json`              | Stage 3       | GeoJSON | Cell-level flow/topology data  |
| `watershed_NNNNN_characteristics.txt`| Stage 3      | Text    | Basin-level metrics (tab-sep)  |
| `*_segment_characteristics.txt`     | Stage 3       | Text    | Segment metrics                |
| `*_subbasin_characteristics.txt`    | Stage 3       | Text    | Subbasin metrics               |

## Outputs

| Output                         | Format | Description                              |
|-------------------------------|--------|-------------------------------------------|
| `watershed_NNNNN.csv`         | CSV    | Cell-level data in tabular format         |
| `watershed_NNNNN_stats.json`  | JSON   | Summary statistics per watershed          |
| `all_watersheds.csv`          | CSV    | Combined cell data across all watersheds  |

## Procedure

1. **Parse watershed JSON** using the output_parser tool:
   ```bash
   python output_parser.py \
       --input /data/output/hexwatershed \
       --output /data/results/ \
       --compute-area
   ```

2. **Verify key metrics** are in expected ranges:

   | Metric                  | Typical Range           | If Outside                   |
   |------------------------|-------------------------|-------------------------------|
   | Mean slope (ratio)     | 0.001 – 0.5            | Check DEM units (feet?)       |
   | Drainage density       | 0.5 – 10 km/km²        | Check area/length units       |
   | Max accumulation       | 10 – n_cells            | Should equal n_cells for outlet|
   | Stream cell ratio      | 0.01 – 0.15            | Adjust accumulation threshold |
   | Elevation range        | >10 m for real terrain  | Check nodata handling         |

3. **Compute derived metrics**:
   ```python
   # Convert accumulation (cells) to drainage area
   drainage_area_km2 = accumulation_cells * mean_cell_area_m2 / 1e6

   # Convert slope ratio to degrees
   slope_deg = math.degrees(math.atan(slope_ratio))

   # Convert slope ratio to percent
   slope_pct = slope_ratio * 100

   # Topographic Wetness Index
   TWI = ln(drainage_area / (slope * cell_width))
   ```

4. **Generate visualizations**:
   ```python
   import matplotlib.pyplot as plt
   import json

   # Load watershed data
   with open('watershed_00001.csv') as f:
       import csv
       reader = csv.DictReader(f)
       data = list(reader)

   # Plot flow accumulation map
   lons = [float(r['longitude_deg']) for r in data]
   lats = [float(r['latitude_deg']) for r in data]
   accum = [float(r['accumulation_cells']) for r in data]

   plt.scatter(lons, lats, c=accum, s=1, cmap='Blues')
   plt.colorbar(label='Flow Accumulation (cells)')
   plt.xlabel('Longitude')
   plt.ylabel('Latitude')
   plt.savefig('flow_accumulation.png', dpi=150)
   ```

5. **Compare with reference data** (if available):
   - Compare watershed area against published basin area
   - Compare stream network against NHD/HydroSHEDS
   - Compare drainage density against literature values

## Verification

```bash
# Quick check of parsed outputs
python3 -c "
import csv
with open('/data/results/watershed_00001.csv') as f:
    reader = csv.DictReader(f)
    rows = list(reader)
    print(f'Cells: {len(rows)}')
    slopes = [float(r['slope_ratio']) for r in rows if float(r['slope_ratio']) > 0]
    print(f'Mean slope ratio: {sum(slopes)/len(slopes):.4f}')
    streams = [r for r in rows if r['is_stream'] == '1']
    print(f'Stream cells: {len(streams)} ({len(streams)/len(rows)*100:.1f}%)')
"

# Verify watershed statistics
python3 -c "
import json
stats = json.load(open('/data/results/watershed_00001_stats.json'))
print(f'Area: {stats[\"total_area_km2\"]:.1f} km²')
print(f'Drainage density: {stats[\"drainage_density_km_per_km2\"]:.2f} km/km²')
print(f'Elevation range: {stats[\"elevation_range_m\"]:.0f} m')
print(f'Segments: {stats[\"n_segments\"]}')
print(f'Subbasins: {stats[\"n_subbasins\"]}')
"
```

## Traps

### TRAP: Accumulation is cell count, not area (dt_002)
The `dAccumulation` field stores the NUMBER of upstream cells, not the upstream
contributing area in m² or km². To get area: `area = accumulation * mean_cell_area`.
Plotting raw accumulation values as "drainage area" produces nonsensical results.

### TRAP: Slope is ratio, not degrees (dt_003)
All slope values (`dSlope_between`, `slope_ratio` in CSV) are dimensionless ratios
(rise/run). A value of 0.1 means 10% slope, NOT 0.1 degrees. Common mistake:
interpreting 0.1 as nearly flat (0.1 degrees ≈ 0.2% slope) when it's actually
moderately steep (10% slope ≈ 5.7 degrees).

### TRAP: Drainage density unit conversion (dt_016)
HexWatershed computes drainage density internally, but if you calculate it yourself
from parsed outputs, remember: area is in m² and length is in m. Convert both to km
before dividing: `density_km_per_km2 = (length_m / 1000) / (area_m2 / 1e6)`.
Forgetting conversion produces values 10⁶× too large.

### TRAP: Missing hillslope data
If `iFlag_hillslope = 0` was set in configuration, the subbasin characteristics
file will lack hillslope columns (left/right/headwater dimensions). This is not
an error — set the flag to 1 and re-run if hillslope analysis is needed.

### TRAP: Empty watershed JSON
If a watershed JSON file exists but contains zero features, it means the outlet
cell was found but no upstream cells could be traced. This usually indicates the
outlet is at the mesh boundary or surrounded by nodata cells.

## Example

```bash
# Full parse with area computation
python output_parser.py \
    --input /data/output/hexwatershed \
    --output /data/results/ \
    --compute-area

# Expected output:
# {
#   "status": "success",
#   "n_watersheds": 1,
#   "n_total_cells": 3456,
#   "watersheds": [
#     {
#       "name": "watershed_00001",
#       "n_cells": 3456,
#       "area_km2": 74.8
#     }
#   ]
# }
```
