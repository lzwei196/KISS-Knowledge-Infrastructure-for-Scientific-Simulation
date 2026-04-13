# Stage 1: Glacier Inventory & Selection

## Purpose

Identify all glaciers within or intersecting the target hydrological basin using the Randolph Glacier Inventory (RGI). This stage determines whether glacier modeling is warranted and produces the glacier list that drives all subsequent OGGM stages. The glacier inventory is the foundation of any OGGM simulation — errors here propagate through every downstream step.

The RGI is a globally complete inventory of glacier outlines, organized into 19 first-order regions. Each glacier has a unique identifier (e.g., `RGI60-15.03473`), outline polygon, and attributes (area, elevation range, aspect, terminus type, surge flag, debris flag). OGGM requires a list of valid RGI IDs to initialize glacier directories.

## Prerequisites

- **Basin boundary shapefile** — From HydroCraft's basin delineation (Step 0) or user-provided. Must be a valid polygon in a known CRS (EPSG:4326 preferred, or will be reprojected).
- **RGI shapefiles** — Either downloaded locally or via OGGM's auto-download (`oggm.utils.get_rgi_dir()`). Approximately 50-500 MB per region.
- **Python packages**: geopandas, shapely, pyproj (all part of OGGM's dependencies).
- **Internet connection** — Required for first-time RGI download. Once cached, works offline.

## Inputs

| Input | Type | Required | Description |
|-------|------|----------|-------------|
| `basin_shp` | file | Yes | Basin boundary shapefile path |
| `rgi_dir` | directory | No | Local RGI directory (auto-detected if OGGM installed) |
| `rgi_version` | string | No | '62' (default) or '70' |
| `rgi_region` | string | No | First-order region number (auto-detected from basin centroid) |
| `buffer_km` | number | No | Buffer around basin (km, default 0) |
| `min_area_km2` | number | No | Minimum glacier area threshold (default 0.01 km2) |
| `basin_area_km2` | number | Yes | Total basin area for glacier fraction computation |

## Procedure

### Step 1: Determine the RGI Region

Each RGI first-order region covers a specific geographic area. The correct region is determined by the basin's centroid coordinates:

| Region | Name | Approximate Coverage |
|--------|------|---------------------|
| 01 | Alaska | Alaska, USA |
| 02 | Western Canada and US | Pacific Northwest to Rockies |
| 05 | Greenland | Greenland periphery |
| 08 | Scandinavia | Norway, Sweden |
| 10 | North Asia | Siberia, Mongolia, Altai |
| 11 | Central Europe | Alps |
| 13 | Central Asia | Tien Shan, Pamir, Karakoram, Kunlun |
| 14 | South Asia West | Hindu Kush, Western Himalaya, Karakoram |
| 15 | South Asia East | Eastern Himalaya, SE Tibet |

If the basin spans multiple RGI regions (e.g., a large Central Asian basin), query all relevant regions and merge results.

### Step 2: Download or Locate RGI Outlines

Use `download_rgi_region.py` to obtain the RGI shapefile. OGGM's `utils.get_rgi_dir()` downloads and caches RGI data automatically. For offline use, download manually from https://www.glims.org/RGI/.

The RGI shapefile contains one polygon per glacier with attributes:
- `RGIId` — Unique identifier (e.g., `RGI60-15.03473`)
- `GLIMSId` — GLIMS database identifier
- `Area` — Glacier area in km2
- `Zmin`, `Zmax`, `Zmed` — Elevation statistics
- `Aspect` — Mean aspect in degrees
- `TermType` — 0=Land-terminating, 1=Marine-terminating, 2=Lake-terminating
- `Surging` — 0=No, 1=Possible, 2=Probable, 3=Observed
- `Connect` — Connectivity level (0-2)
- `Form` — 0=Glacier, 1=Ice cap

### Step 3: Spatial Intersection

Perform a spatial join between the basin polygon and RGI outlines:

1. Load basin shapefile with geopandas
2. Reproject to EPSG:4326 if needed (RGI is in WGS84)
3. Optionally buffer the basin boundary by `buffer_km`
4. Load RGI shapefile for the relevant region(s)
5. Perform `sjoin(rgi_gdf, basin_gdf, how='inner', predicate='intersects')`
6. For glaciers partially outside the basin, clip to basin boundary and recompute area
7. Apply minimum area filter

**CRITICAL CRS WARNING:** If the basin shapefile is in a projected CRS (e.g., UTM) and is not reprojected to EPSG:4326 before the spatial join, the intersection will return **zero glaciers** with no error message. This is the most common silent error in this stage.

### Step 4: Apply Area Thresholds

- Remove glaciers smaller than `min_area_km2` (default 0.01 km2). Glaciers this small have unreliable outlines and cannot be meaningfully simulated with OGGM's flowline model.
- For glaciers partially in the basin, use the clipped area, not the full RGI area.
- Flag debris-covered glaciers (if debris flag available in RGI attributes).

### Step 5: Compute Glacier Fraction

```
glacier_fraction = total_glacier_area_km2 / basin_area_km2 * 100
```

Decision thresholds:
- < 0.1%: Skip OGGM — negligible glacier contribution
- 0.1% - 1%: Optional — minimal impact on discharge
- 1% - 10%: Recommended — affects summer discharge
- > 10%: Required — glaciers dominate summer hydrology

### Step 6: Validate and Export

Run `validate_glacier_selection.py` to check:
- No duplicate RGI IDs
- All areas > 0 and > min_area_km2
- RGI ID format is valid (RGI60-XX.XXXXX)
- Report summary statistics

Export glacier list as CSV with columns: rgi_id, name, area_km2, centroid_lat, centroid_lon, min_elev, max_elev, debris_flag.

## Expected Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `glaciers_in_basin.csv` | CSV | Per-glacier attributes for OGGM initialization |
| `glaciers_in_basin.csv.summary.json` | JSON | Summary: n_glaciers, total_area, glacier_fraction |

## Validation Checks

1. **Non-zero glacier count** — If intersection returns 0 glaciers but the basin is in a glacierized region, suspect CRS mismatch or wrong RGI region.
2. **No duplicate RGI IDs** — Can happen if querying multiple overlapping RGI regions.
3. **Reasonable total area** — Cross-check against published glacier inventories for the region.
4. **Area consistency** — Clipped glacier areas should be <= original RGI areas.
5. **Centroid within basin** — All glacier centroids should be within or near the basin boundary.

## Common Pitfalls

### CRS Mismatch (SILENT)
The basin shapefile may be in a local CRS (e.g., Gauss-Kruger for Chinese basins). RGI is always in EPSG:4326. If not reprojected, `sjoin` returns 0 results silently. Always check `basin_gdf.crs` before the join.

### Wrong RGI Region
RGI regions have boundaries that don't perfectly match political or watershed boundaries. A basin near the border of two regions (e.g., Region 13/14 boundary along the Karakoram) may need glaciers from both regions.

### Nominal Glaciers
Some RGI entries are "nominal" — represented as points rather than polygons, typically for very small or poorly surveyed glaciers. OGGM cannot simulate nominal glaciers. Filter them out (TermType or Area = 0 clues).

### Multi-Part Glaciers
Some RGI polygons represent glacier complexes (connected ice masses). OGGM handles these, but area statistics may be misleading if you expect individual glaciers.

### Buffer Considerations
Use `buffer_km > 0` only if glaciers immediately outside the basin boundary may contribute meltwater that flows into the basin (e.g., glacier tongue outside basin but upper accumulation area drains into basin via subsurface flow). For most basins, `buffer_km = 0` is correct.

## Tools Reference

| Tool | Script | Purpose |
|------|--------|---------|
| `find_glaciers_in_basin` | `tools/s1_glacier_inventory/find_glaciers_in_basin.py` | Spatial intersection of RGI with basin |
| `download_rgi_region` | `tools/s1_glacier_inventory/download_rgi_region.py` | Download RGI shapefiles |
| `validate_glacier_selection` | `tools/s1_glacier_inventory/validate_glacier_selection.py` | Validate glacier list |
