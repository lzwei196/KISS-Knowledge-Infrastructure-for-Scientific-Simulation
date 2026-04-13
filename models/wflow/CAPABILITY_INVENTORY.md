# wflow v1.1.0 (Deltares) -- Capability Inventory

**Model**: wflow v1.1.0-dev (Wflow.jl) -- wflow_sbm + wflow_sediment
**KDT Stage**: s2 (Capability Discovery)
**Date**: 2026-04-01
**Assessed by**: KDT v5.0

---

## 1. Full Capability List

### 1A. wflow_sbm Hydrology

| # | Capability | Status | Current KI Coverage | Notes |
|---|-----------|--------|-------------------|-------|
| 1 | Interception (Gash model) | DONE | Built into wflow_sbm; configured via TOML | Validated Bengbu |
| 2 | Snow accumulation/melt (degree-day, HBV) | DONE | Temperature-based; Kelvin conversion trap documented (dt_w002, dt_w004) | Validated |
| 3 | Infiltration (Brooks-Corey) | DONE | KsatVer parameter calibration documented | Key calibration parameter |
| 4 | Soil water (multi-layer, exponential Ksat decay) | DONE | SoilThickness, f parameter documented | Exponential decay with depth |
| 5 | Evapotranspiration (Penman-Monteith or Hargreaves PET input) | DONE | calculate_pet.py tool exists; dt_w003 documented | PET as forcing input |
| 6 | Surface runoff generation | DONE | PathFrac, InfiltCapSoil documented | Saturation excess + infiltration excess |
| 7 | Subsurface lateral flow (kinematic wave) | DONE | Built-in; SoilThickness and f control partitioning | Validated Bengbu |
| 8 | River routing (kinematic wave) | DONE | Default routing; N_River calibration documented | Validated Bengbu (14s runtime) |
| 9 | River routing (local inertial / Saint-Venant) | PARTIAL | Mentioned in s0 config skill (routing="local_inertial") | Tool supports config but no validated example |
| 10 | Groundwater (unconfined, linear reservoir) | DONE | Built into SBM bucket model; f parameter controls | Baseflow generation validated |
| 11 | Multi-layer soil discretization | PARTIAL | SBM supports configurable layers | Default uses single conceptual layer with Ksat decay |
| 12 | Canopy interception storage | DONE | Part of Gash model in SBM | ScanopyMax parameter |
| 13 | Cold start / warm start (state files) | PARTIAL | dt_w030 documents 11 mandatory state variables | cold_start__flag documented; instates reading not tested |

### 1B. wflow_sediment (Erosion and Transport)

| # | Capability | Status | Current KI Coverage | Notes |
|---|-----------|--------|-------------------|-------|
| 14 | Splash erosion (EUROSEM) | DONE | build_sediment_model.py supports erosion_method selection | Physics-based kinetic energy |
| 15 | Overland flow erosion (ANSWERS/USLE) | DONE | USLE C/K factor tables in s6_s8_sediment_skill.md | Default erosion method |
| 16 | In-stream transport: Engelund-Hansen | DONE | build_sediment_model.py supports formula selection | Total load, sand-bed |
| 17 | In-stream transport: Bagnold | DONE | Available in build_sediment_model.py | Simplified power law |
| 18 | In-stream transport: Kodatie | DONE | Available | D50-class dependent |
| 19 | In-stream transport: Yang | DONE | Available | Sand and gravel bed |
| 20 | In-stream transport: Molinas-Wu | DONE | Available | Large sand-bed rivers |
| 21 | Deposition (Einstein settling) | DONE | Built into wflow_sediment | Settling velocity based |
| 22 | 5 grain size classes (clay, silt, sand, small/large aggregates) | DONE | dt_w019 documents sum-to-1.0 requirement | Mass conservation validated |
| 23 | Erosion classification mapping | DONE | analyze_sediment.py produces erosion rate maps | Annual erosion rates |
| 24 | Sediment yield at outlet | DONE | analyze_sediment.py computes specific sediment yield | t/km2/yr |
| 25 | USLE K factor from soil texture | DONE | derive_usle_k.py: Wischmeier-Smith 1978 equation, HWSD or SoilGrids input, US-to-SI conversion | Validated Bengbu (K=0.034-0.044 for loam) |
| 26 | USLE C factor from land cover | DONE | derive_usle_c.py: AVHRR UMD land cover -> C lookup table, grid + point mode | Validated Bengbu (C=0.30 cropland, 0.0 wetland) |

### 1C. Additional Modules (in Wflow.jl but NOT in current KI)

| # | Capability | Status | Current KI Coverage | Notes |
|---|-----------|--------|-------------------|-------|
| 27 | Glacier module (degree-day melt) | TODO | Mentioned in s0 config (glacier=bool); dt_w016 warns about zero glacier fraction | No glacier setup tool, no validation |
| 28 | Reservoir module (simple/controlled) | DONE | lookup_dams.py + configure_reservoirs.py + s10_reservoir_skill.md | GRanD -> wflow SimpleReservoir (outflowfunc=4); 3 diagnostic triplets (dt_w031-033) |
| 29 | Lake module (natural lakes) | TODO | Not in KI | Wflow.jl supports natural lake storage/routing |
| 30 | Paddy/irrigation module | TODO | Not in KI | Wflow.jl has irrigation demand module |
| 31 | Water demand and allocation | TODO | Not in KI | Wflow.jl supports domestic/industrial/agricultural demand |
| 32 | Floodplain routing (1D) | TODO | Not in KI | Wflow.jl local inertial supports floodplain |
| 33 | Snow (multi-layer energy balance) | TODO | Only degree-day documented | Wflow.jl has optional energy-balance snow |
| 34 | Canopy gap fraction / LAI input | TODO | Not explicitly handled | Wflow.jl supports LAI-driven interception |
| 35 | River width/depth scaling | PARTIAL | Part of staticmaps generation | N_River documented; width/depth from power law |

### 1D. Coupling and Integration

| # | Capability | Status | Current KI Coverage | Notes |
|---|-----------|--------|-------------------|-------|
| 36 | wflow to CaMa-Flood (unrouted runoff) | DONE | wflow_to_cama.py (170 lines); dt_w025 double-counting warning | Yearly NetCDF output |
| 37 | wflow recharge to MODFLOW | DONE | wflow_recharge_to_modflow.py (110 lines) | mm/day to m/day conversion |
| 38 | VIC forcing shared with wflow | DONE | convert_forcing_to_wflow.py handles VIC ASCII | Custom naming pattern (dt_w028) |
| 39 | wflow vs VIC comparison | DONE | compare_with_vic.py (250 lines) | NSE, PBIAS, KGE metrics |
| 40 | wflow_sediment to SWAT+ loading | TODO | Listed in coupling table but marked "(manual)" | No tool |
| 41 | OGGM glacier to wflow | TODO | Listed in coupling table but marked "(manual)" | No tool |
| 42 | HydroMT-wflow automated setup | PARTIAL | build_data_catalog.py + run_hydromt_build.py exist | HydroMT optional (manual build also works) |

### 1E. Calibration and Analysis

| # | Capability | Status | Current KI Coverage | Notes |
|---|-----------|--------|-------------------|-------|
| 43 | Parameter adjustment (scale/offset) | DONE | adjust_parameters.py (280 lines) | TOML-based calibration |
| 44 | Discharge extraction at outlet | DONE | extract_discharge.py (240 lines) | CSV output with Q_m3s |
| 45 | Spatial output extraction (maps) | DONE | extract_spatial_output.py (160 lines) | Per-variable NetCDF maps |
| 46 | Water balance verification | PARTIAL | Mentioned in skill docs but no dedicated tool | P = ET + Q + dS check |
| 47 | Multi-objective calibration (NSE, KGE) | TODO | compare_with_vic.py computes metrics but no automated calibration | No optimization loop |
| 48 | Sensitivity analysis | TODO | No tool | Parameter sensitivity not systematically evaluated |
| 49 | Uncertainty quantification | TODO | No tool | No ensemble or GLUE capability |

---

## 2. Required Input Files per Capability

| Capability | Required Inputs | Tool Status |
|-----------|----------------|-------------|
| Core SBM hydrology (1-8, 10-12) | staticmaps.nc, forcing.nc, wflow_sbm.toml | All tools exist and validated |
| Local inertial routing (9) | Same + floodplain DEM, bankfull depth | Config exists; no floodplain data tool |
| Sediment (14-26) | staticmaps_sediment.nc (USLE_C, USLE_K, grain fracs, D50), wflow_sediment.toml, SBM output | build_sediment_model.py + derive_usle_k.py + derive_usle_c.py |
| Glacier (27) | Glacier fraction map, degree-day factor | No setup tool |
| Reservoir (28) | Reservoir locations, storage-area curves, operating rules | lookup_dams.py + configure_reservoirs.py |
| Lake (29) | Lake locations, storage-outflow relationships | No tool |
| Paddy/irrigation (30) | Crop water demand, irrigation infrastructure | No tool |
| Water demand (31) | Demand sectors (domestic/industrial/agricultural), population, GDP | No tool |
| Floodplain (32) | Floodplain DEM, Manning's n for floodplain, cross-sections | No tool |
| Warm start (13) | State files from previous run (instates.nc) | TOML config exists |

---

## 3. Required Data KIs per Capability

| Capability | Data KI Needed | Data KI Status | Path |
|-----------|---------------|---------------|------|
| Core hydrology forcing | CMFD (China) | EXISTS | data_ki/CMFD/ |
| Core hydrology forcing | MSWX (global) | EXISTS | data_ki/MSWX/ |
| Soil parameters | HWSD | EXISTS | data_ki/HWSD/ |
| Soil parameters (detailed) | SoilGrids | EXISTS | data_ki/SoilGrids/ |
| Land cover | AVHRR | EXISTS | data_ki/AVHRR/ |
| DEM | ChinaDEM / SRTM | EXISTS | data_ki/ChinaDEM/, data_ki/SRTM/ |
| Discharge validation | GRDC | EXISTS | data_ki/GRDC/ |
| Discharge validation | ObservedQ | EXISTS | data_ki/ObservedQ/ |
| Sediment validation | USGS_Sediment | EXISTS | data_ki/USGS_Sediment/ |
| Glacier fraction | RGI (Randolph Glacier Inventory) | EXISTS | data_ki/RGI/ |
| Reservoir data | GRanD (Global Reservoir and Dam) | EXISTS | data_ki/GRanD/ |
| Water table depth | FanWTD | EXISTS | data_ki/FanWTD/ |
| Depth to bedrock | DTB | EXISTS | data_ki/DTB/ |
| Groundwater validation | GRACE | EXISTS | data_ki/GRACE/ |
| Soil moisture validation | ObservedSoilTSM | EXISTS | data_ki/ObservedSoilTSM/ |
| Aquifer properties | GLHYMPS | EXISTS | data_ki/GLHYMPS/ |
| Floodplain mapping | No specific Data KI | MISSING | Need floodplain DEM or MERIT-Hydro |
| Irrigation/water demand | No specific Data KI | MISSING | Need irrigation infrastructure database |

---

## 4. Priority Ranking for Next Implementation

| Priority | Capability | Effort | Impact | Rationale |
|----------|-----------|--------|--------|-----------|
| P1 | Reservoir module (#28) | MEDIUM | HIGH | GRanD Data KI exists; reservoirs significantly affect downstream hydrology; Wflow.jl already has SimpleReservoir |
| P2 | Local inertial routing validation (#9) | LOW | HIGH | Config already supported; just needs a validated flood example |
| ~~P3~~ | ~~Automated USLE C/K from data (#25-26)~~ | ~~MEDIUM~~ | ~~HIGH~~ | **DONE** (2026-04-03): derive_usle_k.py + derive_usle_c.py |
| P4 | Glacier module setup (#27) | MEDIUM | MEDIUM | RGI Data KI exists; important for mountain basins (Himalaya, Andes, Alps) |
| P5 | Water balance verification tool (#46) | LOW | MEDIUM | Simple P=ET+Q+dS check; essential for quality assurance |
| P6 | Lake module (#29) | MEDIUM | MEDIUM | Natural lakes affect routing; HydroLAKES Data KI exists |
| P7 | Multi-objective calibration (#47) | HIGH | HIGH | No automated calibration loop; manual adjust_parameters.py is tedious |
| P8 | Floodplain routing (#32) | HIGH | MEDIUM | Requires floodplain DEM data; important for flood studies |
| P9 | Warm start validation (#13) | LOW | LOW | State file reading exists but not tested; useful for operational forecasting |
| P10 | Paddy/irrigation (#30) | HIGH | MEDIUM | Important for Asian rice basins; complex module |
| P11 | Water demand/allocation (#31) | HIGH | MEDIUM | Important for water resources management; multi-sector |
| P12 | Sensitivity analysis (#48) | MEDIUM | LOW | Systematic parameter sensitivity; useful for calibration guidance |
| P13 | wflow_sediment to SWAT+ coupling (#40) | LOW | LOW | Niche cross-model sediment transfer |
| P14 | OGGM glacier coupling (#41) | HIGH | LOW | Complex; only needed for glacier-dominated basins |

---

## 5. Gap Summary

| Category | Done | Partial | TODO | Coverage |
|----------|------|---------|------|----------|
| SBM hydrology (1-13) | 9 | 3 | 1 | 81% |
| Sediment (14-26) | 13 | 0 | 0 | 100% |
| Additional modules (27-35) | 1 | 1 | 7 | 17% |
| Coupling (36-42) | 4 | 1 | 2 | 64% |
| Calibration/analysis (43-49) | 3 | 1 | 3 | 50% |
| **TOTAL** | **30** | **6** | **13** | **67%** |

**Key findings**:

1. **Core hydrology and sediment are well-covered (81% and 100%)**: The wflow KI is the most complete in HydroCraft for its primary use cases. Both wflow_sbm and wflow_sediment have been validated on Bengbu basin. Sediment reached 100% coverage with automated USLE K/C factor derivation (2026-04-03).

2. **The biggest gap is additional Wflow.jl modules (6% coverage)**: Reservoir, lake, glacier, paddy, water demand, and floodplain modules all exist in Wflow.jl but have zero KI coverage. These are not exotic features -- reservoirs and glaciers are common and have corresponding Data KIs already available (GRanD, RGI).

3. **Automated calibration is missing**: adjust_parameters.py does manual scale/offset changes, and compare_with_vic.py computes metrics, but there is no optimization loop connecting them. This is a structural gap that affects all wflow applications.

4. **USLE factor automation is complete**: derive_usle_k.py computes K from HWSD soil texture using the Wischmeier-Smith (1978) nomograph equation with proper US-to-SI conversion (factor 0.1317). derive_usle_c.py maps AVHRR UMD land cover classes to C-factor values. Both support grid mode (patch staticmaps_sediment.nc) and point mode (verification). Validated on Bengbu: K=0.034-0.044 (loam), C=0.30 (cropland), C=0.0 (wetland).

5. **Data KI coverage is excellent**: 15 out of 17 needed Data KIs already exist. Only floodplain DEM and irrigation infrastructure databases are missing.
