# Stage 1: Domain and Worldfile Setup

## Purpose

Create the spatial domain definition for RHESSys by building a **worldfile** that
describes the hierarchical structure of the watershed (basins, hillslopes, zones,
patches, canopy strata), a **worldfile header** (.hdr) referencing parameter
definition files, and a **flow table** encoding lateral water routing.

## Inputs

| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| DEM | GeoTIFF (m) | SRTM / LiDAR | Digital Elevation Model |
| Watershed boundary | Shapefile | Manual / GIS delineation | Basin outline |
| Soil map | Shapefile/raster | SSURGO / HWSD | Soil class per patch |
| Land cover map | Raster | NLCD / GlobeLand30 | Vegetation type per patch |
| Stream network | Shapefile | NHD / DEM-derived | For routing |

## Outputs

| Output | Format | Location | Description |
|--------|--------|----------|-------------|
| Worldfile | `.world` (text) | `worldfiles/` | Spatial hierarchy definition |
| World header | `.hdr` (text) | `worldfiles/` | References to `.def` files |
| Flow table | `.flow` (text) | `flowtables/` | Patch-to-patch routing |

## Procedure

### Step 1: DEM Preprocessing

1. Clip DEM to watershed boundary
2. Fill sinks (required for flow routing)
3. Compute slope and aspect grids (output in **degrees**, not radians — dt_007)
4. Compute accumulated flow and stream network

### Step 2: Patch Delineation

Patches are the fundamental hydrologic response units. Options:
- **Grid-based**: Each DEM cell = one patch (simplest)
- **Sub-basin based**: Subdivide by sub-catchments
- **Unique combination**: Intersect soil × vegetation × elevation bands

Each patch needs:
- Unique integer ID
- Area in **m^2** (not km^2 — dt_008)
- x, y, z coordinates (UTM or projected, meters)
- Slope and aspect in **degrees**
- Soil and landuse definition IDs

### Step 3: Zone Assignment

Zones define climate input areas. Each zone references a base station (climate
data source). Assign zones by:
- Elevation bands
- Aspect classes (N, S, E, W)
- Proximity to climate stations

### Step 4: Hillslope and Basin Assembly

1. Assign patches to hillslopes (typically one hillslope per sub-catchment side)
2. Assign hillslopes to basins (usually one basin per watershed)
3. Write the hierarchical worldfile

### Step 5: Flow Table Generation

The flow table encodes lateral connectivity:
```
<patch_ID> <num_neighbors>
<neighbor_ID> <gamma> <edge_length>
...
```
Where `gamma` is the fraction of total outflow going to each neighbor.

Tools: `CreateFlowTable` (from RHESSysWorkflows) or GRASS GIS `r.rhessys`.

### Step 6: World Header File

The `.hdr` file maps definition IDs to `.def` files:
```
108                 num_basin_default_files
defs/basin.def
1                   num_hillslope_default_files
defs/hill.def
1                   num_zone_default_files
defs/zone.def
1                   num_soil_default_files
defs/soil_sandyloam.def
1                   num_landuse_default_files
defs/lu_undev.def
1                   num_stratum_default_files
defs/veg_douglasfir.def
```

## Verification

```bash
# Check worldfile has correct hierarchy
head -20 worldfiles/w8TC.world
# Should see: world_id, num_basins, basin_ID, ...

# Count patches
grep -c "patch_ID" worldfiles/w8TC.world

# Check flow table references match worldfile patches
awk '{print $1}' flowtables/w8TC.flow | sort -u | wc -l
# Should match patch count

# Check .hdr references exist
while IFS= read -r line; do
  if [ -f "$line" ]; then echo "OK: $line"; fi
done < worldfiles/w8TC.hdr
```

## Traps

| Trap | Symptom | Fix | Triplet |
|------|---------|-----|---------|
| Slope/aspect in radians | Water routing wrong, weird saturation patterns | Convert to degrees | dt_007 |
| Area in km^2 not m^2 | All fluxes 1e6 too small | Multiply by 1e6 | dt_008 |
| Flow table missing patches | Segfault at runtime | Regenerate flow table | dt_015 |
| Worldfile value ordering wrong | Silent parameter misassignment | Check `value   variable_name` format | dt_011 |

## Example

See `source/repo/Testing/worldfiles/w8TC.world` for a complete example with
247 zones/patches covering HJ Andrews Watershed 8 (Oregon).
