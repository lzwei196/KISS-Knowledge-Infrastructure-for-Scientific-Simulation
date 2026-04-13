# GLM 3.3.3 + AED2 -- Capability Inventory

**Model**: GLM v3.3.3 (General Lake Model) + AED2 water quality library
**KDT Stage**: s2 (Capability Discovery)
**Date**: 2026-04-01
**Assessed by**: KDT v5.0

---

## 1. Full Capability List

### 1A. GLM Core Hydrodynamics

| # | Capability | Status | Current KI Coverage | Notes |
|---|-----------|--------|-------------------|-------|
| 1 | 1D vertical thermal stratification (adaptive Lagrangian layers) | DONE | Full pipeline (s1-s10), validated Miyun | 13 tools, 27 triplets |
| 2 | Surface/deep mixing (wind stirring, convective overturn, KH) | DONE | generate_glm_nml.py handles mixing params | coef_wind_stir, coef_mix_conv, coef_mix_hyp |
| 3 | Water balance (inflow, outflow, rainfall, evaporation, seepage) | PARTIAL | Inflow/outflow tools exist; precip was missing in validation (dt_024) | Seepage not explicitly tested |
| 4 | Ice cover simulation (snow-ice, growth/decay, albedo feedback) | DONE | Critical finding dt_027 documented; dt_iceon_avg required | Validated on Miyun (71 ice days/yr) |
| 5 | Light penetration (multi-band Beer-Lambert extinction) | DONE | Kw parameter documented (dt_019) | Single-band in practice |
| 6 | Inflow dynamics (density-driven insertion at neutral buoyancy) | DONE | convert_inflow_to_glm.py + temp estimation | Validated with CaMa-Flood coupling |
| 7 | Outflow/withdrawal at specified elevation | DONE | configure_outflow.py supports 4 modes | natural/constant/scheduled/balance |
| 8 | Sediment heat flux | PARTIAL | sed_temp_mean/amplitude in namelist | No dedicated tool or calibration guidance |
| 9 | Multi-band light extinction (PAR, UV, NIR) | TODO | Only single Kw parameter used | GLM supports Kw_blue, Kw_green, Kw_red |
| 10 | Bubble plume / artificial destratification | TODO | Not implemented in KI | GLM supports &bubbler block |
| 11 | Multi-lake chains (connected lakes) | TODO | KI handles single lake only | GLM supports connected lake setups |
| 12 | Adaptive layer management tuning | PARTIAL | min/max layer thickness documented | No guidance for very deep (>100m) or shallow (<3m) lakes |

### 1B. AED2 Water Quality Modules

| # | Module | Status | Current KI Coverage | Notes |
|---|--------|--------|-------------------|-------|
| 13 | Dissolved oxygen (DO) | PARTIAL | generate_aed_config.py generates &aed_oxygen | Template with defaults only; no calibration guidance, no validation |
| 14 | Nitrogen (ammonium, nitrate, nitrification, denitrification) | PARTIAL | generate_aed_config.py generates &aed_nitrogen | Template only; no validation against observations |
| 15 | Phosphorus (SRP/FRP, sediment release) | PARTIAL | generate_aed_config.py generates &aed_phosphorus | Template only |
| 16 | Organic matter (POC, DOC, PON, DON, POP, DOP) | PARTIAL | generate_aed_config.py generates &aed_organic_matter | Template only |
| 17 | Silica | PARTIAL | Code exists in generate_aed_config.py | Not in default module set |
| 18 | Carbon / DIC / pH / alkalinity | PARTIAL | Code exists in generate_aed_config.py (&aed_carbon) | Includes atmospheric CO2 exchange |
| 19 | Phytoplankton (multiple functional groups) | DONE | generate_aed_config.py with --phyto_groups; 4 preset groups (diatom, green, cyano, crypto); full growth/limitation params | Validated template; parse_aed_output.py for Chl-a analysis |
| 20 | Zooplankton | PARTIAL | generate_aed_config.py generates &aed_zooplankton template | Basic single-group template; no validation |
| 21 | Sediment diagenesis (dynamic sediment flux) | PARTIAL | Only 'Constant2D' sedflux model | Full CANDI/diagenesis model not implemented |
| 22 | Iron/manganese cycling | TODO | Not in AVAILABLE_MODULES | AED2 supports &aed_iron, &aed_manganese |
| 23 | Pathogens | TODO | Listed in AVAILABLE_MODULES but NO template | AED2 supports E. coli, enterococci |
| 24 | Tracer (conservative/age) | TODO | Listed in AVAILABLE_MODULES but NO template | Useful for residence time studies |
| 25 | Totals (TN, TP, TOC aggregation) | PARTIAL | generate_aed_config.py generates &aed_totals | Works only if component modules are enabled |
| 26 | Inflow water quality loading | DONE | configure_inflow_wq.py: trophic presets, seasonal patterns, custom concentrations | 4 trophic presets, 11 WQ variables, phyto groups |
| 27 | AED2 calibration | TODO | No calibration tool for WQ parameters | calibrate_glm.py only handles thermal params |

### 1C. Coupling and Integration

| # | Capability | Status | Current KI Coverage | Notes |
|---|-----------|--------|-------------------|-------|
| 28 | GLM to CaMa-Flood outflow | DONE | glm_to_cama_outflow.py | Flow + temperature |
| 29 | CaMa-Flood/VIC to GLM inflow | DONE | convert_inflow_to_glm.py | Discharge only |
| 30 | SWAT+ nutrient loading to GLM-AED2 | TODO | Mentioned in coupling table but no tool | Requires inflow WQ CSV generation |
| 31 | CMIP6 climate scenario forcing | TODO | Mentioned but no delta-change tool | Need climate perturbation on met CSV |
| 32 | Multi-source forcing (CMFD/MSWX/NASA_POWER) | DONE | Adapter scripts exist | Via cmfd_to_glm.py |
| 33 | VIC forcing conversion | DONE | convert_met_to_glm.py | VP to RH, mm to m/day |

---

## 2. Required Input Files per Capability

| Capability | Required Inputs | Status |
|-----------|----------------|--------|
| Core thermal (1-7) | morphometry.json, met CSV, inflow CSV, outflow config, init profiles, glm3.nml | All tools exist |
| Ice simulation (4) | Same as core + dt_iceon_avg in &snowice | Tool exists, triplet documented |
| AED2 basic (13-17, 21, 25) | aed2.nml + glm3.nml with aed_filename | generate_aed_config.py exists |
| AED2 phytoplankton (19) | aed2.nml &aed_phytoplankton block | generate_aed_config.py --phyto_groups; parse_aed_output.py |
| AED2 zooplankton (20) | aed2.nml &aed_zooplankton block | generate_aed_config.py (basic template) |
| AED2 inflow WQ (26) | Inflow CSV with nutrient columns (NIT_nit, NIT_amm, PHS_frp, etc.) | configure_inflow_wq.py with trophic presets |
| Multi-lake chains (11) | Multiple glm3.nml files with linked inflow/outflow | NO orchestration tool |
| Bubble plume (10) | &bubbler block in glm3.nml | NO tool |

---

## 3. Required Data KIs per Capability

| Capability | Data KI Needed | Data KI Status | Path |
|-----------|---------------|---------------|------|
| Core thermal | CMFD or MSWX (meteorology) | EXISTS | data_ki/CMFD/, data_ki/MSWX/ |
| Core thermal | HydroLAKES (morphometry) | EXISTS (download needed) | data_ki/HydroLAKES/ |
| Core thermal | NASA_POWER (quick demo) | EXISTS | data_ki/NASA_POWER/ |
| Inflow | CaMa-Flood routing output | EXISTS (pipeline output) | - |
| AED2 DO validation | WQP lake profiles | EXISTS | data_ki/WQP/ |
| AED2 temp validation | WQP lake profiles | EXISTS | data_ki/WQP/ |
| AED2 nutrients validation | WQP (N, P, Si) | EXISTS | data_ki/WQP/ |
| AED2 chlorophyll validation | WQP chlorophyll-a | EXISTS | data_ki/WQP/ |
| AED2 phytoplankton params | Literature / AED2 defaults | NOT NEEDED (built-in) | - |
| Multi-lake chains | GRanD (reservoir database) | EXISTS | data_ki/GRanD/ |
| Sediment heat flux | Literature by latitude | NOT KI (parametric) | - |

---

## 4. Priority Ranking for Next Implementation

| Priority | Capability | Effort | Impact | Rationale |
|----------|-----------|--------|--------|-----------|
| ~~P1~~ | ~~AED2 phytoplankton template (#19)~~ | ~~MEDIUM~~ | ~~HIGH~~ | **DONE** — generate_aed_config.py with 4 phyto groups + parse_aed_output.py |
| ~~P2~~ | ~~AED2 inflow water quality loading (#26)~~ | ~~MEDIUM~~ | ~~HIGH~~ | **DONE** — configure_inflow_wq.py with 4 trophic presets |
| P3 | AED2 calibration tool (#27) | HIGH | HIGH | Current calibrate_glm.py only does thermal; WQ parameters need separate calibration against WQP data |
| ~~P4~~ | ~~AED2 zooplankton template (#20)~~ | ~~LOW~~ | ~~MEDIUM~~ | **DONE** — basic template in generate_aed_config.py |
| P5 | SWAT+ nutrient coupling (#30) | MEDIUM | MEDIUM | Enables full watershed-to-lake nutrient chain |
| P6 | Multi-band light extinction (#9) | LOW | LOW | Refinement of existing Kw; matters for deep clear lakes |
| P7 | Multi-lake chains (#11) | HIGH | LOW | Rare use case; requires orchestration wrapper |
| P8 | Bubble plume (#10) | LOW | LOW | Niche use case for reservoir management |
| P9 | Iron/manganese (#22) | MEDIUM | LOW | Specialized WQ; relevant for drinking water reservoirs |
| P10 | CMIP6 climate scenarios (#31) | LOW | MEDIUM | Delta-change method is straightforward |

---

## 5. Gap Summary

| Category | Done | Partial | TODO | Coverage |
|----------|------|---------|------|----------|
| Core hydrodynamics (1-7) | 6 | 1 | 0 | 93% |
| Advanced hydrodynamics (8-12) | 0 | 2 | 3 | 20% |
| AED2 water quality (13-27) | 2 | 8 | 5 | 40% |
| Coupling (28-33) | 4 | 0 | 2 | 67% |
| **TOTAL** | **12** | **11** | **10** | **53%** |

**Update (2026-04-03)**: Phytoplankton (#19) and inflow WQ loading (#26) are now DONE. AED2 coverage improved from 23% to 40%. Three new tools added: generate_aed_config.py updated with phytoplankton templates (4 functional groups), configure_inflow_wq.py for nutrient inflow loading, and parse_aed_output.py for WQ output analysis. Remaining major gap: AED2 calibration tool (#27) for WQ parameter tuning against observations.
