# Multi-Model Coupling (VIC/CaMa-Flood/DSSAT) — Skill Document

> **Stage ID**: s10_coupling
> **Pipeline order**: 10 of 10
> **Depends on**: none (uses outputs from HydroCraft VIC/CaMa-Flood/DSSAT pipelines)

## Purpose

Bridge outputs from HydroCraft's hydrological (VIC), hydrodynamic (CaMa-Flood), and crop (DSSAT) models to LDNDC biogeochemistry inputs. This ensures physical consistency across models when running coupled hydrology-biogeochemistry-agronomy simulations. Three primary coupling pathways exist: VIC climate/soil, CaMa-Flood water table/flooding, and DSSAT residue/management. A fourth path (LDNDC to water quality) provides feedback for downstream nutrient assessments.

## Prerequisites

- [ ] VIC simulation complete (HydroCraft Steps 1-7) for VIC coupling
- [ ] CaMa-Flood simulation complete for water table coupling
- [ ] DSSAT simulation complete for residue/management coupling
- [ ] Python environment activated with xarray, netCDF4, pandas

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| vic_forcing_dir | directory | HydroCraft VIC | VIC forcing files (7-col ASCII, sub-daily) |
| vic_soil_file | file | HydroCraft VIC | VIC soil parameter file (53+ columns) |
| vic_result_dir | directory | HydroCraft VIC | VIC simulation output (flux files) |
| cama_output_dir | directory | HydroCraft CaMa | CaMa-Flood output NetCDF (sfcelv, flddph, fldfrc) |
| dssat_summary | file | HydroCraft DSSAT | DSSAT Summary.OUT with crop yield and residue |
| lat, lon | number | HydroCraft | Target grid cell coordinates |

## Procedure

### Step 1: Convert VIC forcing to LDNDC climate (VIC -> LDNDC)

```bash
python tools/s10_vic_coupling/vic_to_ldndc_climate.py
```

Set `vic_forcing_dir`, `lat`, `lon`, `output_path`.

**Unit conversions applied**:

| Variable | VIC Unit | LDNDC Unit | Conversion |
|----------|----------|------------|------------|
| Temperature | K | C | subtract 273.15 |
| Precipitation | mm/timestep (3-hourly) | mm/day | SUM all 8 sub-daily values |
| SW radiation | W/m2 | W/m2 | daily mean |
| LW radiation | W/m2 | W/m2 | daily mean |
| Wind | m/s | m/s | daily mean |
| Humidity | Pa (vapor pressure) | % (RH) | RH = 100 * VP / VP_sat(T) |

**Critical**: Precipitation must be SUMMED, not averaged. Taking a single sub-daily value produces 1/8 the correct amount. See dt_014.

**Expected result**: `climate.txt` with tab-separated daily data, temperatures in Celsius.

### Step 2: Convert VIC soil params to LDNDC site (VIC -> LDNDC)

```bash
python tools/s10_vic_coupling/vic_soil_to_ldndc_site.py
```

Set `vic_soil_file`, `lat`, `lon`.

**Key conversions**:
- Bulk density: kg/m3 -> g/cm3 (divide by 1000). If not converted, LDNDC computes negative porosity and segfaults.
- VIC 3 layers -> LDNDC 5-10 layers by depth interpolation
- pH and organic carbon: NOT in VIC file, must come from HWSD separately via `hwsd_to_ldndc_soil`

**Expected result**: JSON with LDNDC-format soil horizons for `generate_site_xml`.

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
| climate.txt (from VIC) | `{project_dir}/input/climate.txt` | Tab-separated, daily, T in Celsius |
| site.xml (from VIC soil) | `{project_dir}/input/site.xml` | Soil texture matches VIC params |
| soil moisture JSON | in-memory | Theta in [0, porosity] per layer |
| Yield comparison | in-memory | LDNDC vs DSSAT within 30% |

## Validation Checks

1. **Temperature unit check**: All tavg values in [-60, 60] C (not Kelvin)
   - If tavg > 100: temperatures are in Kelvin -- see dt_005, dt_014
2. **Precipitation sum**: Compare daily total in climate.txt with sum of VIC sub-daily values for a sample day
3. **Soil consistency**: VIC sand/clay vs LDNDC sand/clay for same cell -- must match within 5%
   - If discrepancy > 10%: models use different soil databases -- see dt_015
4. **Bulk density units**: LDNDC bd in g/cm3 (0.5-2.0), NOT kg/m3 (500-2000)
5. **Organic carbon**: LDNDC corg as mass fraction (0.001-0.05), NOT percentage
6. **Water table depth**: Should be in range [-5, 20] meters (negative = above surface)

## Common Pitfalls

> **PITFALL**: VIC precipitation not summed across sub-daily steps
> Taking a single 3-hourly value gives 1/8 the correct daily precipitation. LDNDC simulates near-drought conditions even in wet climates.
> **Do this instead**: Sum all 8 sub-daily values for each day.
> See diagnostic triplet dt_014.

> **PITFALL**: Inconsistent soil between VIC and LDNDC
> If VIC and LDNDC use different soil databases, the hydrology (VIC) and biogeochemistry (LDNDC) are based on different physical soils. Results are scientifically questionable.
> **Do this instead**: Always derive LDNDC soil from VIC soil params via `vic_soil_to_ldndc_site`.
> See diagnostic triplet dt_015.

> **PITFALL**: VIC bulk density in kg/m3 vs LDNDC in g/cm3
> VIC stores bulk density as kg/m3 (e.g., 1350). LDNDC expects g/cm3 (1.35). Forgetting to divide by 1000 causes negative porosity computation and segfault.
> **Do this instead**: Use `vic_soil_to_ldndc_site` which handles the conversion.

> **PITFALL**: VIC has no pH or organic carbon
> VIC soil param file does not contain pH or organic carbon. These must come from HWSD separately. Zero pH causes numerical instability. Zero corg means no decomposition occurs.
> **Do this instead**: Always supplement VIC soil with HWSD data for pH and corg.

> **PITFALL**: LDNDC yield in kgC vs DSSAT yield in kg DM
> LDNDC reports yield as kgC/ha. DSSAT reports as kg dry matter/ha (HWAM). The carbon content of grain is ~45%, so multiply LDNDC by ~2.2 to get DM equivalent for comparison.

---

*This skill document is part of the ldndc-knowledge-infrastructure package.*
*Stage 10 of 10 | Tools used: vic_to_ldndc_climate, vic_to_ldndc_soilwater, vic_soil_to_ldndc_site | Related triplets: dt_014, dt_015*
