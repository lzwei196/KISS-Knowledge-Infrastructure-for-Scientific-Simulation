# s6-s8 — Sediment Model Skill Document

## Purpose

Build, run, and analyze the wflow_sediment erosion and transport model. This is wflow's unique capability within HydroCraft — no other model provides spatially distributed sediment yield with multiple transport formulas.

## Prerequisites

- Stage s4 complete (wflow_sbm output exists -- required as sediment input)
- Soil texture data (clay/silt/sand fractions) for USLE K factor -- **automated via `derive_usle_k.py`**
- Land cover classification for USLE C factor -- **automated via `derive_usle_c.py`**

## Inputs

| Name | Type | Source | Description |
|------|------|--------|-------------|
| staticmaps.nc | file | s1 | SBM static maps (soil, land use) |
| wflow_sbm output | file | s4 | Hydrological output (overland flow, precip) |

## Procedure

### Stage s6: Build Sediment Model

1. Choose erosion method:
   - **ANSWERS** (default): Uses USLE C and K factors. Simpler, more widely used.
   - **EUROSEM**: Physics-based kinetic energy splash erosion. Needs canopy height.
2. Choose transport capacity formula:
   - **Engelund-Hansen**: Total load, sand-bed rivers (most common)
   - **Bagnold**: Simplified power relationship
   - **Kodatie**: D50-class dependent
   - **Yang**: Sand-bed and gravel-bed
   - **Molinas-Wu**: Large sand-bed rivers
3. **Derive USLE K-factor from HWSD soil texture** (automated):
   ```bash
   # Grid mode: computes K for every cell using Wischmeier-Smith (1978)
   python tools/s6_sediment/derive_usle_k.py \
     --staticmaps staticmaps.nc --output usle_k.nc
   # Point verification:
   python tools/s6_sediment/derive_usle_k.py --lat 32.93 --lon 117.36
   ```
4. **Derive USLE C-factor from AVHRR land cover** (automated):
   ```bash
   # Grid mode: maps UMD land cover classes to C values
   python tools/s6_sediment/derive_usle_c.py \
     --staticmaps staticmaps.nc --output usle_c.nc
   # Point verification:
   python tools/s6_sediment/derive_usle_c.py --lat 32.93 --lon 117.36
   ```
5. Run `build_sediment_model.py` (uses derived K/C if available in staticmaps):
   ```bash
   python build_sediment_model.py \
     --sbm_staticmaps staticmaps.nc \
     --output_dir wflow_sediment/ \
     --erosion_method answers \
     --transport_formula engelund_hansen
   ```
6. Patch K and C into sediment staticmaps:
   ```bash
   python tools/s6_sediment/derive_usle_k.py \
     --staticmaps staticmaps.nc --patch_nc wflow_sediment/staticmaps_sediment.nc
   python tools/s6_sediment/derive_usle_c.py \
     --staticmaps staticmaps.nc --patch_nc wflow_sediment/staticmaps_sediment.nc
   ```
7. Verify USLE_C and USLE_K maps are non-zero for active cells
8. Verify grain size fractions sum to 1.0 (dt_w019)

### Stage s7: Run Sediment Model

9. Run `run_wflow_sediment.py --toml wflow_sediment/wflow_sediment.toml`
10. Same Julia runtime considerations as s4 (JIT delay, memory)

### Stage s8: Analyze Results

11. Run `analyze_sediment.py --output_nc sediment_output.nc --basin_area_km2 <area>`
12. Key outputs:
   - Mean soil loss (t/ha/yr) — typical: 0.5-50
   - Sediment yield at outlet (t/yr)
   - Specific sediment yield (t/km2/yr) — typical: 10-1000
   - Erosion classification map

## USLE Factor Reference

### C Factor (cover management) -- automated via `derive_usle_c.py`

**Derivation**: `derive_usle_c.py` reads the AVHRR 1km UMD land cover raster,
samples each grid cell center, and maps the UMD class code to a C-factor value
using the lookup table below. Supports grid mode (patch staticmaps_sediment.nc)
and point mode (verification).

| Land Use | C Factor | AVHRR UMD Code | Notes |
|----------|----------|----------------|-------|
| Dense forest | 0.003-0.005 | 1-5 | Very low erosion |
| Woodland | 0.008 | 6 | Low erosion |
| Shrubland | 0.015-0.05 | 8-9 | Low-moderate |
| Grassland | 0.03 | 10 | Low erosion |
| Cropland | 0.30 | 11 | High erosion (annual crops) |
| Bare ground | 0.90 | 12 | Very high (near reference) |
| Barren/sparse | 0.45 | 16 | Very high |
| Urban / water / wetland | 0.0 | 0, 13-15 | No erosion |

### K Factor (soil erodibility, SI units) -- automated via `derive_usle_k.py`

**Derivation**: `derive_usle_k.py` uses the Wischmeier & Smith (1978) nomograph:

    K_US = [2.1e-4 * M^1.14 * (12-OM) + 3.25*(s-2) + 2.5*(p-3)] / 100
    K_SI = K_US * 0.1317

Where M = (%silt + 0.2*%sand) * (100 - %clay), OM = OC * 1.724 (Van Bemmelen),
s = soil structure code (1-4, estimated from texture), p = permeability class
(1-6, estimated from texture). Soil data from HWSD (global) or SoilGrids (Bengbu).

**CRITICAL**: The equation gives K in US customary units. Multiply by 0.1317 to
convert to SI (t*ha*h/(ha*MJ*mm)). Omitting this produces 7.6x overestimation
(dt_w005). `derive_usle_k.py` applies this conversion automatically.

| Soil Texture | K (t*ha*h/(ha*MJ*mm)) | Notes |
|-------------|----------------------|-------|
| Clay | 0.01-0.02 | Resistant |
| Sandy loam | 0.02-0.04 | Moderate |
| Loam | 0.03-0.05 | Moderate-high |
| Silt loam | 0.04-0.06 | Erodible |
| Silt | 0.05-0.07 | Very erodible |

**Bengbu validation**: K = 0.034-0.044 for loam soils (sand~34-39%, silt~40-48%,
clay~18-21%), consistent with published values for Huai River basin.

## Expected Outputs

| Output | Path | Verification |
|--------|------|-------------|
| staticmaps_sediment.nc | wflow_sediment/staticmaps_sediment.nc | USLE_C, USLE_K, grain fracs |
| wflow_sediment.toml | wflow_sediment/wflow_sediment.toml | Valid TOML |
| sediment output NC | wflow_sediment/output/ | soilloss, sediment_concentration |
| erosion analysis | analysis/erosion_rate_annual.nc | Spatial erosion map |

## Validation Checks

1. USLE_C mean is 0.01-0.3 for mixed land use basins
2. USLE_K mean is 0.01-0.06 for most soils
3. Grain size fractions sum to 1.0 per cell (dt_w019)
4. Mean soil loss is 0.5-50 t/ha/yr (order of magnitude check)
5. Sediment yield at outlet is within literature range for the basin

## Common Pitfalls

- **dt_w005**: USLE K in wrong units (US vs SI) — 7.6x error
- **dt_w018**: All C factors near zero (forested basins, no erosion)
- **dt_w019**: Grain fractions don't sum to 1.0 (mass balance error)
- D50 must be appropriate for the river: sand-bed ~0.3-2 mm, gravel-bed ~10-50 mm
