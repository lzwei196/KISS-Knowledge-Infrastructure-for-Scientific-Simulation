# SWAT+ Simulation Workflow

## Pipeline Overview

```
S1 Watershed Delineation ──┬──> S2 HRU Definition ──┬──> S5 Land Use & Management ──┐
                           │                        │                               │
                           ├──> S3 Weather Prep ─────┤                               │
                           │                        │                               │
                           │    S4 Soil Database ────┤──> S6 Calibration Parameters ─┤
                           │    (independent)        │                               │
                           │                        │                               │
                           └────────────────────────┴───────────────────────────────> S7 Simulation Config
                                                                                      │
                                                                                      v
                                                                                    S8 Model Execution
                                                                                      │
                                                                                      v
                                                                                    S9 Output Parsing & Analysis
```

## Stage Details

### S1: Watershed Delineation
**Order**: 1 | **Depends on**: none | **Estimated time**: 2-10 min

Process a DEM to define the watershed boundary, subbasins, and stream network. This is the spatial foundation for the entire SWAT+ model.

**Key decisions**:
- Stream definition threshold (km2): smaller = more subbasins = more detail but slower
- Outlet location: must be precisely on the target river
- Projected coordinate system: DEM must be in meters for accurate area/slope

**Outputs**: subbasin shapefile, stream network shapefile, watershed boundary, flow direction/accumulation rasters

**Tools**: `delineate_watershed` (DEM -> spatial framework), `define_subbasins` (spatial -> SWAT+ connectivity)

**Skill document**: `docs/s1_watershed_delineation_skill.md`

---

### S2: HRU Definition
**Order**: 2 | **Depends on**: S1 | **Estimated time**: 5-15 min

Overlay land use, soil type, and slope class onto subbasins to create Hydrologic Response Units (HRUs). Each HRU is a unique combination of subbasin + land use + soil + slope class.

**Key decisions**:
- HRU threshold: 5-10% land use, 5-10% soil, 10-20% slope (too aggressive biases results)
- Slope classes: typically [0-3%, 3-8%, 8-15%, >15%]
- Land use classification: must match plants.plt database codes

**Outputs**: hru-data.hru, hru.con, topography.hyd, hydrology.hyd

**Tools**: `create_hru_overlay`, `apply_hru_threshold`

**Skill document**: `docs/s2_hru_definition_skill.md`

---

### S3: Weather Data Preparation
**Order**: 3 | **Depends on**: S1 (for station locations) | **Estimated time**: 5-60 min

Prepare all weather input files in SWAT+ format. Five variable types, each with:
- A .cli index file listing station data file names
- Individual station data files (.pcp, .tmp, .slr, .hmd, .wnd)
- weather-sta.cli mapping station combinations to spatial objects
- wgn.wgn weather generator statistics for gap-filling

**Key decisions**:
- Forcing source: CMFD (China), MSWX (global), station CSV, NASA POWER
- Number of stations: at least one per subbasin centroid recommended
- Weather generator: needed even if observed data is complete (SWAT+ reads wgn.wgn at startup)

**File format (example .pcp)**:
```
Station precipitation file          <-- Line 1: title
nbyr       tstep      lat         lon         elev       <-- Line 2: column headers
10         0          32.500      116.800     45.0       <-- Line 3: station info (nbyr=years, tstep=0=daily)
2000       1          0.00                               <-- Line 4+: year jday precip(mm)
2000       2          5.20
...
```

**Outputs**: *.pcp, *.tmp, *.slr, *.hmd, *.wnd, pcp.cli, tmp.cli, slr.cli, hmd.cli, wnd.cli, weather-sta.cli, wgn.wgn

**Tools**: `prepare_weather_files`, `generate_weather_stations`, `validate_weather_data`

**Skill document**: `docs/s3_weather_preparation_skill.md`

---

### S4: Soil Database Configuration
**Order**: 4 | **Depends on**: none (independent) | **Estimated time**: 5-15 min

Build soils.sol with physical and hydraulic properties for each soil type in the basin. Multi-line format: one profile line + N layer lines per soil.

**Key decisions**:
- Soil data source: SSURGO (US, detailed), HWSD (global, coarser), SoilGrids (global, API)
- Number of layers: typically 2-5 per profile
- USLE K factor: critical for sediment yield, must be estimated if not in database

**Critical units**:
| Property | Unit | Valid Range |
|----------|------|-------------|
| SOL_Z | mm | 10-3000 |
| SOL_BD | g/cm3 | 0.9-2.5 |
| SOL_AWC | mm H2O / mm soil | 0.0-0.5 |
| SOL_K | mm/hr | 0.001-2000 |
| SOL_CBN | % | 0.01-30 |
| CLAY/SILT/SAND | % | 0-100 (must sum to 100) |

**Outputs**: soils.sol

**Tools**: `build_soils_database`, `validate_soil_properties`

**Skill document**: `docs/s4_soil_database_skill.md`

---

### S5: Land Use and Management Configuration
**Order**: 5 | **Depends on**: S2 | **Estimated time**: 10-30 min

Configure crop/vegetation parameters (plants.plt), management schedules (management.sch), and land use lookup (landuse.lum). Management schedules define the sequence of operations: plant, fertilize, irrigate, harvest, kill.

**Key decisions**:
- Crop types and their planting/harvest dates
- Fertilizer application rates and timing
- Irrigation scheduling (auto vs manual)
- Tillage operations and timing

**Outputs**: plants.plt (usually use default database), management.sch, landuse.lum, fertilizer.frt, tillage.til

**Tools**: `build_management_schedules`, `configure_landuse`

**Skill document**: `docs/s5_landuse_management_skill.md`

---

### S6: Calibration Parameter Setup
**Order**: 6 | **Depends on**: S2, S4 | **Estimated time**: 5-10 min (setup), hours-days (calibration runs)

Create calibration.cal to adjust model parameters without editing individual input files. SWAT+ applies adjustments at runtime.

**Key decisions**:
- Which parameters to calibrate (start with cn2, esco, awc, alpha_bf, gw_delay)
- Change type (absval vs pctchg) — use pctchg for spatially variable parameters
- Parameter ranges (see SKILL.md table)
- Calibration strategy: manual first, then automated (SUFI-2 via SWAT-CUP or iPlusQ)

**Outputs**: calibration.cal

**Tools**: `generate_calibration_file`, `apply_calibration`

**Skill document**: `docs/s6_calibration_parameters_skill.md`

---

### S7: Simulation Configuration
**Order**: 7 | **Depends on**: S1-S6 | **Estimated time**: 5-10 min

Configure file.cio (master control), time.sim (simulation period), print.prt (output settings), object.cnt, codes.bsn, parameters.bsn. Validate that all file references in file.cio point to existing files in TxtInOut.

**Key decisions**:
- Simulation period and warmup years (minimum 2 years warmup)
- Which outputs to print (daily vs monthly vs yearly)
- Basin-wide parameter flags (pet_method, rte_method, deg_method)

**file.cio categories** (in order):
```
simulation        time.sim  print.prt  object.cnt  object.prt  null
basin             codes.bsn  parameters.bsn
climate           weather-wgn.cli  weather-sta.cli  wind-dir.cli  atmo.cli
connect           hru.con  rout_unit.con  aquifer.con  chandeg.con  recall.con  ...
hru               hru-data.hru  hru-lte.hru
lsunit            ls_unit.def  ls_unit.ele
aquifer           aquifer.aqu  initial.aqu
channel           channel-lte.cha  hyd-sed-lte.cha  ...
hydrology         hydrology.hyd  topography.hyd  field.fld
soils             soils.sol  nutrients.sol
landuse           landuse.lum  management.sch  cntable.lum  ...
calibration       calibration.cal  ...
```

**Outputs**: file.cio, time.sim, print.prt, object.cnt, codes.bsn, parameters.bsn

**Tools**: `configure_file_cio`, `configure_time_sim`, `configure_print_prt`, `validate_txtinout`

**Skill document**: `docs/s7_simulation_config_skill.md`

---

### S8: Model Execution
**Order**: 8 | **Depends on**: S7 | **Estimated time**: seconds to hours (basin/period dependent)

Compile SWAT+ from Fortran source (if needed) and run the binary from within the TxtInOut directory. Monitor for runtime errors.

**Key decisions**:
- Use pre-compiled binary vs compile from source
- Compiler: gfortran (open source) vs ifort (Intel, faster)
- Compilation flags: -O2 for production, -g -fcheck=all for debugging

**Compilation** (CMake):
```bash
cd model/swatplus
mkdir build && cd build
cmake .. -DCMAKE_Fortran_COMPILER=gfortran
make -j4
```

**Execution**:
```bash
cd TxtInOut/
/path/to/swatplus
```

The binary reads file.cio from CWD. No command-line arguments.

**Outputs**: channel_sd_day.txt, basin_wb_day.txt, basin_nb_day.txt, hru_wb_day.txt, aquifer_day.txt, etc.

**Tools**: `compile_swatplus`, `run_swatplus`

**Skill document**: `docs/s8_model_execution_skill.md`

---

### S9: Output Parsing and Analysis
**Order**: 9 | **Depends on**: S8 | **Estimated time**: 5-30 min

Parse SWAT+ output files, extract discharge and water quality at the outlet, compare with observations, compute performance metrics, check mass balance.

**Key output files**:
| File | Content | Key Variables |
|------|---------|---------------|
| channel_sd_day.txt | Channel discharge + sediment + nutrients | flo_out (m3/s), sed_out (tons), orgn_out, sedp_out, no3_out, solp_out |
| basin_wb_day.txt | Basin water balance | precip, surq_gen, latq, wateryld, perc, et, sw_final |
| basin_nb_day.txt | Basin nutrient balance | orgn, no3, nh3, orgp, solp, sedp |
| hru_wb_day.txt | Per-HRU water balance | Same as basin_wb but per HRU |
| aquifer_day.txt | Groundwater | flo, dep_wt, stor, rchrg, seep, revap |

**Performance metrics** (Moriasi et al. 2007 ratings):
| Metric | Very Good | Good | Satisfactory | Unsatisfactory |
|--------|-----------|------|-------------|----------------|
| NSE | > 0.75 | 0.65-0.75 | 0.50-0.65 | < 0.50 |
| PBIAS (%) | < +/-10 | +/-10-15 | +/-15-25 | > +/-25 |
| RSR | < 0.50 | 0.50-0.60 | 0.60-0.70 | > 0.70 |

**Tools**: `parse_channel_output`, `parse_basin_output`, `compute_performance_metrics`, `check_mass_balance`

**Skill document**: `docs/s9_output_parsing_skill.md`

---

## Parallel Execution Opportunities

- **S3 and S4** can run in parallel (weather prep and soil database are independent)
- **S5** depends on S2 only (not on S3 or S4)
- **S6** depends on S2 and S4 (not on S3 or S5)
- All of S1-S6 feed into S7 for final assembly

## Coverage Summary

| Layer | Count | Coverage |
|-------|-------|----------|
| Validated tools | 20 | All 9 stages covered |
| Skill documents | 9 | One per stage |
| Diagnostic triplets | 15 | 7 failure domains |

---

*This workflow is part of the SWAT+ knowledge infrastructure, built using the Knowledge Dissection Toolkit v1.0.*
