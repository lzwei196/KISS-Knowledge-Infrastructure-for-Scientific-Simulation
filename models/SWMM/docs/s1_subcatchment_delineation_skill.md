# Subcatchment Delineation — Skill Document

> **Stage ID**: s1_subcatchment_delineation
> **Pipeline order**: 1 of 7
> **Depends on**: none

## Purpose

Subcatchment delineation defines the spatial units where rainfall-runoff processes occur in SWMM. Unlike watershed-scale models (VIC, SWAT+) that delineate from DEM topography alone, urban subcatchments must reflect the built environment: impervious surfaces (roofs, roads, parking lots), storm sewer inlets, lot grading, and drainage district boundaries. A subcatchment in SWMM represents a homogeneous land area that drains to a single outlet point (a junction node, another subcatchment, or an outfall).

Each subcatchment requires six core parameters: (1) area, (2) percent impervious, (3) characteristic width, (4) average slope, (5) Manning's roughness for impervious and pervious surfaces, and (6) infiltration parameters. Getting these parameters right is critical because subcatchment runoff generation is the primary driver of all downstream hydraulic results.

This stage produces the spatial framework referenced by all subsequent stages. LID controls (S4) are placed on subcatchments. Rainfall (S3) is assigned via rain gages linked to subcatchments. Network inflow comes from subcatchment outlets.

## Prerequisites

Before starting this stage, verify:

- [ ] Study area boundary is defined (shapefile or bounding box coordinates)
- [ ] DEM raster is available covering the study area (SRTM 30m, Copernicus GLO-30, or local survey LiDAR)
- [ ] Land use/land cover data is available (NLCD, GlobeLand30, local zoning maps, or satellite imagery classification)
- [ ] Drainage network layout is approximately known (determines where subcatchment outlets are)
- [ ] Decision on delineation method: DEM-based (topographic), parcel-based (GIS), or Thiessen polygons (simple)
- [ ] Python environment has: geopandas, rasterio, shapely, numpy, (optionally WhiteboxTools for DEM processing)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| Study area boundary | file | User-provided shapefile or coordinates | Defines the spatial extent |
| DEM raster | file | SRTM, Copernicus, LiDAR | For slope and flow path calculation |
| Land use raster | file | NLCD, GlobeLand30, local classification | For imperviousness and roughness |
| Drainage network nodes | config | From S2 or preliminary design | Junction locations for outlet assignment |
| Infiltration method | string | User choice | HORTON, GREEN_AMPT, or CURVE_NUMBER |

## Procedure

Follow these steps in exact order. Do not skip, reorder, or improvise.

### Step 1: Choose Delineation Method

Three methods are available, each suited to different situations:

**DEM-based delineation** (method='dem'): Best for undeveloped or peri-urban areas where topography controls drainage. Uses WhiteboxTools or pysheds to delineate contributing areas to each storm inlet. Requires high-resolution DEM (LiDAR preferred for urban areas — SRTM 30m often cannot resolve street-scale drainage).

**Parcel-based delineation** (method='parcels'): Best for developed urban areas with known lot boundaries and drainage districts. Each parcel or drainage district becomes a subcatchment. Requires GIS data from municipal stormwater utilities.

**Thiessen polygon delineation** (method='thiessen'): Simplest method. Creates Voronoi polygons around junction nodes. Appropriate for preliminary analysis or when detailed spatial data is unavailable.

```bash
python tools/s1_subcatchment_delineation/delineate_subcatchments.py \
  --method parcels \
  --parcel_shapefile data/gis/parcels.shp \
  --output_dir outputs/swmm_run/subcatchments/
```

**Expected result**: Subcatchment polygon shapefile with unique IDs and area attributes.

**If this fails**: Check that input shapefile has valid polygon geometries (no null geometries, no self-intersections). For DEM method, verify DEM covers the study area.

### Step 2: Classify Land Use and Compute Imperviousness

Run land use classification on each subcatchment to determine percent impervious, which is the single most important parameter for urban runoff volume.

```bash
python tools/s1_subcatchment_delineation/classify_land_use.py \
  --subcatchment_shapefile outputs/swmm_run/subcatchments/subcatchments.shp \
  --landuse_raster data/landuse/urban_landuse.tif \
  --infiltration_method horton \
  --output_csv outputs/swmm_run/subcatchments/landuse_params.csv
```

Typical imperviousness by land use:
| Land Use | % Impervious | N_imperv | N_perv |
|----------|-------------|----------|--------|
| Commercial/Industrial | 72-95 | 0.012-0.015 | 0.10-0.15 |
| High-density residential | 50-75 | 0.012-0.015 | 0.15-0.25 |
| Medium-density residential | 25-50 | 0.012-0.014 | 0.15-0.25 |
| Low-density residential | 10-30 | 0.012-0.014 | 0.20-0.40 |
| Parks/Open space | 0-10 | 0.012 | 0.15-0.40 |
| Forest | 0-5 | 0.012 | 0.40-0.80 |

**Expected result**: CSV with per-subcatchment percent_impervious, N_imperv, N_perv, and infiltration parameters.

### Step 3: Assign Infiltration Parameters

Infiltration parameters depend on the chosen method:

**Horton method**: MaxRate (mm/hr), MinRate (mm/hr), Decay (/hr), DryTime (days), MaxInfil (mm)
- Sandy soil: MaxRate=75, MinRate=25, Decay=4, DryTime=7, MaxInfil=0
- Clay soil: MaxRate=25, MinRate=2, Decay=2, DryTime=7, MaxInfil=0

**Green-Ampt method**: Suction (mm), Ksat (mm/hr), IMD (fraction)
- Sandy loam: Suction=110, Ksat=11, IMD=0.23
- Clay: Suction=320, Ksat=0.5, IMD=0.38

**SCS Curve Number method**: CN (curve number for pervious area only)
- Hydrologic soil group A, good condition lawn: CN=39
- Hydrologic soil group D, impervious: CN=98

### Step 4: Compute Subcatchment Physical Parameters

Compute width, slope, and depression storage:

```bash
python tools/s1_subcatchment_delineation/compute_subcatchment_params.py \
  --subcatchment_shapefile outputs/swmm_run/subcatchments/subcatchments.shp \
  --dem_path data/dem/urban_dem.tif \
  --output_csv outputs/swmm_run/subcatchments/physical_params.csv
```

**Width calculation** (CRITICAL): Width = Area / longest_overland_flow_path_length. The longest flow path is the distance from the hydraulically most remote point in the subcatchment to the outlet, measured along the actual flow path. Do NOT use Width = sqrt(Area) — this common shortcut overestimates width for elongated subcatchments and underestimates it for wide, shallow ones.

**Slope**: Average surface slope within the subcatchment from DEM. Minimum 0.001 for flat areas (SWMM uses slope in Manning's equation — zero slope produces zero velocity).

**Depression storage**: Depth of surface depressions that must fill before runoff begins.
- Impervious: 1.3-2.5 mm (paved surfaces have small depression storage)
- Pervious: 2.5-7.6 mm (grass, gardens have larger depression storage)

### Step 5: Assign Subcatchment Outlets

Each subcatchment must drain to exactly one outlet: a junction node, another subcatchment, or an outfall. Outlet assignment determines how subcatchment runoff enters the drainage network.

For cascading subcatchments (one draining to another before entering a junction), verify there are no circular loops (A drains to B, B drains to A).

### Step 6: Validate All Subcatchments

```bash
python tools/s1_subcatchment_delineation/validate_subcatchments.py \
  --subcatchment_config outputs/swmm_run/subcatchments/all_params.csv \
  --node_list outputs/swmm_run/network/nodes.csv
```

## Expected Outputs

| Output | Path Pattern | Description |
|--------|-------------|-------------|
| Subcatchment shapefile | `{output_dir}/subcatchments.shp` | Polygons with IDs and areas |
| Land use parameters | `{output_dir}/landuse_params.csv` | %imperv, roughness, infiltration params |
| Physical parameters | `{output_dir}/physical_params.csv` | Width, slope, depression storage |
| Validation report | (stdout/JSON) | Pass/fail for each validation check |

## Validation Checks

After completing all steps, verify:

1. **Area consistency**: Sum of subcatchment areas matches study area (within 5%)
2. **Percent impervious**: All values in [0, 100]; values > 95% are rare (verify)
3. **Width**: Width < sqrt(Area) for most subcatchments; Width = 0 is an error
4. **Slope**: All slopes > 0; slopes > 20% are unusual for urban areas (verify)
5. **Outlets**: Every subcatchment outlet exists in the node list
6. **No orphans**: Every subcatchment eventually drains to an outfall
7. **No loops**: No circular drainage among cascading subcatchments
8. **Infiltration**: All parameters > 0 where required; Horton MaxRate > MinRate

## Common Pitfalls

**Subcatchment width too large (SILENT ERROR)**: Using Width = sqrt(Area) or Width = Area instead of Width = Area / flow_path_length. Produces artificially fast, peaked runoff. The hydrograph shape will look wrong but there is no error message. See diagnostic triplet dt_016.

**Wrong infiltration parameters for method**: Horton parameters entered for a Green-Ampt model or vice versa. SWMM reads the `[INFILTRATION]` section based on the method set in `[OPTIONS]`. If the method changes but parameters are not updated, SWMM misinterprets the parameter columns. See dt_006.

**Subcatchment outlet does not exist**: Referencing a junction ID that does not appear in `[JUNCTIONS]` or `[OUTFALLS]`. SWMM will report an error at simulation start. See dt_005.

**DEM too coarse for urban delineation**: SRTM 30m or even ASTER 30m cannot resolve street-level drainage in dense urban areas. Buildings, walls, and curbs that control actual flow paths are not captured. Use LiDAR DEM (1-5m) for urban applications when available.

**Impervious area double-counted with LID**: If a subcatchment has 65% impervious and 20% of the impervious area is covered by permeable pavement LID, the effective impervious percentage should account for the LID. SWMM handles this internally when LID_USAGE from_imperv is set, but verify the net impervious fraction.

## Tools Reference

| Tool ID | Script | Purpose |
|---------|--------|---------|
| `delineate_subcatchments` | `tools/s1_subcatchment_delineation/delineate_subcatchments.py` | Create subcatchment polygons |
| `classify_land_use` | `tools/s1_subcatchment_delineation/classify_land_use.py` | Classify land use, compute %imperv |
| `compute_subcatchment_params` | `tools/s1_subcatchment_delineation/compute_subcatchment_params.py` | Compute width, slope, depression storage |
| `validate_subcatchments` | `tools/s1_subcatchment_delineation/validate_subcatchments.py` | Validate all subcatchment parameters |
