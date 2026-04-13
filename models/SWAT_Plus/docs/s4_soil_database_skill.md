# Soil Database Configuration — Skill Document

> **Stage ID**: s4_soil_database
> **Pipeline order**: 4 of 9
> **Depends on**: none (independent — can run in parallel with S1-S3)

## Purpose

The soils.sol file provides the physical and hydraulic properties that SWAT+ uses for infiltration, percolation, lateral flow, and sediment yield calculations. Each soil profile has multiple layers with properties controlling water movement and storage. Incorrect soil properties are difficult to detect because the model produces plausible but wrong results — the most dangerous failure mode.

## Prerequisites

Before starting this stage, verify:

- [ ] Soil data source is available:
  - **SSURGO** (US): Detailed county-level soil survey data
  - **HWSD** (global): `data/soil/HWSD_RASTER/hwsd.bil` + `data/forcing/huaihe_raw/soil/HWSD.mdb`
  - **SoilGrids** (global): Online API at soilgrids.org
- [ ] Basin boundary shapefile for spatial query
- [ ] Soil raster values (MUKEY or MU_GLOBAL) identified from S2 HRU definition

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| Soil source | string | User choice | hwsd, ssurgo, or soilgrids |
| Basin shapefile | file | S1 output | For spatial query extent |
| HWSD raster | file | data/soil/HWSD_RASTER/hwsd.bil | HWSD mapping units (global) |
| HWSD MDB | file | data/forcing/huaihe_raw/soil/HWSD.mdb | HWSD attribute database |
| Soil raster values | config | From S2 overlay | List of unique soil types in basin |

## Procedure

### Step 1: Extract soil properties from source database

```bash
python tools/s4/build_soils_database.py
```

For each soil type in the basin, extract:
- **Profile-level**: hydrologic group (HYDGRP A/B/C/D), maximum root depth (SOL_ZMX mm), anion exclusion, crack volume
- **Per-layer**: depth (SOL_Z mm), bulk density (SOL_BD g/cm3), available water capacity (SOL_AWC mm/mm), saturated hydraulic conductivity (SOL_K mm/hr), organic carbon (SOL_CBN %), clay/silt/sand (%), rock fragment (%), albedo, USLE K factor, electrical conductivity, calcium carbonate, pH

**Expected result**: Raw soil property table for all basin soil types.

### Step 2: Apply pedotransfer functions for missing properties

If source data lacks some properties (common for HWSD), estimate using pedotransfer functions:
- **AWC**: Saxton & Rawls (2006) from texture + organic matter
- **Ksat**: Saxton & Rawls from texture
- **USLE K**: Williams (1995) equation from texture + organic matter + structure
- **Bulk density**: from organic carbon and texture

**Expected result**: Complete property set for all layers.

### Step 3: Write soils.sol

The soils.sol format is unique — multi-line records:

```
soils.sol: written by SWAT+ knowledge infrastructure
  name           nly    hyd_grp     zmx    anion_excl    crk    texture
  soil_001       3      B           1500   0.50          0.50   SiL-SiCL-C
  dp            bd          awc         k           cbn         clay     silt     sand     rock     alb      usle_k   ec       cal      ph
  300.000       1.400       0.180       12.500      1.200       18.0     55.0     27.0     5.0      0.12     0.32     0.00     0.00     6.5
  800.000       1.450       0.150       6.200       0.800       25.0     50.0     25.0     3.0      0.12     0.35     0.00     0.00     6.8
  1500.000      1.500       0.120       2.100       0.400       35.0     42.0     23.0     2.0      0.12     0.38     0.00     0.00     7.0
```

Profile line comes first, then one line per layer. Layers must be in order of increasing depth.

**Expected result**: soils.sol file in TxtInOut.

### Step 4: Validate soil properties

```bash
python tools/s4/validate_soil_properties.py
```

**Expected result**: All properties within valid physical ranges.

**If this fails**: See diagnostic triplet dt_006.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| soils.sol | `TxtInOut/soils.sol` | Profile + layer lines for each soil; properties in valid ranges |
| nutrients.sol | `TxtInOut/nutrients.sol` | Initial nutrient pools (optional, SWAT+ can initialize from soil CBN) |

## Validation Checks

1. **Texture sum**: CLAY + SILT + SAND = 100% +/- 1% for each layer.
   - If wrong: See diagnostic triplet dt_006

2. **Bulk density range**: 0.9 - 2.5 g/cm3. Values outside this indicate data errors.

3. **AWC range**: 0.0 - 0.5 mm/mm. Values > 0.5 are physically impossible.

4. **Layer depth ordering**: Each layer's SOL_Z must be greater than the previous layer's.

5. **Layer count**: Number of layer lines must match `nly` in the profile line.
   - Mismatch causes SWAT+ to read wrong data — silent error.

6. **Ksat > 0**: Zero Ksat means no water movement — causes ponding and unrealistic runoff.

## Common Pitfalls

> **PITFALL**: Layer count mismatch between profile line and actual layer lines
> If the profile line says `nly=3` but only 2 layer lines follow, SWAT+ reads the next soil's profile line as a layer line. This corrupts all subsequent soil data silently.
> **Do this instead**: Always verify layer count matches nly value after generating soils.sol.
> See diagnostic triplet dt_006.

> **PITFALL**: AWC and Ksat in wrong units
> HWSD provides Ksat in cm/day; SWAT+ expects mm/hr. Factor = 10/24 = 0.417. Getting this wrong makes infiltration 24x too fast or slow.
> **Do this instead**: Always verify units match the soils.sol specification.

> **PITFALL**: Missing USLE K factor
> If USLE K = 0, SWAT+ computes zero sediment yield for that soil. The model runs fine but all sediment/nutrient transport is wrong for those HRUs.
> **Do this instead**: Estimate USLE K from texture using Williams (1995) equation if not available from source database.

---

*This skill document is part of the SWAT+ knowledge infrastructure.*
*Stage 4 of 9 | Tools used: build_soils_database, validate_soil_properties | Related triplets: dt_006*
