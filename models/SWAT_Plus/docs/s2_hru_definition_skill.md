# HRU Definition — Skill Document

> **Stage ID**: s2_hru_definition
> **Pipeline order**: 2 of 9
> **Depends on**: s1_watershed_delineation

## Purpose

Hydrologic Response Units (HRUs) are the fundamental computational units in SWAT+. Each HRU is a unique combination of subbasin + land use + soil type + slope class. SWAT+ simulates water balance, nutrient cycling, and plant growth independently for each HRU, then aggregates results to the subbasin level. Incorrect HRU definition propagates errors through all hydrological and water quality calculations.

## Prerequisites

Before starting this stage, verify:

- [ ] Subbasin shapefile exists from Stage 1 (`subbasins.shp`)
- [ ] Land use raster exists and covers the basin (NLCD, GlobeLand30, ESA WorldCover, or local)
- [ ] Land use lookup table maps raster values to SWAT+ plant codes (e.g., NLCD 41 -> FRSD)
- [ ] Soil raster exists (SSURGO MUKEY, HWSD MU, or FAO soil map)
- [ ] Soil lookup table maps raster values to soils.sol names
- [ ] DEM (for slope calculation)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| Subbasin shapefile | file | S1 output | Subbasin boundaries |
| Land use raster | file | NLCD / ESA / GlobeLand30 | Land use/land cover classification |
| Land use lookup | file | User-created CSV | Maps raster values to SWAT+ codes |
| Soil raster | file | SSURGO / HWSD / FAO | Soil type spatial data |
| Soil lookup | file | User-created CSV | Maps raster values to soils.sol names |
| DEM | file | Same as S1 | For slope calculation |
| Slope classes | config | User choice | Slope break points in percent |

## Procedure

### Step 1: Reclassify land use raster

Map raw land use raster values to SWAT+ plant database codes using the lookup table.

Common SWAT+ land use codes:
- `AGRL` (generic agriculture), `CORN` (corn), `SOYB` (soybean), `WWHT` (winter wheat)
- `FRSD` (deciduous forest), `FRSE` (evergreen forest), `FRST` (mixed forest)
- `PAST` (pasture), `RNGE` (range), `URBN` (urban), `WATR` (water), `WETL` (wetland)

**Expected result**: Reclassified land use raster with SWAT+ codes.

### Step 2: Reclassify soil raster

Map soil raster values to soil names matching entries in soils.sol.

**Expected result**: Reclassified soil raster with names matching soils.sol.

### Step 3: Generate slope classes

Compute slope from DEM and classify into user-defined classes.

Default slope classes: [0, 3, 8, 15, 9999] (i.e., 0-3%, 3-8%, 8-15%, >15%)

**Expected result**: Slope class raster.

### Step 4: Create HRU overlay

```bash
python tools/s2/create_hru_overlay.py
```

Overlay land use, soil, and slope class rasters onto subbasin boundaries. Each unique combination becomes an HRU.

**Expected result**: hru-data.hru file with one record per HRU.

### Step 5: Apply HRU thresholds

```bash
python tools/s2/apply_hru_threshold.py
```

Remove HRUs below area thresholds and redistribute their area to dominant HRUs. Recommended thresholds: land use 5-10%, soil 5-10%, slope 10-20%.

**Expected result**: Filtered hru-data.hru with reduced HRU count. Total area preserved.

**If this fails**: See diagnostic triplet dt_004. Verify area conservation after filtering.

### Step 6: Generate HRU connectivity

Write hru.con (HRU connectivity to routing units and landscape units).

**Expected result**: hru.con file with routing entries for all HRUs.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| hru-data.hru | `TxtInOut/hru-data.hru` | 50-5000 HRUs; each has valid land use, soil, slope |
| hru.con | `TxtInOut/hru.con` | One entry per HRU; all route to valid spatial objects |
| topography.hyd | `TxtInOut/topography.hyd` | Slope and slope length for each HRU |
| hydrology.hyd | `TxtInOut/hydrology.hyd` | Hydrological parameters (CN, etc.) for each HRU |

## Validation Checks

1. **HRU count**: Should be 50-5000 for typical basins. <10 is too few for spatial heterogeneity; >10000 slows execution without improving accuracy.

2. **Land use coverage**: All dominant land uses in the basin are represented in the HRU set.
   - Parse hru-data.hru and count unique land use types
   - Expected: at least 3-5 land use types for typical basins

3. **Area conservation**: Total HRU area equals watershed area within 0.1%.
   - Sum all HRU areas in hru-data.hru
   - Compare to watershed area from S1

4. **No orphan HRUs**: Every HRU in hru-data.hru has a corresponding entry in hru.con.

## Common Pitfalls

> **PITFALL**: HRU threshold too aggressive (>20%), biasing water yield
> Removing >20% of basin area through thresholds significantly changes the land use/soil distribution. Agricultural land (often small patches) may be entirely removed, eliminating nutrient source areas.
> **Do this instead**: Use 5-10% thresholds. For water quality studies, use 0% threshold (keep all HRUs).
> See diagnostic triplet dt_004 for full details.

> **PITFALL**: Land use raster values not matching SWAT+ plant codes
> If the lookup table is wrong, HRUs get assigned non-existent plant types. SWAT+ may crash or silently use default parameters.
> **Do this instead**: Verify every raster value has a valid mapping. Check against plants.plt database.

> **PITFALL**: Soil raster and soils.sol name mismatch
> If soil names in the raster lookup do not match soils.sol entries exactly (case-sensitive), SWAT+ assigns zero soil properties.
> **Do this instead**: Cross-check soil names after HRU creation against soils.sol header names.

---

*This skill document is part of the SWAT+ knowledge infrastructure.*
*Stage 2 of 9 | Tools used: create_hru_overlay, apply_hru_threshold | Related triplets: dt_004*
