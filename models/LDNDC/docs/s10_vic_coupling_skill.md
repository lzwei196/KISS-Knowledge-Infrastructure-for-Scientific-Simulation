# VIC-LDNDC Coupling — Skill Document

> **Stage ID**: s10_vic_coupling
> **Pipeline order**: 10 of 10
> **Depends on**: none (uses VIC outputs from HydroCraft pipeline)

## Purpose

Bridge the VIC hydrological model outputs from HydroCraft to LDNDC biogeochemistry inputs. This ensures consistent climate forcing, soil properties, and hydrological state between the two models when running coupled hydrology-biogeochemistry simulations. Three coupling pathways: climate forcing, soil properties, and soil moisture.

## Prerequisites

- [ ] VIC simulation complete (HydroCraft Steps 1-7)
- [ ] VIC forcing files available at `outputs/{run_name}/vic_temp/forcing/forcing_final/`
- [ ] VIC soil parameter file available at `outputs/{run_name}/vic_temp/soil/SOIL_PARAM_COMPLETE.txt`
- [ ] VIC output files available at `outputs/{run_name}/vic_result/`

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| vic_forcing_dir | directory | HydroCraft | VIC forcing files (7-col ASCII) |
| vic_soil_file | file | HydroCraft | VIC soil parameter file |
| vic_result_dir | directory | HydroCraft | VIC simulation output |
| lat, lon | number | HydroCraft | Target grid cell |

## Procedure

### Step 1: Convert VIC forcing to LDNDC climate

```bash
python tools/s10_vic_coupling/vic_to_ldndc_climate.py
```

**Unit conversions applied**:

| Variable | VIC Column | VIC Unit | LDNDC Unit | Conversion |
|----------|-----------|----------|------------|------------|
| Temperature | col 1 (Tmin), col 2 (Tmax) | K | C | T_C = T_K - 273.15 |
| Precipitation | col 3 | mm/timestep | mm/day | Sum 8 sub-daily values |
| SW radiation | col 4 | W/m2 | W/m2 | Daily mean |
| LW radiation | col 5 | W/m2 | W/m2 | Daily mean |
| Wind | col 7 | m/s | m/s | Daily mean |
| Humidity | col 6 | Pa (vapor pressure) | % (RH) | RH = 100 * VP / VP_sat(T) |
| Pressure | col 8 | kPa | kPa | Pass through |

**Critical**: VIC forcing is sub-daily (typically 3-hourly, 8 records/day). Precipitation must be SUMMED, not averaged, across sub-daily steps. Temperature min/max are the actual min/max across all sub-daily steps. Other variables are averaged. See dt_014.

### Step 2: Convert VIC soil params to LDNDC site

```bash
python tools/s10_vic_coupling/vic_soil_to_ldndc_site.py
```

**VIC to LDNDC soil mapping**:

| VIC Parameter (53-col) | VIC Col | LDNDC Attribute | Conversion |
|------------------------|---------|-----------------|------------|
| Sand fraction | 47-49 | sand | Direct (fraction) |
| Clay fraction | Same file | clay | Calculated: 1 - sand - silt (or from soil type) |
| Bulk density | 44-46 | bd | kg/m3 -> g/cm3 (divide by 1000) |
| Layer depth | 14-16 | depth | m -> m (direct, but split to more layers) |
| Organic fraction | Derived | corg | Estimated from VIC soil type via HWSD lookup |
| pH | Not in VIC | pH | Must come from HWSD separately |

**Important**: VIC has 3 soil layers; LDNDC typically needs 5-10 layers. The tool interpolates VIC properties across LDNDC layers based on depth correspondence.

### Step 3: Extract VIC soil moisture for initial conditions (optional)

```bash
python tools/s10_vic_coupling/vic_to_ldndc_soilwater.py
```

Uses VIC output soil moisture columns to set LDNDC initial water content, mapped from VIC 3-layer to LDNDC multi-layer profile.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| climate.txt | `{project_dir}/input/climate.txt` | Tab-separated, daily, T in Celsius |
| site.xml (soil from VIC) | `{project_dir}/input/site.xml` | Soil texture matches VIC params |

## Validation Checks

1. **Temperature unit check**: All tavg values in [-60, 60] C (not K)
2. **Precipitation sum**: Compare daily total in climate.txt with sum of VIC sub-daily values for a sample day
3. **Soil consistency**: Compare VIC sand/clay with LDNDC sand/clay for same grid cell -- should match within 5%
4. **Bulk density**: LDNDC bd in g/cm3 (0.5-2.0), not kg/m3 (500-2000)
5. **Organic carbon**: LDNDC corg as mass fraction (0.001-0.05), not percentage

## Common Pitfalls

> **PITFALL**: VIC precipitation not summed across sub-daily steps
> Taking a single 3-hourly value gives 1/8 the correct daily precipitation. LDNDC simulates near-drought conditions.
> See diagnostic triplet dt_014.

> **PITFALL**: Inconsistent soil between VIC and LDNDC
> If VIC and LDNDC use different soil databases, the coupled simulation has physically inconsistent soil properties. Always derive LDNDC soil from VIC params.
> See diagnostic triplet dt_015.

> **PITFALL**: VIC bulk density in kg/m3 vs. LDNDC in g/cm3
> VIC stores bulk density as kg/m3 (e.g., 1350). LDNDC expects g/cm3 (1.35). Forgetting to divide by 1000 causes porosity calculation to produce negative values and segfault.

> **PITFALL**: VIC has no pH or organic carbon
> VIC soil param file does not contain pH or organic carbon. These MUST come from HWSD separately (via hwsd_to_ldndc_soil). Do not leave them as zero -- zero pH causes numerical instability, zero corg means no decomposition.

---

*This skill document is part of the ldndc-knowledge-infrastructure package.*
*Stage 10 of 10 | Tools used: vic_to_ldndc_climate, vic_to_ldndc_soilwater, vic_soil_to_ldndc_site | Related triplets: dt_014, dt_015*
