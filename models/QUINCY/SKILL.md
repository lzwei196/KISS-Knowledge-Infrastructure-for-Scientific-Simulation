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

<!-- KI-MAP:BEGIN (projected by generate_skill_map.py — edit the KI, not this table) -->
## KI map — what to read, and when

| when you need | read | why |
|---|---|---|
| FIRST, always | `preflight_check.py` | run it (`python preflight_check.py`): proves env/binary/data are usable and emits a machine-readable `PREFLIGHT_REPORT=` line. Do not debug a run that never had a healthy environment. |
| to run the pipeline stages | `tools/` (4 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (5 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (25 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (15 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/convert_forcing_to_quincy.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing_to_quincy.py --help` |
| `tools/convert_parameters_to_quincy.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_parameters_to_quincy.py --help` |
| `tools/parse_output_quincy.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_output_quincy.py --help` |
| `tools/run_quincy.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_quincy.py --help` |

*4 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

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

### Stage Skill Documents

- [S0 Configuration](docs/s0_configuration.md)
- [S1 Forcing conversion](docs/s1_forcing_conversion.md)
- [S2 Parameter setup](docs/s2_parameter_setup.md)
- [S3 Model execution](docs/s3_model_execution.md)
- [S4 Output parsing](docs/s4_output_parsing.md)

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

## 6. Output Description

Source of truth: `dag.yaml`. If this section and the dag disagree, the dag wins.

**Headline output** (`validation_rank: 1`):

> `GPP` -- Gross primary production (Farquhar co-limitation with N-limited Vcmax and Beer's-law canopy scaling), scaled by day fraction (daylength/24) to a 24-h mean. (`umol CO2/m2/s`)

| Output variable (dag `var`) | Rank | Emitted in | Unit | Description |
|-----------------------------|------|------------|------|-------------|
| GPP | 1 | results CSV | umol CO2/m2/s | Gross primary production (Farquhar co-limitation with N-limited Vcmax and Beer's-law canopy scaling), scaled by day fraction (daylength/24) to a 24-h mean. |
| LE | 2 | results CSV | W/m2 | Latent heat flux (water-use-efficiency approximation from GPP; simplified Penman-Monteith). |
| NEE | 3 | results CSV | umol CO2/m2/s | Net ecosystem exchange = Reco - GPP (micrometeorological convention, positive = net source to atmosphere). |
| Reco | 4 | results CSV | umol CO2/m2/s | Ecosystem respiration (Ra + Rh). |
| Ra | 5 | results CSV | umol CO2/m2/s | Terrestrial ecosystem autotrophic respiration (maintenance + growth), coupled to instantaneous GPP. |
| Rh | 6 | results CSV | umol CO2/m2/s | Soil heterotrophic respiration in the terrestrial ecosystem (CENTURY-like Q10 temperature response with a bell-shaped precipitation moisture response). |
| LAI | 7 | results CSV | m2/m2 | Vegetation leaf area index from temperature-driven (Gaussian) phenology. |
| H | 8 | results CSV | W/m2 | Terrestrial ecosystem sensible heat flux as the Rn-LE residual (no independent energy-balance closure). |

Other observable dag outputs: `NEE`, `Reco`, `Ra`, `Rh`, `LAI`, `LE`, `H`.

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

## 8. Unit Table / Unit Conversion Table

Source of truth: `docs/format_spec.yaml`, `dag.yaml`, and the existing input/unit-trap tables above. Verify source-data attributes before running a new dataset.

| Variable | Source unit (verified in this KI) | Model/output unit | Conversion | Type |
|----------|-----------------------------------|-------------------|------------|------|
| SW_IN | W/m2 | W/m2 | none | identity |
| TA | K for CMFD/MSWX; deg C for FLUXNET2015 `TA_F` after conversion | deg C | subtract 273.15 when source is K | additive |
| VPD | hPa for FLUXNET2015 `VPD_F` | hPa | none | identity |
| PRECIP | kg/m2/s for CMFD; mm/3hr for MSWX; FLUXNET2015 `P_F` to mm/day monthly mean | mm/day | multiply CMFD by 86400; sum 8 MSWX steps | multiplicative / aggregation |
| CO2 | ppm for FLUXNET2015 `CO2_F_MDS` | ppm | none | identity |
| DAYLENGTH | derived hours | hours | derived from latitude and day-of-year | derived |
| GPP | model result | umol CO2/m2/s | none after model execution | output |
| NEE | model result | umol CO2/m2/s | none after model execution | output |
| Reco | model result | umol CO2/m2/s | none after model execution | output |
| Ra | model result | umol CO2/m2/s | none after model execution | output |
| Rh | model result | umol CO2/m2/s | none after model execution | output |
| LAI | model result | m2/m2 | none after model execution | output |
| LE | model result | W/m2 | none after model execution | output |
| H | model result | W/m2 | none after model execution | output |

**Output sign convention**: `NEE = Reco - GPP`; positive NEE is net source to atmosphere.

---

## 11. Validated Results

Source of truth: `knowledge_infrastructure.yaml` for recorded KI validation status and `docs/validation_convention.yaml` for cited performance bars. Do not replace null convention bands with remembered thresholds.

### Recorded KI Validation Status

| Property | Value |
|----------|-------|
| Validation tier | not_runnable |
| Tier justification | measured: NSE=0.952, R=0.980 |
| Recorded metric | best_nse = 0.9516 |
| Recorded metric | best_r = 0.9804 |

`bengbu_summary.json` contains summary statistics for 132 valid rows for each model output and an empty `metrics` object; the manifest metrics above are the only scored metrics currently recorded in the KI manifest.

### Performance Bars From Convention

| Dag variable | Metric | Direction | Very good band | Good band | Satisfactory band | Convention cites |
|--------------|--------|-----------|----------------|-----------|-------------------|------------------|
| GPP | r2 | maximize | no cited threshold (tramontana2016, thum2025, thum2019) | no cited threshold (tramontana2016, thum2025, thum2019) | 0.7 (tramontana2016, thum2025, thum2019) | tramontana2016, thum2025, thum2019 |
| GPP | pbias | zero_centered | no cited threshold (thum2025, miinalainen2025, yang2023) | no cited threshold (thum2025, miinalainen2025, yang2023) | 20.0 (thum2025, miinalainen2025, yang2023) | thum2025, miinalainen2025, yang2023 |
| NEE | nse | maximize | no cited threshold (no cites in convention) | no cited threshold (no cites in convention) | no cited threshold (no cites in convention) | none |
| NEE | r2 | maximize | no cited threshold (no cites in convention) | no cited threshold (no cites in convention) | no cited threshold (no cites in convention) | none |

For GPP `pbias`, apply the `zero_centered` convention as absolute percent bias around zero; the cited satisfactory band is `20.0` (thum2025, miinalainen2025, yang2023). For NEE, the convention explicitly withholds numeric NSE and r2 pass bands.

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
