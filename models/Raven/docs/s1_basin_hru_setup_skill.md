# s1: Basin and HRU Setup

## Purpose

Generate the Raven .rvh file defining subbasins and HRUs (Hydrologic Response Units). The .rvh file is the spatial foundation — it defines where and how water moves through the basin.

## Prerequisites

- Basin boundary shapefile (from HydroCraft delineation or GRDC/HYDAT)
- DEM raster (china_dem_90m.tif for China, Copernicus GLO-30 for global)
- AVHRR land cover raster (optional, for land-use based HRUs)
- Chosen HRU strategy

## HRU Strategies

### Lumped (1 HRU)
- **When**: GR4J, HYMOD, quick assessment, basins < 500 km2
- **Advantage**: Simplest, fastest, minimal data needed
- **Disadvantage**: No spatial heterogeneity

### Elevation Bands (N HRUs)
- **When**: Mountainous basins, UBC model, elevation range > 500m
- **Advantage**: Captures orographic precipitation and temperature lapse
- **Typical N**: 3-10 bands
- **Rule of thumb**: 1 band per 300-500m of elevation range

### Land Use (N HRUs)
- **When**: Mixed land use basins, agricultural/forest/urban areas
- **Advantage**: Different ET and infiltration by land type
- **Typical N**: 3-8 classes (merge classes < 5% of area)

## Procedure

1. **Run tool**:
```bash
python build_rvh_from_shapefile.py \
    --basin_shp <path> --dem <path> \
    --landcover <path> \
    --output_dir <path> --basin_name <name> \
    --strategy elevation_bands --n_bands 5
```

2. **Verify output**:
   - Total HRU area matches basin area (within 1%)
   - All HRU elevations are within DEM range
   - Land use class names are standard Raven names

3. **Note class names** — these MUST be defined in .rvp (stage s2)

## Validation Checks

- [ ] Sum of HRU areas = basin area (within 1%)
- [ ] All HRU IDs are unique integers starting from 1
- [ ] Basin ID references valid SubBasin IDs
- [ ] Latitude/longitude are within basin bounds
- [ ] Elevation values are reasonable (not 0 or -9999)

## Common Pitfalls

- **dt_006**: HRU area sum != basin area — Raven crashes
- **dt_007**: Soil profile name in .rvh not defined in .rvp
- **dt_008**: Land use or vegetation class not defined in .rvp
