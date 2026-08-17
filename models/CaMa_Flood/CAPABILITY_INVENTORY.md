# CaMa-Flood v4.20 (Yamazaki Lab, U-Tokyo) -- Capability Inventory

**Model**: CaMa-Flood v4.20 (Catchment-based Macro-scale Floodplain model)
**KDT Stage**: s3 (Tools + Diagnostics + Validated Pipeline)
**Date**: 2026-04-03
**Assessed by**: KDT v5.0
**Binary location**: `KISSPATH_BINARIES/cmf_v420_pkg/src/MAIN_cmf`

---

## 1. Full Capability List

### 1A. River Routing Core

| # | Capability | Status | Current KI Coverage | Notes |
|---|-----------|--------|-------------------|-------|
| 1 | Kinematic wave river routing | DONE | Default routing scheme; PMANRIV controls Manning's n | Validated Bengbu NSE=0.598 |
| 2 | Diffusion wave routing | DONE | Activated via PDSTMTH parameter (distance threshold) | Used for backwater-affected reaches |
| 3 | Adaptive time stepping | DONE | LADPSTP=.TRUE., PCADP=0.7 (CFL condition) | Default in all run scripts |
| 4 | Local inertial equation | DONE | Available in v4.20 source (cmf_calc_outflw_mod.F90) | Not yet validated in KI |
| 5 | Bifurcation channel routing | DONE | bifprm.txt, bifori.txt in map directories | Handles distributary channels |

### 1B. Floodplain Dynamics

| # | Capability | Status | Current KI Coverage | Notes |
|---|-----------|--------|-------------------|-------|
| 6 | Floodplain inundation depth (flddph) | DONE | Output variable; validated Bengbu | Core flood output |
| 7 | Floodplain inundation fraction (fldfrc) | DONE | Output variable; validated Bengbu | 0-1 fraction per cell |
| 8 | Floodplain storage (fldsto) | DONE | Available output variable | m3 per grid cell |
| 9 | Floodplain area (fldare) | DONE | Available output variable | m2 per grid cell |
| 10 | Multi-layer floodplain topography | DONE | fldhgt.bin with 10 layers (default) in diminfo | Sub-grid topography |
| 11 | Flood stage calculation | DONE | cmf_calc_fldstg_mod.F90 | River + floodplain partitioning |

### 1C. Input/Output

| # | Capability | Status | Current KI Coverage | Notes |
|---|-----------|--------|-------------------|-------|
| 12 | NetCDF forcing input (gridded runoff) | DONE | LINPCDF=.TRUE., CROFCDF path; tools/prepare_runoff_input.py | VIC/wflow/HYPE mm/day input |
| 13 | Binary forcing input (gridded runoff) | DONE | LINPCDF=.FALSE. option in namelist | Legacy format; less recommended |
| 14 | Input matrix interpolation (inpmat) | DONE | LINTERP=.TRUE., CINPMAT path; generate_inpmat Fortran tool | Maps source grid to CaMa grid |
| 15 | Direct grid input (no interpolation) | DONE | LINTERP=.FALSE. when grids match exactly | Recommended for aligned grids |
| 16 | NetCDF output (multi-variable) | DONE | LOUTCDF=.TRUE., CVARSOUT='outflw,rivdph,...' | Default output mode |
| 17 | Binary output (single variable) | DONE | LOUTCDF=.FALSE., CVARSOUT='flddph' | Used for CaMa-SFINCS downscaling |
| 18 | Restart file I/O | DONE | LRESTCDF=.TRUE., CRESTSTO, CRESTDIR | NetCDF restart for multi-year runs |
| 19 | Discharge output (outflw) | DONE | m3/s at every grid cell per time step | Primary validation variable |
| 20 | River depth output (rivdph) | DONE | m; river channel water depth | |
| 21 | Water surface elevation (sfcelv) | DONE | m above sea level | Used for flood mapping |
| 22 | River storage (rivsto) | DONE | m3; channel storage volume | Water balance component |

### 1D. Map Preparation Pipeline

| # | Capability | Status | Current KI Coverage | Notes |
|---|-----------|--------|-------------------|-------|
| 23 | Regional map extraction (cut_domain) | DONE | src_region/cut_domain Fortran binary; tools/configure_simulation.py | Cuts from glb_15min |
| 24 | High-resolution data combination (combine_hires) | DONE | src_region/combine_hires; 1min/30sec/15sec/3sec | Required for downscaling |
| 25 | Input matrix generation (generate_inpmat) | DONE | src_param/generate_inpmat Fortran binary | VIC grid -> CaMa grid mapping |
| 26 | Annual mean runoff climatology (calc_outclm) | DONE | src_param/calc_outclm; uses ELSE_GPCC data | Must run from glb_15min |
| 27 | Channel width/depth estimation (calc_rivwth) | DONE | src_param/calc_rivwth; power-law from mean Q | Generates rivwth.bin, rivhgt.bin |
| 28 | Flow gauge allocation | DONE | src_param/allocate_flow_gauge | For validation against observed Q |

### 1E. Coupling (Upstream Sources)

| # | Capability | Status | Current KI Coverage | Notes |
|---|-----------|--------|-------------------|-------|
| 29 | VIC runoff to CaMa-Flood | DONE | tools/prepare_runoff_input.py; vic_post/process_vic_for_cama.py | OUT_RUNOFF + OUT_BASEFLOW -> Runoff mm/day |
| 30 | wflow runoff to CaMa-Flood | DONE | wflow KI has wflow_to_cama.py | Unrouted runoff extraction |
| 31 | HYPE runoff to CaMa-Flood | PARTIAL | tools/prepare_runoff_input.py supports HYPE format | Not validated |
| 32 | Generic NetCDF runoff input | DONE | tools/prepare_runoff_input.py with custom format adapter | Any lat/lon/time NetCDF |

### 1F. Coupling (Downstream Consumers)

| # | Capability | Status | Current KI Coverage | Notes |
|---|-----------|--------|-------------------|-------|
| 33 | CaMa-Flood to SFINCS downscaling | DONE | skills/cama-downscale/ (main_downscale.sh) | Binary flddph -> hi-res flood map |
| 34 | CaMa-Flood to visualization | DONE | tools/parse_cama_output.py extracts time series | Discharge at gauge points |

### 1G. Advanced Features (Available but Not in Current KI)

| # | Capability | Status | Current KI Coverage | Notes |
|---|-----------|--------|-------------------|-------|
| 35 | Dam/reservoir operation | TODO | GRanD_allocated.csv exists in map/data/ | NDAMOUT namelist section |
| 36 | Levee representation | TODO | Levee test data in etc/levee_test/ | NLEVEE namelist section |
| 37 | Sea level boundary condition | TODO | etc/sealev_boundary/ exists | NBOUND namelist section |
| 38 | Sediment transport | TODO | etc/sediment/ exists; compile with -Dsediment | Requires additional modules |
| 39 | MPI parallelization | TODO | set_mpi_region in src_param; UseMPI_CMF in source | For global-scale runs |
| 40 | N-year flood depth estimation | TODO | etc/n-year_flood_depth/ scripts exist | Statistical post-processing |
| 41 | Water level gauge allocation | TODO | allocate_level_gauge in src_param | For satellite altimetry validation |

---

## 2. Required Input Files per Capability

| Capability | Required Inputs | Tool Status |
|-----------|----------------|-------------|
| Core routing (1-5) | nextxy.bin, ctmare.bin, elevtn.bin, nxtdst.bin, rivlen.bin, fldhgt.bin, rivwth.bin, rivhgt.bin, rivman.bin, diminfo.txt | configure_simulation.py generates all |
| Forcing input (12-15) | Gridded runoff NetCDF (time, lat, lon), inpmat.bin (if interpolation needed) | prepare_runoff_input.py |
| Floodplain output (6-11) | Same as core routing; fldhgt.bin with multi-layer topography | Included in map preparation |
| Channel parameters (27) | outclm.bin (from calc_outclm on global grid), regional diminfo | configure_simulation.py step 3 |
| Downscaling (33) | Binary flddph output, 1min/ high-res directory | CaMa BIN output mode |
| Dam operation (35) | Dam locations, storage curves, operating rules | Not yet tooled |
| Restart/warm-start (18) | restart{YYYY}010100.nc from previous run | Automatic from prior year |

---

## 3. Required Data KIs per Capability

| Capability | Data KI Needed | Data KI Status | Path |
|-----------|---------------|---------------|------|
| Core routing | CaMa-Flood global river network (glb_15min) | EXISTS | model/cmf_v420_pkg/map/glb_15min/ |
| Channel parameters | ELSE_GPCC runoff climatology | EXISTS | model/cmf_v420_pkg/map/data/ELSE_GPCC_coastmod_dayclm-1981-2010.one |
| VIC forcing | VIC model output (flux files) | EXISTS | Per-basin in outputs/{basin}/vic_result/ |
| wflow forcing | wflow model output (run_default/) | EXISTS | Per-basin in outputs/{basin}/ |
| Discharge validation | GRDC | EXISTS | data_ki/GRDC/ |
| Discharge validation | ObservedQ (Chinese stations) | EXISTS | data_ki/ObservedQ/ |
| High-res downscaling | glb_15min/1min/ (MERIT-Hydro derived) | EXISTS | model/cmf_v420_pkg/map/glb_15min/1min/ |
| Dam operation | GRanD (Global Reservoir and Dam) | EXISTS | data_ki/GRanD/ |
| Sea level boundary | Tide gauge / reanalysis | MISSING | Not available |

---

## 4. Validated Results

| Basin | Source Model | Period | Gauge | NSE | PBIAS | Notes |
|-------|-------------|--------|-------|-----|-------|-------|
| Bengbu (Huai River) | VIC 5.1 | 2000-2005 | Bengbu station | 0.598 | -- | PMANRIV=0.30, PMANFLD=0.10, 2 spin-up years |
| Wangjiaba (Huai River) | VIC 5.1 | -- | Wangjiaba station | -- | -- | Map prepared; pending validation |
| Chuhe | VIC 5.1 | 2005-2015 | -- | -- | -- | Run completed; output exists |
| Nuxia (Yarlung Tsangpo) | VIC 5.1 | 1990-2000 | Nuxia station | -- | -- | Calibration in progress |

---

## 5. Priority Ranking for Next Implementation

| Priority | Capability | Effort | Impact | Rationale |
|----------|-----------|--------|--------|-----------|
| P1 | Dam/reservoir operation (#35) | MEDIUM | HIGH | GRanD Data KI exists; dams dominate flood regulation on Huai River; namelist section ready |
| P2 | N-year flood depth (#40) | LOW | HIGH | Scripts exist in etc/; statistical analysis of existing output |
| P3 | Local inertial validation (#4) | LOW | MEDIUM | Already compiled into binary; just needs a test case with known backwater |
| P4 | MPI parallelization (#39) | MEDIUM | MEDIUM | Needed for global or large continental runs; set_mpi_region tool exists |
| P5 | Sea level boundary (#37) | MEDIUM | MEDIUM | Important for coastal flood studies; requires tide data |
| P6 | Levee representation (#36) | HIGH | HIGH | Critical for realistic flood simulation; requires levee database |
| P7 | Sediment transport (#38) | HIGH | MEDIUM | Requires recompile with -Dsediment flag; limited validation data |

---

## 6. Tool Inventory

| Tool | Location | Status | Purpose |
|------|----------|--------|---------|
| prepare_runoff_input.py | tools/ | NEW | Convert VIC/wflow/HYPE runoff to CaMa-Flood NetCDF input |
| configure_simulation.py | tools/ | NEW | Generate map directory, diminfo, inpmat, channel params, run script |
| run_cama.py | tools/ | NEW | Execute CaMa-Flood binary with preflight checks and error handling |
| parse_cama_output.py | tools/ | NEW | Extract discharge at gauge points, flood extent/depth analysis |
| process_vic_for_cama.py | vic_post/ | EXISTS | VIC text files -> CaMa NetCDF (legacy, basin-specific) |
| process_data_windows_ymd.py | vic_post/ | EXISTS | VIC text files -> CaMa NetCDF (legacy, Huaihe-specific) |
| setup_cama_basin.py | skills/cama-flood-run/ | EXISTS | Automated basin setup (known calc_rivwth bug, see dt_cama_008) |
| preflight_check.py | ./ | EXISTS | Verify binary and data availability |
