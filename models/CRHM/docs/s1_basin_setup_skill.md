# HRU Basin Setup -- Skill Document

> **Stage ID**: s1_basin_setup
> **Pipeline order**: 1 of 6
> **Depends on**: none

## Purpose

Delineate the basin into Hydrological Response Units (HRUs) for CRHM. Unlike VIC's regular lat/lon grid cells, CRHM HRUs are irregular landscape units grouped by hydrological similarity: combinations of elevation band, land cover type, slope, and aspect. HRU definition directly controls which cold regions processes are simulated and how snow is redistributed between landscape units. If HRUs are poorly defined, blowing snow transport calculations will be meaningless because fetch distances and vegetation heights are HRU-level parameters.

## Prerequisites

Before starting this stage, verify:

- [ ] Basin boundary shapefile exists (from HydroCraft delineation or user upload)
- [ ] DEM raster covering the basin (90m China DEM or Copernicus GLO-30)
- [ ] Land cover classification raster (AVHRR 1km or MODIS)
- [ ] Python environment activated with rasterio, geopandas, numpy

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| dem_path | file | HydroCraft DEM or Copernicus GLO-30 | Digital elevation model raster |
| landcover_path | file | AVHRR 1km land cover | Land use classification raster |
| shapefile_path | file | Basin delineation (Step 0) | Basin boundary polygon |
| n_elevation_bands | number | User choice or default 5 | Number of elevation bands |

## Procedure

### Step 1: Assess basin characteristics

Before creating HRUs, understand the basin landscape:
- **Total relief** (max elevation - min elevation): >500m suggests 5+ elevation bands
- **Dominant land cover**: prairie (open, wind-exposed), forest (canopy effects), alpine (rocky, steep)
- **Basin area**: <100 km2 use 3-5 HRUs; 100-1000 km2 use 5-15 HRUs; >1000 km2 use 10-50 HRUs

CRHM is NOT a distributed model -- it does not benefit from hundreds of HRUs. Each HRU adds parameters that must be set. Keep HRU count manageable (typically 3-30).

### Step 2: Run HRU delineation

```bash
python tools/s1_basin_setup/create_hru_config.py \
  --dem_path <dem_path> \
  --landcover_path <landcover_path> \
  --shapefile_path <shapefile_path> \
  --n_elevation_bands <n_bands> \
  --output_dir outputs/<run>/crhm/hru
```

**Expected result**: `hru_config.json` with nhru, areas, elevations, land cover classes.

**If this fails**: See diagnostic triplet dt_012 (HRU area mismatch with basin).

### Step 3: Review HRU configuration

Open `hru_config.json` and verify:
1. nhru is reasonable (3-30 for most basins)
2. Sum of HRU areas approximately equals basin area
3. Elevation range covers the DEM range
4. Land cover classes are physically meaningful for the basin

### Step 4: Assign CRHM-specific HRU properties

For each HRU, the following must be set for cold regions modules:
- **Vegetation height (Ht)**: controls snow trapping. Prairie: 0.1-0.5m. Forest: 5-20m. Crop stubble: 0.1-0.2m.
- **Fetch distance**: distance wind travels over uniform surface before reaching HRU. Open prairie: 500-2000m. Sheltered forest: 10-50m. Exposed ridge: 2000-5000m.
- **Canopy flag**: does this HRU have forest canopy? Enables CRHMCanopy interception/sublimation.

These are pre-populated from land cover class defaults in create_hru_config.py but should be reviewed.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| hru_config.json | `outputs/{run}/crhm/hru/hru_config.json` | File exists, nhru > 0, total area > 0 |

## Validation Checks

1. **HRU count**: nhru should be between 3 and 50 for most basins
   - Command: `python -c "import json; d=json.load(open('hru_config.json')); print(d['nhru'])"`
   - Expected: 3-50
   - If unexpected: Adjust n_elevation_bands or land cover classification

2. **Area conservation**: Sum of HRU areas should be within 5% of basin area
   - Command: Check `basin_area_km2` in hru_config.json
   - If off: CRS mismatch between DEM and shapefile. See dt_012.

3. **Elevation coverage**: HRU elevation range should match DEM
   - If HRUs have identical elevations: DEM is flat or not clipped to basin properly

## Common Pitfalls

> **PITFALL**: CRS mismatch between DEM and shapefile
> The DEM may be in a projected CRS (UTM) while the shapefile is in WGS84. The clip operation returns zero pixels. Area calculations will be wrong.
> **Do this instead**: Reproject to a common CRS before clipping. Always check `gdf.crs == raster.crs`.
> See diagnostic triplet dt_012.

> **PITFALL**: Too many HRUs for a small basin
> CRHM performance degrades and parameter calibration becomes ill-conditioned with >30 HRUs for basins <500 km2. Each HRU needs its own parameter set.
> **Do this instead**: Start with 5-10 HRUs. Only add more if validation shows important landscape heterogeneity is being missed.

> **PITFALL**: Ignoring aspect for mountain basins
> South-facing and north-facing slopes receive very different radiation in cold regions (>50% difference in winter at 50N). Lumping them into one HRU averages out this critical difference.
> **Do this instead**: For mountain basins, stratify HRUs by both elevation band AND aspect (N/S at minimum).

---

*This skill document is part of the hydrocraft-crhm knowledge infrastructure.*
*Stage 1 of 6 | Tools used: create_hru_config | Related triplets: dt_012*
