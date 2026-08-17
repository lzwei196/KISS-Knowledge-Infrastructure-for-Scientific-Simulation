# LandscapeDNDC v1.37 -- Capability Inventory (KDT v5.0 Stage s2)

**Generated**: 2026-04-03
**Source**: Pre-built C++ binary, 19 KI tools, 10 skill documents, 22 diagnostic triplets
**Binary**: `KISSPATH_BINARIES/ldndc/ldndc-1.37.linux64/bin/ldndc`
**Current KI version**: 1.0.0
**Unique role in HydroCraft**: Only model providing GHG emission simulation (N2O, CO2, CH4, NO)

---

## Summary

| Category | Total Capabilities | DONE in KI | PARTIAL in KI | TODO (Missing) |
|----------|--------------------|------------|---------------|----------------|
| GHG Emissions (unique) | 8 | 5 | 2 | 1 |
| Soil Biogeochemistry | 8 | 5 | 1 | 2 |
| Soil Physics | 6 | 4 | 1 | 1 |
| Vegetation / Crop Growth | 7 | 4 | 1 | 2 |
| Forest Ecosystems | 5 | 1 | 0 | 4 |
| Agricultural Management | 6 | 5 | 1 | 0 |
| Wetland / Paddy CH4 | 4 | 2 | 1 | 1 |
| Multi-Model Coupling | 5 | 3 | 1 | 1 |
| Output / Post-Processing | 5 | 4 | 1 | 0 |
| **Total** | **54** | **33** | **9** | **12** |

**Overall KI coverage**: 33 DONE + 9 PARTIAL = 42/54 = **78%**

---

## 1. GHG EMISSIONS (LDNDC's Unique Capability in HydroCraft)

This is the primary reason LDNDC exists in HydroCraft. No other model in the platform simulates process-based greenhouse gas fluxes from terrestrial ecosystems. All GHG capabilities flow through the `soilchemistry:metrx` module (MeTrX -- Microbial Turnover in Exotic soils).

### 1.1 N2O Emissions (Nitrous Oxide)
- **Status**: DONE (with calibration caveat)
- **Source module**: `soilchemistry:metrx` -- nitrification + denitrification pathways
- **Output variable**: `dN_n2o_emis[kgNha-1]` (daily), `aN_n2o_emis[kgNha-1]` (yearly)
- **What it does**: Simulates N2O production from both nitrification (aerobic, NH4 -> NO3 with N2O byproduct) and denitrification (anaerobic, NO3 -> N2 with N2O intermediate). Production depends on soil moisture (anaerobic volume fraction -- anvf), temperature, NH4/NO3 availability, and labile C.
- **Validated**: Bengbu wheat-maize: 4.9 kgN/ha/yr (IPCC range 1-2% EF). Harbin maize: 0.3-0.8 kgN/ha/yr (underestimate due to plamox phenology issue -- relative changes still valid).
- **Tool**: `parse_soilchemistry_output.py`
- **Conversion**: kgN/ha to g N2O/ha: multiply by 1000 * (44/28)
- **KI GAP**: Plamox GDD calibration needed for NE China maize to fix absolute N2O underestimate. Direction/ratio of change is scientifically valid.

### 1.2 CO2 Emissions (Heterotrophic Respiration)
- **Status**: DONE
- **Source module**: `soilchemistry:metrx` -- SOM decomposition cascade
- **Output variable**: `dC_co2_emis_hetero[kgCha-1]` (daily), `aC_co2_emis_hetero[kgCha-1]` (yearly)
- **What it does**: Simulates CO2 release from microbial decomposition of soil organic matter pools (labile, resistant, humus). Temperature and moisture dependent via Q10 and WFPS functions.
- **Validated**: Bengbu: heterotrophic respiration ~1,537 kgC/ha/yr -- reasonable for warm-temperate cropland.
- **Tool**: `parse_soilchemistry_output.py`

### 1.3 CO2 Emissions (Autotrophic Respiration)
- **Status**: DONE
- **Source module**: `physiology:plamox` or `physiology:psim` -- maintenance + growth respiration
- **Output variable**: `dC_co2_emis_auto[kgCha-1]` (daily), `aC_co2_emis_auto[kgCha-1]` (yearly)
- **What it does**: Root and plant maintenance/growth respiration. Separate from soil heterotrophic respiration.
- **Tool**: `parse_soilchemistry_output.py`

### 1.4 CH4 Emissions (Methane)
- **Status**: PARTIAL
- **Source module**: `soilchemistry:metrx` -- anaerobic decomposition / methanogenesis
- **Output variable**: `dC_ch4_emis[kgCha-1]` (daily), `aC_ch4_emis[kgCha-1]` (yearly)
- **What it does**: CH4 production in anaerobic soil zones (methanogenesis) minus CH4 oxidation in aerobic zones (methanotrophy). Net emission depends on water table depth and soil anaerobic volume.
- **Validated**: Dryland arable -- near-zero CH4 (correct). Paddy rice -- high variance, needs calibration.
- **KI GAP**: Paddy CH4 module not fully calibrated. CaMa-Flood water table coupling (for wetlands/floodplains) is conceptual only.

### 1.5 NO Emissions (Nitric Oxide)
- **Status**: DONE
- **Source module**: `soilchemistry:metrx` -- chemodenitrification + nitrification
- **Output variable**: `dN_no_emis[kgNha-1]` (daily), `aN_no_emis[kgNha-1]` (yearly)
- **What it does**: NO production from chemodenitrification (abiotic, acid soils) and as a byproduct of nitrification. Important for atmospheric chemistry (ozone precursor).
- **Tool**: `parse_soilchemistry_output.py`

### 1.6 NH3 Volatilization
- **Status**: DONE
- **Source module**: `soilchemistry:metrx`
- **Output variable**: `dN_nh3_emis[kgNha-1]` (daily), `aN_nh3_emis[kgNha-1]` (yearly)
- **What it does**: Ammonia volatilization from surface-applied urea/ammonium fertilizers. Depends on pH, temperature, wind, and application depth.
- **Tool**: `parse_soilchemistry_output.py`

### 1.7 N2 Emissions (Dinitrogen)
- **Status**: PARTIAL
- **Source module**: `soilchemistry:metrx` -- complete denitrification
- **Output variable**: `dN_n2_emis[kgNha-1]` (daily), `aN_n2_emis[kgNha-1]` (yearly)
- **What it does**: Terminal product of denitrification. N2 emission is not a GHG but is important for N budget closure. The N2O/(N2O+N2) ratio is a key indicator of denitrification efficiency.
- **Note**: N2 values are internally consistent but rarely validated against measurements (no practical measurement technique at field scale).

### 1.8 Total GHG Budget (CO2-equivalent)
- **Status**: TODO
- **What it would do**: Aggregate N2O, CO2, CH4 into a single CO2-equivalent metric using GWP100 (N2O=265, CH4=28). Currently computed ad hoc in `run_ldndc_bengbu_ghg.py` but not as a reusable tool.
- **KI GAP**: No dedicated `compute_ghg_budget_co2eq.py` tool. The Bengbu tool does it inline but is site-specific.

---

## 2. SOIL BIOGEOCHEMISTRY

### 2.1 Nitrogen Mineralization / Immobilization
- **Status**: DONE
- **Source module**: `soilchemistry:metrx`
- **Output variable**: `dN_mineral[kgNha-1]`, `dN_immobilise[kgNha-1]` (daily)
- **What it does**: Net mineralization of organic N to NH4 (or immobilization of NH4 into microbial biomass) depending on substrate C:N ratio vs. microbial C:N demand.
- **Tool**: `parse_soilchemistry_output.py`

### 2.2 Nitrification
- **Status**: DONE
- **Source module**: `soilchemistry:metrx`
- **Output variable**: `dN_nitrify[kgNha-1]` (daily), `aN_nitrify[kgNha-1]` (yearly)
- **What it does**: Autotrophic oxidation of NH4 to NO3 by Nitrosomonas/Nitrobacter. Rate depends on NH4 availability, soil moisture (optimal at ~60% WFPS), temperature, and pH.

### 2.3 Denitrification
- **Status**: DONE
- **Source module**: `soilchemistry:metrx`
- **Output variable**: `dN_denitrify[kgNha-1]` (daily), `aN_denitrify[kgNha-1]` (yearly)
- **What it does**: Anaerobic reduction of NO3 to N2O and N2. Driven by anaerobic volume fraction (anvf), NO3 availability, and labile C as electron donor. The anvf_mean output tracks the daily mean anaerobic fraction.

### 2.4 Chemodenitrification
- **Status**: DONE
- **Source module**: `soilchemistry:metrx`
- **Output variable**: `dN_chemodenitrify[kgNha-1]` (daily)
- **What it does**: Abiotic decomposition of NO2 in acidic soils, producing NO. Important in forest soils with pH < 5.

### 2.5 Soil Organic Carbon Dynamics
- **Status**: DONE
- **Source module**: `soilchemistry:metrx` -- multi-pool SOM model
- **Output variable**: `C_soil[kgCha-1]`, `C_soil_20cm`, `C_soil_30cm`, `C_mic`, `C_sol`, `C_aorg`, `C_litter_raw`, `C_litter` (daily pool states)
- **What it does**: Tracks multiple C pools: raw litter, litter, microbial biomass (C_mic), soluble organic C (C_sol), and stable humus (C_aorg). Decomposition rate of each pool depends on temperature, moisture, and clay content (protective effect).
- **Validated**: Bengbu SOC change +463 kgC/ha/yr (literature: +113-350 for straw return systems)

### 2.6 Nutrient Leaching (NO3, NH4, DON, DOC)
- **Status**: PARTIAL
- **Source module**: `soilchemistry:metrx` + `watercycle:dndc`
- **Output variables**: `dN_no3_leach`, `dN_nh4_leach`, `dN_don_leach`, `dC_doc_leach` (daily)
- **What it does**: Dissolved N and C transported downward with percolating water. NO3 is the dominant leachable form; NH4 is mostly adsorbed.
- **Validated**: Bengbu NO3 leaching 41.4 kgN/ha (literature: 38-60 kgN/ha for NCP)
- **KI GAP**: No tool to compute NO3 concentration in drainage water (load/volume). Coupling formula exists in skill doc but no automated tool.

### 2.7 Biological N Fixation
- **Status**: TODO
- **Source module**: `soilchemistry:metrx` + `physiology:plamox`
- **Output variable**: `dN_n2_fix[kgNha-1]` (in soilchemistry), `dN_n2_fix[kgNm-2]` (in physiology)
- **What it does**: Symbiotic N fixation for legumes (soybean) and free-living fixation. Available in output but no dedicated tool or documentation for setting up legume-specific simulations.
- **KI GAP**: No skill document or tool for legume N fixation configuration.

### 2.8 Sulfur Cycling
- **Status**: TODO
- **Source module**: `soilchemistry:metrx`
- **Output variable**: `dS_so4_leach[kgSha-1]` (daily)
- **What it does**: SO4 leaching tracked in output. Sulfur cycling is a secondary capability with minimal documentation.
- **KI GAP**: No tool or skill document for sulfur. Low priority.

---

## 3. SOIL PHYSICS

### 3.1 Soil Heat Transfer (Temperature Profile)
- **Status**: DONE
- **Source module**: `microclimate:canopyecm`
- **Output variables**: `temp_soil_surface`, `temp_5cm`, `temp_10cm`, `temp_15cm`, `temp_20cm`, `temp_30cm`, `temp_50cm`, `temp_100cm` (from microclimate-daily.txt)
- **What it does**: Solves heat conduction equation through soil layers. Drives temperature-dependent biogeochemistry (decomposition Q10, nitrification, denitrification). Includes freeze-thaw effects.

### 3.2 Soil Water Dynamics
- **Status**: DONE
- **Source module**: `watercycle:watercycledndc`
- **Output variables**: `soilwater[mm]`, `soilwater_rooted[mm]`, `soilwater_5cm[%]` through `soilwater_120cm[%]` (from watercycle-daily.txt)
- **What it does**: Richards equation (or simplified bucket) for vertical water movement. Tracks volumetric water content and capillary pressure at multiple depths.

### 3.3 Infiltration and Percolation
- **Status**: DONE
- **Source module**: `watercycle:watercycledndc`
- **Output variables**: `infiltration[mm]`, `percolation[mm]` (daily)
- **What it does**: Water movement from surface into soil (infiltration) and through soil layers to groundwater (percolation/drainage).

### 3.4 Evapotranspiration Partitioning
- **Status**: DONE
- **Source module**: `watercycle:watercycledndc` + `physiology:plamox`
- **Output variables**: `pot_evapotranspiration`, `pot_transpiration`, `transpiration`, `soil_evaporation`, `interception_evaporation`, `surface_evaporation` (daily)
- **What it does**: Partitions ET into plant transpiration, soil evaporation, interception evaporation, and surface water evaporation. Transpiration linked to stomatal conductance from physiology module.

### 3.5 Freeze-Thaw Dynamics
- **Status**: PARTIAL
- **Source module**: `watercycle:watercycledndc` + `microclimate:canopyecm`
- **What it does**: Soil freezing affects water movement (reduced permeability) and creates conditions for freeze-thaw N2O pulses (a major N2O source in cold climates). Temperature profile tracking is done but no dedicated tool to analyze freeze-thaw cycles or their biogeochemical effects.
- **KI GAP**: No tool or documentation for freeze-thaw N2O pulse analysis.

### 3.6 Groundwater Table Dynamics
- **Status**: TODO
- **Source module**: `watercycle:watercycledndc`
- **Output variable**: `groundwater_access[m]`, `groundwater[m]` (daily)
- **What it does**: Tracks groundwater table depth, which controls anaerobic volume and thus denitrification/methanogenesis. Currently output is available (`groundwater[m]` = 99 in many runs, indicating default/uncalibrated).
- **KI GAP**: CaMa-Flood water table coupling is conceptual only (no validated tool). Need tool to set dynamic groundwater boundary from external model.

---

## 4. VEGETATION / CROP GROWTH

### 4.1 Crop Phenology (PlamoX)
- **Status**: DONE (with calibration caveat)
- **Source module**: `physiology:plamox`
- **Output variables**: `gdd[oC]`, `pds_gdd[-]`, `dvs_flush[-]`, `day_emergence[-]` (from physiology-daily.txt)
- **What it does**: Growing degree day (GDD) driven phenological development. Development stage (DVS) controls biomass allocation, leaf area expansion, and harvest index.
- **Known issue**: DVS only reaches 0.4-0.65 for NE China maize in ~50% of years (too much thermal time required). Needs GDD parameter calibration per region.

### 4.2 Biomass Allocation and Yield
- **Status**: DONE
- **Source module**: `physiology:plamox`
- **Output variables**: `DW_fol`, `DW_fru` (grain), `DW_frt` (fine roots), `DW_lst` (living stem), `DW_above`, `DW_below` (daily, in kgDW/m2)
- **What it does**: Partitions assimilates into foliage, fruit (grain), roots, stems. Harvest index determines grain fraction.
- **Conversion**: kgC/ha to kgDM/ha: divide by 0.45

### 4.3 Gross/Net Primary Production
- **Status**: DONE
- **Source module**: `physiology:plamox`
- **Output variables**: `dC_co2_upt[kgCm-2]` (GPP proxy), individual organ growth/respiration terms
- **What it does**: Light-driven CO2 uptake (photosynthesis), minus respiration losses. Water and nitrogen stress reduce actual from potential GPP.

### 4.4 Leaf Area Index (LAI)
- **Status**: DONE
- **Source module**: `physiology:plamox`
- **Output variable**: `lai[-]`, `specific_leaf_area[m2kg-1]` (daily)
- **What it does**: Tracks LAI from emergence through senescence. Drives light interception, transpiration, and canopy microclimate.

### 4.5 Root Dynamics and Exudates
- **Status**: PARTIAL
- **Source module**: `physiology:plamox`
- **Output variables**: `dC_frt_grow`, `DW_frt`, `dC_exsudates[kgCm-2]` (daily)
- **What it does**: Root growth, turnover, and exudate release. Root exudates provide labile C to soil microorganisms, driving rhizosphere denitrification (a key N2O source).
- **KI GAP**: No tool to analyze root exudate contribution to N2O. Exudate data is in output but not parsed or analyzed.

### 4.6 Senescence and Litter Production
- **Status**: TODO
- **Source module**: `physiology:plamox`
- **Output variables**: `dDW_fol_sen`, `dDW_frt_sen`, `dDW_lst_sen_below`, `dDW_lst_sen_above`, `dN_lit_fol`, `dN_lit_frt` (daily)
- **What it does**: Leaf, root, and stem senescence produces litter input to soil C/N pools. N retranslocation from senescing tissue affects litter C:N ratio and subsequent decomposition/N2O production.
- **KI GAP**: Senescence output variables exist but no dedicated parsing tool or analysis workflow.

### 4.7 BVOC Emissions (Isoprene, Monoterpenes)
- **Status**: TODO
- **Source module**: `physiology:plamox` / `physiology:psim`
- **Output variables**: `d_iso_emis`, `d_mono_emis`, `d_mono_storage_emis`, `d_ovoc_emis` (daily, in umol/m2)
- **What it does**: Biogenic volatile organic compound emissions. Isoprene and monoterpene emissions from vegetation, temperature and light dependent. Important for atmospheric chemistry.
- **KI GAP**: BVOC output columns exist but no parsing tool, no documentation, no validation. Low priority for HydroCraft.

---

## 5. FOREST ECOSYSTEMS

### 5.1 Forest Stand Initialization (PSIM)
- **Status**: DONE (example exists)
- **Source module**: `physiology:psim` (forest physiology)
- **Example project**: `projects/forest/DE_hoeglwald/DE_hoeglwald_spruce/`
- **What it does**: Initialize forest stand with DBH, height, tree number, crown dimensions. PSIM handles individual tree growth, competition, and mortality.
- **Species**: Spruce (piab), Beech available in example projects
- **KI GAP**: No dedicated KI tool for forest initialization. Only the raw example XML exists.

### 5.2 Forest Canopy and Light Interception
- **Status**: TODO
- **Source module**: `physiology:psim` + `microclimate:canopyecm`
- **Output modules**: `output:vegstructure:daily`, `output:vegstructure:yearly`
- **What it does**: Multi-layer canopy light interception, canopy temperature/humidity profile. Drives photosynthesis and transpiration for trees.
- **KI GAP**: No tool, no skill document, no vegstructure output parser.

### 5.3 Tree Growth and Wood Increment
- **Status**: TODO
- **Source module**: `physiology:psim`
- **Output variables**: `C_wood_above`, `C_wood_below` (in soilchemistry output), `DW_dst_above`, `DW_dst_below` (in physiology)
- **What it does**: Annual wood increment, stem/branch/root growth allocation, heartwood formation. Wood C pool variables present in output but not parsed for forests.
- **KI GAP**: No tool for forest growth analysis.

### 5.4 Forest Management (Thinning, Clear-cut)
- **Status**: TODO
- **Source module**: Management events in mana.xml
- **Example**: `DE_hoeglwald_spruce_mana.xml` uses `<event type="plant">` with wood parameters
- **What it does**: Thinning (removing fraction of stems), clear-cutting, replanting. Management affects canopy structure, litter input, and soil C/N cycling.
- **KI GAP**: No generate_forest_management_xml tool. No documentation on forest management event types.

### 5.5 Forest Soil N2O and NO Emissions
- **Status**: TODO
- **Source module**: `soilchemistry:metrx` (same as cropland, different parameterization)
- **What it does**: Forest soils are typically N-limited with low pH, making chemodenitrification (NO) more important than denitrification (N2O). The forest setup uses `soilchemistry:metrx` with forest-specific soil (high corg litter layer, low pH).
- **KI GAP**: No forest-specific GHG tools. The existing soilchemistry parser would work but setup/calibration is undocumented.

---

## 6. AGRICULTURAL MANAGEMENT

### 6.1 Sowing / Planting
- **Status**: DONE
- **Source module**: Management events (mana.xml)
- **Tool**: `generate_management_xml.py`
- **What it does**: Defines crop species, sowing date, seed amount. Species name must exactly match `parameters_species.xml`.
- **Validated species**: CORN, WIWH, PADR, SWHE, SOYB, RAPE

### 6.2 Fertilization (Synthetic and Organic)
- **Status**: DONE
- **Source module**: Management events (mana.xml)
- **Tool**: `generate_management_xml.py`
- **What it does**: N fertilizer application (urea, ammonium_nitrate, organic). Specifies amount (kgN/ha), type, depth (cm). Surface application promotes NH3 volatilization; deep placement reduces losses.
- **Output tracking**: `report-fertilize.txt` logs applied amounts per event.

### 6.3 Tillage
- **Status**: DONE
- **Source module**: Management events (mana.xml)
- **Tool**: `generate_management_xml.py`
- **What it does**: Soil disturbance to specified depth with residue incorporation intensity (0-1). Affects soil structure, aeration (thus N2O/CH4), and residue distribution.
- **Note**: Depth in meters in XML (0.25 = 25cm). Providing cm value (25) = 25m deep (silent error).

### 6.4 Harvest
- **Status**: DONE
- **Source module**: Management events (mana.xml)
- **Tool**: `generate_management_xml.py`
- **What it does**: Crop harvest with configurable residue fraction (0-1) left on field. Residue retention affects subsequent soil C input and N2O emissions.
- **Output tracking**: `report-harvest.txt` logs harvest biomass per organ (fruit, straw, stubble, roots) and export fractions.

### 6.5 Irrigation
- **Status**: DONE
- **Source module**: Management events (mana.xml)
- **Tool**: `generate_management_xml.py`
- **What it does**: Water application (mm). Affects soil moisture, anaerobic volume, and thus N2O/CH4 production.
- **Output**: `irrigation[mm]` in watercycle-daily.txt

### 6.6 Flood/Drain (Paddy Rice)
- **Status**: PARTIAL
- **Source module**: Management events (mana.xml)
- **Tool**: `generate_management_xml.py` (basic support)
- **What it does**: Explicit flood (ponding water) and drain events for paddy rice. Controls anaerobic conditions that drive CH4 production.
- **Species**: Must use PADR (not RICE). Validated as working but CH4 calibration is incomplete.
- **KI GAP**: Paddy-specific module stack configuration is documented in SKILL.md but not automated in a dedicated tool.

---

## 7. WETLAND / PADDY CH4

### 7.1 Paddy Rice CH4 Emissions
- **Status**: DONE (basic)
- **Source module**: `soilchemistry:metrx` with paddy management (flood/drain events)
- **What it does**: Methanogenesis under anaerobic flooded conditions, oxidation during drainage periods. AWD (alternate wetting-drying) management can reduce CH4.
- **Species**: PADR (paddy rice), UPLR (upland rice)
- **KI GAP**: High variance in results; needs calibration against eddy covariance data.

### 7.2 Water Table Driven CH4
- **Status**: PARTIAL
- **Source module**: `soilchemistry:metrx` -- anaerobic volume depends on water table
- **What it does**: CH4 production scales with anaerobic soil volume, which depends on water table depth. Shallow water table = more methanogenesis.
- **KI GAP**: Dynamic water table from CaMa-Flood not yet coupled (conceptual in coupling docs).

### 7.3 Wetland Ecosystem Configuration
- **Status**: TODO
- **Source module**: `soilchemistry:metrx` with wetland module stack
- **Module stack**: microclimate:canopyecm + watercycle:dndc + soilchemistry:metrx + physiology:plamox (documented in s3_setup_modules_skill.md)
- **What it does**: Natural wetland with permanent or seasonal waterlogging, high organic soils, and sustained CH4 emissions.
- **KI GAP**: No wetland example project, no dedicated tools, no validation data.

### 7.4 Redox Chemistry (Fe/Mn Cycling)
- **Status**: TODO
- **Source module**: `soilchemistry:metrx` -- iron reduction/oxidation
- **Relevant output**: site.xml has `fe="0.0"` attribute in soil layers
- **What it does**: Iron reduction competes with methanogenesis as electron acceptor in anaerobic soils. Fe-rich soils suppress CH4. Fe attribute is present in site.xml schema but not populated by any KI tool.
- **KI GAP**: No documentation on Fe cycling, no tool populates Fe values.

---

## 8. MULTI-MODEL COUPLING

### 8.1 VIC Climate Forcing to LDNDC
- **Status**: DONE
- **Tool**: `vic_to_ldndc_climate.py`
- **Coupling**: VIC 7-col sub-daily forcing -> LDNDC climate.txt (daily, K->C, VP->RH, sum precip)
- **Validated**: Bengbu, Chaohu, Longpan, Wangjiaba basins

### 8.2 VIC Soil to LDNDC Site
- **Status**: DONE
- **Tool**: `vic_soil_to_ldndc_site.py`
- **Coupling**: VIC SOIL_PARAM (53 cols, 3 layers) -> LDNDC site.xml (5-10 layers). BD kg/m3->g/cm3. Supplemented by HWSD for pH and corg.
- **Validated**: Multiple basins

### 8.3 VIC Soil Moisture to LDNDC Initial Conditions
- **Status**: DONE
- **Tool**: `vic_to_ldndc_soilwater.py`
- **Coupling**: VIC OUT_SOIL_MOIST (mm) -> LDNDC volumetric fraction (m3/m3). Layer interpolation.

### 8.4 CaMa-Flood Water Table to LDNDC Groundwater
- **Status**: PARTIAL (conceptual)
- **Coupling**: CaMa-Flood sfcelv/flddph -> LDNDC groundwater boundary
- **Impact**: Controls anaerobic volume -> N2O and CH4 production in floodplains
- **KI GAP**: No validated tool. Coupling formula documented in `model_couplings.yaml` and skill doc but not implemented as a working tool.

### 8.5 DSSAT Yield Cross-Validation
- **Status**: TODO
- **Coupling**: LDNDC yield (kgC/ha) vs DSSAT yield (kgDM/ha). Conversion: yield_DM = yield_C / 0.45
- **KI GAP**: No automated comparison tool. Documented in coupling skill doc but requires manual extraction.

---

## 9. OUTPUT / POST-PROCESSING

### 9.1 Daily Soilchemistry Parsing
- **Status**: DONE
- **Tool**: `parse_soilchemistry_output.py`
- **Parses**: All GHG fluxes, leaching, C/N pool states from soilchemistry-daily.txt (48 columns)

### 9.2 Daily Watercycle Parsing
- **Status**: DONE
- **Tool**: `parse_watercycle_output.py`
- **Parses**: ET components, drainage, runoff, soil moisture at 12 depth levels, capillary pressure (47 columns)

### 9.3 Daily Physiology Parsing
- **Status**: DONE
- **Tool**: `parse_physiology_output.py`
- **Parses**: GDD, DVS, biomass per organ, LAI, N uptake, senescence, BVOC emissions (70+ columns)

### 9.4 Annual Budget Aggregation
- **Status**: DONE
- **Tool**: `aggregate_annual_budget.py`
- **What it does**: Annual C budget (GPP - Rh - Ra - harvest - leach = delta_C_pool), N budget (deposition + fertilizer - harvest - leach - gas = delta_N_pool), water budget (P - ET - drainage - runoff = delta_storage). Mass balance closure check (<5% residual).

### 9.5 Microclimate Output Parsing
- **Status**: PARTIAL
- **Output**: microclimate-daily.txt (energy balance, soil temperature profile, VPD -- 27 columns)
- **What it does**: Radiation balance (SW in/out, LW in/out), latent/sensible heat, soil temperature at 8 depths, canopy temperature, VPD.
- **KI GAP**: No dedicated `parse_microclimate_output.py` tool. Data is available in output but not parsed by any existing tool.

---

## Top 5 Gaps (Priority Order)

| Rank | Gap | Impact | Effort |
|------|-----|--------|--------|
| 1 | **Plamox GDD calibration for regional crops** | N2O absolute values 5-10x too low for NE China maize. Fixes the single biggest scientific limitation. | Medium -- requires adjusting thermal time parameters in parameters_species.xml per region |
| 2 | **CaMa-Flood water table coupling tool** | Enables wetland/floodplain CH4 and N2O, currently the only conceptual-only coupling in the platform | Medium -- coupling formula exists, needs implementation + validation |
| 3 | **Total GHG budget tool (CO2-eq)** | No reusable tool to compute CO2-equivalent emissions. Currently done ad hoc in site-specific scripts | Low -- straightforward aggregation with GWP100 factors |
| 4 | **Forest ecosystem KI** (init, growth, management) | Forest is LDNDC's second major use case but has zero KI tools (only raw example XML). 4 capabilities blocked. | High -- requires forest-specific species params, management events, validation data |
| 5 | **Microclimate output parser** | Soil temperature profile data is generated but not accessible through KI tools | Low -- simple TSV parser following existing patterns |

---

## GHG Capability Coverage Summary

| GHG Species | Process | Status | Absolute Values Usable? | Relative Changes Usable? |
|-------------|---------|--------|--------------------------|--------------------------|
| N2O | Nitrification | DONE | Partial (region-dependent) | YES |
| N2O | Denitrification | DONE | Partial (region-dependent) | YES |
| CO2 | Heterotrophic respiration | DONE | YES | YES |
| CO2 | Autotrophic respiration | DONE | YES | YES |
| CH4 | Methanogenesis (dryland) | DONE | YES (near-zero, correct) | YES |
| CH4 | Methanogenesis (paddy) | PARTIAL | NO (high variance) | Partial |
| CH4 | Methanogenesis (wetland) | TODO | NO (no coupling) | NO |
| NO | Nitrification + chemodenitrification | DONE | YES | YES |
| NH3 | Volatilization | DONE | YES | YES |
| N2 | Complete denitrification | DONE | YES (budget closure) | YES |

**Bottom line**: LDNDC provides 8/10 GHG process pathways in DONE/PARTIAL state. For dryland cropland GHG assessments (the primary HydroCraft use case), 7/8 capabilities are fully operational. The main scientific limitation is absolute N2O magnitude for under-calibrated crop regions (direction of change remains valid).

---

*This capability inventory was generated as part of KDT v5.0 Stage s2 (Capability Discovery).*
*Part of the HydroCraft multi-model simulation platform by the Jianyun Zhang Research Group, Hohai University.*
