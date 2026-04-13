# Parameter Configuration -- Skill Document

> **Stage ID**: s4_parameters
> **Pipeline order**: 4 of 7
> **Depends on**: s1_domain_setup, s3_decisions

## Purpose

Set site-specific parameters that override SUMMA's default lookup table values (VEGPARM.TBL, SOILPARM.TBL, GENPARM.TBL, MPTABLE.TBL). The trial parameters file is where calibrated values are applied. Parameters not in the trial file use defaults from the lookup tables based on vegTypeIndex and soilTypeIndex from the attributes file.

## Prerequisites

- [ ] Local attributes NetCDF exists (from Stage 1)
- [ ] Decisions file configured (from Stage 3) -- some parameters are only relevant for certain decisions
- [ ] Soil properties known (from HWSD or field data) for key soil parameters

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| attributes_nc | file | Stage 1 | SUMMA local attributes NetCDF |
| parameters | config | user/calibration | Dict of parameter_name -> value |

## Key Calibration Parameters

| Parameter | Typical Range | Units | What It Controls |
|-----------|--------------|-------|-----------------|
| k_soil | 1e-7 to 1e-3 | m/s | Saturated hydraulic conductivity |
| theta_sat | 0.3 to 0.55 | - | Porosity / saturated water content |
| theta_res | 0.01 to 0.15 | - | Residual water content |
| vGn_alpha | 0.5 to 5.0 | 1/m | van Genuchten alpha |
| vGn_n | 1.1 to 3.0 | - | van Genuchten n |
| critSoilWilting | 0.05 to 0.20 | - | Wilting point (controls ET shutoff) |
| critSoilTranspire | 0.15 to 0.40 | - | Transpiration threshold |
| heightCanopyTop | 0.1 to 40.0 | m | Canopy height (radiation, roughness) |
| rootingDepth | 0.5 to 3.0 | m | Root zone depth |
| qSurfScale | 10 to 100 | - | Surface runoff scaling |
| aquiferScaleFactor | 10 to 500 | m | Aquifer response time |
| tempCritRain | 272 to 275 | K | Rain/snow temperature threshold |
| frozenPrecipMultip | 0.8 to 1.5 | - | Snow undercatch correction |

## Procedure

### Step 1: Determine parameter sources

For each HRU, determine soil and vegetation parameters from:
1. **HWSD database**: Use `hwsd_soil_adapter.py` from HydroCraft for soil properties
2. **Literature**: Published values for similar basins
3. **Calibration**: If observed data is available (Stage 7 of HydroCraft workflow)
4. **Defaults**: SUMMA's lookup tables (acceptable for uncalibrated runs)

### Step 2: Generate trial parameters NetCDF

```bash
python tools/s4_parameters/set_trial_parameters.py \
  --attributes_nc outputs/<run>/summa_settings/attributes.nc \
  --output_nc outputs/<run>/summa_settings/trialParams.nc \
  --parameters '{"k_soil": 0.001, "theta_sat": 0.45, "tempCritRain": 273.15}'
```

**Expected result**: `trialParams.nc` created with specified parameters.

### Step 3: Copy parameter lookup tables

SUMMA needs four parameter table files in the settings directory:

```bash
cp model/summa/settings/VEGPARM.TBL outputs/<run>/summa_settings/
cp model/summa/settings/SOILPARM.TBL outputs/<run>/summa_settings/
cp model/summa/settings/GENPARM.TBL outputs/<run>/summa_settings/
cp model/summa/settings/MPTABLE.TBL outputs/<run>/summa_settings/
```

Also copy the parameter info files:

```bash
cp model/summa/settings/meta/localParamInfo.txt outputs/<run>/summa_settings/
cp model/summa/settings/meta/basinParamInfo.txt outputs/<run>/summa_settings/
```

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| Trial parameters | `outputs/<run>/summa_settings/trialParams.nc` | Has hru dimension matching attributes |
| Parameter tables | `outputs/<run>/summa_settings/VEGPARM.TBL` etc. | Files exist and are non-empty |

## Validation Checks

1. **Parameter names are valid**: `ncdump -h trialParams.nc` -- all variable names should be recognized SUMMA parameters.
2. **Values in range**: Check each parameter against PARAM_RANGES in set_trial_parameters.py.
3. **HRU dimension matches**: `ncdump -h trialParams.nc | grep hru` should match attributes.nc.

## Common Pitfalls

> **PITFALL**: Using wrong parameter name (e.g., 'ksat' instead of 'k_soil').
> SUMMA silently ignores unknown parameters and uses lookup table defaults. No error, wrong results. See dt_014.

> **PITFALL**: Setting theta_res >= theta_sat.
> Residual moisture must be less than saturated moisture. SUMMA may crash or produce NaN soil moisture.

---

*This skill document is part of the hydrocraft-summa knowledge infrastructure.*
*Stage 4 of 7 | Tools used: set_trial_parameters | Related triplets: dt_014*
