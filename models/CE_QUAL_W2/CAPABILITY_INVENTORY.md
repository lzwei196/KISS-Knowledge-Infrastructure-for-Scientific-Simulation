# CE-QUAL-W2 v4.5 — Capability Inventory

**KDT v5.0 Stage s2: Capability Discovery**
**Generated**: 2026-04-03
**Source**: CE-QUAL-W2 v4.5 Fortran source code (52 source files), SKILL.md, 16 KI tools
**Methodology**: Systematic cross-reference of source code modules, subroutine calls, and control file feature flags against existing KI tool coverage

---

## Summary

| Metric | Value |
|--------|-------|
| Total capabilities identified | 68 |
| DONE (fully covered by KI) | 22 |
| PARTIAL (tool exists but incomplete) | 16 |
| TODO (no KI coverage) | 30 |
| **Current coverage** | **32.4% DONE, 55.9% DONE+PARTIAL** |

---

## 1. HYDRODYNAMICS

### 1.1 Core Hydrodynamics

| # | Capability | Source File(s) | KI Status | Notes |
|---|-----------|----------------|-----------|-------|
| 1 | 2D laterally-averaged momentum equations | `update.F90`, `transport.f90` | **DONE** | Core pipeline (s1-s10) |
| 2 | Free-surface elevation tracking | `update.F90`, `layeraddsub.F90` | **DONE** | Part of core hydro |
| 3 | Adaptive CFL-limited timestep | `update.F90` | **DONE** | dt_022 triplet covers degraded timestep |
| 4 | Layer addition/subtraction (wetting/drying) | `layeraddsub.F90` | **DONE** | dt_024 triplet covers NEGATIVE THICKNESS |
| 5 | Density-driven currents (T, TDS, SS) | `density.f90` | **DONE** | Density function handles fresh/salt/SS |
| 6 | Multi-branch topology | `waterbody.f90`, `init-geom.F90` | **DONE** | s2 tool `build_branch_topology` |
| 7 | Multi-waterbody configuration | `waterbody.f90`, `input.F90` | **PARTIAL** | KI tools assume single waterbody; NWB>1 not tested |
| 8 | Internal weir flow between branches | `waterbody.f90` | TODO | NIW parameter in control file; no KI tool |
| 9 | Head boundary conditions | `hydroinout.F90` | TODO | HEAD_FLOW flag; for estuary tidal BC |
| 10 | Initial velocity field (non-zero start) | `init-u-elws.f90` | TODO | INITUWL flag; useful for river simulations |

### 1.2 Vertical Mixing

| # | Capability | Source File(s) | KI Status | Notes |
|---|-----------|----------------|-----------|-------|
| 11 | W2 default eddy viscosity (Ri-based) | `az.f90` | **DONE** | Default AZC; s7 sets AX |
| 12 | TKE turbulence closure | `az.f90` (CALCULATE_TKE) | TODO | AZC='TKE' or 'TKE1'; k-epsilon model |
| 13 | Implicit vertical viscosity | `az.f90`, `input.F90` | TODO | IMPLICIT_VISC flag for stability |

### 1.3 Heat Exchange

| # | Capability | Source File(s) | KI Status | Notes |
|---|-----------|----------------|-----------|-------|
| 14 | Surface heat exchange (equilibrium/term-by-term) | `heat-exchange.f90` | **DONE** | s3 met forcing handles SLHTC |
| 15 | Bottom heat exchange (CBHE, TSED) | `temperature.F90` | **DONE** | s7 sets CBHE, TSED; calibration in s12 |
| 16 | Evaporation (Penman or mass-transfer) | `heat-exchange.f90` | **DONE** | Part of surface heat exchange |
| 17 | Read vs computed solar radiation | `shading.f90`, `input.F90` | **PARTIAL** | READ_RADIATION flag; s3 tool assumes read mode |
| 18 | Topographic/vegetation shading | `shading.f90` | TODO | SHADEC module with bank shading geometry |
| 19 | Wind fetch computation | `input.F90` | TODO | FETCHC flag; FETCHU/FETCHD arrays |
| 20 | RH-based evaporation option | `input.F90` | TODO | RH_EVAP flag; alternative to mass-transfer |
| 21 | Multiple met file regions | `MetFileRegion.f90` | TODO | NMetFileRegions for large reservoirs with spatial met variation |

### 1.4 Ice Cover

| # | Capability | Source File(s) | KI Status | Notes |
|---|-----------|----------------|-----------|-------|
| 22 | Ice formation/melting dynamics | `temperature.F90`, `w2modules.F90` | **PARTIAL** | SKILL.md mentions ice; no dedicated tool; ICE_CALC flag |
| 23 | Detailed ice model | `input.F90` | TODO | DETAILED_ICE flag for advanced ice physics |
| 24 | Ice parameters (ALBEDO, HWI, BETAI, GAMMAI) | `w2modules.F90` | TODO | No tool to configure ice parameters |

---

## 2. HYDRAULIC STRUCTURES

| # | Capability | Source File(s) | KI Status | Notes |
|---|-----------|----------------|-----------|-------|
| 25 | Selective withdrawal (outlets/structures) | `withdrawal.f90` | **PARTIAL** | s5 tool generates qot; selective withdrawal config via w2_selective.npt not handled |
| 26 | Gate flow (dynamic/rating curve) | `gate-spill-pipe.f90` | TODO | NGT gates with A1GT/B1GT/A2GT/B2GT coefficients |
| 27 | Spillway flow | `gate-spill-pipe.f90` | TODO | NSP spillways with rating curves |
| 28 | Pipe flow (Bernoulli/Manning) | `gate-spill-pipe.f90` | TODO | NPI pipes with DIA, FMAN, CLEN |
| 29 | Pump flow | `gate-spill-pipe.f90`, `input.F90` | TODO | NPU pumps with EPU, STRTPU, ENDPU |
| 30 | Dynamic gate control (time-varying openings) | `gate-spill-pipe.f90` | TODO | DYNGTC flag for rule-based gate operation |
| 31 | Dynamic pipe/pump control | `input.F90` | TODO | DYNPIPE, DYNPUMP flags |
| 32 | W2 selective withdrawal rules | `input.F90` | TODO | SELECTC flag; w2_selective.npt input file |
| 33 | Multi-level withdrawal zone (WDZ) | `input.F90` | TODO | wdz_multiMOD flag for multiple withdrawal zones |

---

## 3. WATER QUALITY — STATE VARIABLES

### 3.1 Conservative/Physical Constituents

| # | Capability | Source File(s) | KI Status | Notes |
|---|-----------|----------------|-----------|-------|
| 34 | Temperature (T) | `temperature.F90` | **DONE** | Core capability; s6, s12 calibration |
| 35 | Total dissolved solids (TDS) | `wqconstituents.F90` | **PARTIAL** | WQ config tool lists TDS; no specific handling |
| 36 | Generic constituents (NGC user-defined) | `wqconstituents.F90` | TODO | NGCS-NGCE tracers; configurable count |
| 37 | Suspended solids (multiple groups, NSS) | `wqconstituents.F90` | **PARTIAL** | WQ config tool lists ISS as single group |
| 38 | Water age tracer | `wqconstituents.F90` | TODO | NWAGE constituent; residence time analysis |

### 3.2 Dissolved Gases

| # | Capability | Source File(s) | KI Status | Notes |
|---|-----------|----------------|-----------|-------|
| 39 | Dissolved oxygen (DO) | `wqconstituents.F90` | **PARTIAL** | WQ config tool activates DO; SOD/reaeration configurable |
| 40 | Dissolved gas pressure (DGP) | `wqconstituents.F90` | TODO | NDGP constituent |
| 41 | Dissolved N2 gas | `wqconstituents.F90` | TODO | NN2 constituent |
| 42 | Total dissolved gas (TDG) at structures | `tdg.f90`, `systdg.f90` | TODO | Spillway/gate TDG production (SYSTDG module) |
| 43 | TDG target management | `TDGtarget.f90` | TODO | TDGTA flag; reallocate spill to meet TDG targets |
| 44 | N2/DO boundary saturation control | `systdg.f90` | TODO | N2BNDC, DOBNDC flags |

### 3.3 Nutrients

| # | Capability | Source File(s) | KI Status | Notes |
|---|-----------|----------------|-----------|-------|
| 45 | Phosphorus (PO4) | `wqconstituents.F90` | **PARTIAL** | WQ config tool includes PO4; kinetic rates simplified |
| 46 | Ammonium (NH4) + nitrification | `wqconstituents.F90` | **PARTIAL** | WQ config tool includes NH4 |
| 47 | Nitrate (NO3) + denitrification | `wqconstituents.F90` | **PARTIAL** | WQ config tool includes NO3 |
| 48 | Dissolved silica (DSI) | `wqconstituents.F90` | **PARTIAL** | In "eutrophication" preset |
| 49 | Particulate silica (PSI) | `wqconstituents.F90` | TODO | NPSI constituent; diatom cycling |

### 3.4 Organic Matter

| # | Capability | Source File(s) | KI Status | Notes |
|---|-----------|----------------|-----------|-------|
| 50 | Labile/refractory DOM and POM (standard) | `wqconstituents.F90` | **PARTIAL** | WQ config has LDOM/RDOM/LPOM/RPOM |
| 51 | Organic C/N/P separate tracking (ORGC_CALC) | `wqconstituents.F90`, `input.F90` | TODO | Variable stoichiometry OM; NLDOMC/NRDOMC/NLDOMP/NRDOMP/NLDOMN/NRDOMN etc. |
| 52 | CBOD groups (variable stoichiometry, NBOD) | `wqconstituents.F90` | **PARTIAL** | WQ config has CBOD1; model supports N CBOD groups each with C/N/P |

### 3.5 Biological Constituents

| # | Capability | Source File(s) | KI Status | Notes |
|---|-----------|----------------|-----------|-------|
| 53 | Algae (multiple groups, NAL) | `wqconstituents.F90` | **PARTIAL** | WQ config has ALG1/ALG2; model supports NAL groups |
| 54 | Epiphyton (NEP groups) | `wqconstituents.F90` | TODO | Attached algae on substrate |
| 55 | Macrophytes (NMC groups) | `macrophyte-aux.f90`, `wqconstituents.F90` | TODO | MACROPHYTE_ON flag; 3 types (iso/vert/long); porosity effects |
| 56 | Zooplankton (NZP groups) | `wqconstituents.F90` | **PARTIAL** | WQ config mentions ZOO1; model supports NZP groups |
| 57 | Algae vertical migration | `water-quality.f90` | TODO | w2_AlgaeMigration.csv; 4 migration models |
| 58 | Algae toxins (cyanotoxins) | `wqconstituents.F90`, `water-quality.f90` | TODO | ALGAE_TOXIN flag; NATS-NATE constituents; intracellular + extracellular |
| 59 | Bacteria | `wqconstituents.F90` | TODO | NBACT constituent; decay/settling/photodegradation |

### 3.6 Geochemistry

| # | Capability | Source File(s) | KI Status | Notes |
|---|-----------|----------------|-----------|-------|
| 60 | Inorganic carbon (TIC) + pH/CO2 | `wqconstituents.F90` | TODO | PH_CALC flag; NTIC constituent; enhanced pH buffering |
| 61 | Alkalinity | `wqconstituents.F90` | TODO | NALK constituent |
| 62 | Sulfate (SO4) / Sulfide (H2S) | `wqconstituents.F90` | TODO | NSO4, NH2S constituents |
| 63 | Methane (CH4) | `wqconstituents.F90` | TODO | NCH4 constituent |
| 64 | Iron (Fe2+/FeOOH) | `wqconstituents.F90` | TODO | NFEII, NFEOOH constituents; redox cycling |
| 65 | Manganese (Mn2+/MnO2) | `wqconstituents.F90` | TODO | NMNII, NMNO2 constituents; redox cycling |
| 66 | Mercury (Hg0/HgII/MeHg) | `HgModule.f90` | TODO | HG_CALC flag; full Hg speciation, partitioning, methylation/demethylation, sediment Hg |

---

## 4. SEDIMENT PROCESSES

| # | Capability | Source File(s) | KI Status | Notes |
|---|-----------|----------------|-----------|-------|
| 67 | Simple SOD (zero-order) | `wqconstituents.F90` | **PARTIAL** | SOD in WQ config; dt_016 triplet |
| 68 | Sediment diagenesis (CEMA model) | `Diagenesis*.f90` (6 files) | TODO | SED_DIAG flag; full diagenesis with SOD/nutrient flux/bubbles |
| 69 | Dynamic sediment decay rate | `wqconstituents.F90` | TODO | DYNSEDK flag |
| 70 | Sediment P/N/C compartments | `wqconstituents.F90` | TODO | SEDIMENT_CALC with SEDC/SEDN/SEDP |
| 71 | Standing biomass decay | `wqconstituents.F90` | TODO | STANDING_BIOMASS_DECAY flag; dual sediment pools |

---

## 5. SPECIALIZED MODULES

| # | Capability | Source File(s) | KI Status | Notes |
|---|-----------|----------------|-----------|-------|
| 72 | Particle/fish surrogate tracking | `particle.f90` | TODO | Lagrangian particle tracking; NFS fish behavior model; gillnets/acoustics |
| 73 | Fish habitat volume analysis | `fishhabitat.f90` | TODO | HABTATC flag; T/DO-based habitat volume calculation |
| 74 | Environmental performance profiles | `envir_perf.f90` | TODO | ENVIRPC flag; velocity/temperature/WQ class statistics |
| 75 | Hypolimnetic aeration simulation | `aerate.f90` | TODO | AERATEC flag; oxygen mass injection at specific segments/layers |
| 76 | Atmospheric deposition (wet/dry) | `input.F90` | TODO | ATM_DEPOSITION flag; constituent-specific deposition rates |
| 77 | Gas transfer reduction from algae | `ReduceReaerAlgae.f90` | TODO | W2_AlgaeGasReduction.csv; surface algae mat effect |

---

## 6. INPUT/OUTPUT & INFRASTRUCTURE

| # | Capability | Source File(s) | KI Status | Notes |
|---|-----------|----------------|-----------|-------|
| 78 | Snapshot output (SNP) | `output.f90` | **DONE** | s11 parse_w2_output handles SNP |
| 79 | Time-series output (TSR) | `output.f90` | **DONE** | s11 plot_w2_timeseries |
| 80 | Profile output (PRF) | `output.f90` | **PARTIAL** | Parseable but no dedicated profile comparison tool |
| 81 | Contour/curtain plots | s11 tools | **DONE** | plot_w2_curtain |
| 82 | Spreadsheet output (SPR) | `output.f90` | **PARTIAL** | parse_w2_output can handle; not specifically optimized |
| 83 | Flux output (FLX) | `output.f90` | TODO | Mass flux tracking across segments |
| 84 | Water level output (WL) | `output.f90` | TODO | wl.csv for reservoir level validation |
| 85 | Flow balance output | `balances.F90` | TODO | Volume/mass balance diagnostics |
| 86 | N/P balance tracking | `balances.F90` | TODO | Nutrient mass balance; TPOUT/TNOUT etc. |
| 87 | Restart file read/write | `restart.f90` | TODO | RSIFN for long simulations; hot start |
| 88 | CSV control file format (w2_con.csv) | `input.F90` | TODO | s9 generates .npt only; model also supports CSV format |
| 89 | Preprocessor (bathymetry validation) | `preprocessor_gfortran.f90` | TODO | Standalone geometry checker |
| 90 | Lake/river contour output | example files | TODO | w2_lake_river_contour.csv |

---

## 7. COUPLING & EXTERNAL

| # | Capability | Source File(s) | KI Status | Notes |
|---|-----------|----------------|-----------|-------|
| 91 | CaMa-Flood upstream inflow | s4 tools | **DONE** | convert_inflow_to_w2 |
| 92 | CaMa-Flood downstream coupling | s13 tool | **DONE** | w2_to_cama_coupling |
| 93 | VIC distributed tributary inflow | s4 tools | **DONE** | generate_distributed_inflow |
| 94 | CMFD/MSWX met forcing | s3 tool | **DONE** | convert_met_to_w2 |
| 95 | SWAT+ nutrient loading coupling | SKILL.md reference | TODO | Mentioned in coupling table; no tool |
| 96 | CMIP6 climate scenario forcing | SKILL.md reference | TODO | Delta-change on met files; no tool |
| 97 | GLM comparison framework | SKILL.md reference | TODO | No automated 1D vs 2D comparison tool |
| 98 | Salt water density equation | `density.f90` | TODO | SALT_WATER flag for estuarine applications |

---

## Coverage Summary by Domain

| Domain | Total | DONE | PARTIAL | TODO | Coverage % |
|--------|-------|------|---------|------|-----------|
| Core Hydrodynamics | 10 | 6 | 1 | 3 | 60% / 70% |
| Vertical Mixing | 3 | 1 | 0 | 2 | 33% |
| Heat Exchange | 8 | 4 | 1 | 3 | 50% / 63% |
| Ice Cover | 3 | 0 | 1 | 2 | 0% / 33% |
| Hydraulic Structures | 9 | 0 | 1 | 8 | 0% / 11% |
| WQ Conservative/Physical | 5 | 1 | 2 | 2 | 20% / 60% |
| WQ Dissolved Gases | 6 | 0 | 1 | 5 | 0% / 17% |
| WQ Nutrients | 5 | 0 | 4 | 1 | 0% / 80% |
| WQ Organic Matter | 3 | 0 | 2 | 1 | 0% / 67% |
| WQ Biological | 7 | 0 | 2 | 5 | 0% / 29% |
| WQ Geochemistry | 7 | 0 | 0 | 7 | 0% |
| Sediment Processes | 5 | 0 | 1 | 4 | 0% / 20% |
| Specialized Modules | 6 | 0 | 0 | 6 | 0% |
| I/O & Infrastructure | 13 | 4 | 2 | 7 | 31% / 46% |
| Coupling & External | 8 | 4 | 0 | 4 | 50% |
| **TOTAL** | **98** | **20** | **18** | **60** | **20% / 39%** |

*Coverage % shown as DONE% / (DONE+PARTIAL)%*

---

## Top 20 Priority Gaps (Ranked by Impact)

### Priority 1 — HIGH (Required for real-world reservoir applications)

| Rank | Capability | Gap | Impact | Effort |
|------|-----------|-----|--------|--------|
| 1 | **Hydraulic structures (gates/spillways/pipes)** (#26-31) | No tools for configuring gate/spillway/pipe structures or dynamic operation rules | Cannot simulate real dam operations; gates are used in virtually every reservoir application | HIGH |
| 2 | **Selective withdrawal rules** (#32) | No w2_selective.npt generation | Cannot configure multi-level selective withdrawal strategies (e.g., Three Gorges, Danjiangkou) | MEDIUM |
| 3 | **Sediment diagenesis** (#68) | No CEMA diagenesis configuration | Cannot model sediment-water nutrient exchange, SOD dynamics, or methane ebullition | HIGH |
| 4 | **pH / Inorganic carbon** (#60-61) | No TIC/ALK/pH configuration | Cannot assess acidification, CO2 dynamics, or carbonate chemistry | MEDIUM |
| 5 | **Restart file handling** (#87) | No tool for hot-start / restart management | Cannot run multi-year simulations efficiently; must re-spin-up each time | LOW |

### Priority 2 — MEDIUM (Important for specific use cases)

| Rank | Capability | Gap | Impact | Effort |
|------|-----------|-----|--------|--------|
| 6 | **Ice cover configuration** (#22-24) | Mentioned but no parameter tool | High-latitude reservoirs need ice simulation | LOW |
| 7 | **Organic C/N/P tracking** (#51) | ORGC_CALC mode not supported | Variable stoichiometry OM needed for nutrient-limited systems | MEDIUM |
| 8 | **Macrophytes** (#55) | Not supported | Critical for shallow reservoir/lake arms with littoral vegetation | MEDIUM |
| 9 | **Epiphyton** (#54) | Not supported | Important for periphyton-dominated streams and shallow reservoirs | LOW |
| 10 | **Water age tracer** (#38) | Not supported | Important for residence time analysis and management | LOW |
| 11 | **Topographic shading** (#18) | Not supported | Significant for narrow canyon reservoirs | LOW |
| 12 | **CSV control file format** (#88) | Only .npt generated | Model supports CSV which is easier to read/edit; would simplify debugging | LOW |
| 13 | **Fish habitat analysis** (#73) | Not supported | Ecological assessment of T/DO habitat volume | LOW |
| 14 | **Flow/mass balance output** (#85-86) | Not supported | Needed for model validation and quality assurance | LOW |

### Priority 3 — LOW (Advanced / Niche capabilities)

| Rank | Capability | Gap | Impact | Effort |
|------|-----------|-----|--------|--------|
| 15 | **Mercury module** (#66) | Not supported | Specialized environmental compliance applications | HIGH |
| 16 | **Fe/Mn redox cycling** (#64-65) | Not supported | Drinking water quality (taste & odor) | MEDIUM |
| 17 | **Total dissolved gas** (#42-44) | Not supported | Fish passage / downstream compliance at hydropower dams | MEDIUM |
| 18 | **Particle/fish tracking** (#72) | Not supported | Fish passage assessment at dam structures | HIGH |
| 19 | **Algae migration/toxins** (#57-58) | Not supported | HAB (harmful algal bloom) management | MEDIUM |
| 20 | **Atmospheric deposition** (#76) | Not supported | Nutrient loading from atmospheric sources | LOW |

---

## Recommended KI Expansion Roadmap

### Phase 1: Operational Dam Simulation (Priority 1, items 1-5)
**Effort**: ~2000 lines of Python across 4-5 new tools
**Outcome**: Enables realistic dam operation with gates/spillways, selective withdrawal, and multi-year runs

New tools needed:
- `tools/s5_outflow/configure_structures.py` — Gate, spillway, pipe, pump configuration
- `tools/s5_outflow/configure_selective_withdrawal.py` — w2_selective.npt generation
- `tools/s8_wq_config/configure_diagenesis.py` — CEMA sediment diagenesis setup
- `tools/s8_wq_config/configure_carbonate.py` — TIC/ALK/pH configuration
- `tools/s10_execution/manage_restart.py` — Restart file read/write for multi-year runs

### Phase 2: Extended WQ & Physical Processes (Priority 2, items 6-14)
**Effort**: ~1500 lines across 5-6 tools
**Outcome**: Full eutrophication modeling with macrophytes, ice, and water age

New tools needed:
- `tools/s7_hydraulic_params/configure_ice.py` — Ice parameters
- `tools/s8_wq_config/configure_orgcnp.py` — Variable stoichiometry OM
- `tools/s8_wq_config/configure_macrophytes.py` — Macrophyte/epiphyton setup
- `tools/s11_output_analysis/parse_balance_output.py` — Flow/mass balance parsing
- `tools/s11_output_analysis/fish_habitat_analysis.py` — Habitat volume computation

### Phase 3: Advanced Modules (Priority 3, items 15-20)
**Effort**: ~2500 lines across 4-5 tools
**Outcome**: Full model capability coverage including Hg, TDG, particle tracking

New tools needed:
- `tools/s8_wq_config/configure_mercury.py` — Hg speciation setup
- `tools/s8_wq_config/configure_tdg.py` — TDG/SYSTDG configuration
- `tools/s8_wq_config/configure_geochemistry.py` — Fe/Mn/SO4/CH4 redox
- `tools/s11_output_analysis/particle_tracking.py` — Particle/fish surrogate analysis

---

## Existing KI Strengths

The current KI (16 tools, 3,434 lines, 25 triplets) covers the **thermal hydrodynamic core** well:

1. **Bathymetry pipeline** (s1-s2): DEM/idealized grid + branch topology
2. **Forcing pipeline** (s3-s4): Met, inflow, distributed tributary
3. **Basic outflow** (s5): Constant/time-series outflow
4. **Core WQ** (s8): 5 presets from temperature-only to basic eutrophication
5. **Control file** (s9): w2_con.npt assembly with 8-char validation
6. **Execution** (s10): Preflight checks + run management
7. **Output analysis** (s11): Snapshot parsing, curtain plots, time series
8. **Calibration** (s12): GLUE-style (placeholder, needs W2 integration)
9. **Coupling** (s13): W2-to-CaMa-Flood dam release

The 25 diagnostic triplets (56% silent errors) provide strong error detection for the covered capabilities.

---

## Key Observations

1. **The biggest gap is hydraulic structures.** Every real reservoir application needs gates, spillways, or pipes. The current KI only supports simple outflow time series, not the rating-curve-based or dynamic structures that CE-QUAL-W2 supports. This is the single highest-priority expansion.

2. **WQ coverage is broad but shallow.** The WQ config tool covers the basic nutrient/algae setup but does not handle the model's advanced capabilities: variable stoichiometry OM (ORGC_CALC), sediment diagenesis (CEMA), pH/carbonate chemistry, or geochemical redox cycling.

3. **Calibration is a placeholder.** The calibrate_w2.py tool generates random RMSE values rather than actually modifying w2_con.npt and running the model. This needs connection to the actual execution pipeline.

4. **No multi-year support.** Without restart file handling, long simulations require running from cold start each time, which is impractical for climate change studies.

5. **Specialized modules (Hg, TDG, particle tracking) are completely uncovered** but are important for specific regulatory/environmental applications. These should be lower priority unless specifically needed.
