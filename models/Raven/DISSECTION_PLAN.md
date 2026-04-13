# Raven Hydrological Modelling Framework -- Knowledge Dissection Plan

**Prepared for**: HydroCraft platform (AI-driven multi-model Earth system simulation)
**Prepared by**: Jianyun Zhang Research Group, Hohai University
**Date**: 2026-03-21
**Status**: PLANNING (pre-installation, pre-dissection)

---

## 1. Model Overview

| Field | Value |
|-------|-------|
| **Full name** | Raven Hydrological Modelling Framework |
| **Version** | v4.1 (Dec 2024 stable) / v4.12 (Mar 2025 latest) |
| **Developer** | University of Waterloo, Civil & Environmental Engineering (Prof. James Craig) |
| **Repository** | https://github.com/CSHS-CWRA/RavenHydroFramework |
| **License** | Artistic License 2.0 (open source) |
| **Language** | C++ (98.3%), compiled executable |
| **Platforms** | Linux, macOS, Windows (g++ / CMake / Visual Studio) |
| **Documentation** | https://raven.uwaterloo.ca, User Manual PDF (~2.6 MB) |

### What Raven Does

Raven is a **flexible hydrological modelling framework** that allows users to assemble custom hydrological models by selecting algorithms from a library of **100+ process options** and **40+ forcing function generators**. Unlike monolithic models (VIC, HBV, GR4J), Raven treats each hydrological process (infiltration, ET, snowmelt, baseflow, routing) as an interchangeable module. Users define model structure in a text configuration file (.rvi), selecting one algorithm per process type from the library. This produces an astronomical number of possible model configurations (~8 x 10^12 by some estimates).

### Key Differentiator for HydroCraft

Raven's unique value is **model structure intercomparison from a single codebase**. For any basin, an AI agent can:
1. Run HBV, GR4J, HMETS, SAC-SMA, HYMOD, MOHYSE, and UBC emulations on **identical data**
2. Compare performance metrics automatically (NSE, KGE, PBIAS, RMSE -- 18+ diagnostics built in)
3. Identify which model structure best suits the basin's hydrology
4. Build **hybrid/blended** models combining the best algorithms from different model families

No other HydroCraft model can do this. VIC is one model structure. WRF-Hydro is one model structure. Raven is a meta-framework that encompasses many.

### Models Raven Can Emulate

Raven provides **15 emulation templates** in Appendix F of the manual:

| Emulation | Level | Description |
|-----------|-------|-------------|
| **GR4J** | Level 1 (near-exact) | 4-parameter French lumped model (Perrin et al., 2003) |
| **HBV-EC** | Level 1 | Environment Canada variant of HBV (Bergstrom, 1976) |
| **HBV-Light** | Level 1 | Simplified HBV (Seibert & Vis, 2012) |
| **HMETS** | Level 1 | Canadian hybrid multi-model (Martel et al., 2017) |
| **MOHYSE** | Level 1 | Simple 10-parameter model (Fortin & Turcotte, 2007) |
| **SAC-SMA** | Level 1 | Sacramento Soil Moisture Accounting (NWS, Burnash 1973) |
| **HYMOD / HYMOD2** | Level 1 | Conceptual rainfall-runoff (Boyle, 2001) |
| **UBC Watershed Model** | Level 1 | University of British Columbia model (Quick, 1995) |
| **HYPR** | Level 1 | Hybrid model for prairies (Ahmed et al., 2020) |
| **AWB** | Level 1 | Australian Water Balance model |
| **Canadian Shield** | Config | Tuned for Canadian Shield basins |
| **Blended v1/v2** | Config | Multi-algorithm hybrid configurations |
| **Routing-only** | Config | Channel routing without land surface |
| **EnKF** | Config | Ensemble Kalman Filter data assimilation |

Level 2 (conceptual) emulations of algorithms from: Brook90, SWAT, VIC, PRMS, TOPMODEL, PDM, Xinanjiang, AWBM.

### Process Algorithm Library (Verified from Source Code)

**Infiltration (19 algorithms)**:
INF_RATIONAL, INF_SCS, INF_SCS_NOABSTRACTION, INF_ALL_INFILTRATES, INF_GREEN_AMPT, INF_GA_SIMPLE, INF_UPSCALED_GREEN_AMPT, INF_PHILIP_1957, INF_VIC, INF_VIC_ARNO, INF_PRMS, INF_HBV, INF_TOPMODEL, INF_UBC, INF_GR4J, INF_HMETS, INF_XINANXIANG, INF_PDM, INF_AWBM

**Evapotranspiration (24 algorithms)**:
PET_CONSTANT, PET_NONE, PET_LINEAR_TEMP, PET_DATA, PET_BLENDED, PET_FROMMONTHLY, PET_MONTHLY_FACTOR, PET_PENMAN_MONTEITH, PET_PENMAN_COMBINATION, PET_JENSEN_HAISE, PET_HAMON, PET_PRIESTLEY_TAYLOR, PET_HARGREAVES, PET_HARGREAVES_1985, PET_TURC_1961, PET_MAKKINK_1957, PET_SHUTTLEWORTH_WALLACE, PET_PENMAN_SIMPLE33, PET_PENMAN_SIMPLE39, PET_MOHYSE, PET_OUDIN, PET_LINACRE, PET_VAPDEFICIT, PET_GRANGERGRAY

**Snow Balance (9 algorithms)**:
SNOBAL_SIMPLE_MELT, SNOBAL_COLD_CONTENT, SNOBAL_HBV, SNOBAL_UBCWM, SNOBAL_CEMA_NEIGE, SNOBAL_TWO_LAYER, SNOBAL_GAWSER, SNOBAL_CRHM_EBSM, SNOBAL_HMETS

**Baseflow (10 algorithms)**:
BASE_LINEAR, BASE_LINEAR_ANALYTIC, BASE_LINEAR_CONSTRAIN, BASE_CONSTANT, BASE_POWER_LAW, BASE_VIC, BASE_TOPMODEL, BASE_GR4J, BASE_THRESH_POWER, BASE_THRESH_STOR

**Percolation (12 algorithms)**:
PERC_CONSTANT, PERC_GAWSER, PERC_GAWSER_CONSTRAIN, PERC_POWER_LAW, PERC_LINEAR, PERC_LINEAR_ANALYTIC, PERC_PRMS, PERC_SACRAMENTO, PERC_GR4J, PERC_GR4JEXCH, PERC_GR4JEXCH2, PERC_ASPEN

**Additional Process Categories** (counts estimated from manual TOC, 26 sections total):
- Precipitation partitioning (~5 algorithms)
- Canopy interception and drip (~5 algorithms)
- Interflow (~5 algorithms)
- Soil evaporation (~5 algorithms)
- Capillary rise (~3 algorithms)
- Depression/wetland storage (~4 algorithms)
- Lake release (~3 algorithms)
- Open water evaporation (~4 algorithms)
- Sublimation (~3 algorithms)
- Snow refreeze (~4 algorithms)
- Snow albedo evolution (~4 algorithms)
- Glacier melt/release/infiltration (~6 algorithms)
- Lake freezing (~2 algorithms)
- Crop heat unit evolution (~2 algorithms)

**Total confirmed**: 74 algorithms across 5 verified categories. Estimated **120+ algorithms** across all 26 process categories.

### Routing Capabilities

**In-catchment routing**: Convolution-based unit hydrograph, time-of-concentration methods.
**In-channel routing**: Muskingum, Muskingum-Cunge, diffusive wave (analytically integrated in v4.1+).
**Lake/reservoir routing**: Stage-discharge curves (managed reservoirs), weir overflow (natural lakes), level-pool routing.
**Water management**: Demand optimization, diversions, environmental flows, water allocation via linear programming (v4.0+).

### State Variables

SOIL[0..n], SNOW, SNOW_LIQ, COLD_CONTENT, CANOPY_SNOW, CANOPY, DEPRESSION, WETLAND, LAKE_STORAGE, PONDED_WATER, ATMOS_PRECIP, ATMOSPHERE, SNOW_DEPTH, ICE_THICKNESS, THAW_DEPTH, SNOW_COVER, GLACIER, GLACIER_ICE, SNOW_DEFICIT, SNOW_ALBEDO, CONVOLUTION

### Forcing Variables Required

PRECIP, TEMP_MIN, TEMP_MAX, TEMP_AVE, SNOWFALL, RAINFALL, PET, OW_PET, WIND_VEL, AIR_DENS, AIR_PRES, REL_HUMIDITY, SW_RADIA, SW_RADIA_NET, LW_INCOMING, LW_RADIA_NET, POTENTIAL_MELT, RECHARGE

Minimum forcing: PRECIP + TEMP_MIN + TEMP_MAX (Raven generates all others via its 40+ forcing function generators).

---

## 2. Input/Output File Architecture

### Input Files (5 required + 3 optional)

| Extension | Name | Purpose | Required |
|-----------|------|---------|----------|
| **.rvi** | Model Definition | Model structure: process algorithms, timestep, evaluation metrics, output options, transport | Yes |
| **.rvp** | Parameters | Soil/vegetation/land-use/terrain class parameters, soil profiles, global parameters | Yes |
| **.rvh** | HRU/Basin Definition | Subbasins, HRUs (area, elevation, slope, aspect, soil profile, land use, vegetation), reservoirs, HRU groups | Yes |
| **.rvt** | Time Series | Meteorological forcing (gauge data or NetCDF), observation data for calibration, reservoir operations | Yes |
| **.rvc** | Initial Conditions | Starting values for all state variables (optional warm start) | No (but recommended) |
| **.rve** | Ensemble | Ensemble Kalman Filter configuration | No |
| **.rvm** | Water Management | Demand/supply optimization, constraints, goals | No |
| **.rvl** | Live File | Runtime commands (e.g., parameter overrides mid-simulation) | No |

### Input Format Details

**Gauge data (.rvt)**:
```
:Gauge StationName
  :Latitude 40.5
  :Longitude 116.8
  :Elevation 500.0
  :Data PRECIP mm
    2000-01-01 00:00:00.0 1.0 365
    value1
    value2
    ...
  :EndData
  :Data TEMP_MIN degC
    2000-01-01 00:00:00.0 1.0 365
    ...
  :EndData
:EndGauge
```

**NetCDF forcing (.rvt)**:
```
:Data PRECIP mm
  :ReadFromNetCDF
    :FileNameNC forcing.nc
    :VarNameNC pr
    :DimNamesNC station time
    :StationIdx 1
  :EndReadFromNetCDF
:EndData
```

**HRU definition (.rvh)**:
```
:SubBasins
  :Attributes NAME DOWNSTREAM_ID PROFILE REACH_LENGTH GAUGED
  :Units none none none km none
  1 sub1 -1 NONE 0 1
:EndSubBasins

:HRUs
  :Attributes AREA ELEVATION LATITUDE LONGITUDE BASIN_ID ...
  :Units km2 m deg deg none ...
  1 100.0 500.0 40.5 116.8 1 ...
:EndHRUs
```

**Process selection (.rvi)**:
```
:HydrologicProcesses
  :Precipitation PRECIP_RAVEN
  :SnowBalance SNOBAL_HBV SNOW PONDED_WATER
  :Infiltration INF_HBV PONDED_WATER MULTIPLE
  :Baseflow BASE_POWER_LAW SOIL[0] SURFACE_WATER
  :Percolation PERC_LINEAR SOIL[0] SOIL[1]
  :Baseflow BASE_LINEAR SOIL[1] SURFACE_WATER
:EndHydrologicProcesses
```

### Output Files

| File | Content |
|------|---------|
| **Hydrographs.csv** | Simulated vs observed hydrographs at gauged basins |
| **WatershedStorage.csv** | Basin-wide water balance time series |
| **ForcingFunctions.csv** | Processed forcing at each gauge (if requested) |
| **MassBalance.csv** | All internal fluxes between state variables |
| **Diagnostics.csv** | NSE, KGE, RMSE, PBIAS, etc. for all observation points |
| **solution.rvc** | Final state (for warm restart) |
| **Custom outputs** | User-defined: any SV, any temporal/spatial aggregation |

**Output format options**: CSV (default), Ensim (.tb0), NetCDF (.nc).

**Built-in diagnostics** (18+): NASH_SUTCLIFFE, PCT_BIAS, LOG_NASH, KLING_GUPTA, RMSE, ABSERR, ABSMAX, RCOEF, R2, NSC, RSR, PDIFF, TMVOL, MBF, PERSINDEX, DAILY_KGE, plus custom evaluation periods.

---

## 3. Installation Plan

### 3.1 Compile from Source (Primary Path)

**Prerequisites**:
- g++ (GCC C++ compiler) -- already available on HydroCraft server
- CMake 3.x -- likely already available
- Make -- standard Linux build tool
- NetCDF C/C++ libraries (optional, for NetCDF I/O) -- already installed for WRF-Hydro/VIC

**Compilation steps**:
```bash
# Download source
wget https://raven.uwaterloo.ca/files/v4.1/RavenSource_v4.1.zip
unzip RavenSource_v4.1.zip -d /mnt/disk1/Hydrocraft_server/model/raven_v4.1/

# Option A: CMake build
cd /mnt/disk1/Hydrocraft_server/model/raven_v4.1/
mkdir build && cd build
cmake -DCOMPILE_EXE=ON -DCOMPILE_LIB=OFF ../
make -j$(nproc)
# Binary at: build/Raven.exe (or similar)

# Option B: Makefile build (alternative)
cd /mnt/disk1/Hydrocraft_server/model/raven_v4.1/
make -f Makefile
```

**Expected result**: Single static binary `Raven.exe` (no external runtime dependencies beyond libc).

**Estimated effort**: 15-30 minutes including download, compile, and verify.

### 3.2 Python Wrappers (Secondary)

| Wrapper | Source | Purpose | Install |
|---------|--------|---------|---------|
| **RavenPy** | Ouranosinc/RavenPy | Python wrapper for Raven execution, model configuration, calibration (PAVICS-Hydro ecosystem) | `pip install ravenpy` or `conda install -c conda-forge ravenpy` |
| **raven-hydro** | PyPI | Compiled Raven binary distributed as Python package (no manual compilation needed) | `pip install raven-hydro` |
| **RavenR** | CRAN / GitHub | R package for output visualization and analysis | R ecosystem, not needed for HydroCraft |
| **BasinMaker** | GitHub | Automated watershed delineation, generates .rvh files | Python, useful for HRU setup |

**Recommended approach for HydroCraft**: Compile from source (full control, NetCDF support) + build custom Python tools (consistent with HydroCraft's tool-based approach rather than depending on RavenPy).

### 3.3 External Calibration Tools

Raven integrates with **Ostrich** (McMaster University) for automated calibration using DDS, PSO, or other global optimization algorithms. Ostrich wraps Raven as a black box and optimizes parameters by repeatedly running the model.

Alternative: Use HydroCraft's existing AI calibration approach (as in `vic_cali_ai`), adapted for Raven's parameter space.

---

## 4. Pipeline Stages (Proposed)

| Stage ID | Name | Description | Knowledge Type | Depends On |
|----------|------|-------------|---------------|------------|
| **s0** | Configuration | Select model emulation template or custom process algorithms; define basin, period, resolution | Evaluative | -- |
| **s1** | Basin/HRU Setup | Define subbasins and HRUs from shapefile + DEM + land cover + soil; generate .rvh file | Procedural + Evaluative | s0, basin delineation |
| **s2** | Soil & Vegetation Parameters | Extract soil/veg/landuse class parameters from HWSD/AVHRR; generate .rvp file | Procedural | s1 |
| **s3** | Forcing Preparation | Convert CMFD/MSWX/NASA POWER forcing to Raven .rvt format (gauge or NetCDF); minimum: precip + temp_min + temp_max | Procedural | s1 |
| **s4** | Model Structure Definition | Generate .rvi file: process selections, timestep, output options, diagnostics | Procedural + Evaluative | s0 |
| **s5** | Initial Conditions | Generate .rvc file from default or warm-start values | Procedural | s1, s2 |
| **s6** | Execution | Run Raven.exe; parse stdout for errors; collect output | Procedural | s1-s5 |
| **s7** | Output Analysis | Parse Hydrographs.csv, Diagnostics.csv; compare with observed; generate plots | Procedural + Evaluative | s6 |
| **s8** | Multi-Model Ensemble | Run multiple emulation templates on same basin; compare diagnostics; rank model structures | Evaluative | s1-s5 (shared), s6 (per model) |
| **s9** | Calibration | Optimize parameters using DDS/AI calibration for the best-performing model structure | Procedural + Evaluative | s7 or s8 |
| **s10** | Coupling Output | Convert Raven output to CaMa-Flood/Lohmann routing input; or extract for cross-model comparison with VIC | Procedural | s6 |

### Parallelism

- s2 and s3 can run in parallel after s1
- s4 is independent of s1-s3 (only needs s0)
- s5 depends on s1 and s2
- For multi-model ensemble (s8): all emulation runs can execute in parallel (same forcing/HRU, different .rvi/.rvp)

---

## 5. Tools to Build (Proposed)

| Tool Name | Stage | Est. Lines | Purpose |
|-----------|-------|-----------|---------|
| `select_model_template.py` | s0 | 200 | Select from 15 emulation templates; generate .rvi skeleton with correct process algorithms |
| `build_rvh_from_shapefile.py` | s1 | 450 | Generate .rvh from basin shapefile + DEM + AVHRR + HWSD; define subbasins and HRUs |
| `build_rvp_parameters.py` | s2 | 400 | Generate .rvp with soil/veg/landuse parameters from HWSD global database; model-specific parameter defaults |
| `convert_forcing_to_rvt.py` | s3 | 500 | Convert CMFD/MSWX/NASA POWER forcing to Raven .rvt format; handle gauge vs NetCDF; unit conversions |
| `generate_rvi_file.py` | s4 | 350 | Generate complete .rvi: process algorithms, timestep, evaluation metrics, output options |
| `generate_rvc_initial.py` | s5 | 150 | Generate .rvc with default or user-specified initial conditions |
| `run_raven.py` | s6 | 300 | Execution wrapper: preflight checks, run binary, parse stdout, collect output, JSON summary |
| `parse_raven_output.py` | s7 | 300 | Parse Hydrographs.csv + Diagnostics.csv; compute additional metrics; export standardized results |
| `run_ensemble_comparison.py` | s8 | 500 | Run N emulation templates on same basin; aggregate diagnostics; rank model structures; generate comparison report |
| `calibrate_raven_dds.py` | s9 | 400 | DDS (Dynamically Dimensioned Search) calibration wrapper; generate Ostrich config or internal DDS loop |
| `raven_to_cama_coupling.py` | s10 | 300 | Convert Raven runoff output to CaMa-Flood NetCDF input format |
| `raven_vic_comparison.py` | s10 | 250 | Compare Raven vs VIC output for same basin: discharge, ET, soil moisture; correlation, bias |
| `validate_raven_inputs.py` | all | 250 | Validate all .rv* files for consistency: parameter names, HRU IDs, time ranges, file existence |
| `plot_raven_results.py` | s7 | 300 | Generate standard HydroCraft plots: hydrograph, diagnostics summary, forcing preview |

**Total**: 14 tools, ~4,650 estimated lines.

---

## 6. Skill Documents (Proposed)

| Document | Stage | Content |
|----------|-------|---------|
| `s0_model_selection_skill.md` | s0 | Decision guide for choosing model structure: lumped vs semi-distributed, snow-dominated vs rain-dominated, data-rich vs data-poor; emulation template selection criteria; algorithm compatibility matrix |
| `s1_basin_hru_setup_skill.md` | s1 | HRU definition strategies: by land use only (lumped), by elevation bands (mountain), by soil+landuse (agricultural), by subcatchment (semi-distributed); guidelines for HRU count vs model complexity |
| `s3_forcing_conversion_skill.md` | s3 | Forcing requirements by model structure; minimum forcing (3 vars) vs full forcing (18 vars); unit expectations; Raven's internal forcing generators; NetCDF vs gauge format trade-offs |
| `s4_process_algorithm_guide.md` | s4 | Complete reference for all 120+ algorithms: when to use each, parameter requirements, known limitations, compatibility with other algorithms |
| `s8_model_intercomparison_skill.md` | s8 | Multi-model ensemble methodology: which metrics to compare, how to handle structural uncertainty, how to weight ensemble members, when to use blended configurations |
| `s9_calibration_skill.md` | s9 | Calibration strategy by model structure: which parameters to calibrate, DDS settings, convergence criteria, over-fitting prevention, regionalization for ungauged basins |
| `coupling_skill.md` | s10 | Raven-VIC comparison methodology; Raven-CaMa-Flood coupling; forcing data sharing across models |

**Total**: 7 skill documents.

---

## 7. Diagnostic Triplets (Anticipated)

| Category | Est. Count | Examples |
|----------|-----------|----------|
| **File format errors** | 8 | Missing .rv* file, wrong column count in .rvh, inconsistent HRU IDs between .rvh and .rvp, soil profile name mismatch |
| **Unit/conversion errors** | 6 | Raven ignores units (stated on cheat sheet) -- user must ensure correct units before input; CMFD mm/3hr vs Raven mm/d; temperature C vs K |
| **Process compatibility** | 5 | Incompatible algorithm combinations (e.g., GR4J infiltration with HBV baseflow), missing soil layers for multi-layer algorithms, glacier processes without glacier HRU type |
| **Silent errors** | 8 | Wrong model structure emulation (runs fine, wrong physics), forcing mismatch (daily data at sub-daily timestep -- Raven interpolates silently), missing observation data (diagnostics report -9999), parameter at bounds (calibration stuck), blank data marker -1.2345 misinterpreted |
| **Runtime errors** | 5 | Mass balance violation, timestep too large for routing, negative storage, NetCDF dimension mismatch, memory overflow for large domains |
| **Calibration errors** | 4 | DDS not converging, parameter outside physical bounds, overfitting to calibration period, wrong objective function for flow regime |
| **Coupling errors** | 4 | Time step mismatch Raven vs CaMa-Flood, runoff unit mismatch, spatial grid alignment, double-counting processes (Raven routing + external routing) |

**Total**: ~40 diagnostic triplets anticipated.

---

## 8. Coupling Points with HydroCraft

### 8.1 Forcing Data (Input Coupling)

| HydroCraft Source | Raven Target | Conversion |
|-------------------|-------------|------------|
| CMFD 0.1deg 3-hourly NetCDF | .rvt gauge data or NetCDF | Resample to daily or sub-daily; extract PRECIP, TEMP_MIN, TEMP_MAX (minimum); optionally WIND_VEL, REL_HUMIDITY, SW_RADIA, AIR_PRES |
| MSWX 0.1deg 3-hourly NetCDF | .rvt gauge data or NetCDF | Same as CMFD; global coverage |
| NASA POWER 0.5deg API | .rvt gauge data | API fetch + format conversion; hourly or daily |
| VIC forcing ASCII files | .rvt gauge data | Parse VIC per-cell forcing; aggregate to subbasin-mean |

**Critical note**: Raven states "Raven ignores units and will not do units conversion" (cheat sheet page 1). All unit conversions must happen in the conversion tool. This is a major source of silent errors.

### 8.2 Output Coupling (Raven to Other Models)

| Raven Output | HydroCraft Target | Conversion |
|-------------|-------------------|------------|
| Hydrographs.csv (m3/s) | CaMa-Flood runoff input | Convert point discharge to gridded runoff (mm/d) per subbasin area |
| Hydrographs.csv (m3/s) | Lohmann routing | Convert to VIC-format runoff/baseflow per cell |
| CustomOutput (soil moisture) | DSSAT/RZWQM2 | Extract soil moisture for crop model initialization |
| Diagnostics.csv | VIC calibration comparison | Direct comparison of NSE/KGE/PBIAS |

### 8.3 Cross-Model Comparison (Key Use Case)

The primary coupling is **Raven vs VIC on the same basin**:
1. Same shapefile, same period, same forcing data
2. VIC runs its energy/water balance; Raven runs HBV/GR4J/SAC-SMA
3. Compare discharge at outlet: NSE, KGE, hydrograph shape, peak timing
4. Quantify **structural uncertainty** (how much do results vary by model choice?)

This directly supports HydroCraft's multi-model philosophy and is unique to the Raven integration.

### 8.4 Coupling Registry (model_couplings.yaml entries)

| Coupling ID | Source | Target | Variables | Transformation |
|-------------|--------|--------|-----------|----------------|
| c_raven_01 | CMFD/MSWX forcing | Raven .rvt | precip, temp, wind, humidity, radiation | Spatial aggregation to HRU/subbasin; temporal resampling; unit standardization |
| c_raven_02 | VIC forcing files | Raven .rvt | 7 VIC forcing variables | Parse ASCII per-cell; aggregate to subbasin means; reformat to Raven gauge blocks |
| c_raven_03 | HydroCraft basin shapefile | Raven .rvh | subbasin geometry, DEM, land cover, soil | Spatial analysis (intersection, zonal stats); class assignment |
| c_raven_04 | HWSD global soil | Raven .rvp soil classes | sand/silt/clay/bulk density/Ksat | Pedotransfer functions; map to Raven soil class parameters |
| c_raven_05 | Raven Hydrographs.csv | CaMa-Flood input | discharge (m3/s) | Point-to-grid conversion; m3/s to mm/d over subbasin area |
| c_raven_06 | Raven Hydrographs.csv | VIC comparison | discharge (m3/s) | Direct comparison; no transformation needed |
| c_raven_07 | Raven CustomOutput | DSSAT soil moisture | soil water content | Extract from WatershedStorage.csv; unit conversion to mm or fraction |

---

## 9. Validation Plan

### 9.1 Single-Basin Validation (Tier 1)

Run Raven on a basin where VIC has already been validated in HydroCraft.

**Candidate basin**: Chaohe (潮河), 8,783 km2, semi-humid North China
- VIC already calibrated (mean Q = 27.6 m3/s)
- Observed data available in `data/obs/`
- CMFD forcing already prepared
- Small enough for fast iteration (~20 HRUs at subbasin level)

**Validation steps**:
1. Run GR4J emulation (4 parameters, fastest to debug)
2. Run HBV-EC emulation (standard reference)
3. Compare both against VIC output and observed data
4. Verify mass balance closure
5. Verify output file formats are parseable

### 9.2 Multi-Model Ensemble (Tier 2)

Run all 8 Level-1 emulations on Chaohe:
- GR4J, HBV-EC, HBV-Light, HMETS, MOHYSE, SAC-SMA, HYMOD, UBC
- Same forcing, same period, same HRU definition
- Compare NSE, KGE, PBIAS, peak timing, recession behavior
- Identify which model structure performs best for semi-humid monsoon climate

### 9.3 Cross-Climate Validation (Tier 3)

Run the ensemble on basins spanning different climates:
- **Yajiang/Nuxia** (Tibetan Plateau, high altitude, snowmelt-dominated) -- VIC NSE=0.90
- **Bengbu** (Huai River, humid subtropical, large basin) -- VIC validated
- **Koksilah** (Canada, temperate maritime, small basin) -- MSWX forcing
- **Heihe Upper** (arid/semi-arid, continental) -- VIC validated

This tests whether the "best model structure" varies by hydroclimatic regime (it should).

### 9.4 Coupling Validation (Tier 4)

- Raven runoff -> CaMa-Flood: verify discharge continuity
- Raven vs VIC forcing consumption: verify identical forcing produces physically consistent (not identical) results

---

## 10. Estimated Effort

| Phase | Tasks | Estimated Time | Dependencies |
|-------|-------|---------------|-------------|
| **Installation** | Download source, compile with g++/CMake, verify binary | 0.5 day | g++, CMake (already on server) |
| **Phase 1: Pipeline Mapping** | Map 11 stages, define dependencies, generate workflow diagram | 0.5 day | Manual review |
| **Phase 2: Knowledge Classification** | Classify procedural/evaluative/debugging knowledge per stage | 1 day | Phase 1 |
| **Phase 3: Tool Extraction** | Build 14 tools (~4,650 lines) | 5 days | Phase 2, compiled binary |
| **Phase 4: Skill Documents** | Write 7 skill documents | 2 days | Phase 3 |
| **Phase 5: Diagnostic Triplets** | Build ~40 triplets from real runs + cross-model patterns | 2 days | Phase 3 validation runs |
| **Phase 6: Assembly & Validation** | Cross-reference audit, end-to-end verification, SKILL.md | 2 days | Phase 3-5 |
| **Tier 1 Validation** | Single basin (Chaohe), GR4J + HBV | 1 day | Phase 6 |
| **Tier 2 Validation** | 8-model ensemble on Chaohe | 1 day | Tier 1 |
| **Tier 3 Validation** | Cross-climate (4 basins x 8 models) | 2 days | Tier 2 |

**Total estimated effort**: ~17 days (3.5 weeks) for full knowledge infrastructure with cross-climate validation.

---

## 11. Priority and Dependencies

### Priority: HIGH

Raven fills a critical gap in HydroCraft that no other model addresses:
1. **Model structure uncertainty quantification** -- essential for scientific credibility
2. **Rapid prototyping** -- test 8 model structures in minutes, not days
3. **Hybrid model construction** -- combine best algorithms from different families
4. **Educational value** -- demonstrates HydroCraft's model-agnostic philosophy
5. **Publication impact** -- "we tested 8 model structures and VIC on the same basin" is a compelling result

### Dependencies on Existing HydroCraft Infrastructure

| Dependency | Status | Notes |
|-----------|--------|-------|
| Basin delineation (WhiteboxTools) | Ready | Produces shapefile for .rvh generation |
| HWSD soil database | Ready | Shared with VIC, DSSAT, RZWQM2 |
| AVHRR land cover | Ready | Shared with VIC |
| CMFD forcing | Ready | Convert to .rvt format |
| MSWX forcing | Ready | Convert to .rvt format |
| CaMa-Flood routing | Ready | Accepts gridded runoff |
| Observed discharge (GRDC/HYDAT) | Ready | For calibration/validation |
| Plotting scripts (`skills/plot/`) | Ready | Extend for Raven output |
| AI calibration (`vic_cali_ai`) | Ready | Adapt DDS loop for Raven parameters |

### Dependencies Raven Needs (New)

| Need | Solution |
|------|----------|
| Raven binary compiled on server | Compile from source (~30 min) |
| Forcing conversion tool (CMFD/MSWX -> .rvt) | Build `convert_forcing_to_rvt.py` |
| HRU builder (.rvh from shapefile) | Build `build_rvh_from_shapefile.py`; or use BasinMaker |
| Emulation template library | Extract from Raven manual Appendix F; encode as JSON/YAML configs |

---

## 12. Unique Challenges and Risks

### 12.1 "Raven ignores units" (Silent Error Risk: CRITICAL)

The cheat sheet explicitly states: "Note: Raven ignores units and will not do units conversion." This means:
- If CMFD precipitation is in mm/3hr and Raven expects mm/d, the model will run without error but produce 8x too much precipitation
- Every unit conversion must happen in the conversion tools, with explicit validation
- This is the #1 anticipated source of silent errors

**Mitigation**: Build unit validation into `convert_forcing_to_rvt.py` with physical bounds checking (e.g., daily precip > 500 mm triggers warning).

### 12.2 Algorithm Compatibility Matrix

Not all algorithm combinations are valid. For example:
- GR4J infiltration expects GR4J-specific state variables
- UBC snow balance expects UBC-specific parameters
- Mixing algorithms from different model families may produce numerical instability

**Mitigation**: Build compatibility checks into `generate_rvi_file.py`; use emulation templates as safe starting points.

### 12.3 HRU Definition Complexity

Raven's HRU system is more flexible but also more complex than VIC's grid:
- VIC: regular lat/lon grid, one cell = one computation unit
- Raven: irregular HRUs grouped by land use/soil/elevation, can be lumped or semi-distributed
- Converting a VIC grid to Raven HRUs requires decisions about aggregation

**Mitigation**: Default to elevation-band HRUs (simple, works everywhere); offer lumped mode for quick runs.

### 12.4 Timestep Flexibility

Raven supports sub-daily timesteps (unlike some emulated models that are inherently daily). When using 3-hourly CMFD/MSWX forcing:
- Run at daily timestep with daily forcing (standard, all emulations work)
- Run at sub-daily with sub-daily forcing (some algorithms may not support this)

**Mitigation**: Default to daily timestep; document which algorithms support sub-daily.

---

## 13. Knowledge Infrastructure File Structure (Target)

```
models/Raven/knowledge_infrastructure/
  SKILL.md                              # Agent entry point
  DISSECTION_PLAN.md                    # This file (planning phase)
  knowledge_infrastructure.yaml         # Schema-compliant package definition
  workflow/
    pipeline.drawio                     # Visual pipeline diagram
    workflow.md                         # Agent-readable workflow document
  tools/
    s0_config/
      select_model_template.py          # Select emulation template
    s1_basin_setup/
      build_rvh_from_shapefile.py       # Generate .rvh from shapefile + DEM
    s2_parameters/
      build_rvp_parameters.py           # Generate .rvp from HWSD/AVHRR
    s3_forcing/
      convert_forcing_to_rvt.py         # CMFD/MSWX/POWER -> .rvt
    s4_model_structure/
      generate_rvi_file.py              # Generate .rvi with process selections
    s5_initial_conditions/
      generate_rvc_initial.py           # Generate .rvc
    s6_execution/
      run_raven.py                      # Execution wrapper
    s7_output/
      parse_raven_output.py             # Parse output files
      plot_raven_results.py             # HydroCraft-style plots
    s8_ensemble/
      run_ensemble_comparison.py        # Multi-model ensemble runner
    s9_calibration/
      calibrate_raven_dds.py            # DDS calibration wrapper
    s10_coupling/
      raven_to_cama_coupling.py         # Raven -> CaMa-Flood
      raven_vic_comparison.py           # Raven vs VIC comparison
    common/
      validate_raven_inputs.py          # Cross-file consistency checks
  templates/
    emulations/
      gr4j.yaml                         # GR4J template (.rvi + .rvp defaults)
      hbv_ec.yaml                       # HBV-EC template
      hbv_light.yaml                    # HBV-Light template
      hmets.yaml                        # HMETS template
      mohyse.yaml                       # MOHYSE template
      sac_sma.yaml                      # SAC-SMA template
      hymod.yaml                        # HYMOD template
      ubc.yaml                          # UBC Watershed Model template
      hypr.yaml                         # HYPR template
      awb.yaml                          # AWB template
  docs/
    s0_model_selection_skill.md
    s1_basin_hru_setup_skill.md
    s3_forcing_conversion_skill.md
    s4_process_algorithm_guide.md
    s8_model_intercomparison_skill.md
    s9_calibration_skill.md
    coupling_skill.md
  diagnostics/
    triplets.yaml
    error_log.yaml
    episodes.yaml
```

---

## 14. Integration with HydroCraft Platform Numbers

After Raven integration, HydroCraft platform statistics would update:

| Metric | Before | After Raven | Change |
|--------|--------|-------------|--------|
| Model packages | 19 | 20 | +1 |
| Autonomous tools | 242 | 256 | +14 |
| Tool lines | ~33,000 | ~37,650 | +4,650 |
| Skill documents | 56 | 63 | +7 |
| Diagnostic triplets | 293 | ~333 | +40 |
| Cross-model couplings | 23 | 30 | +7 |
| Emulable model structures | 0 | 15 | +15 (unique to Raven) |

---

## 15. Open Questions (To Resolve During Dissection)

1. **NetCDF support**: Does the HydroCraft server have the NetCDF development headers needed for Raven's NetCDF I/O? (Likely yes, since WRF-Hydro and VIC both use NetCDF.)

2. **BasinMaker vs custom tool**: Should we use the BasinMaker Python package for .rvh generation, or build a custom tool that reuses HydroCraft's existing DEM/shapefile infrastructure? (Recommendation: custom tool for consistency.)

3. **RavenPy adoption**: Should we use RavenPy as a library dependency, or keep all tools self-contained? (Recommendation: self-contained tools, reference RavenPy for algorithm details only.)

4. **Ostrich calibration**: Should we integrate Ostrich (external optimizer) or build a native Python DDS loop? (Recommendation: native Python DDS, consistent with `vic_cali_ai` approach.)

5. **v4.1 vs v4.12**: v4.1 is the stable release with full documentation. v4.12 adds glacier ice flow and CF-compliant NetCDF. Start with v4.1; upgrade after validation.

6. **Diffusive wave routing change in v4.1**: The manual notes DIFFUSIVE_WAVE routing was changed to "analytically integrated calculations" in v4.1, affecting hydrograph timing for large hourly models. This needs testing with CaMa-Flood coupling.

7. **BMI (Basic Model Interface)**: Raven supports BMI for external coupling. Could HydroCraft use BMI instead of file-based coupling? (Lower priority; file-based is proven.)
