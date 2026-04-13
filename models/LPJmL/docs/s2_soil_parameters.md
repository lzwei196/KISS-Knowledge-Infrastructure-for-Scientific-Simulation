# Stage 2: Soil Parameter Preparation

## Purpose

Convert global soil texture data (HWSD, SoilGrids, or custom datasets) into LPJmL's 13-type soil classification system. Each grid cell is assigned one of 13 soil texture classes based on sand/silt/clay fractions.

## Inputs

| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| Sand fraction | NetCDF/raster | HWSD / SoilGrids | Topsoil sand percentage (0-100%) |
| Silt fraction | NetCDF/raster | HWSD / SoilGrids | Topsoil silt percentage (0-100%) |
| Clay fraction | NetCDF/raster | HWSD / SoilGrids | Topsoil clay percentage (0-100%) |
| Grid file | CLM binary | LPJmL | Grid coordinates for spatial matching |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Soil type file | CLM binary (byte) | Integer codes 1-13 per grid cell |

## Procedure

1. **Obtain soil texture data**: Download HWSD v2.0 or SoilGrids250m
2. **Regrid to LPJmL grid**: Resample to 0.5-degree resolution (area-weighted mean)
3. **Check fraction units**: Fractions may be 0-1 or 0-100 — normalize to percentages
4. **Verify sum**: sand + silt + clay should sum to ~100% per cell
5. **Classify**: Use USDA texture triangle to assign LPJmL soil code (1-13)
6. **Handle special cases**:
   - Rock/ice: code 13 (very high sand, no silt/clay, or glaciated areas)
   - Ocean/missing: code 0 (null)
   - Organic soils: classify based on mineral fraction
7. **Write binary**: Output as byte array with CLM header

## LPJmL Soil Types

| Code | Name | Key Properties |
|------|------|----------------|
| 1 | Clay | Low Ks (3.5 mm/h), high water retention |
| 2 | Silty clay | Low Ks (4.8), high silt content |
| 3 | Sandy clay | Moderate Ks (26), high sand+clay |
| 4 | Clay loam | Moderate Ks (8.8), balanced texture |
| 5 | Silty clay loam | Low Ks (7.3), high silt |
| 6 | Sandy clay loam | Moderate Ks (16), sandy with some clay |
| 7 | Loam | Moderate Ks (12.2), balanced |
| 8 | Silt loam | Moderate Ks (10.1), high silt |
| 9 | Sandy loam | Moderate-high Ks (18.8) |
| 10 | Silt | Moderate Ks (10.1), very high silt |
| 11 | Loamy sand | High Ks (50.7), low water retention |
| 12 | Sand | Very high Ks (167.8), minimal retention |
| 13 | Rock and ice | Near-zero Ks (0.1), no vegetation |

## Verification

- Distribution should roughly match known global patterns:
  - Loam/clay loam dominant in temperate regions
  - Sandy soils in Sahara, Arabian Peninsula
  - Clay soils in tropical lowlands
- No single type should dominate >50% of cells globally
- Rock/ice (type 13) should match known glaciated/bare rock areas
- Use `printclm` to inspect the output file

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Fractions as 0-1 instead of 0-100 | All cells classified as sand (type 12) | Multiply by 100 |
| Sand+silt+clay ≠ 100 | Wrong classification | Normalize fractions |
| Missing data as 0 | Ocean cells classified as rock | Set missing to null (code 0) |
| Soil depth in cm vs mm | Wrong water capacity | LPJmL soil depths are in mm |
| HWSD dominant soil vs area-weighted | Non-representative classification | Use area-weighted average |
| Organic soils as clay | Wrong hydraulic properties | Map peat soils separately |

## Example

```bash
# Convert HWSD soil data to LPJmL soil codes
python tools/convert_soil_to_lpjml.py \
    --input hwsd_soil_texture.nc \
    --sand_var T_SAND --silt_var T_SILT --clay_var T_CLAY \
    --output input/soil_13types.bin \
    --grid input/grid.bin

# Verify with LPJmL utility
bin/printclm input/soil_13types.bin
```

## Soil Parameter Effects on Model Behavior

Soil type affects:
- **Hydraulic conductivity** (Ks): Controls infiltration rate and drainage
- **Water holding capacity** (w_fc - w_pwp): Determines plant-available water
- **Thermal properties**: Affects soil temperature and permafrost
- **Nitrogen cycling**: Denitrification and nitrification rates differ by texture
- **Runoff generation**: Sandy soils drain quickly, clay soils promote surface runoff
