# Stage 3: Soil Parameter Preparation

## Purpose

Map external soil property databases (HWSD, SoilGrids, or custom surveys)
to CLM5's 25-layer soil column structure. CLM5 uses sand/clay texture
percentages, organic matter density, and color class to determine hydraulic
conductivity, thermal properties, and water retention via pedotransfer
functions.

## Prerequisites

- Soil data source identified (HWSD, SoilGrids, or field measurements)
- Target latitude/longitude or grid region
- Understanding of CLM5's exponentially-spaced soil layers (25 layers to ~8.5 m)

## Inputs

| Input | Source | Format | Variables |
|---|---|---|---|
| HWSD v1.2 | FAO/IIASA | CSV/raster | Sand%, Clay%, OC%, Bulk Density, Gravel% |
| SoilGrids 2.0 | ISRIC | NetCDF/GeoTIFF | Sand, Clay, SOC, BD at 6 depths |
| Field survey | Local | CSV | Sand%, Clay%, OM%, at measured depths |

### CLM5 Soil Layer Structure

CLM5 uses 25 soil layers with exponentially increasing thickness:

```
Layer  Depth_top(m)  Depth_bot(m)  Thickness(m)  Node_depth(m)
  1      0.000         0.018        0.0175         0.0071
  2      0.018         0.045        0.0276         0.0279
  3      0.045         0.091        0.0455         0.0623
  4      0.091         0.166        0.0750         0.1189
  5      0.166         0.289        0.1236         0.2122
  6      0.289         0.493        0.2038         0.3661
  7      0.493         0.829        0.3360         0.6199
  8      0.829         1.383        0.5539         1.0380
  9      1.383         2.296        0.9133         1.7276
 10      2.296         3.802        1.5058         2.8647
 ...     ...           ...          ...            ...
 25     (deep bedrock layers)
```

## Procedure

### Step 1: Obtain soil data for target location

For HWSD:
- Download from FAO HWSD viewer or pre-extracted CSV
- Identify mapping unit for target lat/lon

For SoilGrids:
- Download tiles or use API for target region
- Note: SoilGrids uses g/kg for sand/clay (divide by 10 for %)

### Step 2: Run soil parameter converter

```bash
python ki/tools/convert_soil_params.py \
    --source hwsd \
    --input soil_data.csv \
    --lat 40.0 --lon 116.0 \
    --output clm_soil_params.json
```

### Step 3: Apply to CLM5 surface dataset

The output JSON contains per-layer sand, clay, silt, and organic matter
values that can be used to modify the CLM5 surface dataset via
`modify_input_files/fsurdat_modifier.py` or `mksurfdata_esmf`.

```bash
# Example: modify existing surface dataset
python $CTSMROOT/tools/modify_input_files/fsurdat_modifier.py \
    --fsurdat_in original_surfdata.nc \
    --fsurdat_out modified_surfdata.nc \
    --PCT_SAND 45.0 --PCT_CLAY 25.0
```

## Outputs

| Output | Format | Description |
|---|---|---|
| clm_soil_params.json | JSON | 25-layer sand, clay, silt, OM profiles |
| Modified surface dataset | NetCDF | Updated fsurdat file for CLM5 |

### Output JSON Structure

```json
{
  "status": "success",
  "source": "hwsd",
  "n_layers": 25,
  "sand_pct": [45.0, 45.0, ...],
  "clay_pct": [25.0, 25.0, ...],
  "silt_pct": [30.0, 30.0, ...],
  "organic_matter": [2.1, 1.8, ...],
  "layer_depths_m": [0.0071, 0.0279, ...],
  "warnings": []
}
```

## Verification

1. Sand + clay + silt must equal 100% for each layer
2. Organic matter should decrease with depth (exponential decay)
3. Sand/clay percentages should be physically reasonable (0–100%)
4. Compare against published soil maps for the region
5. Verify that deep layers (>2m) have very low organic matter

## Common Traps

### dt_005: Soil layer interpolation mismatch (DEGRADED)

HWSD provides only 2 layers (0–30 cm topsoil, 30–100 cm subsoil).
CLM5 needs 25 layers to 8.5 m. Naive constant extrapolation puts
topsoil properties at 8 m depth, overestimating deep soil carbon
and hydraulic conductivity.

**Fix**: Use exponential decay for organic matter below measurement
depth. Mineral texture (sand/clay) can be held constant below the
deepest measurement.

### dt_006: PFT fraction normalization (DEGRADED)

When modifying the surface dataset, PFT fractions must sum to 1.0
per grid cell. If you modify soil and accidentally change PCT_NATVEG
or PCT_CROP, the PFT fractions may not normalize, causing mass
conservation violations.

### dt_014: Incorrect soil organic matter initialization (SILENT)

If SoilGrids SOC values (in g/kg) are directly used as kg/m3 without
converting via bulk density, organic matter is typically 10–100x wrong.
This affects soil thermal conductivity and water retention, causing
biased soil temperature and moisture throughout the simulation.

**Correct conversion**: `OM_kgm3 = SOC_gkg * bulk_density_kgm3 / 1000`

## Example

Process SoilGrids data for a site in Bengbu, China:

```bash
python ki/tools/convert_soil_params.py \
    --source soilgrids \
    --input /path/to/soilgrids_bengbu.nc \
    --lat 32.95 --lon 117.35 \
    --output bengbu_soil.json
```

Expected output for Bengbu (Huaihe River basin):
- Topsoil: ~40% sand, ~20% clay, ~40% silt (silty loam)
- Organic matter: ~1.5% at surface, decreasing to < 0.1% below 2m
