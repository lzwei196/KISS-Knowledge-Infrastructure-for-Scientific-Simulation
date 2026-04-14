> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model.
>
>
> Before starting, run: `python preflight_check.py` (in this KI directory)
> to verify that the model binary/package and required data are available.
>
> **DEBUGGING PROTOCOL** — When something goes wrong, follow this order:
> 1. **Check triplets** — `diagnostics/triplets.yaml` may already cover this error
> 2. **Read official docs** — The model's own documentation for expected formats/units
> 3. **Find working examples** — Check `outputs/` or the model's shipped test data
> 4. **Fix the tool** — With knowledge of what "correct" looks like
>
> Do NOT write custom debug scripts. The answers are in the docs and examples.

# QUINCY (QUantifying Interactions between terrestrial Nutrient CYcles) -- Knowledge Infrastructure

**Package**: `kdt-quincy` v1.0.0
**Model**: QUINCY (Thum et al. 2019, GMD)
**Domain**: Terrestrial biogeochemistry (coupled C-N-P cycling)
**Created by**: KDT Auto-Dissection
**Last updated**: 2026-03-30
**Stats**: 4 tools | 1 skill document | ~1,800 lines of validated Python
**Validation status**: `real-data` (FI-Hyy Hyytiala, FLUXNET2015 monthly)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/FLUXNET/SKILL.md` for eddy covariance flux observations.


## Overview

This knowledge infrastructure enables autonomous simulation of terrestrial carbon,
nitrogen, and phosphorus cycling using QUINCY's process representations. The pipeline
converts global forcing data (FLUXNET2015, CMFD, MSWX) to QUINCY-expected inputs,
manages PFT parameter files, runs the QUINCY analytic model, and parses output
timeseries for GPP, NEE, Reco, LE, and H.

**What QUINCY does**: Point-scale coupled biogeochemical model simulating:
- **Photosynthesis**: Farquhar model with nitrogen limitation on Vcmax
  - Rubisco-limited (Wc) and RuBP-regeneration-limited (Wj) rates
  - Arrhenius temperature response with activation energies
  - Big-leaf canopy scaling via Beer's law light extinction
- **Stomatal conductance**: Ball-Berry type (g1 slope parameter)
  - VPD effect on Ci/Ca ratio
- **Coupled C-N-P cycling**: Leaf N content modulates Vcmax (N-limitation on GPP)
  - Vcmax25_eff = vcmax_n_slope * leaf_N (capped at Vcmax25)
  - P limitation on nutrient uptake (future extension)
- **Decomposition**: CENTURY-like multi-pool soil organic matter
  - Q10 temperature response
  - Bell-shaped moisture response from precipitation
- **Autotrophic respiration**: Maintenance (leaf, stem, root) + growth fraction
  - Arrhenius temperature dependence on maintenance components
  - Growth respiration as fixed fraction of NPP
- **Phenology**: Temperature-driven LAI for boreal evergreen
  - Gaussian temperature response maintaining minimum LAI year-round

**Key model characteristics**:
- Point-scale (single column, no spatial coupling)
- Monthly or daily timestep (analytic reimplementation uses monthly)
- Reads FLUXNET2015 CSV forcing directly
- Supports CMFD/MSWX as alternative forcing with unit conversion
- Coupled C-N cycling is the distinguishing feature vs. C-only models

---

## Pipeline Stages

| Stage | Name | Tool | Description |
|-------|------|------|-------------|
| S0 | Configuration | -- | Define site location, period, PFT type |
| S1 | Forcing conversion | `convert_forcing_to_quincy.py` | FLUXNET2015/CMFD/MSWX -> QUINCY forcing CSV |
| S2 | Parameter setup | `convert_parameters_to_quincy.py` | PFT params (Vcmax, Jmax, leaf_N, SLA, C:N, P) -> JSON |
| S3 | Model execution | `run_quincy.py` | Run QUINCY analytic model with forcing + params |
| S4 | Output parsing | `parse_output_quincy.py` | Model output -> timeseries CSV (GPP, NEE, Reco, LE, H) |

---

## Input File Formats

### Forcing data (FLUXNET2015 FULLSET CSV)

QUINCY expects the following meteorological forcing variables:

| Variable | FLUXNET2015 Column | Unit | Description |
|----------|-------------------|------|-------------|
| SW_IN | SW_IN_F | W/m2 | Incoming shortwave radiation |
| TA | TA_F | deg C | Air temperature at 2m |
| VPD | VPD_F | hPa | Vapor pressure deficit |
| PRECIP | P_F | mm/day (monthly mean) | Precipitation |
| CO2 | CO2_F_MDS | ppm | Atmospheric CO2 concentration |

**Missing value**: -9999 in FLUXNET2015 (replaced with NaN during conversion).

### Alternative forcing (CMFD/MSWX)

| Source | Variable | Source Unit | QUINCY Unit | Conversion |
|--------|----------|------------|-------------|------------|
| CMFD | Precipitation | kg/m2/s | mm/day | multiply by 86400 |
| CMFD | Temperature | K | deg C | subtract 273.15 |
| MSWX | Precipitation | mm/3hr | mm/day | sum 8 steps |
| MSWX | Temperature | K | deg C | subtract 273.15 |
| Both | SW radiation | W/m2 | W/m2 | (no conversion) |

### Observation data (FLUXNET2015 FULLSET CSV)

| Variable | FLUXNET2015 Column | Unit | Description |
|----------|-------------------|------|-------------|
| GPP | GPP_NT_VUT_REF | umol CO2/m2/s | Gross primary production |
| NEE | NEE_VUT_REF | umol CO2/m2/s | Net ecosystem exchange |
| Reco | RECO_NT_VUT_REF | umol CO2/m2/s | Ecosystem respiration |
| LE | LE_F_MDS | W/m2 | Latent heat flux |
| H | H_F_MDS | W/m2 | Sensible heat flux |

---

## Parameter Reference

### Photosynthesis Parameters

| Parameter | Symbol | Default (ENF) | Unit | Description |
|-----------|--------|--------------|------|-------------|
| vcmax25 | Vcmax25 | 45.0 | umol/m2/s | Max carboxylation rate at 25C |
| jmax_vcmax_ratio | Jmax/Vcmax | 1.9 | - | Electron transport / carboxylation ratio |
| alpha_j | alpha | 0.3 | mol/mol | Quantum yield of electron transport |
| theta_j | theta | 0.9 | - | Curvature of light response |
| ea_vcmax | Ea(Vcmax) | 65330 | J/mol | Activation energy for Vcmax |
| ea_jmax | Ea(Jmax) | 43540 | J/mol | Activation energy for Jmax |

### N-Limitation Parameters (QUINCY Key Feature)

| Parameter | Symbol | Default (ENF) | Unit | Description |
|-----------|--------|--------------|------|-------------|
| n_leaf_ref | Nleaf,ref | 1.8 | gN/m2_leaf | Reference leaf nitrogen content |
| vcmax_n_slope | dVcmax/dN | 25.0 | umol/s/gN | Vcmax per unit leaf N |

### Stomatal Conductance (Ball-Berry)

| Parameter | Symbol | Default (ENF) | Unit | Description |
|-----------|--------|--------------|------|-------------|
| g1_bb | g1 | 6.0 | - | Ball-Berry slope parameter |

### Respiration Parameters

| Parameter | Symbol | Default (ENF) | Unit | Description |
|-----------|--------|--------------|------|-------------|
| r_maint_leaf | Rm,leaf | 0.015 | umol/m2leaf/s | Leaf maintenance resp. at 25C |
| r_maint_stem | Rm,stem | 0.4 | umol/m2ground/s | Stem maintenance resp. at 25C |
| r_maint_root | Rm,root | 0.3 | umol/m2ground/s | Root maintenance resp. at 25C |
| r_growth_frac | f_growth | 0.25 | - | Growth respiration fraction of NPP |
| ea_rd | Ea(Rd) | 46390 | J/mol | Activation energy for dark respiration |

### Soil Decomposition (CENTURY-like)

| Parameter | Symbol | Default | Unit | Description |
|-----------|--------|---------|------|-------------|
| rh_base | Rh,base | 1.8 | umol/m2/s | Base heterotrophic resp. rate at Tref |
| rh_q10 | Q10 | 2.0 | - | Temperature sensitivity |
| rh_t_ref | Tref | 15.0 | deg C | Reference temperature for Rh |
| rh_precip_scale | - | 0.02 | - | Precipitation scaling for moisture |
| rh_precip_opt | Popt | 2.5 | mm/day | Optimal precipitation for decomposition |

### Phenology / LAI

| Parameter | Symbol | Default (ENF) | Unit | Description |
|-----------|--------|--------------|------|-------------|
| lai_max | LAImax | 5.5 | m2/m2 | Maximum LAI |
| lai_min | LAImin | 3.5 | m2/m2 | Minimum LAI (evergreen base) |
| lai_t_opt | Topt | 15.0 | deg C | Temperature for maximum LAI |
| lai_t_range | Trange | 15.0 | deg C | Temperature range for LAI response |

### C:N:P Stoichiometry

| Parameter | Symbol | Typical Range | Unit | Description |
|-----------|--------|--------------|------|-------------|
| cn_leaf | C:N_leaf | 30-60 | gC/gN | Leaf C:N ratio |
| cn_root | C:N_root | 40-80 | gC/gN | Fine root C:N ratio |
| cn_wood | C:N_wood | 200-500 | gC/gN | Wood C:N ratio |
| cp_leaf | C:P_leaf | 400-800 | gC/gP | Leaf C:P ratio |
| np_leaf | N:P_leaf | 10-25 | gN/gP | Leaf N:P ratio |

---

## Michaelis-Menten Kinetics (Farquhar Model Constants)

| Constant | Value at 25C | Activation Energy (J/mol) | Unit |
|----------|-------------|--------------------------|------|
| Kc | 404.9 | 79430 | umol/mol |
| Ko | 278.4 | 36380 | mmol/mol |
| Gamma* | 42.75 | 37830 | umol/mol |
| Oi | 210 | -- | mmol/mol |

---

## Output Variables

| Variable | Unit | Description |
|----------|------|-------------|
| GPP | umol CO2/m2/s | Gross primary production (Farquhar + canopy scaling) |
| NEE | umol CO2/m2/s | Net ecosystem exchange (Reco - GPP, micmet convention) |
| Reco | umol CO2/m2/s | Ecosystem respiration (Ra + Rh) |
| Ra | umol CO2/m2/s | Autotrophic respiration (maintenance + growth) |
| Rh | umol CO2/m2/s | Heterotrophic respiration (CENTURY-like) |
| LAI | m2/m2 | Leaf area index (temperature-driven) |
| LE | W/m2 | Latent heat flux (Penman-Monteith approximation) |
| H | W/m2 | Sensible heat flux (residual energy balance) |

---

## Unit Trap Table

| Variable | External Source | QUINCY Expected | Conversion | Trap |
|----------|---------------|-----------------|------------|------|
| Temperature | CMFD/MSWX: K | deg C | subtract 273.15 | Fatal if K used |
| VPD | FLUXNET2015: hPa | hPa | none | Model uses hPa internally |
| Precipitation | CMFD: kg/m2/s | mm/day | multiply by 86400 | 86400x error if raw |
| Precipitation | MSWX: mm/3hr | mm/day | sum 8 steps | 8x if single step |
| CO2 | FLUXNET2015: ppm | ppm | none | Not fraction |
| SW radiation | all sources: W/m2 | W/m2 | none | Check daylight avg |
| Missing values | FLUXNET2015: -9999 | NaN | replace | Corrupts statistics |
| Leaf N | literature: gN/m2 | gN/m2 | none | Not kgN or mgN |
| Vcmax25 | literature: umol/m2/s | umol/m2/s | none | Not nmol |
| SLA | literature: m2/kgC | m2/kgC | none | Not m2/gC (1000x) |

---

## Tool Reference

| Tool | Script | Purpose |
|------|--------|---------|
| Forcing converter | `tools/convert_forcing_to_quincy.py` | FLUXNET2015/CMFD/MSWX -> QUINCY forcing CSV |
| Parameter converter | `tools/convert_parameters_to_quincy.py` | PFT params -> validated JSON |
| Execution wrapper | `tools/run_quincy.py` | Run analytic QUINCY model |
| Output parser | `tools/parse_output_quincy.py` | Model output -> timeseries CSV |

---

## References

- Thum, T., et al. (2019). QUINCY v1.0: a model to QUantify Interactions between terrestrial Nutrient CYcles. *Geoscientific Model Development*, 12, 4781-4802.
- Farquhar, G.D., von Caemmerer, S., Berry, J.A. (1980). A biochemical model of photosynthetic CO2 assimilation in leaves of C3 species. *Planta*, 149, 78-90.
- Ball, J.T., Woodrow, I.E., Berry, J.A. (1987). A model predicting stomatal conductance and its contribution to the control of photosynthesis under different environmental conditions. *Progress in Photosynthesis Research*, 4, 221-224.
- Parton, W.J., et al. (1993). Observations and modeling of biomass and soil organic matter dynamics for the grassland biome worldwide. *Global Biogeochemical Cycles*, 7, 785-809.

---

## Notes and Caveats

1. **N-limitation is key**: QUINCY's distinguishing feature is that leaf N content directly modulates Vcmax. Without N data, the model falls back to reference N values.
2. **P cycling is structural**: The C:N:P stoichiometry is tracked but P limitation is not yet fully implemented in the analytic reimplementation.
3. **Monthly timestep**: The analytic reimplementation operates at monthly resolution. Daily forcing is aggregated.
4. **Daylength matters**: GPP is scaled by day fraction (daylength/24h) since FLUXNET GPP is a 24h mean.
5. **VPD affects stomata**: VPD reduces Ci/Ca ratio via Ball-Berry relationship, strongly controlling GPP in dry conditions.
6. **Q10 for Rh**: Heterotrophic respiration uses Q10=2.0 with a bell-shaped moisture response from precipitation.
7. **Calibration recommended**: Default parameters are for boreal ENF (Scots pine). Calibration against site data improves performance significantly.
8. **FLUXNET missing values**: -9999 must be replaced with NaN before any computation. Failure to do so corrupts means and statistics.
9. **CO2 trend**: If CO2 data is >50% missing, a linear trend (360 ppm in 1996 + 2.1 ppm/yr) is applied.
10. **NEE convention**: NEE = Reco - GPP (micrometeorological convention: positive = net source to atmosphere).
