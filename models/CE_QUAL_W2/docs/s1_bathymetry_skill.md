# s1: Bathymetry and Grid Generation — Skill Document

## Purpose

Convert reservoir geometry into a CE-QUAL-W2 segment-layer grid and write the bathymetry file (bth_wb*.npt). This is the most complex and labor-intensive stage. For HydroCraft automation, two modes are supported: DEM-based (for any reservoir with DEM coverage) and idealized (for quick starts with minimal data).

## Prerequisites

- [ ] Reservoir parameters from s0 (length, depth, area, dam location)
- [ ] For DEM mode: DEM raster (China 90m or Copernicus GLO-30) + reservoir extent shapefile
- [ ] For idealized mode: reservoir length (km), max depth (m), surface area (km^2)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| DEM | Raster | HydroCraft data | `data/dem/china_dem_90m/china_dem_90m.tif` or auto-downloaded GLO-30 |
| Reservoir shapefile | Shapefile | User or HydroLAKES | Reservoir water extent polygon |
| Dam lat/lon | Float | User | Dam location for thalweg tracing |
| Upstream lat/lon | Float | User | Upstream end for thalweg direction |
| Segment length | Float | s0 | Target segment length in meters |
| Layer thickness | Float | s0 | Layer thickness in meters |

## Procedure

### Step 1: Choose mode

- **DEM mode**: Have DEM + reservoir shapefile? Use DEM mode for realistic bathymetry.
- **Idealized mode**: No DEM or quick assessment? Use idealized trapezoidal geometry.

### Step 2: Run build_reservoir_grid

**Idealized mode** (most common for initial setup):
```bash
python tools/s1_bathymetry/build_reservoir_grid.py \
    --idealized --reservoir_length_km 80 --max_depth 80 \
    --surface_area_km2 745 --dam_elevation 170 \
    --segment_length 2000 --layer_thickness 2.0 \
    --output_dir <run_dir>
```

**DEM mode**:
```bash
python tools/s1_bathymetry/build_reservoir_grid.py \
    --dem /path/to/dem.tif --reservoir_shp /path/to/reservoir.shp \
    --dam_lat 32.54 --dam_lon 111.51 \
    --upstream_lat 33.10 --upstream_lon 111.80 \
    --segment_length 1000 --layer_thickness 1.0 \
    --output_dir <run_dir>
```

### Step 3: Validate outputs

Check `reservoir_grid.json`:
- `n_segments` >= 4 (2 boundary + at least 2 active)
- `n_layers` >= 2
- `max_depth_m` matches expected value
- `surface_elevation_m` matches dam crest

Check `bth_wb1.npt`:
- First column (boundary segment 1) is all zeros
- Last column (boundary segment IMX) is all zeros
- Active segments have at least one non-zero width (dt_010)
- Width decreases from surface to bottom (within each segment)

### Step 4: Check bottom elevation monotonicity (dt_013)

Bottom elevations must be monotonically NON-INCREASING from upstream to downstream.
If bottom elevation increases at any downstream segment, water gets trapped.

```python
import json
g = json.load(open('reservoir_grid.json'))
for i in range(2, len(g['bottom_elevations_m'])-1):
    if g['bottom_elevations_m'][i] > g['bottom_elevations_m'][i-1] + 0.01:
        print(f"WARNING: Bottom elevation increases at segment {i+1}")
```

## Expected Outputs

| Output | Path | Verification |
|--------|------|-------------|
| Grid JSON | `reservoir_grid.json` | Contains n_segments, n_layers, width_matrix |
| Bathymetry file | `bth_wb1.npt` | Fixed-width, rows=layers, cols=segment widths |

## Validation Checks

1. All active segments have non-zero width in at least one layer (dt_010)
2. Bottom elevations are monotonically non-increasing downstream (dt_013)
3. Boundary segments (1 and IMX) have zero width at all layers
4. Width matrix dimensions: [n_layers] x [n_segments]
5. All widths are non-negative

## Common Pitfalls

| Pitfall | Triplet | How to detect |
|---------|---------|--------------|
| Zero-width active segment | dt_010 | Model crashes at startup with "layer error" |
| Bottom elevation increases downstream | dt_013 | Water flows upstream (silent) |
| CFL violation from short segments | dt_011 | Extremely slow runtime (dt < 1s) |
| DEM lacks underwater bathymetry | N/A | Use idealized mode with known max depth |
