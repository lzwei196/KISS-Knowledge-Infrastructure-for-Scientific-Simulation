# Model Decisions Configuration -- Skill Document

> **Stage ID**: s3_decisions
> **Pipeline order**: 3 of 7
> **Depends on**: none (can run in parallel with Stage 1)

## Purpose

Configure SUMMA's model decisions -- the feature that distinguishes SUMMA from all other hydrologic models. Each decision selects one physics option from a set of alternatives. There are 35 decision categories covering snow, soil, vegetation, radiation, groundwater, and numerical methods. The decisions file determines **which equations SUMMA solves**, not just parameter values. This enables systematic evaluation of model structural uncertainty.

## Prerequisites

Before starting this stage, verify:

- [ ] Understanding of the basin's dominant hydrologic processes (snow-dominated? groundwater-dominated? forest canopy?)
- [ ] Decision on whether to compare multiple physics options (Stage 7) or run a single configuration

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| decisions | config | user/defaults | Dictionary of decision_name to option_value |

## Complete Decision Reference

### Soil and Vegetation Tables

| Decision | Options | Recommendation |
|----------|---------|----------------|
| soilCatTbl | `STAS`, `STAS-RUC`, `ROSETTA` | `STAS` for most cases |
| vegeParTbl | `USGS`, `MODIFIED_IGBP_MODIS_NOAH` | Must match land cover raster classification |

### Stomatal Resistance (controls ET partitioning)

| Decision | Options | Recommendation |
|----------|---------|----------------|
| soilStress | `NoahType`, `CLM_Type`, `SiB_Type` | `NoahType` is most common |
| stomResist | `BallBerry`, `Jarvis`, `simpleResistance` | `BallBerry` for most; `Jarvis` for grasslands |

### Snow Physics (critical for cold regions)

| Decision | Options | Impact |
|----------|---------|--------|
| snowLayers | `jrdn1991`, `CLM_2010` | Snow layer management algorithm; CLM_2010 is newer |
| compaction | `consettl`, `anderson` | Snow compaction; anderson is empirical, robust |
| thCondSnow | `tyen1965`, `melr1977`, `jrdn1991`, `smnv2000` | Snow thermal conductivity |
| snowDenNew | `hedAndPom`, `anderson`, `pahaut_76`, `constDens` | New snow density |
| alb_method | `conDecay`, `varDecay` | Snow albedo decay |
| snowIncept | `stickySnow`, `lightSnow` | Canopy snow interception |

### Soil Hydraulics (controls runoff generation)

| Decision | Options | Impact |
|----------|---------|--------|
| f_Richards | `moisture`, `mixdform` | Richards equation form; `mixdform` more stable |
| groundwatr | `qTopmodl`, `bigBuckt`, `noXplict` | Groundwater representation |
| hc_profile | `constant`, `pow_prof` | Hydraulic conductivity profile |
| thCondSoil | `funcSoilWet`, `mixConstit`, `hanssonVZJ` | Soil thermal conductivity |

### Boundary Conditions

| Decision | Options | When to change |
|----------|---------|----------------|
| bcUpprTdyn | `presTemp`, `nrg_flux`, `zeroFlux` | `nrg_flux` default; `presTemp` for prescribed surface T |
| bcLowrTdyn | `presTemp`, `zeroFlux` | `zeroFlux` unless deep temperature data available |
| bcUpprSoiH | `presHead`, `liq_flux` | `liq_flux` for most cases |
| bcLowrSoiH | `presHead`, `bottmPsi`, `drainage`, `zeroFlux` | `drainage` for free drainage at bottom |

### Radiation

| Decision | Options | Impact |
|----------|---------|--------|
| canopySrad | `noah_mp`, `CLM_2stream`, `UEB_2stream`, `NL_scatter`, `BeersLaw` | Canopy shortwave radiation transfer |
| canopyEmis | `simplExp`, `difTrans` | Canopy longwave emission |

### Numerical Methods

| Decision | Options | Impact |
|----------|---------|--------|
| num_method | `itertive`, `non_iter`, `itersurf` | `itertive` most robust, `itersurf` fastest |
| fDerivMeth | `numericl`, `analytic` | `numericl` safer, `analytic` faster |

## Procedure

### Step 1: Choose decisions for your basin type

**Snow-dominated basin** (alpine, high-latitude):
- snowLayers: CLM_2010, compaction: anderson, thCondSnow: smnv2000
- alb_method: varDecay, snowDenNew: anderson

**Humid, forested basin**:
- stomResist: BallBerry, canopySrad: CLM_2stream
- groundwatr: qTopmodl (TOPMODEL-based)

**Semi-arid basin**:
- stomResist: Jarvis (simpler, less data-hungry)
- groundwatr: bigBuckt or noXplict
- bcLowrSoiH: drainage (free drainage)

### Step 2: Generate decisions file

```bash
python tools/s3_decisions/configure_decisions.py \
  --output outputs/<run>/summa_settings/decisions.txt \
  --use_defaults \
  --decisions '{"snowLayers": "CLM_2010", "stomResist": "BallBerry"}'
```

**Expected result**: `decisions.txt` with one keyword-option pair per line.

**If this fails**: See diagnostic triplet dt_009.

### Step 3: Verify decisions

Open the decisions file and check that each line has a valid keyword and option. Pay special attention to SUMMA's abbreviated spelling:
- `itertive` (NOT `iterative`)
- `numericl` (NOT `numerical`)
- `consettl` (NOT `constant_settling`)

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| Decisions file | `outputs/<run>/summa_settings/decisions.txt` | All keywords have valid options |

## Validation Checks

1. **No unknown keywords**: Every keyword in the file should be in the VALID_DECISIONS catalog.
2. **No typos in options**: Cross-reference with configure_decisions.py VALID_DECISIONS.
3. **Compatible combinations**: Check that f_Richards matches bcLowrSoiH, that groundwatr matches spatial_gw.

## Common Pitfalls

> **PITFALL**: Using 'iterative' instead of 'itertive'.
> SUMMA uses intentionally abbreviated option names. The correct spelling is `itertive`. See dt_009.

> **PITFALL**: Setting Ball-Berry options when stomResist is Jarvis.
> Ball-Berry sub-options (bbTempFunc, etc.) are ignored when stomResist is Jarvis or simpleResistance. No error, but confusing.

> **PITFALL**: Using pressure head lower BC with moisture-form Richards.
> `bcLowrSoiH: presHead` requires `f_Richards: mixdform`. Using it with `moisture` causes numerical instability.

---

*This skill document is part of the hydrocraft-summa knowledge infrastructure.*
*Stage 3 of 7 | Tools used: configure_decisions | Related triplets: dt_009*
