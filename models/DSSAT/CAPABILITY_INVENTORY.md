# DSSAT-CSM v4.8.5 -- Capability Inventory

**Model**: DSSAT-CSM v4.8.5 (Decision Support System for Agrotechnology Transfer)
**KDT Stage**: s2 (Capability Discovery)
**Date**: 2026-04-01
**Assessed by**: KDT v5.0

---

## 1. Full Capability List

### 1A. Crop Species (Plant Models)

Source: KISSPATH_HOME/DSSAT/Plant/ directories and KISSPATH_HOME/DSSAT/Data/Genotype/*.CUL files.
DSSAT v4.8.5 README states "more than 45 crops." The installed source has 28 plant model directories.

| # | Crop | Model | CUL File | KI Status | Notes |
|---|------|-------|----------|-----------|-------|
| 1 | Maize | CERES-Maize | MZCER048.CUL | DONE | Validated Bengbu (5,324 kg/ha), Chinese cultivar library (12 varieties) |
| 2 | Wheat (winter/spring) | CERES-Wheat | WHCER048.CUL | DONE | Validated Bengbu (4,876 kg/ha), Chinese cultivar library (17 varieties) |
| 3 | Rice | CERES-Rice | RICER048.CUL | DONE | setup_rice_experiment.py, 11 Chinese cultivars (3 regions), auto cultivar selection |
| 4 | Soybean | CROPGRO | SBGRO048.CUL | DONE | setup_soybean_experiment.py, 7 Chinese cultivars (MG 0-VI), auto cultivar selection |
| 5 | Sorghum | CERES-Sorghum | SGCER048.CUL | TODO | CUL/ECO/SPE files exist |
| 6 | Millet (pearl) | CERES-Millet | MLCER048.CUL | TODO | CUL/ECO/SPE files exist |
| 7 | Barley (CERES) | CERES-Barley | BACER048.CUL | TODO | CUL/ECO/SPE files exist |
| 8 | Barley (CROPSIM) | CROPSIM | BACRP048.CUL | TODO | Alternative barley model |
| 9 | Cotton | CROPGRO-Cotton | COGRO048.CUL | TODO | v4.8.5 added lint yield output |
| 10 | Peanut/Groundnut | CROPGRO | PNGRO048.CUL | TODO | CUL/ECO/SPE files exist |
| 11 | Sunflower | OilCrop-Sunflower | SUOIL048.CUL | TODO | Oilseed model |
| 12 | Potato | SUBSTOR-Potato | PTSUB048.CUL | TODO | Tuber crop model |
| 13 | Cassava | CSYCA-Cassava | CSYCA048.CUL | TODO | Root crop model |
| 14 | Sugarcane (CANEGRO) | CANEGRO | SCCAN048.CUL | TODO | Australian sugarcane model |
| 15 | Sugarcane (CASUPRO) | CASUPRO | SCCSP048.CUL | TODO | Brazilian sugarcane model |
| 16 | Sugarcane (SAMUCA) | SAMUCA | SCSAM048.CUL | TODO | Advanced sugarcane model |
| 17 | Sugarbeet | CERES-Sugarbeet | BSCER048.CUL | TODO | |
| 18 | Sweet corn | CERES-SweetCorn | SWCER048.CUL | TODO | |
| 19 | Maize (IXIM) | CERES-IXIM | MZIXM048.CUL | TODO | Alternative maize model |
| 20 | Teff | CERES-TEFF | TFCER048.CUL | TODO | Ethiopian grain |
| 21 | Rye | CERES (?) | RYCER048.CUL | TODO | |
| 22 | Dry bean | CROPGRO | BNGRO048.CUL | TODO | |
| 23 | Chickpea | CROPGRO | CHGRO048.CUL | TODO | |
| 24 | Cowpea | CROPGRO | CPGRO048.CUL | TODO | |
| 25 | Pigeon pea | CROPGRO | PPGRO048.CUL | TODO | |
| 26 | Faba bean | CROPGRO | FBGRO048.CUL | TODO | |
| 27 | Lentil | CROPGRO | LTGRO048.CUL | TODO | New in v4.8.5 |
| 28 | Tomato | CROPGRO | TMGRO048.CUL | TODO | |
| 29 | Pepper (bell) | CROPGRO | PRGRO048.CUL | TODO | |
| 30 | Cabbage | CROPGRO | CBGRO048.CUL | TODO | |
| 31 | Strawberry | CROPGRO | SRGRO048.CUL | TODO | |
| 32 | Velvet bean | CROPGRO | VBGRO048.CUL | TODO | |
| 33 | Quinoa | CROPGRO | QUGRO048.CUL | TODO | |
| 34 | Hemp | CROPGRO | HMGRO048.CUL | TODO | |
| 35 | Canola | CROPGRO | CNGRO048.CUL | TODO | |
| 36 | Safflower | CROPGRO | SFGRO048.CUL | TODO | |
| 37 | Sesame | CROPGRO | SUGRO048.CUL | TODO | |
| 38 | Sunnhemp | G0GRO048.CUL | TODO | | Cover crop |
| 39 | Pineapple | ALOHA-Pineapple | PIALO048.CUL | TODO | Tropical fruit |
| 40 | Taro | AROIDS | TRARO048.CUL | TODO | Root crop |
| 41 | Tanier | AROIDS | TNARO048.CUL | TODO | Root crop |
| 42 | Alfalfa | FORAGE-Alfalfa | ALFRM048.CUL | TODO | Perennial forage |
| 43 | Bermuda grass | FORAGE-Bermuda | BMFRM048.CUL | TODO | Perennial forage |
| 44 | Brachiaria | FORAGE-Brachiaria | BRFRM048.CUL | TODO | Tropical forage |
| 45 | Bahia grass | FORAGE-Bahia | BHFRM048.CUL | TODO | New default in v4.8.5 |
| 46 | Guinea grass | FORAGE-Guinea | GGFRM048.CUL | TODO | Tropical forage |
| 47 | Bambara groundnut | CROPGRO | BGGRO048.CUL | TODO | New in v4.8.5 |
| 48 | Amaranth | CROPGRO | AMGRO048.CUL | TODO | New in v4.8.5 |
| 49 | Cassava (CSCAS) | CSCAS | CSCAS048.CUL | TODO | Alternative cassava model |
| 50 | Gypsophila | CROPGRO | GYGRO048.CUL | TODO | Ornamental |
| 51 | Wheat (WHAPS) | WHAPS | WHAPS048.CUL | TODO | Australian wheat model |
| 52 | Wheat (CROPSIM) | CROPSIM | WHCRP048.CUL | TODO | Alternative wheat |
| 53 | Wheat (NWheat) | NWHEAT | N/A (uses WHAPS CUL) | TODO | CSIRO wheat model |
| 54 | Teff (APSIM) | APSIM-Teff | TFAPS048.CUL | TODO | Alternative teff |
| 55 | Bahia (CROPGRO) | CROPGRO-Bahia | BHGRO048.CUL | TODO | Alternative bahia |
| 56 | Brachiaria (CROPGRO) | CROPGRO-Brachiaria | BRGRO048.CUL | TODO | Alternative brachiaria |
| 57 | Bean/cowpea (?) | CROPGRO | BCGRO048.CUL | TODO | |
| 58 | Cicer (?) | CROPGRO | CIGRO048.CUL | TODO | |
| 59 | Groundbean (?) | CROPGRO | GBGRO048.CUL | TODO | |

### 1B. Soil Process Modules

Source: KISSPATH_HOME/DSSAT/Soil/ directories.

| # | Capability | Status | Current KI Coverage | Notes |
|---|-----------|--------|-------------------|-------|
| 60 | Soil water balance (Ritchie tipping-bucket) | DONE | convert_hwsd_to_sol.py, validate_soil_profile.py | SLLL, SDUL, SSAT validated |
| 61 | Soil water balance (van Genuchten) | TODO | RETC_VG.for exists in SoilWater/ | Alternative hydraulic model |
| 62 | Tile drainage | TODO | TILEDRAIN.for exists | Subsurface drainage |
| 63 | Saturated flow | TODO | SATFLO.for exists | Perched water table |
| 64 | Nitrogen dynamics (mineralization, immobilization, nitrification, denitrification) | PARTIAL | ISWWAT=Y, ISWNIT=Y switches documented | No N-specific calibration or validation |
| 65 | Inorganic N (NO3, NH4) | PARTIAL | Initial conditions (SNO3, SNH4) documented in s6 | Transport/leaching not validated |
| 66 | Phosphorus dynamics (inorganic P) | TODO | PHOSP=Y switch exists; SoilPi.for, IPHedley_inorg.for source exists | No KI tool for P setup |
| 67 | Potassium dynamics (inorganic K) | TODO | POTAS=Y switch exists; SoilKi.for source exists | New in recent DSSAT versions |
| 68 | CENTURY organic matter model | TODO | MESOM=P switch documented; CENTURY.for + 20 source files exist | Full CENTURY SOM module available |
| 69 | CERES organic matter model | PARTIAL | MESOM=G (default); CERES_OrganicMatter/ exists | Default but not explicitly validated |
| 70 | Flood nitrogen (paddy rice) | TODO | FloodN/ directory with source files | Specific to flooded rice |
| 71 | GHG emissions (N2O, CH4, CO2) | TODO | GHG/ directory: denitrification (CERES/DayCent), methane, NOx | v4.8.5 added GHG.OUT and net CO2 in Summary.OUT |
| 72 | Mulch effects | TODO | Mulch/ directory: MULCHEVAP, MULCHWAT, MULCHLAYER | Residue mulch impacts on evaporation/temperature |
| 73 | Soil temperature | PARTIAL | Implicit in soil water balance | Not separately validated |

### 1C. Management and Analysis

| # | Capability | Status | Current KI Coverage | Notes |
|---|-----------|--------|-------------------|-------|
| 74 | Planting management | DONE | s7_management_spec_skill.md covers planting details | PDATE, PPOP, PLDP, row spacing |
| 75 | Fertilizer application | PARTIAL | s7 covers fertilizer section; FMCD codes documented | No optimization or recommendation tool |
| 76 | Irrigation scheduling | PARTIAL | IRRIG switch documented; automatic irrigation available | No irrigation optimization tool |
| 77 | Tillage operations | TODO | TILL switch exists; tillage section in FileX | No KI tool |
| 78 | Residue management | TODO | RESID section in FileX | No KI tool |
| 79 | Harvest management | PARTIAL | HARVS section; automatic vs reported harvest | Maturity-based harvest works |
| 80 | Crop rotation / sequences | TODO | DSSAT supports multi-year rotation via NYERS + sequential treatments | No rotation setup tool |
| 81 | Seasonal analysis (economic) | TODO | DSSAT seasonal analysis module | No KI coverage |
| 82 | CO2 enrichment / climate scenarios | PARTIAL | CO2 switch (M=measured, W=from weather file, D=default 380 ppm) documented | No scenario generation tool |
| 83 | Automatic management (planting window, irrigation triggers) | PARTIAL | s5 documents PLANT/IRRIG switches (R=reported, A=automatic) | Auto-planting not tested |
| 84 | GLUE calibration | PARTIAL | GLUE tool exists at KISSPATH_HOME/DSSAT/Tools/GLUE/ (R scripts) | R-based, not integrated into KI Python pipeline |
| 85 | Pest/disease simulation | TODO | Generic-Pest/ plant module exists; DISES switch | No KI coverage |

### 1D. Output and Post-Processing

| # | Capability | Status | Current KI Coverage | Notes |
|---|-----------|--------|-------------------|-------|
| 86 | Summary.OUT parsing (yield, phenology) | DONE | parse_summary_out.py (504 lines) | HWAM, ADAT, MDAT, CWAM |
| 87 | PlantGro.OUT parsing (daily growth) | DONE | parse_plantgro.py (extract_growth_summary, get_timeseries) | Daily LAI, biomass, stress, phenology |
| 88 | SoilWat.OUT parsing | TODO | Not implemented | v4.8.5 added LL/DUL/SAT/BD daily output |
| 89 | GHG.OUT parsing | TODO | Not implemented | New in v4.8.5 |
| 90 | Evaluate.OUT parsing (sim vs obs) | TODO | Referenced in KI YAML but no tool | Model evaluation |
| 91 | MgmtEvent.OUT parsing | TODO | Not implemented | v4.8.5 added multiple harvest output |
| 92 | Gridded/spatial simulation | TODO | No spatial wrapper | DSSAT is point-based; needs grid loop |

### 1E. Coupling and Integration

| # | Capability | Status | Current KI Coverage | Notes |
|---|-----------|--------|-------------------|-------|
| 93 | VIC forcing to DSSAT weather | DONE | cmfd_to_dssat.py adapter | CMFD/MSWX/NASA_POWER supported |
| 94 | HWSD to DSSAT soil profile | DONE | hwsd_to_dssat.py adapter | convert_hwsd_to_sol.py tool |
| 95 | DSSAT-VIC grid coupling | PARTIAL | Referenced in related_packages but bridge tools not in DSSAT KI | vic_forcing_to_wth.py, vic_soil_to_dssat_sol.py mentioned |
| 96 | DSSAT yield to economic models | TODO | No coupling | |
| 97 | DSSAT water use to VIC irrigation demand | TODO | No coupling | Potential for irrigation feedback loop |

---

## 2. Required Input Files per Capability

| Capability | Required Inputs | Tool Status |
|-----------|----------------|-------------|
| Core crop simulation (1-4) | FileX, .WTH, SOIL.SOL, .CUL/.ECO/.SPE, DSSBatch.v48 | dssat_workdir_setup.py handles all |
| Additional crops (5-59) | Same as above + species-specific CUL/ECO files | CUL/ECO/SPE files exist; KI workflow identical (change crop code) |
| Nitrogen dynamics (64-65) | ISWNIT=Y, initial SNO3/SNH4 in FileX | Switch documented; init tool missing |
| Phosphorus dynamics (66) | PHOSP=Y, initial P in FileX, Hedley P fractions in soil | No tool |
| Potassium dynamics (67) | POTAS=Y, initial K in FileX | No tool |
| CENTURY SOM (68) | MESOM=P, CENTURY-specific soil parameters | No tool for CENTURY param setup |
| GHG emissions (71) | Specific switches, GHG initial conditions | No tool |
| Crop rotation (80) | Multi-treatment FileX with sequential years | No rotation builder |
| GLUE calibration (84) | R installation, GLUE scripts, observation data | R scripts exist but not Python-integrated |

---

## 3. Required Data KIs per Capability

| Capability | Data KI Needed | Data KI Status | Path |
|-----------|---------------|---------------|------|
| Weather forcing | CMFD (China) | EXISTS | data_ki/CMFD/ |
| Weather forcing | MSWX (global) | EXISTS | data_ki/MSWX/ |
| Weather forcing | NASA_POWER (API) | EXISTS | data_ki/NASA_POWER/ |
| Soil profiles | HWSD | EXISTS | data_ki/HWSD/ |
| Soil properties | SoilGrids | EXISTS | data_ki/SoilGrids/ |
| Crop yields (validation) | FAOSTAT | EXISTS | data_ki/FAOSTAT/ |
| Crop distribution | SPAM | EXISTS | data_ki/SPAM/ |
| Fertilizer rates | NPKGRIDS | EXISTS | data_ki/NPKGRIDS/ |
| Crop calendar | GGCMI phase 3 | EXISTS | data_ki/GGCMI/ |
| Crop calendar (China) | China Phenology GeoTIFF | EXISTS (external) | KISSPATH_HOME/Crop_model_dataset/8313530/ |
| CROPGRIDS (global) | CROPGRIDS | EXISTS | data_ki/CROPGRIDS/ |
| P dynamics validation | No specific P obs Data KI | MISSING | Need water quality or soil P database |
| GHG validation | FLUXNET (eddy covariance) | EXISTS | data_ki/FLUXNET/ |
| Irrigation scheduling | No irrigation database | MISSING | Need irrigation practice database |

---

## 4. Priority Ranking for Next Implementation

| Priority | Capability | Effort | Impact | Rationale |
|----------|-----------|--------|--------|-----------|
| ~~P1~~ | ~~Rice simulation (#3) validation~~ | ~~LOW~~ | ~~HIGH~~ | **DONE** — setup_rice_experiment.py, 11 cultivars, 3 regions |
| ~~P2~~ | ~~Soybean simulation (#4) validation~~ | ~~LOW~~ | ~~HIGH~~ | **DONE** — setup_soybean_experiment.py, 7 cultivars, MG 0-VI |
| P3 | Nitrogen dynamics validation (#64-65) | MEDIUM | HIGH | Already partially implemented; N is critical for yield accuracy and water quality linkage |
| ~~P4~~ | ~~PlantGro.OUT parser (#87)~~ | ~~LOW~~ | ~~MEDIUM~~ | **DONE** — parse_plantgro.py with summary extraction |
| P5 | Crop rotation builder (#80) | MEDIUM | MEDIUM | Wheat-maize double cropping is standard in North China; currently no tool |
| P6 | Additional major crops: cotton (#9), sorghum (#5), potato (#12) | MEDIUM | MEDIUM | Each needs a test run with existing CUL files; workflow is identical |
| P7 | CENTURY SOM model (#68) | MEDIUM | MEDIUM | More accurate long-term C/N cycling; 20+ Fortran source files exist |
| P8 | Phosphorus dynamics (#66) | MEDIUM | MEDIUM | Important for water quality coupling with GLM-AED2 and SWAT+ |
| P9 | GHG emissions (#71) | MEDIUM | MEDIUM | v4.8.5 added GHG.OUT; climate impact assessment increasingly important |
| P10 | Irrigation optimization (#76) | MEDIUM | MEDIUM | Water-food nexus; automatic irrigation exists but no optimization guidance |
| P11 | GLUE Python integration (#84) | HIGH | MEDIUM | R-based GLUE exists; needs Python wrapper for KI pipeline |
| P12 | Gridded spatial simulation (#92) | HIGH | HIGH | Major structural gap; needs grid loop wrapper + parallelization |
| P13 | Potassium dynamics (#67) | LOW | LOW | Niche; K limitation rare in most cropping systems |
| P14 | Pest/disease (#85) | HIGH | LOW | Complex module; rarely calibrated outside specialized studies |

---

## 5. Gap Summary

| Category | Done | Partial | TODO | Coverage |
|----------|------|---------|------|----------|
| Crop species (1-59) | 4 | 0 | 55 | 7% (by count), ~95% by practical demand |
| Soil processes (60-73) | 1 | 4 | 9 | 21% |
| Management/analysis (74-85) | 2 | 4 | 6 | 33% |
| Output parsing (86-92) | 2 | 0 | 5 | 29% |
| Coupling (93-97) | 2 | 1 | 2 | 50% |
| **TOTAL** | **11** | **9** | **77** | **18%** |

**Key findings**:

1. **Crop species coverage is 7% by count but ~95% by actual use**: The KI handles maize, wheat, rice, and soybean (the four crops users actually request). The remaining 55 crops share the same pipeline -- only the crop code and cultivar file change.

2. **The KI YAML itself documents 18 missing tools** (out of 24 referenced): create_filex_skeleton, convert_weather_to_wth, convert_soil_to_sol, check_water_limits, list_available_cultivars, validate_cultivar_match, generate_simulation_controls, validate_switch_consistency, generate_initial_conditions, validate_ic_vs_soil, generate_management_section, validate_management_dates, build_dssat, run_dssat, check_model_errors, parse_plantgro_out, parse_evaluate_out, compare_sim_obs. However, dssat_workdir_setup.py subsumes many of these.

3. **Nitrogen is the critical process gap**: N dynamics are partially implemented but not validated. This matters because N leaching connects DSSAT to water quality models (GLM-AED2, SWAT+).

4. **GHG capability is entirely new in v4.8.5** and represents a unique opportunity: DSSAT can now estimate N2O and CO2 emissions, which no other HydroCraft model provides for agricultural land.
