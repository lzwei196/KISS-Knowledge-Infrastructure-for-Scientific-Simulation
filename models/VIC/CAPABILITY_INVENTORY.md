# VIC 5.1.0 -- Capability Inventory (KDT v5.0 Stage s2)

**Generated**: 2026-04-03
**Source**: VIC 5.1.0, 59 C source files in `vic_run/src/`, 3 drivers (Classic, Image, CESM)
**Binary**: `/mnt/disk1/Hydrocraft_server/model/VIC-5.1.0/vic/drivers/classic/vic_classic.exe` (compiled, 1.5 MB)
**Image driver**: Source present, NOT compiled (`/mnt/disk1/Hydrocraft_server/model/VIC-5.1.0/vic/drivers/image/`)
**Extensions**: RVIC routing extension (source only, not compiled)
**Current KI version**: 1.1 (2025-02-01)
**Usage**: 64 VIC result directories in outputs/ -- the most-used model in HydroCraft (vs 15 HYPE, ~249 total)

---

## Summary

| Category | Total Capabilities | In Current KI | Missing from KI |
|----------|--------------------|---------------|-----------------|
| Hydrology (core) | 6 | 4 | 2 |
| Energy Balance | 3 | 0 (mentioned) | 3 |
| Frozen Soil / Permafrost | 5 | 0 (mentioned as pitfall) | 5 |
| Snow Processes | 4 | 1 (basic SWE output) | 3 |
| Lakes/Wetlands | 3 | 0 | 3 |
| Carbon Cycle | 3 | 0 | 3 |
| Drivers / Parallelism | 3 | 1 (classic only) | 2 |
| Routing (external) | 3 | 1 (CaMa-Flood post-proc) | 2 |
| Calibration | 2 | 0 | 2 |
| Data Prep Pipeline | 5 | 5 | 0 |
| **Total** | **37** | **12** | **25** |

---

## 1. HYDROLOGY (CORE)

### 1.1 Variable Infiltration Capacity (VIC Curve)
- **Status**: DONE in KI (default behavior)
- **Source**: `runoff.c`, `arno_evap.c`
- **What it does**: Sub-grid variable infiltration capacity parameterization (Liang et al., 1994). Controls partitioning of rainfall into infiltration vs surface runoff. ARNO baseflow formulation for drainage from bottom soil layer.
- **Soil param fields**: b_infilt, Ds, Dsmax, Ws, c (exponent)
- **KI tools**: `s3_soil/fill_parameters1.py`, `s3_soil/fill_parameters2.py`
- **Data KI**: HWSD (YES via hwsd_to_vic.py adapter), SoilGrids (indirect)

### 1.2 Multi-Layer Soil Moisture
- **Status**: DONE in KI (3 layers default)
- **Source**: `runoff.c`, `soil_conduction.c`
- **What it does**: Arbitrary number of soil layers (typically 3). Gravity-driven flow between layers (Brooks and Corey). ARNO evaporation from top layers.
- **Global param**: NLAYER (default 3)
- **Soil param fields**: soil_density, bulk_density, Ksat, expt, bubble, residual_moist per layer; layer depths
- **Output**: OUT_SOIL_MOIST, OUT_SOIL_LIQ, OUT_SOIL_ICE per layer

### 1.3 Vegetation Mosaic (Land Cover Tiles)
- **Status**: DONE in KI
- **Source**: `calc_veg_params.c`, `canopy_evap.c`, `surface_fluxes.c`
- **What it does**: Subdivides each grid cell into arbitrary number of vegetation tiles. Jarvis-style stomatal resistance for transpiration. Canopy energy balance. Partial vegetation coverage (clumped scheme, Bohn & Vivoni 2016).
- **KI tools**: `s4_veg/process_vegetation_detailed.py`
- **Input**: veglib.LDAS (vegetation library), veg_param file
- **Output**: OUT_EVAP, OUT_TRANSP_VEG, OUT_EVAP_CANOP, OUT_EVAP_BARE

### 1.4 Evapotranspiration
- **Status**: DONE in KI (implicit in model run)
- **Source**: `penman.c`, `canopy_evap.c`, `arno_evap.c`, `compute_pot_evap.c`
- **What it does**: Penman-Monteith PET with Jarvis stomatal resistance. Actual ET reduced by soil moisture limitation. Canopy interception evaporation. Bare soil evaporation.
- **Output**: OUT_EVAP, OUT_PET, OUT_TRANSP_VEG

### 1.5 Water Table Depth
- **Status**: NOT in KI (not documented or configured)
- **Source**: `compute_zwt.c`
- **What it does**: Computes water table depth from soil moisture profile and soil texture (Bohn et al., 2013b).
- **Output**: OUT_ZWT, OUT_ZWT_LUMPED
- **KI GAP**: Water table output not mentioned in SKILL.md or OUTVAR configuration.

### 1.6 Share Layer Moisture
- **Status**: NOT in KI (not documented)
- **Source**: `surface_fluxes.c`
- **Global param**: SHARE_LAYER_MOIST (default TRUE)
- **What it does**: Allows plant roots to access moisture from wetter layers when the primary root layer exceeds critical point. Important for drought simulation.
- **KI GAP**: Not documented. Default is TRUE so it works silently, but users should know about it.

---

## 2. ENERGY BALANCE

### 2.1 Full Energy Balance
- **Status**: NOT in KI (FULL_ENERGY=FALSE in current config)
- **Source**: `calc_surf_energy_bal.c`, `func_surf_energy_bal.c`, `calc_atmos_energy_bal.c`
- **Global param**: FULL_ENERGY (TRUE/FALSE, default FALSE)
- **What it does**: When TRUE, iteratively computes surface temperature that balances surface energy budget. When FALSE, surface temperature = air temperature. Required for frozen soil, lakes, carbon cycle.
- **Output**: OUT_SURF_TEMP, OUT_BARESOILT, OUT_GRND_FLUX, OUT_R_NET, OUT_LATENT, OUT_SENSIBLE
- **KI GAP**: Major capability not enabled. The SKILL.md only mentions FROZEN_SOIL=FALSE as a pitfall but never explains how/when to enable full energy balance.

### 2.2 Closed Energy Balance
- **Status**: NOT in KI
- **Source**: `surface_fluxes.c`
- **Global param**: CLOSE_ENERGY (requires FULL_ENERGY=TRUE)
- **What it does**: Iterates between canopy and surface energy balances until consistent.
- **KI GAP**: Not documented.

### 2.3 Quick Flux vs Finite Difference Thermal Solution
- **Status**: NOT in KI
- **Source**: `soil_conduction.c`, `soil_thermal_eqn.c`
- **Global params**: QUICK_FLUX, IMPLICIT, NOFLUX, EXP_TRANS
- **What it does**: QUICK_FLUX=TRUE uses Liang et al. (1999) approximate method. QUICK_FLUX=FALSE uses Cherkauer & Lettenmaier (1999) finite element method (required for frozen soil).
- **KI GAP**: Not documented.

---

## 3. FROZEN SOIL / PERMAFROST

### 3.1 Frozen Soil
- **Status**: NOT in KI (explicitly set to FALSE; mentioned only as error pitfall)
- **Source**: `frozen_soil.c`, `soil_thermal_eqn.c`
- **Global param**: FROZEN_SOIL (TRUE/FALSE), requires FULL_ENERGY=TRUE or QUICK_FLUX=FALSE
- **Soil param field**: FS_ACTIVE (per cell flag, column in soil param file)
- **What it does**: Water/ice phase change with latent heat effects. Impacts infiltration, runoff, and soil thermal regime.
- **Output**: OUT_SOIL_ICE, OUT_FDEPTH, OUT_TDEPTH, OUT_SMFROZFRAC, OUT_SURF_FROST_FRAC
- **KI GAP**: Critical for cold-region basins (Lhasa, Nuxia already in outputs/). Currently blocked; would need FULL_ENERGY=TRUE + NODES>3 + FS_ACTIVE=1 in soil file.

### 3.2 Spatial Frost
- **Status**: NOT in KI
- **Source**: `frozen_soil.c`
- **Global param**: SPATIAL_FROST (TRUE Nfrost)
- **Soil param field**: frost_slope
- **What it does**: Horizontal temperature heterogeneity within a cell -- even when mean temp < 0C, some soil portion may be above freezing.
- **KI GAP**: Not documented. Relevant for permafrost regions.

### 3.3 Permafrost Excess Ice
- **Status**: NOT in KI
- **Source**: `frozen_soil.c`
- **What it does**: Simulates melting of excess ground ice in permafrost (Adam & Lettenmaier, 2008). Ground subsidence.
- **KI GAP**: Not documented.

### 3.4 Exponential Thermal Node Distribution
- **Status**: NOT in KI
- **Source**: `soil_conduction.c`
- **Global param**: EXP_TRANS (default TRUE when FROZEN_SOIL=TRUE)
- **What it does**: Dense node spacing near surface, sparse at depth. Better resolution where thermal gradients are steepest.
- **KI GAP**: Not documented.

### 3.5 Implicit Thermal Solution
- **Status**: NOT in KI
- **Source**: `soil_thermal_eqn.c`
- **Global param**: IMPLICIT (default TRUE)
- **What it does**: Numerically stable implicit solution for soil heat flux. Explicit solution only stable for certain dt/dx combinations.
- **KI GAP**: Not documented.

---

## 4. SNOW PROCESSES

### 4.1 Two-Layer Snow Pack
- **Status**: PARTIALLY in KI (SWE output configured)
- **Source**: `snow_melt.c`, `snow_intercept.c`, `solve_snow.c`, `SnowPackEnergyBalance.c`
- **What it does**: Quasi-two-layer pack: surface layer for energy balance, bulk layer for mass. Tracks albedo evolution, liquid water content, cold content. Canopy snow interception.
- **Output**: OUT_SWE, OUT_SNOW_DEPTH, OUT_SNOW_MELT, OUT_SNOW_COVER, OUT_SNOW_CANOPY
- **KI GAP**: Snow output variables not explicitly configured in OUTVAR. Users get default output only.

### 4.2 Elevation Bands (Snow Bands)
- **Status**: NOT in KI
- **Source**: `surface_fluxes.c`
- **Global param**: SNOW_BAND (integer = number of bands, + snow band file)
- **What it does**: Subdivides grid cell into elevation bands. Meteorological forcings lapsed to band elevation. Critical for mountain snow pack (Tibetan Plateau, Rockies).
- **Input file**: Snow band parameter file (area_frac, median_elev, Pfactor per band)
- **Output**: Band-specific OUT_SWE_BAND, OUT_SNOW_DEPTH_BAND, etc.
- **KI GAP**: Major capability for mountainous basins. Would need elevation band file generation tool. Relevant for Nuxia, Lhasa, Yajiang basins.

### 4.3 Blowing Snow Sublimation
- **Status**: NOT in KI
- **Source**: `CalcBlowingSnow.c`
- **Global params**: BLOWING (TRUE/FALSE), BLOWING_VAR_THRESHOLD, BLOWING_CALC_PROB, BLOWING_SIMPLE, BLOWING_FETCH, BLOWING_SPATIAL_WIND
- **What it does**: Evaporative fluxes from blowing snow (Bowling et al., 2004). Saltation and suspension layers.
- **Output**: OUT_SUB_BLOWING
- **KI GAP**: Not documented. Relevant for open, windy terrain.

### 4.4 Spatial Snow / Partial Coverage
- **Status**: NOT in KI
- **Source**: `calc_snow_coverage.c`
- **Global param**: SPATIAL_SNOW (TRUE/FALSE)
- **Soil param field**: max_snow_distrib_slope
- **What it does**: Spatial heterogeneity in SWE for partial snow coverage during melt.
- **KI GAP**: Not documented.

---

## 5. LAKES / WETLANDS

### 5.1 Dynamic Lake Model
- **Status**: NOT in KI
- **Source**: `lakes.eb.c`, `lake_utils.c`, `initialize_lake.c`, `compute_derived_lake_dimensions.c`, `water_under_ice.c`, `IceEnergyBalance.c`, `ice_melt.c`
- **Global param**: LAKES (path to lake param file), LAKE_PROFILE (TRUE/FALSE), LAKE_NODES
- **Requirements**: FULL_ENERGY=TRUE
- **What it does**: Multi-layer energy balance lake model (Hostetler & Bartlein 1990). Mixing, radiation attenuation, variable ice cover. Dynamic lake area as function of storage.
- **Input file**: Lake parameter file (bathymetry, outlet width, etc.)
- **Output**: OUT_LAKE_DEPTH, OUT_LAKE_VOLUME, OUT_LAKE_ICE, OUT_LAKE_SURF_TEMP, OUT_LAKE_EVAP, OUT_LAKE_AREA_FRACT, etc.
- **KI GAP**: Entirely missing. Would need lake parameter file generation tool. Relevant for Hongzehu (already in outputs/).

### 5.2 Dynamic Wetland Interaction
- **Status**: NOT in KI
- **Source**: `lakes.eb.c`
- **What it does**: Wetland area = tile area - lake area. Seasonal inundation. Wetter soils from lake recharge.
- **KI GAP**: Part of lake model.

### 5.3 Lake Channel Inflow
- **Status**: NOT in KI
- **Source**: `lakes.eb.c`
- **Forcing variable**: CHANNEL_IN
- **What it does**: Allows upstream channel inflows to feed the lake, enabling larger lake systems that need water from beyond the local grid cell.
- **KI GAP**: Would need routing model to provide inflows.

---

## 6. CARBON CYCLE

### 6.1 Photosynthesis (GPP)
- **Status**: NOT in KI
- **Source**: `photosynth.c`, `canopy_assimilation.c`, `calc_Nscale_factors.c`, `faparl.c`
- **Global params**: CARBON=TRUE, RC_MODE=RC_PHOTO, VEGLIB_PHOTO=TRUE
- **What it does**: Farquhar photosynthesis model for C3/C4 plants. Stomatal conductance linked to carbon assimilation. N-scaling for canopy layers.
- **Input**: Requires photosynthesis-enabled veg library (with Ctype, MaxCarboxRate, MaxETransport, etc.)
- **Forcing**: OUT_CATM (atmospheric CO2, can be specified)
- **Output**: OUT_GPP, OUT_RAUT, OUT_NPP, OUT_APAR
- **KI GAP**: Entirely missing. Would need photosynthesis veg library. Relevant for carbon flux studies (bengbu_bgc already attempted).

### 6.2 Soil Carbon Balance
- **Status**: NOT in KI
- **Source**: `soil_carbon_balance.c`, `compute_soil_resp.c`
- **What it does**: Three soil carbon pools (litter, intermediate, slow) with distinct residence times. Heterotrophic respiration as f(temperature, moisture).
- **Output**: OUT_RHET, OUT_NEE, OUT_CLITTER, OUT_CINTER, OUT_CSLOW, OUT_LITTERFALL
- **KI GAP**: Entirely missing.

### 6.3 Canopy Resistance via Photosynthesis
- **Status**: NOT in KI
- **Source**: `canopy_assimilation.c`
- **Global param**: RC_MODE=RC_PHOTO
- **What it does**: Alternative canopy resistance calculation based on photosynthetic demand rather than Jarvis approach.
- **KI GAP**: Not documented.

---

## 7. DRIVERS / PARALLELISM

### 7.1 Classic Driver (ASCII I/O)
- **Status**: DONE in KI (the only driver used)
- **Binary**: `/mnt/disk1/Hydrocraft_server/model/VIC-5.1.0/vic/drivers/classic/vic_classic.exe`
- **What it does**: Serial execution. ASCII parameter files and forcing. One grid cell at a time (space-after-time). Suitable for small-to-medium domains.
- **Limitation**: No parallelism. For large domains (>1000 cells), wall time becomes significant.

### 7.2 Image Driver (NetCDF + MPI)
- **Status**: NOT in KI (source present, not compiled)
- **Source**: `/mnt/disk1/Hydrocraft_server/model/VIC-5.1.0/vic/drivers/image/`
- **What it does**: NetCDF I/O. Space-before-time evaluation. MPI parallel processing. Modern implementation for large-scale applications.
- **Requirements**: NetCDF libraries, MPI environment
- **KI GAP**: Not compiled, not documented. Would enable parallel execution for large basins. All parameter files would need conversion to NetCDF format.

### 7.3 CESM Driver (Earth System Model Coupling)
- **Status**: NOT in KI (not applicable to standalone usage)
- **Source**: `/mnt/disk1/Hydrocraft_server/model/VIC-5.1.0/vic/drivers/cesm/`
- **What it does**: Couples VIC as a land surface scheme within CESM.
- **KI GAP**: Not relevant for HydroCraft use case.

---

## 8. ROUTING (EXTERNAL)

### 8.1 CaMa-Flood Post-Processing
- **Status**: DONE in KI (via separate CaMa-Flood KI)
- **KI tools**: `vic_post/` scripts convert VIC flux output to CaMa-Flood input NetCDF
- **What it does**: Converts per-cell VIC ASCII output (OUT_RUNOFF + OUT_BASEFLOW) to gridded NetCDF for CaMa-Flood routing.
- **KI GAP**: Post-processing script must be manually created per basin (hardcoded grid dimensions).

### 8.2 Lohmann Routing Model
- **Status**: NOT in KI
- **Source**: `/mnt/disk1/Hydrocraft_server/model/route_1.0/`
- **What it does**: Unit hydrograph-based routing (Lohmann et al., 1996/1998). Simpler than CaMa-Flood. Produces streamflow at gauge points from VIC runoff fields.
- **KI GAP**: Binary exists at `/mnt/disk1/Hydrocraft_server/model/route_1.0/` but no KI tools for flow direction file preparation.

### 8.3 RVIC Extension (Built-in Routing)
- **Status**: NOT in KI
- **Source**: `/mnt/disk1/Hydrocraft_server/model/VIC-5.1.0/vic/extensions/rout_rvic/`
- **What it does**: RVIC routing compiled directly into VIC Image Driver. Convolution-based routing.
- **Requirements**: Image Driver must be compiled with ROUT=rout_rvic
- **KI GAP**: Image driver not compiled. RVIC extension not configured.

---

## 9. CALIBRATION

### 9.1 Manual Parameter Adjustment
- **Status**: NOT in KI (no tooling)
- **What it does**: VIC has no built-in calibration. Typically calibrated via external frameworks (MOCOM-UA, SCE-UA, DDS).
- **Key calibration parameters**: b_infilt, Ds, Dsmax, Ws, soil depths, Ksat
- **KI GAP**: No calibration tool. Other KIs (HYPE) have built-in optimization documented.

### 9.2 State File Save/Restore (Spinup)
- **Status**: NOT in KI
- **Global params**: INIT_STATE, STATENAME, STATEYEAR/MONTH/DAY, STATE_FORMAT
- **What it does**: Save model state at a specific time for warm restart. Essential for spinup (run multiple cycles to equilibrate soil moisture).
- **KI GAP**: Not documented. Users may be running without proper spinup, affecting early-period results.

---

## 10. DATA PREPARATION PIPELINE

### 10.1 Grid Generation (s1_grid)
- **Status**: DONE in KI
- **Tool**: `s1_grid/make_basin_grid_nc.py`
- **What it does**: Creates 0.25-degree grid from basin shapefile. Aligns to global anchor grid. Outputs NetCDF with mask.
- **Input**: Basin shapefile (.shp)

### 10.2 Forcing Preparation (s2_forcing)
- **Status**: DONE in KI
- **Tools**: `s2_forcing/forcing_1d.py` (crops CMFD to basin), `s2_forcing/process_forcing.py` (generates per-cell forcing files)
- **Also**: Data KI adapters (`cmfd_to_vic.py`) for CMFD, MSWX, NASA POWER
- **What it does**: Converts gridded meteorological data to VIC per-cell ASCII forcing format.

### 10.3 Soil Parameter Generation (s3_soil)
- **Status**: DONE in KI
- **Tools**: `s3_soil/fill_parameters1.py` (framework from grid+DEM+soil), `s3_soil/fill_parameters2.py` (interpolation from global template)
- **Also**: Data KI adapter (`hwsd_to_vic.py`)
- **What it does**: Generates complete VIC soil parameter file with all required fields.

### 10.4 Vegetation Parameter Generation (s4_veg)
- **Status**: DONE in KI
- **Tool**: `s4_veg/process_vegetation_detailed.py`
- **What it does**: Generates VIC vegetation parameter file from land cover raster and vegetation library.

### 10.5 Configuration and Preflight (config + check)
- **Status**: DONE in KI
- **Tools**: `config_paths.py` (path substitution), `preflight_check.py` (binary + data verification), `check_data.py` (completeness check)
- **What it does**: Automates path configuration across all scripts, verifies environment before run.

---

## STRUCTURAL ASSESSMENT: VIC KI vs Well-Structured KIs

### Current VIC KI Architecture
```
VIC/knowledge_infrastructure/
    SKILL.md              (530 lines, Chinese, detailed pipeline)
    SKILL_en.md           (English translation)
    config_paths.py       (path configuration)
    check_data.py         (data validation -- STALE, references Mac paths)
    preflight_check.py    (environment check)
    run_vic_pipeline_enhanced.py  (orchestrator -- STALE, references Mac paths)
    s1_grid/              (1 tool: make_basin_grid_nc.py)
    s2_forcing/           (2 tools: forcing_1d.py, process_forcing.py)
    s3_soil/              (2 tools: fill_parameters1.py, fill_parameters2.py)
    s4_veg/               (1 tool: process_vegetation_detailed.py)
    [NO diagnostics/]
    [NO tools/ subdirectory]
    [NO knowledge_infrastructure.yaml]
```

### Well-Structured KI Architecture (HYPE, MODFLOW6)
```
{model}/knowledge_infrastructure/
    SKILL.md              (structured, English, capability-aware)
    CAPABILITY_INVENTORY.md  (this file pattern)
    knowledge_infrastructure.yaml
    preflight_check.py
    diagnostics/
        triplets.yaml     (error pattern -> remedy mapping)
    tools/
        s1_.../            (named by function)
        s2_.../
        ...
        s10_.../
    docs/
    templates/
    workflow/
    lib/
```

### Gap Analysis

| Aspect | HYPE/MODFLOW6 | VIC | Gap |
|--------|--------------|-----|-----|
| tools/ subdirectory | YES (10-13 tools) | NO (scripts in s1-s4 at KI root) | STRUCTURAL |
| diagnostics/triplets.yaml | YES | NO | MISSING |
| knowledge_infrastructure.yaml | YES | NO | MISSING |
| CAPABILITY_INVENTORY.md | YES | NO (now created) | FIXED |
| Number of pipeline steps | 10-13 | 7 (s1-s4 + config + run + postproc) | ADEQUATE for basic |
| English documentation | YES | Mostly Chinese | LANGUAGE |
| Advanced feature coverage | 23-42 capabilities documented | Only basic water balance | SIGNIFICANT |
| Calibration tools | YES (HYPE built-in) | NO | MISSING |
| Output analysis tools | YES | NO (manual inspection) | MISSING |
| Post-processing tools | YES (structured) | Scattered per-basin scripts | WEAK |
| Stale Mac paths | N/A | YES (check_data.py, run_vic_pipeline_enhanced.py) | MAINTENANCE |

---

## RECOMMENDATION

### Verdict: RESTRUCTURE NEEDED -- but incrementally, not all at once

VIC is the workhorse (64/249 = 26% of all model runs), yet its KI has the least structure of any major model. The current SKILL.md is excellent for the basic water balance pipeline but leaves 25 of 37 capabilities completely undocumented. Here is a prioritized plan:

### Priority 1: STRUCTURAL (do now)
1. **Create `tools/` subdirectory** and move s1-s4 into it as `tools/s1_grid/`, `tools/s2_forcing/`, `tools/s3_soil/`, `tools/s4_veg/`
2. **Create `diagnostics/triplets.yaml`** -- VIC error messages are well-known (forcing file not found, FROZEN_SOIL is neither TRUE nor FALSE, root zone fractions > 1, etc.). The SKILL.md already documents 5+ errors that should become triplets.
3. **Create `knowledge_infrastructure.yaml`** -- metadata file for KDT integration
4. **Fix stale paths** in `check_data.py` and `run_vic_pipeline_enhanced.py` (still reference `/Volumes/Expansion2t/` and `/Users/yc/`)

### Priority 2: CAPABILITY EXPANSION (high value)
5. **Add `tools/s5_execution/` with `run_vic.py`** -- wrapper that builds global param file, validates it, runs VIC binary, checks output
6. **Add `tools/s6_output_analysis/`** -- parse VIC flux output, compute water balance, generate summary statistics, plot time series
7. **Add `tools/s7_snow_bands/`** -- elevation band file generation from DEM. Unlocks mountain basin modeling (Lhasa, Nuxia, Yajiang)
8. **Add `tools/s8_frozen_soil/`** -- guide + tool for enabling FROZEN_SOIL with correct NODES, FS_ACTIVE, FULL_ENERGY. Unlocks permafrost basins.
9. **Add `tools/s9_state_files/`** -- spinup management (save state, restart from state)
10. **Document the Image Driver compilation** -- for users who need parallelism on large domains

### Priority 3: ADVANCED (future)
11. Lake/wetland parameter file generation
12. Carbon cycle configuration (photosynthesis veg library)
13. Calibration framework integration (DDS or similar)
14. Blowing snow configuration

### What NOT to do
- Do NOT add tools for CESM driver (not relevant to HydroCraft)
- Do NOT restructure the existing s1-s4 scripts internally -- they work and are battle-tested across 64+ basins
- Do NOT rewrite SKILL.md from scratch -- extend it with capability sections

### Is the current SKILL.md adequate?
**For basic water balance runs: YES.** The SKILL.md is detailed, captures key pitfalls, and the s1-s4 tools work. The 64 successful runs prove this.

**For anything beyond basic water balance: NO.** Users attempting frozen soil (Lhasa), lakes (Hongzehu), carbon (bengbu_bgc), or mountain snow (Nuxia) would have no KI guidance. They would need to read the raw VIC documentation.

**Bottom line**: VIC's KI is a solid v1.0 that covers the 80% use case. The 20% gap is where the advanced capabilities live -- and that is exactly where users will go next as they move beyond basic water balance demonstrations.
