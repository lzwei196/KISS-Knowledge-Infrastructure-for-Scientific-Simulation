# S1: Domain / Grid Setup Skill

## Purpose

Define the computational domain for HEC-HMS: subbasin delineation, reach
connectivity, and junction/outlet locations. For lumped basin simulation
(single subbasin), this stage extracts basin properties from the DEM and
shapefile.

## Inputs

| Input | Format | Example |
|-------|--------|---------|
| Basin shapefile | .shp | `bengbu_clip.shp` |
| DEM | GeoTIFF | `china_dem_90m.tif` |
| Stream network (optional) | .shp | HydroSHEDS river network |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Basin model file | `.basin` (native) or JSON | Subbasin definitions, reach connectivity |
| Basin properties | JSON | Area, slope, longest flow path, centroid |

## Procedure

### Lumped Basin (single subbasin)

1. **Extract basin boundary**: Read shapefile, compute total area.

2. **Compute basin slope**: Extract DEM within basin, compute mean slope.
   ```python
   import rasterio
   from rasterio.mask import mask
   # Read DEM, clip to basin, compute gradient
   slope_pct = np.mean(np.gradient(dem_array)) * 100  # Convert to %
   ```

3. **Estimate longest flow path**: For lumped basins, approximate as:
   ```
   L_km = 1.312 * Area_km2^0.568  # Hack's law
   ```

4. **Compute time of concentration**: Using Kirpich equation:
   ```
   Tc_hr = 0.0195 * (L_m^0.77) / (S^0.385)
   ```
   Where L_m = flow path length in meters, S = slope (m/m).

5. **Set basin connectivity**: For a lumped basin, only one subbasin draining
   to the outlet. For semi-distributed, define subbasin→junction→reach→outlet
   network.

### Semi-Distributed Basin

1. **Delineate subbasins**: Use DEM-based watershed delineation (pysheds, whitebox).

2. **Define reaches**: Connect subbasins via channel reaches at junctions.

3. **Assign routing parameters**: Reach length, slope, Manning's n.

4. **Write .basin file** (native HEC-HMS format):
   ```
   Subbasin: Sub1
     Area: 500.0
     Downstream: J1
   End:
   ```

## Verification

- [ ] Total subbasin area matches basin shapefile area (within 5%)
- [ ] All subbasins have a downstream connection
- [ ] No orphaned reaches or disconnected subbasins
- [ ] Basin slope is physically reasonable (0.1-10% for most river basins)

## Traps

- **CRS mismatch**: DEM in UTM meters, shapefile in geographic degrees. Always
  reproject to a common CRS before extraction.
- **Area double-counting**: In semi-distributed setups, subbasin areas must not
  overlap. Sum of subbasin areas = total basin area.
- **Flat DEM artifacts**: 90m SRTM DEM in flat areas (Huai River plains) may have
  artifacts causing wrong flow directions. Consider DEM conditioning (pit filling).

## Example

```python
# Lumped basin for Bengbu
basin_props = {
    "name": "Bengbu",
    "area_km2": 121330,
    "mean_slope_pct": 1.2,
    "longest_flow_path_km": 850,
    "tc_hr": 174,  # Time of concentration
    "centroid": [116.5, 33.0],  # lon, lat
}
```
