# Stage 5: Validation — Skill Document

## Purpose

Validate HexWatershed results against reference data (published watershed boundaries,
known stream networks, literature values) to confirm the model is producing physically
reasonable outputs. This stage catches configuration errors, unit problems, and mesh
quality issues that may not cause runtime errors but produce wrong results.

## Inputs

| Input                    | Source               | Format  | Notes                          |
|-------------------------|----------------------|---------|--------------------------------|
| Parsed watershed CSV    | Stage 4              | CSV     | Cell-level data with metrics   |
| Watershed statistics    | Stage 4              | JSON    | Summary metrics                |
| Reference watershed area| Published literature  | Number  | km² from USGS/GRDC catalogs   |
| Reference stream network| NHDPlus / HydroSHEDS | Shapefile| For visual comparison         |
| Reference drainage density| Literature          | Number  | km/km² from published studies |

## Outputs

| Output                       | Format | Description                             |
|-----------------------------|--------|-----------------------------------------|
| Validation report           | Text   | Pass/fail for each metric               |
| Comparison figure           | PNG    | Observed vs modeled watershed properties|
| Metric summary              | JSON   | Quantitative validation scores          |

## Procedure

1. **Compare watershed area**:
   ```python
   # USGS watershed area for HUC 02050306 (Susquehanna): 71,251 km²
   published_area_km2 = 71251.0
   modeled_area_km2 = stats["total_area_km2"]
   area_error_pct = abs(modeled_area_km2 - published_area_km2) / published_area_km2 * 100
   # Acceptable: <10% for coarse mesh, <5% for fine mesh
   ```

2. **Compare stream network structure**:
   - Number of segments vs reference
   - Strahler order at outlet vs reference
   - Visual overlay of modeled vs reference streams

3. **Validate slope statistics**:
   ```python
   # Typical ranges for mid-latitude watersheds
   assert 0.001 < stats["slope_mean_ratio"] < 0.5, "Slope outside expected range"
   # If mean slope > 0.5 → check DEM units (feet instead of meters)
   # If mean slope < 0.001 → check if DEM is flat/constant
   ```

4. **Validate drainage density**:
   ```python
   # Typical range: 0.5 – 10 km/km² for natural watersheds
   dd = stats["drainage_density_km_per_km2"]
   if dd < 0.1:
       print("WARNING: Very low drainage density. Check accumulation threshold.")
   elif dd > 20:
       print("WARNING: Very high drainage density. Check unit conversions.")
   ```

5. **Check elevation consistency**:
   ```python
   # Elevation at outlet should be lowest in watershed
   outlet_elev = [r for r in cells if r["is_outlet"] == 1][0]["elevation_filled_m"]
   min_elev = stats["elevation_min_m"]
   assert outlet_elev <= min_elev * 1.01, "Outlet not at lowest elevation"
   ```

6. **Check flow direction consistency**:
   ```python
   # Every non-outlet cell should have a valid downslope cell
   n_no_downslope = sum(1 for r in cells
                        if r["downslope_cell_id"] <= 0 and r["is_outlet"] == 0)
   assert n_no_downslope == 0, f"{n_no_downslope} cells have no downslope neighbor"
   ```

7. **Generate validation figure**:
   ```python
   import matplotlib.pyplot as plt

   fig, axes = plt.subplots(1, 3, figsize=(15, 5))

   # Panel 1: Elevation map
   ax = axes[0]
   sc = ax.scatter(lons, lats, c=elevations, s=1, cmap='terrain')
   plt.colorbar(sc, ax=ax, label='Elevation (m)')
   ax.set_title('DEM (depression-filled)')

   # Panel 2: Flow accumulation
   ax = axes[1]
   import numpy as np
   sc = ax.scatter(lons, lats, c=np.log10(np.array(accum)+1), s=1, cmap='Blues')
   plt.colorbar(sc, ax=ax, label='log10(Accumulation)')
   ax.set_title('Flow Accumulation')

   # Panel 3: Stream network + watershed boundary
   ax = axes[2]
   ax.scatter(lons, lats, c='lightgray', s=1)
   stream_lons = [r['longitude_deg'] for r in cells if r['is_stream']]
   stream_lats = [r['latitude_deg'] for r in cells if r['is_stream']]
   ax.scatter(stream_lons, stream_lats, c='#2563EB', s=2)
   ax.set_title('Stream Network')

   plt.tight_layout()
   plt.savefig('validation.png', dpi=150, bbox_inches='tight')
   ```

## Verification

```bash
# Run all validation checks
python3 -c "
import json

stats = json.load(open('/data/results/watershed_00001_stats.json'))

checks = {
    'Area > 0': stats['total_area_km2'] > 0,
    'Has streams': stats['n_stream_cells'] > 0,
    'Slope in range': 0.001 < (stats['slope_mean_ratio'] or 0) < 0.5,
    'Drainage density': 0.1 < stats['drainage_density_km_per_km2'] < 50,
    'Has segments': stats['n_segments'] > 0,
    'Has subbasins': stats['n_subbasins'] > 0,
    'Elev range > 0': (stats['elevation_range_m'] or 0) > 0,
}

for check, passed in checks.items():
    status = 'PASS' if passed else 'FAIL'
    print(f'  [{status}] {check}')

n_pass = sum(checks.values())
print(f'\n{n_pass}/{len(checks)} checks passed')
"
```

## Traps

### TRAP: Comparing raw vs filled elevations
The output `dElevation_mean` is the depression-FILLED elevation, not the raw DEM
value. When comparing to input DEM, use `dElevation_raw` or expect differences in
depression areas (valleys, pits, flat regions).

### TRAP: Area comparison with different mesh resolutions
Watershed area depends on mesh resolution. A 1km hex mesh will delineate a more
accurate boundary than a 10km mesh. Expect 5-20% area error for coarse meshes.

### TRAP: Stream network comparison at different thresholds
The `dAccumulation_threshold` directly controls stream density. Using 0.001
produces a very dense network; 0.1 produces only major rivers. When comparing
to NHDPlus, match the threshold to the NHDPlus stream order you want to reproduce.

### TRAP: Drainage density depends on resolution
Finer meshes produce higher drainage density because they capture more small streams.
Literature values are resolution-dependent. Compare at matched resolution.

## Example

```bash
# Parse outputs
python output_parser.py --input /data/output/hexwatershed \
    --output /data/results/ --compute-area

# Run validation checks
python3 << 'EOF'
import json

stats = json.load(open('/data/results/watershed_00001_stats.json'))

# Published Susquehanna watershed: 71,251 km², mean slope ~0.05
ref_area = 71251.0
area_err = abs(stats['total_area_km2'] - ref_area) / ref_area * 100

print(f"Modeled area: {stats['total_area_km2']:.1f} km²")
print(f"Reference area: {ref_area:.1f} km²")
print(f"Area error: {area_err:.1f}%")
print(f"Mean slope: {stats['slope_mean_ratio']:.4f}")
print(f"Drainage density: {stats['drainage_density_km_per_km2']:.2f} km/km²")
print(f"Stream segments: {stats['n_segments']}")
print(f"Strahler orders represented: check segment characteristics")
EOF
```
