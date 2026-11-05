# Multi-Model Coupling (VIC/CaMa-Flood/DSSAT) — Skill Document

> **Stage ID**: s10_coupling
> **Pipeline order**: 10 of 10
> **Depends on**: none (uses outputs from HydroCraft VIC/CaMa-Flood/DSSAT pipelines)

## Purpose

Bridge RESULTS from HydroCraft's hydrological (VIC), hydrodynamic (CaMa-Flood), and crop (DSSAT) models to LDNDC biogeochemistry inputs. This ensures physical consistency across models when running coupled hydrology-biogeochemistry-agronomy simulations. Three primary coupling pathways exist: VIC soil-moisture results for the initial water content, CaMa-Flood water table/flooding, and DSSAT residue/management. A fourth path (LDNDC to water quality) provides feedback for downstream nutrient assessments.

## Prerequisites

- [ ] VIC simulation complete (HydroCraft Steps 1-7) for VIC coupling
- [ ] CaMa-Flood simulation complete for water table coupling
- [ ] DSSAT simulation complete for residue/management coupling
- [ ] Python environment activated with xarray, netCDF4, pandas

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| vic_result_dir | directory | HydroCraft VIC | VIC simulation output (flux files) |
| cama_output_dir | directory | HydroCraft CaMa | CaMa-Flood output NetCDF (sfcelv, flddph, fldfrc) |
| dssat_summary | file | HydroCraft DSSAT | DSSAT Summary.OUT with crop yield and residue |
| lat, lon | number | HydroCraft | Target grid cell coordinates |

## Procedure

Coupling works on model RESULTS. LDNDC climate and soil are not made from VIC forcing files or the VIC soil parameter file: build them from the data source with S4 (`convert_forcing_to_ldndc_climate.py`) and S2 (`hwsd_to_ldndc_soil.py`). (Steps 1 and 2 of the earlier version of this document did that conversion; they were removed on 2026-10-02.)

### Step 3: Extract VIC soil moisture for initial conditions (VIC -> LDNDC)

```bash
python tools/s10_vic_coupling/vic_to_ldndc_soilwater.py
```

Extracts VIC soil moisture on simulation start date, converts mm to volumetric fraction (theta = SM_mm / layer_depth_mm), interpolates from VIC 3-layer to LDNDC multi-layer profile.

### Step 4: CaMa-Flood water table coupling (CaMa -> LDNDC)

Extract CaMa-Flood surface water elevation and flood depth to determine water table depth for LDNDC groundwater boundary conditions.

```
wt_depth = surface_elevation - water_level
if flooding: wt_depth = -flddph (water above surface)
```

**Impact**: Shallow water table increases anaerobic soil volume, promoting denitrification (N2O) and methanogenesis (CH4). Critical for floodplain and wetland biogeochemistry.

**Status**: Conceptual -- no validated tool yet. Use CaMa output values to manually set LDNDC groundwater parameters.

### Step 5: DSSAT management/residue coupling (DSSAT -> LDNDC)

Compare DSSAT-simulated crop yield with LDNDC yield for cross-validation. Use DSSAT residue and management data to inform LDNDC management events.

**Yield conversion**: LDNDC yield is in kgC/ha. DSSAT yield (HWAM) is in kg DM/ha. Convert: `yield_DM = yield_C / 0.45`.

### Step 6: LDNDC nutrient leaching for water quality (LDNDC -> downstream)

LDNDC NO3 leaching output can feed into water quality assessment when coupled with VIC drainage:

```
NO3_load_kg = NO3_leaching_kgN_ha * basin_area_ha
NO3_concentration_mgL = (NO3_load_kg * 1e6) / (drainage_mm * basin_area_m2)
```

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| soil moisture JSON | in-memory | Theta in [0, porosity] per layer |
| Yield comparison | in-memory | LDNDC vs DSSAT within 30% |

## Validation Checks

1. **Bulk density units**: LDNDC bd in g/cm3 (0.5-2.0), NOT kg/m3 (500-2000)
2. **Organic carbon**: LDNDC corg as mass fraction (0.001-0.05), NOT percentage
3. **Water table depth**: Should be in range [-5, 20] meters (negative = above surface)

## Common Pitfalls

> **PITFALL**: LDNDC yield in kgC vs DSSAT yield in kg DM
> LDNDC reports yield as kgC/ha. DSSAT reports as kg dry matter/ha (HWAM). The carbon content of grain is ~45%, so multiply LDNDC by ~2.2 to get DM equivalent for comparison.

---

*This skill document is part of the ldndc-knowledge-infrastructure package.*
*Stage 10 of 10 | Tools used: vic_to_ldndc_soilwater*
