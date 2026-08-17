# HYPE v5.35.0 -- Capability Inventory (KDT v5.0 Stage s2)

**Generated**: 2026-04-01
**Source**: 38 Fortran 90 files, 93,622 lines (`KISSPATH_BINARIES/hype/hype_5_35_0_src/`)
**Binary**: `KISSPATH_BINARIES/hype/hype`
**Current KI version**: 1.0.0

---

## Summary

| Category | Total Capabilities | In Current KI | Missing from KI |
|----------|--------------------|---------------|-----------------|
| Hydrology (core) | 12 | 8 | 4 |
| Water Quality (NPC) | 6 | 0 (mentioned) | 6 |
| Cryosphere | 4 | 1 (basic snow) | 3 |
| Lakes/Reservoirs | 4 | 3 (olake+LakeData+DamData) | 1 |
| Advanced Processes | 6 | 0 | 6 |
| Calibration/DA | 4 | 1 (built-in optimization) | 3 |
| **Total** | **36** | **13** | **23** |

---

## 1. HYDROLOGY (CORE)

### 1.1 Soil Water Balance (DEFAULT SOIL MODEL)
- **Status**: DONE in KI
- **Source**: `soilmodel0.f90` (SOILMODEL_DEFAULT), `soil_proc.f90` (SOIL_PROCESSES)
- **What it does**: Multi-layer (1-3) soil moisture accounting with field capacity/wilting point/effective porosity. Surface runoff, macropore flow, tile drainage, percolation, groundwater table.
- **Input files**: GeoClass.txt (soil depths, numlayers), par.txt (wcfc, wcwp, wcep, rrcs1, rrcs2, srrcs)
- **Output**: Soil moisture (soim), runoff components (ro1, ro2, rod, ros, crun)
- **Data KI needed**: HWSD (soil types), SoilGrids (soil properties)
- **Data KI exists**: HWSD (YES), SoilGrids (YES)

### 1.2 Precipitation and Temperature Forcing
- **Status**: DONE in KI
- **Source**: `atm_proc.f90` (ATMOSPHERIC_PROCESSES)
- **What it does**: Precipitation correction (elevation, phase, undercatch), temperature lapse rate, rain/snow separation, snowfall distribution (wind redistribution).
- **Input files**: Pobs.txt, Tobs.txt, ForcKey.txt, info.txt (tempcorr, preccorr, pcurain, pcusnow, pcelevmax, etc.)
- **Output**: Corrected precipitation (cprc), temperature
- **Data KI needed**: CMFD, MSWX, NASA_POWER
- **Data KI exists**: CMFD (YES), MSWX (YES), NASA_POWER (YES)

### 1.3 Potential Evapotranspiration (6 PET models)
- **Status**: DONE in KI (petmodel 1 Jensen-Haise used)
- **Source**: `atm_proc.f90` -- `calculate_potential_evaporation`
- **Options (modeloption petmodel)**:
  - 0: Default HYPE (temperature-based)
  - 1: Jensen-Haise (T + radiation) -- **used in KI**
  - 2: Modified Hargreaves-Samani (Tmin, Tmax)
  - 3: (reserved)
  - 4: Priestley-Taylor (needs radiation)
  - 5: FAO Penman-Monteith (needs wind, humidity, radiation, pressure)
- **Input files**: Tobs.txt; optionally SWobs.txt, TMINobs.txt, TMAXobs.txt, Uobs.txt, RHobs.txt
- **Output**: epot (potential ET), evap (actual ET)
- **Data KI needed**: CMFD/MSWX (T); for petmodel 5: wind, humidity, radiation from CMFD
- **Data KI exists**: CMFD (YES -- has all variables)
- **KI GAP**: Only petmodel 1 documented. Petmodels 2-5 need additional forcing files and adapter support.

### 1.4 Actual Evapotranspiration
- **Status**: DONE in KI
- **Source**: `soil_proc.f90` -- `calculate_actual_soil_evapotranspiration`
- **What it does**: Reduces PET based on soil moisture (lp parameter), splits between soil layers, handles snow evaporation option.
- **Parameters**: lp, cevp, epotdist, fepotsnow, kc (crop coefficient)

### 1.5 River Routing (MAINDOWN topology)
- **Status**: DONE in KI
- **Source**: `sw_proc.f90` -- `translation_in_river`, `calculate_river_characteristics`
- **What it does**: Internal routing via MAINDOWN topology. Translation (lag) in river based on rivvel/rivlen. Damping (damp parameter).
- **Input files**: GeoData.txt (MAINDOWN, RIVLEN), par.txt (rivvel, damp)
- **Output**: cout (computed outflow), timeCOUT.txt
- **Data KI needed**: DEM for topology
- **Data KI exists**: ChinaDEM (YES), SRTM (YES)

### 1.6 Surface Runoff
- **Status**: DONE in KI
- **Source**: `soil_proc.f90` -- `calculate_surface_runoff`, `calculate_infiltration_flow_diversion`
- **Options (modeloption surfacerunoff, infiltration)**:
  - infiltration 0: standard
  - infiltration 1: restricted into frozen soils
  - infiltration 2: old scheme (runoff before infiltration)
- **Parameters**: srrcs, srrate, macrate, mactrinf, mactrsm

### 1.7 Tile Drainage
- **Status**: DONE in KI (via GeoClass tiledepth)
- **Source**: `soil_proc.f90` -- `calculate_tile_drainage`
- **What it does**: Preferential flow through tile drains when soil layers exceed field capacity above tile depth.
- **Input files**: GeoClass.txt (tiledepth column)
- **Parameters**: trrcs (tile drainage recession)

### 1.8 Groundwater Table Calculation
- **Status**: DONE in KI
- **Source**: `soil_proc.f90` -- `calculate_groundwater_table`
- **What it does**: Calculates GW table depth from soil moisture profile. Used for output and some process interactions.

### 1.9 Soil Temperature and Frost
- **Status**: PARTIALLY in KI (soil temp used, frost not configured)
- **Source**: `soil_proc.f90` -- `calculate_soiltemp`, `calculate_frostdepth`, `calculate_unfrozen_soil_water`
- **Options (modeloption frozensoil)**:
  - 0: No frozen water (current default)
  - 1: Unfrozen water as function of temperature
  - 2: Unfrozen water as function of three temperatures
- **Parameters**: cfrost, sfrost, soilmem, deepmem
- **KI GAP**: Frozen soil model not documented or configured.

### 1.10 Snow Heat Content Model
- **Status**: NOT in KI
- **Source**: `soil_proc.f90` -- `calculate_snowheat_processes`
- **Options (modeloption snowheat)**: 0=off, 1=on (melt delayed until heat content corresponds to 0 C)
- **Parameters**: (uses snow thermal conductivity function)
- **KI GAP**: Not documented. Relevant for cold-region basins.

### 1.11 Recharge/Discharge Classes
- **Status**: NOT in KI
- **Source**: `soilmodel0.f90` (via `p_redischarge`)
- **Options (modeloption redischarge)**: 0=off, 1=recharge and discharge classes defined
- **What it does**: Separates landscape into recharge zones (losing water to GW) and discharge zones (receiving GW). Fraction-based.
- **KI GAP**: Not documented.

### 1.12 Connectivity (Fill-and-Spill / HDS)
- **Status**: NOT in KI
- **Source**: `sw_proc.f90`, `ll_proc.f90` (LAYEREDLAKE_PROCESSES)
- **Options (modeloption connectivity)**:
  - 0: No connectivity
  - 1: ilake fill-and-spill model (multiple lake sections)
  - 2: HDS model
  - 3: Both
- **What it does**: Internal lake connectivity within subbasins. Fill-and-spill between lake sections.
- **KI GAP**: Not documented. New in v5.35.

---

## 2. WATER QUALITY (NITROGEN, PHOSPHORUS, ORGANIC CARBON)

### 2.1 Nitrogen Transport (IN, ON pools)
- **Status**: NOT in KI (mentioned as future work)
- **Source**: `npc_soil_proc.f90`, `npc_sw_proc.f90`
- **What it does**: Simulates inorganic nitrogen (IN) and organic nitrogen (ON) in soil and water.
  - Soil: mineralization, plant uptake, denitrification, humus decomposition, atmospheric deposition
  - Water: denitrification in rivers/lakes, sedimentation, production/mineralization
- **Input files**: info.txt (`substance N`), par.txt (fastn0, humusn0, denitrlu, minerfn, dissolhn, dissolfn, degradhn, etc.)
- **Output**: crunIN, crunON, reIN, reON, reTN, soildenitr, cropNupt
- **Data KI needed**: Atmospheric deposition data, crop/fertilizer data
- **Data KI exists**: FAOSTAT (YES -- fertilizer), NPKGRIDS (YES -- nutrient inputs), CROPGRIDS (YES -- crop data)

### 2.2 Phosphorus Transport (SP, PP pools)
- **Status**: NOT in KI (mentioned as future work)
- **Source**: `npc_soil_proc.f90`, `npc_sw_proc.f90`
- **What it does**: Simulates soluble phosphorus (SP) and particulate phosphorus (PP) in soil and water.
  - Soil: Freundlich adsorption, humus decomposition, crop uptake, erosion/particle transport
  - Water: sedimentation, internal loading, macrophyte uptake
- **Input files**: info.txt (`substance P`), par.txt (fastp0, humusp0, partp0, minerfp, dissolfp, dissolhp, etc.)
- **Output**: crunSP, crunPP, reSP, rePP, reTP
- **Parameters**: Freundlich coefficients (freuc, freuexp, freurate), erosion (soilcoh, soilerod, sedexp)
- **Data KI needed**: Soil P content, atmospheric P deposition
- **Data KI exists**: NPKGRIDS (YES), SoilGrids (YES)

### 2.3 Organic Carbon Transport (OC)
- **Status**: NOT in KI
- **Source**: `npc_soil_proc.f90` -- `soil_carbon_pool_transformations`, `carbon_runoff_delay`
- **What it does**: Simulates organic carbon (OC) with fast/humus pools, decay, and runoff delay.
- **Input files**: info.txt (`substance C`), par.txt (humusc0st, humusc1-3, fastc1-3, minc, klh, klo, kho, koc, kof)
- **Output**: crunOC, reOC, csoilOC

### 2.4 Sediment / Soil Erosion
- **Status**: NOT in KI
- **Source**: `npc_soil_proc.f90` -- `calculate_MMF_erosion`, `calculate_hbvsed_erosion`, `particle_processes_for_runoff`
- **Options (modeloption erosionmodel)**: 0=MMF-based, 1=HBV-Sed based
- **What it does**: Erosion-driven particulate phosphorus and suspended sediment transport.
- **Parameters**: soilcoh, soilerod, sedexp, sreroexp

### 2.5 Riparian Zone Processes
- **Status**: NOT in KI
- **Source**: `npc_soil_proc.f90` -- `class_riparian_zone_processes`
- **What it does**: Nutrient retention in riparian buffer zones. Uses moisture-dependent denitrification and phosphorus filtering.
- **Parameters**: ripz, rips, ripe, filtPbuf, filtPinner, filtPother

### 2.6 Atmospheric Deposition (wet + dry)
- **Status**: NOT in KI
- **Source**: `npc_soil_proc.f90` -- `add_dry_deposition_to_landclass`; `modvar.f90` -- `set_class_deposition`
- **What it does**: Wet and dry deposition of N, P, and other substances to land and water surfaces.
- **Input files**: AtmdepData.txt (optional monthly/annual deposition)
- **Parameters**: drypp, wetsp, ponatm

---

## 3. CRYOSPHERE

### 3.1 Snow Module (Temperature-Index + Radiation)
- **Status**: PARTIALLY in KI (snowmeltmodel 2 configured)
- **Source**: `soil_proc.f90` -- `calculate_snow`, `calculate_snowmelt`, `calculate_snowdepth`, `snowalbedo_function`
- **Options (modeloption snowmeltmodel)**:
  - 0: Temperature-index (degree-day)
  - 1: Temperature-index with snow cover area scaling
  - 2: Temperature + radiation index -- **used in KI**
- **Parameters**: ttmp, cmlt, cmrad (radiation melt factor), snalbmin/max/kexp, fscmax/min/fsclim, fscdistmax/0/1
- **Additional features**: Fractional snow cover area, snow density evolution (sdnsnew, snowdensdt), snow liquid water content
- **Output**: snow (SWE), snowdepth, snowdens, snowcov
- **KI GAP**: Snow cover area and density sub-models not fully documented. Snowfall distribution model (wind redistribution) not documented.

### 3.2 Glacier Module
- **Status**: NOT in KI
- **Source**: `glacier_soilmodel.f90` (GLACIER_SOILMODEL), `soil_proc.f90` -- `calculate_glacier_melt`
- **What it does**: Full glacier soil model. Volume-area scaling, glacier melt (degree-day + radiation), glacier density, two glacier types (mountain vs. ice cap).
- **Input files**: GlacierData.txt (glacier volume, area, type), info.txt (glacier_model option)
- **Parameters**: glacvcoef, glacvexp, glacdens, glaccmlt, glacttmp, glaccmrad, glacalb, glacannmb, glacvcoef1, glacvexp1, glac2arlim
- **Output**: glacvol (glacier volume), glacier melt contribution to runoff
- **Data KI needed**: RGI (Randolph Glacier Inventory)
- **Data KI exists**: RGI (YES)

### 3.3 Lake and River Ice
- **Status**: NOT in KI
- **Source**: `sw_proc.f90` -- `calculate_icedepth`, `calculate_lakeice_lakewater_interaction`, `riverice_riverwater_interaction`, `calculate_snow_on_ice`
- **Options (modeloption lakeriverice)**: 0=off, 1=version1, 2=version2
- **What it does**: Black ice growth, snow-ice formation, ice melt (degree-day + radiation + water heat flux), ice cover fraction, snow on ice.
- **Parameters**: licetf, licetmelt, licekika, licekexp, licermelt, licebupo, liceqhw (lake); ricetf, ricetmelt, etc. (river)
- **Output**: lakeice, lakebice, lakeicecov, riverice, riverbice, rivericecov

### 3.4 Snow Evaporation (Sublimation)
- **Status**: NOT in KI
- **Source**: `soil_proc.f90`
- **Options (modeloption snowevaporation)**: 0=off, 1=epotsnow = epot * fepotsnow
- **Parameters**: fepotsnow (fraction of PET used for snow evaporation, landuse-dependent)

---

## 4. LAKES AND RESERVOIRS

### 4.1 Internal Lakes (ilake)
- **Status**: DONE in KI (GeoClass special=2 marks water class, documented)
- **Source**: `sw_proc.f90` -- `calculate_flow_from_undivided_lake`
- **What it does**: Internal lakes within subbasins. Rating curve outflow.
- **Input files**: GeoData.txt (LAKE_DEPTH), GeoClass.txt (special=2)
- **KI tool**: `generate_lakedata.py` documents rating curve setup and configures lake_depth

### 4.2 Outlet Lakes (olake) with Regulation
- **Status**: DONE in KI (automated LakeData.txt generation)
- **Source**: `sw_proc.f90` -- `calculate_outlet_outflow_of_oneoutletpersubbasin_lake`, `get_current_lake_outflow_parameters`
- **What it does**: Outlet lakes with configurable outflow: rating curves, regulated outflow, production flow, threshold levels, seasonal variation.
- **Input files**: LakeData.txt (lake area, depth, regulation volume, rating parameters, production flow)
- **Data KI needed**: HydroLAKES, GRanD (dams)
- **Data KI exists**: HydroLAKES (YES), GRanD (YES)
- **KI tool**: `tools/s6_lake_reservoir_config/generate_lakedata.py` -- generates LakeData.txt from HydroLAKES + GRanD, with --update_geodata to add lakedataid/lake_depth to GeoData.txt

### 4.3 Dam Regulation (DamData)
- **Status**: DONE in KI (automated DamData.txt generation)
- **Source**: `sw_proc.f90` -- flood control dam parameters (kthrflood, klowflood, krelflood)
- **What it does**: Flood control dams with threshold inflow, low-level releases, and regulation volumes.
- **Input files**: DamData.txt (dam properties, purpose, regulation rules)
- **Data KI needed**: GRanD (dam database)
- **Data KI exists**: GRanD (YES)
- **KI tool**: `tools/s6_lake_reservoir_config/generate_damdata.py` -- generates DamData.txt from GRanD with monthly inflow estimation, purpose classification, and flood control parameters

### 4.4 Layered Lake Model
- **Status**: NOT in KI
- **Source**: `ll_proc.f90` (LAYEREDLAKE_PROCESSES) -- new in v5.35
- **What it does**: Multi-layer lake model with stratification, layer mixing, heat transfer between layers, settling/sinking of substances.
- **Subroutines**: add_water_to_layered_lake_from_above, mix_lake_layers, move_water_volume_between_lake_layers, lake_epilimnion_depth, etc.
- **KI GAP**: Entirely new module, not documented.

---

## 5. ADVANCED PROCESSES

### 5.1 Irrigation Demand and Supply
- **Status**: NOT in KI
- **Source**: `irrigation.f90` (IRRIGATION_MODULE)
- **What it does**: Calculates crop water demand (soil moisture deficit), local/regional water supply, abstraction from rivers/lakes/aquifers, application with evaporation losses.
- **Input files**: MgmtData.txt or CropData.txt (irrigation parameters), info.txt
- **Parameters**: irrdemand, iwdfrac, immdepth, regirr, sswcorr, irrcomp, pirrs, pirrg
- **Data KI needed**: CROPGRIDS (crop types), SPAM (irrigated area)
- **Data KI exists**: CROPGRIDS (YES), SPAM (YES)

### 5.2 Floodplain Module
- **Status**: NOT in KI
- **Source**: `soilmodel4.f90` (FLOODPLAIN_SOILMODEL)
- **Options (modeloption floodmodel)**: 0=off, 1=simple (P-E), 2=full soilmodel for non-flooded floodplain
- **What it does**: Floodplain inundation, water exchange between river/lake and floodplain, soil processes on floodplain.
- **Source subroutines**: `sw_proc.f90` -- `calculate_floodplain_volume`, `calculate_floodplain_equilibriumlevel`, `calculate_interflow_between_floodplains2`
- **Input files**: FloodData.txt (floodplain properties)
- **Parameters**: opt6, opt7, optonoff

### 5.3 Regional Groundwater / Aquifer Model
- **Status**: NOT in KI
- **Source**: `regional_groundwater.f90` (REGIONAL_GROUNDWATER_MODULE)
- **Options (modeloption deepground)**:
  - 0: None
  - 1: Instant transport to outlet of same subbasin
  - 2: Explicit aquifer modeling with delay
- **What it does**: Deep percolation from soil to aquifer, aquifer storage with delay, return flow to rivers/lakes, aquifer water level calculation, aquifer denitrification.
- **Input files**: AquiferData.txt (aquifer properties, connections)
- **Parameters**: rcgrw, rcgrwst, rrcs3, aqretcorr, aqdelcorr, aqpercorr, denitaq, deepmem
- **Data KI needed**: GLHYMPS (aquifer K), FanWTD (water table depth)
- **Data KI exists**: GLHYMPS (YES), FanWTD (YES)

### 5.4 Water Temperature (T2 tracer)
- **Status**: NOT in KI
- **Source**: `t_proc.f90` (TRACER_PROCESSES), `sw_proc.f90` -- `calculate_water_temperature`, `set_water_temperature`
- **Options (modeloption swtemperature)**: Controls surface water temperature model
- **What it does**: Water temperature simulation as T2 tracer. Soil temperature to stream/lake temperature coupling. Air-water heat exchange (temperature difference, solar radiation, wind). Lake stratification temperature.
- **Input files**: info.txt (`substance T2`), par.txt (t2trriver, t2trlake, tcfriver/lake, scfriver/lake, etc.)
- **Output**: Water temperature at river/lake outlets
- **Parameters**: t2trriver, t2trlake, tcfriver, scfriver, ccfriver, lcfriver, tcflake, scflake, ccflake, lcflake, upper2deep, laketemp, stbcorr1-3

### 5.5 General Tracer (T1)
- **Status**: NOT in KI
- **Source**: `t_proc.f90` -- `soil_tracer_processes`, `tracer_processes_in_river`, `tracer_processes_in_lake`
- **What it does**: Conservative or decaying tracer with adsorption (Freundlich), sedimentation/resuspension, point sources. Includes Craig-Gordon isotope fractionation for 18O and 2H.
- **Input files**: info.txt (`substance T1`), par.txt (init1, t1evap, t1zero)
- **Features**: Decay, sorption, crop sources, incorporation into soil

### 5.6 Wetland Processing
- **Status**: NOT in KI
- **Source**: `sw_proc.f90` -- `calculate_internal_wetland`, `calculate_outlet_wetland`, `T2_processes_in_wetland`; `npc_sw_proc.f90` -- `calculate_river_wetland`, `wetland_substance_processes`
- **Options (modeloption wetlandmodel)**: 0=off, 1=river wetlands, 2=landclass wetlands
- **What it does**: Wetland water balance (inflow, outflow, evaporation), nutrient retention, denitrification.
- **Input files**: GeoClass.txt (special wetland classes), GeoData.txt (wetland area fractions)
- **Parameters**: wsfluse, wsfscale, wsfbias

---

## 6. CALIBRATION AND DATA ASSIMILATION

### 6.1 Built-in Optimization (DDS, DEMC, Monte Carlo)
- **Status**: DONE in KI (s10_calibration tools)
- **Source**: `optim.f90` (OPTIMIZATION)
- **Methods**:
  - DEMC (Differential Evolution Markov Chain)
  - Monte Carlo (random sampling)
  - Bounded Monte Carlo
  - Stage Monte Carlo
  - Line search (quasi-Newton, Brent, DFP, BFGS)
  - Parameter scanning
- **Input files**: optpar.txt (parameter ranges, optimization settings)
- **KI tools**:
  - `setup_calibration.py` -- generates optpar.txt + updates info.txt with criteria
  - `parse_calibration_results.py` -- parses allsim.txt/bestsims.txt, extracts best params

### 6.2 Ensemble Kalman Filter (Data Assimilation)
- **Status**: NOT in KI
- **Source**: `assimilation_routines.f90`, `assimilation_interface.f90`, `assimilation_variables.f90`
- **What it does**: Ensemble-based data assimilation. Can assimilate discharge, snow, soil moisture observations.
- **Input files**: info.txt (assim settings), observation files
- **KI GAP**: No KI tools for data assimilation setup.

### 6.3 Discharge Updating (AR correction, Q replacement)
- **Status**: NOT in KI
- **Source**: `update.f90` (UPDATING)
- **Methods**:
  - quseobs: Replace simulated Q with observed Q
  - qarupd: AR (auto-regressive) error correction
  - warupd: Water level AR updating
  - wendupd: Lake water level end updating
  - cuseobs: Concentration replacement
  - nutrientcorr: Nutrient concentration correction
- **Input files**: update.txt (update method, stations, factors)

### 6.4 Multi-basin Regionalization
- **Status**: NOT in KI
- **Source**: `modvar.f90` -- region divisions, parameter regions
- **What it does**: Parameters can vary by region (up to 6 region divisions). Supports parameter transfer between similar basins.
- **Input files**: par.txt (regional parameters with m_rpar type), GeoData.txt (region columns)

---

## 7. DATA KI MAPPING

| HYPE Capability | Required Data | Data KI | Status |
|-----------------|---------------|---------|--------|
| Forcing (P, T) | CMFD / MSWX / NASA_POWER | CMFD, MSWX, NASA_POWER | AVAILABLE + adapter exists |
| Subbasin delineation | DEM | ChinaDEM, SRTM | AVAILABLE + tool exists |
| SLC classification | Land cover + Soil | AVHRR, HWSD | AVAILABLE + tool exists |
| Soil parameters | Soil properties | HWSD, SoilGrids | AVAILABLE |
| Observed Q | Streamflow gauges | ObservedQ, GRDC | AVAILABLE |
| Lake/reservoir config | Lake database | HydroLAKES, GRanD | AVAILABLE + adapter exists (generate_lakedata.py, generate_damdata.py) |
| Glacier data | Glacier inventory | RGI | AVAILABLE (no adapter) |
| Nutrient inputs | Fertilizer, deposition | FAOSTAT, NPKGRIDS, CROPGRIDS | AVAILABLE (no adapter) |
| Irrigation data | Irrigated area, crops | CROPGRIDS, SPAM | AVAILABLE (no adapter) |
| Aquifer properties | Subsurface K | GLHYMPS, FanWTD | AVAILABLE (no adapter) |
| Elevation statistics | DEM stats per subbasin | ChinaDEM, SRTM | AVAILABLE |
| Snow observations | SWE, snow depth | SNOTEL | AVAILABLE (US only) |
| GRACE total water storage | TWS anomalies | GRACE | AVAILABLE (no adapter) |
| Soil moisture validation | In-situ SM | ObservedSoilTSM, RISMA | AVAILABLE |

---

## 8. PRIORITY RANKING FOR KI EXPANSION

### High Priority (enable new HydroCraft capabilities)
1. **Nitrogen transport** (2.1) -- Unique HYPE capability, no other HydroCraft model does it
2. **Phosphorus transport** (2.2) -- Same as above
3. ~~**Lake/reservoir regulation** (4.2, 4.3)~~ -- DONE: generate_lakedata.py + generate_damdata.py
4. ~~**Built-in calibration** (6.1)~~ -- DONE: setup_calibration.py + parse_calibration_results.py

### Medium Priority (improve existing runs)
5. **Glacier module** (3.2) -- Needed for mountain basins
6. **Regional groundwater** (5.3) -- Complements MODFLOW6
7. **Water temperature** (5.4) -- Needed for ecological applications
8. **Discharge updating** (6.3) -- Operational forecasting
9. **Semi-distributed setup tools** -- Multi-subbasin automation

### Lower Priority (specialized applications)
10. **Irrigation** (5.1) -- Agricultural basins
11. **Floodplain** (5.2) -- Large river basins
12. **Lake/river ice** (3.3) -- Cold regions
13. **Wetland** (5.6) -- Wetland-dominated basins
14. **Organic carbon** (2.3) -- Water quality
15. **Data assimilation** (6.2) -- Research/operational
16. **Connectivity** (1.12) -- Small-scale hydrology
17. **Layered lake** (4.4) -- Deep lake thermodynamics
