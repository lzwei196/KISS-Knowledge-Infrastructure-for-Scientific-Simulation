# AquaCrop-OSPy Capability Inventory

**KDT Version**: 5.0 Stage s2 -- Capability Discovery
**Model**: AquaCrop-OSPy v3.0.12 (FAO AquaCrop v7.1 Python implementation)
**Date**: 2026-04-03
**Total Capabilities**: 52
**Coverage**: 35 DONE / 4 PARTIAL / 13 TODO = 67.3% DONE, 7.7% PARTIAL, 25.0% TODO

---

## Coverage Summary

| Domain                         | Total | DONE | PARTIAL | TODO | Coverage % |
|-------------------------------|-------|------|---------|------|------------|
| A. Crop Growth & Development  |    10 |    9 |       0 |    1 |       90.0 |
| B. Soil Water Balance         |     9 |    8 |       1 |    0 |       88.9 |
| C. Irrigation Management      |     8 |    7 |       1 |    0 |       87.5 |
| D. Salinity Stress            |     5 |    0 |       0 |    5 |        0.0 |
| E. Field Management           |     5 |    5 |       0 |    0 |      100.0 |
| F. CO2 & Climate              |     4 |    3 |       1 |    0 |       75.0 |
| G. Water Productivity Analysis|     4 |    4 |       0 |    0 |      100.0 |
| H. Multi-Crop & Rotation      |     3 |    2 |       0 |    1 |       66.7 |
| I. Model Coupling             |     4 |    2 |       1 |    1 |       50.0 |
| **TOTAL**                     | **52**| **35**|  **4** |**13**| **67.3**   |

---

## A. Crop Growth & Development (10 capabilities)

### A1. Canopy Cover Dynamics -- DONE
- **Model Feature**: Simulates canopy expansion (CGC), maximum canopy (CCx), and senescence (CDC) using logistic growth curves
- **KI Coverage**: `select_crop.py` (S1), `validate_crop_params.py` (S1)
- **Source Module**: `solution/canopy_cover.py`, `solution/cc_development.py`
- **Parameters**: CGC, CDC, CCx, SeedSize, PlantPop, CC0

### A2. Biomass Accumulation -- DONE
- **Model Feature**: Daily biomass from normalized water productivity (WP*) x transpiration / ET0, with CO2 adjustment
- **KI Coverage**: `extract_results.py` (S9) outputs biomass and biomass_ns
- **Source Module**: `solution/biomass_accumulation.py`
- **Parameters**: WP, WPy, fCO2, bsted, bface, fsink

### A3. Harvest Index Build-Up -- DONE
- **Model Feature**: Reference HI development with pre-anthesis, post-anthesis, and pollination stress adjustments
- **KI Coverage**: `extract_results.py` (S9) outputs HI and HI_adj
- **Source Module**: `solution/harvest_index.py`, `solution/HIref_current_day.py`, `solution/HIadj_*.py`
- **Parameters**: HI0, dHI_pre, dHI0, a_HI, b_HI, HIGC, tLinSwitch

### A4. Root Development -- DONE
- **Model Feature**: Root zone expansion from Zmin to Zmax driven by GDD, with water stress and restrictive layer feedbacks
- **KI Coverage**: `extract_results.py` (S9) outputs z_root
- **Source Module**: `solution/root_development.py`
- **Parameters**: Zmin, Zmax, fshape_r, SxTopQ, SxBotQ, PctZmin

### A5. Growing Degree Day Phenology -- DONE
- **Model Feature**: GDD-based crop calendar (emergence, max rooting, senescence, maturity, flowering, HI start)
- **KI Coverage**: `select_crop.py` (S1) supports both CalendarType=1 (CD) and CalendarType=2 (GDD)
- **Source Module**: `solution/growing_degree_day.py`, `initialize/compute_crop_calendar.py`
- **Parameters**: Tbase, Tupp, GDDmethod (1/2/3), all phenology GDD thresholds

### A6. Crop Type Differentiation -- DONE
- **Model Feature**: Three crop types with distinct HI behavior: (1) leafy vegetable, (2) root/tuber, (3) fruit/grain
- **KI Coverage**: `select_crop.py` (S1) via CropType parameter
- **Source Module**: `entities/crop.py` CropType attribute
- **Crops Available**: 18 calendar-day + 19 GDD variants = 37 built-in crop parameterizations

### A7. Germination Conditions -- DONE
- **Model Feature**: Germination requires minimum soil water content in germination zone; delayed growth if too dry
- **KI Coverage**: Handled internally; `create_initial_water_content.py` (S4) ensures proper soil moisture
- **Source Module**: `solution/germination.py`
- **Parameters**: GermThr, z_germ

### A8. Temperature Stress on Pollination -- DONE
- **Model Feature**: Heat and cold stress reduce pollination success (fruit/grain crops only)
- **KI Coverage**: `validate_crop_params.py` (S1) checks temperature stress parameters
- **Source Module**: `solution/temperature_stress.py`, `solution/HIadj_pollination.py`
- **Parameters**: PolHeatStress, Tmax_up, Tmax_lo, PolColdStress, Tmin_up, Tmin_lo

### A9. Cold Stress on Transpiration -- DONE
- **Model Feature**: GDD-based cold stress reduces transpiration (KsCold coefficient)
- **KI Coverage**: Handled internally in transpiration calculations
- **Source Module**: `solution/transpiration.py` (lines 154-178)
- **Parameters**: TrColdStress, GDD_up, GDD_lo

### A10. Multi-Season Simulation -- PARTIAL (framework exists, no dedicated tool)
- **Model Feature**: AquaCrop can simulate multiple consecutive growing seasons with fallow periods
- **KI Gap**: No dedicated tool for multi-season scenario setup or inter-annual analysis
- **Source Module**: `core.py` (season_counter, n_seasons), `timestep/reset_initial_conditions.py`
- **Status TODO**: Create `tools/s8_execution/run_multiyear.py` for multi-season analysis with inter-annual yield trends

---

## B. Soil Water Balance (9 capabilities)

### B1. Multi-Layer Soil Profile -- DONE
- **Model Feature**: Up to 12 compartments across multiple layers, each with thWP, thFC, thS, Ksat, penetrability
- **KI Coverage**: `create_soil_profile.py` (S2), `validate_soil_hydraulics.py` (S2)
- **Source Module**: `entities/soil.py`, `entities/soilProfile.py`
- **Built-in Types**: 16 soil types (Clay, ClayLoam, Loam, LoamySand, Sand, SandyClay, SandyClayLoam, SandyLoam, Silt, SiltClay, SiltClayLoam, SiltLoam, Paddy, Default, ac_TunisLocal, custom)

### B2. Pedotransfer Functions -- DONE
- **Model Feature**: Saxton-Rawls (2006) equations convert sand/clay/OM to thWP, thFC, thS, Ksat
- **KI Coverage**: `create_soil_profile.py` (S2) via `add_layer_from_texture()`, integrated with HWSD lookup
- **Source Module**: `entities/soil.py` `calculate_soil_hydraulic_properties()`

### B3. Drainage -- DONE
- **Model Feature**: Gravity drainage from each compartment based on tau drainage characteristic
- **KI Coverage**: Internal process, outputs via `get_water_flux()` (DeepPerc column)
- **Source Module**: `solution/drainage.py`

### B4. Soil Evaporation -- DONE
- **Model Feature**: Two-stage evaporation (energy-limited then falling-rate), with mulch and canopy shelter effects
- **KI Coverage**: Internal process, outputs via `get_water_flux()` (Es, EsPot columns)
- **Source Module**: `solution/soil_evaporation.py`
- **Parameters**: evap_z_surf, evap_z_min, evap_z_max, kex, f_evap, REW

### B5. Surface Runoff (SCS-CN) -- DONE
- **Model Feature**: SCS Curve Number method with antecedent moisture adjustment
- **KI Coverage**: `create_field_management.py` (S6) for CN adjustment
- **Source Module**: `solution/rainfall_partition.py`
- **Parameters**: cn, adj_cn, z_cn, curve_number_adj_pct

### B6. Infiltration -- DONE
- **Model Feature**: Infiltration into soil compartments after rainfall partitioning, with bund surface storage
- **KI Coverage**: Internal process, outputs via `get_water_flux()` (Infl column)
- **Source Module**: `solution/infiltration.py`

### B7. Capillary Rise -- DONE
- **Model Feature**: Upward water movement from shallow groundwater table, parameterized by aCR/bCR per soil class
- **KI Coverage**: `apply_cama_flood.py` (S6) provides groundwater depth; capillary rise computed internally
- **Source Module**: `solution/capillary_rise.py`, `entities/soil.py` `add_capillary_rise_params()`

### B8. Groundwater Table Interaction -- DONE
- **Model Feature**: Constant or variable water table depth affects field capacity adjustment, capillary rise, and waterlogging
- **KI Coverage**: `apply_cama_flood.py` (S6) for CaMa-Flood coupling; GroundWater entity supports direct specification
- **Source Module**: `entities/groundWater.py`, `solution/check_groundwater_table.py`, `solution/groundwater_inflow.py`

### B9. Restrictive Soil Layer -- PARTIAL (model supports it, KI does not expose)
- **Model Feature**: Impermeable/restrictive layer at specified depth limits root penetration and drainage
- **KI Gap**: `create_soil_profile.py` does not expose z_res parameter
- **Source Module**: `entities/soil.py` z_res attribute, `entities/modelConstants.py`
- **Status TODO**: Add z_res parameter to `create_soil_profile.py`

---

## C. Irrigation Management (8 capabilities)

### C1. Rainfed Baseline -- DONE
- **Model Feature**: No irrigation (method=0), used as reference for irrigation benefit analysis
- **KI Coverage**: `create_irrigation_management.py` (S5), `compare_irrigation_scenarios.py` (S10)
- **Source Module**: `solution/irrigation.py`

### C2. Soil Moisture Target (Deficit Irrigation) -- DONE
- **Model Feature**: Irrigation triggered when soil moisture drops below SMT (% TAW) per growth stage
- **KI Coverage**: `create_irrigation_management.py` (S5), `optimize_deficit_irrigation.py` (S5)
- **Source Module**: `solution/irrigation.py`, `entities/irrigationManagement.py`
- **Parameters**: SMT[4] (one per growth stage), MaxIrr, AppEff, WetSurf

### C3. Fixed Interval Irrigation -- DONE
- **Model Feature**: Irrigation at regular intervals (e.g., every 3 days)
- **KI Coverage**: `create_irrigation_management.py` (S5)
- **Source Module**: `entities/irrigationManagement.py` IrrInterval
- **Parameters**: IrrInterval (days)

### C4. Predefined Schedule -- DONE
- **Model Feature**: User-specified irrigation dates and depths via DataFrame
- **KI Coverage**: `create_irrigation_management.py` (S5)
- **Source Module**: `entities/irrigationManagement.py` Schedule (DataFrame with Date, Depth)

### C5. Net Irrigation Requirement -- DONE
- **Model Feature**: Automatic irrigation to maintain soil moisture at NetIrrSMT, calculates net requirement
- **KI Coverage**: `create_irrigation_management.py` (S5), `compare_irrigation_scenarios.py` (S10)
- **Source Module**: `solution/transpiration.py` (lines 441-507)
- **Parameters**: NetIrrSMT (% TAW)

### C6. Constant Depth Irrigation -- DONE
- **Model Feature**: Fixed daily application depth (e.g., drip irrigation)
- **KI Coverage**: `create_irrigation_management.py` (S5)
- **Source Module**: `entities/irrigationManagement.py` depth
- **Parameters**: depth (mm/day)

### C7. Irrigation Application Efficiency -- DONE
- **Model Feature**: AppEff parameter accounts for conveyance/application losses; WetSurf limits wetted area
- **KI Coverage**: `create_irrigation_management.py` (S5)
- **Source Module**: `entities/irrigationManagement.py`
- **Parameters**: AppEff (%), WetSurf (%), MaxIrr (mm/event), MaxIrrSeason (mm/season)

### C8. Growth-Stage-Specific Deficit Irrigation -- PARTIAL (model supports, tool partially covers)
- **Model Feature**: Different SMT values for each of 4 growth stages (establishment, vegetative, flowering, yield formation)
- **KI Gap**: `optimize_deficit_irrigation.py` only sweeps uniform SMT[x]*4; does not optimize stage-specific combinations
- **Source Module**: `solution/irrigation.py`, `solution/growth_stage.py`
- **Status TODO**: Extend `optimize_deficit_irrigation.py` to support stage-specific SMT optimization (e.g., [80,60,90,70])

---

## D. Salinity Stress (5 capabilities) -- ALL TODO

### D1. Soil Salinity Profile -- TODO
- **FAO AquaCrop Feature**: Soil salinity (ECe) per compartment, initial profile specification
- **AquaCrop-OSPy Status**: NOT IMPLEMENTED in v3.0.12. The FAO desktop version (v7.1) tracks SaltIn, SaltOut, SaltUp, SaltProf, SaltStr (visible in .OUT reference files), but AquaCrop-OSPy does not include salinity solution modules.
- **Evidence**: No salinity-related modules in `solution/` directory. Grep for salt/salin/ECe/osmotic found only .OUT column headers in reference data files.
- **Impact**: Cannot simulate irrigated agriculture in arid/semi-arid regions with saline water or saline soils.

### D2. Osmotic Stress on Crop Growth -- TODO
- **FAO AquaCrop Feature**: Soil salinity reduces water uptake via osmotic effect on water stress thresholds
- **AquaCrop-OSPy Status**: NOT IMPLEMENTED. No osmotic stress coefficient in `solution/water_stress.py`.
- **Impact**: Salinity-induced yield loss cannot be quantified.

### D3. Toxic Ion Stress -- TODO
- **FAO AquaCrop Feature**: Specific ion toxicity (Na, Cl, B) affects canopy expansion independent of osmotic effects
- **AquaCrop-OSPy Status**: NOT IMPLEMENTED.
- **Impact**: Cannot model crops sensitive to specific ion toxicity (e.g., citrus, avocado).

### D4. Irrigation Water Quality -- TODO
- **FAO AquaCrop Feature**: Salinity of irrigation water (ECw) affects soil salinity buildup
- **AquaCrop-OSPy Status**: NOT IMPLEMENTED. IrrigationManagement entity has no ECw parameter.
- **Impact**: Cannot evaluate irrigation with saline water (e.g., treated wastewater, brackish groundwater).

### D5. Salt Leaching and Accumulation -- TODO
- **FAO AquaCrop Feature**: Salt transport with drainage water, leaching requirement calculation
- **AquaCrop-OSPy Status**: NOT IMPLEMENTED.
- **Impact**: Cannot design leaching schedules or assess long-term soil salinization.

---

## E. Field Management (5 capabilities)

### E1. Mulching -- DONE
- **Model Feature**: Reduces soil evaporation by mulch coverage percentage and evaporation adjustment factor
- **KI Coverage**: `create_field_management.py` (S6)
- **Source Module**: `entities/fieldManagement.py`
- **Parameters**: mulches (bool), mulch_pct (%), f_mulch (0-1)

### E2. Surface Bunds -- DONE
- **Model Feature**: Soil bunds retain surface water for paddy rice or water harvesting; prevents runoff
- **KI Coverage**: `create_field_management.py` (S6) with unit conversion warning (m not mm)
- **Source Module**: `entities/fieldManagement.py`
- **Parameters**: bunds (bool), z_bund (m, converted to mm internally), bund_water (mm)

### E3. Curve Number Adjustment -- DONE
- **Model Feature**: Percentage adjustment to SCS curve number for field conditions (e.g., terracing, contour farming)
- **KI Coverage**: `create_field_management.py` (S6)
- **Source Module**: `entities/fieldManagement.py`
- **Parameters**: curve_number_adj (bool), curve_number_adj_pct (%)

### E4. Surface Runoff Inhibition -- DONE
- **Model Feature**: Complete inhibition of surface runoff (e.g., perfect terracing, micro-catchment)
- **KI Coverage**: `create_field_management.py` (S6)
- **Source Module**: `entities/fieldManagement.py`
- **Parameters**: sr_inhb (bool)

### E5. Fallow Period Field Management -- DONE
- **Model Feature**: Separate field management settings during fallow (off-season) periods
- **KI Coverage**: `assemble_model.py` (S7) accepts fallow_field_management parameter
- **Source Module**: `core.py` fallow_field_management attribute

---

## F. CO2 & Climate (4 capabilities)

### F1. CO2 Effect on Water Productivity -- DONE
- **Model Feature**: Elevated CO2 increases WP* via fCO2 adjustment factor (Steduto/FACE parameterization), with C3/C4 differentiation
- **KI Coverage**: Handled internally during model initialization
- **Source Module**: `initialize/compute_variables.py` (lines 114-198)
- **Parameters**: bsted, bface, fsink, WP (C3 vs C4 discrimination at WP=20-40 g/m2)

### F2. CO2 Effect on Transpiration -- DONE
- **Model Feature**: Elevated CO2 reduces crop coefficient (Kcb) via stomatal closure
- **KI Coverage**: Handled internally in transpiration calculations
- **Source Module**: `solution/transpiration.py` (lines 116-119, 142-143)

### F3. Historical CO2 Timeseries -- DONE
- **Model Feature**: Built-in Mauna Loa CO2 data (1902-2100); auto-selects concentration for simulation year
- **KI Coverage**: CO2 object created automatically; user can override with constant_conc or custom co2_data
- **Source Module**: `entities/co2.py`, `data/MaunaLoaCO2.txt`

### F4. Climate Change Scenario Analysis -- PARTIAL (framework exists, no dedicated tool)
- **Model Feature**: Custom CO2 timeseries and modified weather data can simulate future climate scenarios
- **KI Gap**: No tool to automatically generate climate-perturbed weather (delta method, GCM downscaling) or RCP/SSP CO2 trajectories
- **Source Module**: CO2 entity accepts custom `co2_data` DataFrame; weather can be modified externally
- **Status TODO**: Create `tools/s3_weather_prep/generate_climate_scenarios.py` for delta-change weather perturbation and SSP CO2 pathways

---

## G. Water Productivity Analysis (4 capabilities)

### G1. Crop Water Productivity (CWP) -- DONE
- **Model Feature**: Yield per unit water consumed (kg/m3), computed from ET-based and Tr-based perspectives
- **KI Coverage**: `compute_water_productivity.py` (S10)
- **Metrics**: CWP_ET (yield/ET), CWP_Tr (yield/Tr), evaporation fraction

### G2. Irrigation Water Use Efficiency (IWUE) -- DONE
- **Model Feature**: Yield per unit irrigation water applied (kg/m3)
- **KI Coverage**: `compute_water_productivity.py` (S10)
- **Metrics**: IWUE (yield/irrigation)

### G3. Water Footprint -- DONE
- **Model Feature**: Water consumed per unit yield (m3/tonne), decomposed into green and blue components
- **KI Coverage**: `compute_water_productivity.py` (S10)
- **Metrics**: WF_total, WF_green (rain-fed transpiration), WF_blue (irrigation)

### G4. Deficit Irrigation Optimization -- DONE
- **Model Feature**: Multi-scenario SMT sweep to find optimal yield-water tradeoff
- **KI Coverage**: `optimize_deficit_irrigation.py` (S5), `compare_irrigation_scenarios.py` (S10)
- **Output**: Yield vs irrigation curves, optimal CWP identification, scenario comparison tables and plots

---

## H. Multi-Crop & Rotation (3 capabilities)

### H1. Built-in Crop Library -- DONE
- **Model Feature**: 37 built-in crop parameterizations (18 CD + 19 GDD variants)
- **KI Coverage**: `select_crop.py` (S1) with full crop list
- **Crops**: Barley, Cotton, DryBean, Maize, PaddyRice, Potato, Quinoa, Sorghum, Soybean, SugarBeet, SugarCane, Sunflower, Tomato, Wheat, Tef, Cassava + GDD variants + special variants (AlfalfaGDD, MaizeChampionGDD, WheatLongGDD, etc.)

### H2. Custom Crop Parameterization -- DONE
- **Model Feature**: Full custom crop definition by setting c_name='custom' and providing all parameters
- **KI Coverage**: `select_crop.py` (S1), `validate_crop_params.py` (S1) checks consistency
- **Parameters**: 70+ configurable crop attributes

### H3. Crop Rotation Simulation -- TODO
- **Model Feature**: AquaCrop can simulate sequential crops in multi-year simulations with carry-over soil moisture
- **KI Gap**: No tool for defining crop rotations, managing planting/harvest sequences, or analyzing rotation effects
- **Status TODO**: Create `tools/s1_crop_selection/define_crop_rotation.py` for crop sequence definition and inter-crop soil moisture tracking

---

## I. Model Coupling (4 capabilities)

### I1. CaMa-Flood Waterlogging Coupling -- DONE
- **Model Feature**: CaMa-Flood flood depth/fraction converted to GroundWater object for mechanistic waterlogging stress
- **KI Coverage**: `apply_cama_flood.py` (S6) -- validated: Bengbu maize 14.18 t/ha (no flood) to 4.28 t/ha (with flood, -69.8%)
- **Status**: Fully operational with CLI and Python API

### I2. HWSD Soil Data Integration -- DONE
- **Model Feature**: HWSD v1.2 global soil database provides texture/OC for any location
- **KI Coverage**: `ki_tools_common.soil_utils.lookup_hwsd()` + `add_layer_from_texture()` in Soil class
- **Data Path**: `/home/server/Crop_model_dataset/HWSD/`

### I3. Multi-Data Source Weather Adapter -- PARTIAL (CMFD done, MSWX/NASA POWER partial)
- **Model Feature**: Weather adapter supports CMFD, MSWX, and NASA POWER data sources
- **KI Coverage**: `cmfd_to_aquacrop.py` adapter in data_ki; `prepare_weather_df.py` (S3), `compute_eto_penman_monteith.py` (S3)
- **Status**: CMFD fully tested; MSWX and NASA POWER adapters exist but have less validation

### I4. VIC/DSSAT/WOFOST Ensemble Coupling -- TODO
- **Model Feature**: Cross-model yield comparison and ensemble analysis
- **KI Gap**: No tool for running ensemble comparisons, harmonizing inputs, or merging outputs across crop models
- **Status TODO**: Create `tools/s10_water_productivity/ensemble_yield_comparison.py`

---

## Top 5 Capability Gaps (Priority Order)

| Rank | Gap                                    | Domain   | Impact                                                    | Effort |
|------|----------------------------------------|----------|-----------------------------------------------------------|--------|
| 1    | **Salinity stress (D1-D5)**            | Salinity | Cannot model irrigated agriculture in arid/semi-arid zones with saline water/soil. 5 missing capabilities. Blocked by AquaCrop-OSPy upstream (not implemented in Python version). | HIGH -- requires upstream PR to aquacrop-ospy or custom implementation |
| 2    | **Growth-stage-specific deficit optimization (C8)** | Irrigation | Current tool only sweeps uniform SMT; real-world deficit irrigation varies by growth stage. | LOW -- extend existing optimize_deficit_irrigation.py |
| 3    | **Climate change scenario tools (F4)** | Climate  | No automated workflow for delta-change perturbation, RCP/SSP pathways, or sensitivity analysis. | MEDIUM -- new tool, well-defined requirements |
| 4    | **Crop rotation simulation (H3)**      | Multi-Crop | Cannot simulate common agricultural practices like wheat-maize double cropping. | MEDIUM -- new tool with multi-season orchestration |
| 5    | **Restrictive soil layer exposure (B9)** | Soil     | z_res parameter exists in model but not exposed in KI tool. | LOW -- parameter addition to existing tool |

---

## Salinity Gap Analysis (Special Focus)

The salinity module is the **single largest gap** in AquaCrop-OSPy vs the FAO desktop AquaCrop v7.1. The desktop version implements:

1. **Soil salinity transport**: Salt movement with drainage, capillary rise, and irrigation water
2. **ECe-based stress**: Osmotic stress reduces effective water uptake
3. **Cell-specific toxicity**: Ion-specific damage to canopy expansion
4. **Leaching requirements**: Calculates minimum drainage for salt management
5. **Seasonal salt balance**: SaltIn, SaltOut, SaltUp, SaltProf tracking

Evidence from reference .OUT files (e.g., `tunis_test_1_windows.OUT`) confirms the desktop version outputs SaltIn, SaltOut, SaltUp, SaltProf, SaltStr columns -- none of which have corresponding solution modules in AquaCrop-OSPy.

**Workaround options**:
- (a) Use FAO desktop AquaCrop v7.1 for salinity studies (requires Windows/.exe, not Python)
- (b) Implement salt transport equations from AquaCrop Reference Manual Ch. 3.15 (pg. 167-180) as a post-processing module
- (c) Monitor aquacrop-ospy GitHub (github.com/aquacropos/aquacrop) for salinity module PRs

---

## Data Availability Matrix

| Data Source           | Path on Server                                     | Used By        | Status   |
|-----------------------|---------------------------------------------------|----------------|----------|
| CMFD (China, 1979-2018) | `/mnt/disk1/Hydrocraft_server/data_ki/CMFD/`   | S3 weather     | Active   |
| MSWX (Global, 1979-2026) | `/home/server/Crop_model_dataset/MSWX/`       | S3 weather     | Active   |
| NASA POWER            | API (online)                                      | S3 weather     | Active   |
| HWSD v1.2             | `/home/server/Crop_model_dataset/HWSD/`           | S2 soil        | Active   |
| GGCMI Crop Calendar   | `/home/server/Crop_model_dataset/GGCMI_phase3_crop_calendar/` | S1 crop | Available |
| China Phenology       | `/home/server/Crop_model_dataset/8313530/`        | S1 crop        | Available |
| SPAM Crop Distribution| `/home/server/Crop_model_dataset/dataverse_files/`| Regional setup | Available |
| CaMa-Flood Output     | `/mnt/disk1/Hydrocraft_server/model/cmf_v420_pkg/out/` | S6 flood  | Active   |
| Mauna Loa CO2         | Built into aquacrop package                       | CO2 adjustment | Active   |

---

*Generated by KDT v5.0 Stage s2 Capability Discovery. Jianyun Zhang Research Group, Hohai University.*
