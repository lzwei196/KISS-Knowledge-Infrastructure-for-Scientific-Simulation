> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model. Doing so produces
> scientifically invalid results and defeats the purpose of the KI.
>
> Before starting, run: `python preflight_check.py` (in this KI directory)
> to verify that the model binary/package and required data are available.

---

# CRHM (Cold Regions Hydrological Model) -- Knowledge Infrastructure

**Package**: hydrocraft-crhm v1.0.0
**Model**: CRHM 1.3 (crhmcode, University of Saskatchewan)
**Domain**: Cold regions hydrology -- blowing snow, sublimation, frozen soil infiltration, energy-balance snowmelt
**Coupling target**: VIC 5.1.0 (cold regions process enhancement)

---

## What is CRHM?

CRHM is a modular, physically-based hydrological model designed for cold regions. Unlike grid-based models (VIC, WRF-Hydro), CRHM uses **Hydrological Response Units (HRUs)** -- irregular landscape units grouped by elevation, land cover, slope, and aspect. Its key strength is a library of cold-regions-specific modules:

- **PBSM** (Prairie Blowing Snow Model): Wind transport, sublimation, redistribution of snow
- **CRHMCanopy**: Forest canopy interception, sublimation (30-40% of snowfall in boreal forests)
- **SnobalCRHM**: Full energy-balance snowmelt with wind and radiation effects
- **PrairieInfil**: Frozen soil infiltration using Gray's equation (prairie clay soils)
- **Slope_Qsi**: Solar radiation correction for slope and aspect (critical in mountains)

Modules form a **chain**: output of one feeds input to the next via `declvar()`/`declgetvar()`. The chain order determines the physics.

## Installation

CRHM is built from C++ source with CMake and GCC:

```bash
bash KISSPATH_KI_ROOT/CRHM/knowledge_infrastructure/install_crhm.sh
```

**Requirements**: cmake, g++ (C++14), git, Boost 1.75.0 (auto-downloaded by install script).

**Executable**: `KISSPATH_BINARIES/crhmcode/crhmcode/build/crhm`

**CLI**:
```bash
crhm [-t ISO|YYYYMMDD] [-f STD|OBS] [-o output.txt] [-p 100] [--obs_file_directory dir] project.prj
```

## Pipeline Stages

| Stage | Name | Skill Document | Key Tools |
|-------|------|----------------|-----------|
| s1 | HRU Basin Setup | `docs/s1_basin_setup_skill.md` | `create_hru_config.py` |
| s2 | Observation Data | `docs/s2_observation_data_skill.md` | `convert_vic_to_obs.py`, `validate_obs_file.py` |
| s3 | Module Selection | `docs/s3_module_selection_skill.md` | `select_modules.py` |
| s4 | Parameter Config | `docs/s4_parameter_config_skill.md` | `create_prj_file.py`, `validate_prj.py` |
| s5 | Execution | `docs/s5_execution_skill.md` | `run_crhm.py`, `parse_crhm_output.py`, `plot_crhm_results.py` |
| s6 | VIC Coupling | `docs/s6_vic_coupling_skill.md` | `convert_vic_to_obs.py`, `merge_crhm_vic.py` |

**Dependencies**: s1 and s2 can run in parallel. s3 depends on s1. s4 depends on s1+s3. s5 depends on s2+s4. s6 depends on s5.

## Tools Reference

| Tool | Stage | Script Path | Purpose |
|------|-------|-------------|---------|
| create_hru_config | s1 | `tools/s1_basin_setup/create_hru_config.py` | Generate HRU definitions from DEM + land cover |
| convert_vic_to_obs | s2 | `tools/s2_observation_data/convert_vic_to_obs.py` | Convert VIC forcing to CRHM .obs format |
| validate_obs_file | s2 | `tools/s2_observation_data/validate_obs_file.py` | Check .obs format, units, gaps |
| select_modules | s3 | `tools/s3_module_selection/select_modules.py` | Configure module chain by landscape type |
| create_prj_file | s4 | `tools/s4_parameter_config/create_prj_file.py` | Generate .prj project file |
| validate_prj | s4 | `tools/s4_parameter_config/validate_prj.py` | Validate .prj structure and parameter ranges |
| run_crhm | s5 | `tools/s5_execution/run_crhm.py` | Execute CRHM with progress reporting |
| parse_crhm_output | s5 | `tools/s5_execution/parse_crhm_output.py` | Parse CRHM output to CSV/NetCDF |
| plot_crhm_results | s5 | `tools/s5_execution/plot_crhm_results.py` | Generate diagnostic plots (SWE, discharge, etc.) |
| merge_crhm_vic | s6 | `tools/s6_vic_coupling/merge_crhm_vic.py` | Combine CRHM + VIC results for comparison |

## .prj File Format

CRHM project files use section delimiters (`######`):

```
######
Dimensions:
######
nhru 5
nlay 1
nobs 1

######
Observations:
######
/absolute/path/to/basin.obs

######
Dates:
######
2000 1 1
2010 12 31

######
Modules:
######
Basin_Group Macro 04/20/06
 +basin CRHM 04/20/06
 +global CRHM 04/20/06
 +obs CRHM 04/20/06
 +PBSM CRHM 04/20/06
 +PrairieInfil CRHM 04/20/06
 +Soil CRHM 04/20/06
 +Netroute CRHM 04/20/06

######
Parameters:
######
PBSM fetch <10 to 10000>
1500.0 1500.0 200.0 50.0 30.0
```

## .obs File Format

```
Station data converted from VIC
t 1 (C)
rh 1 (%)
u 1 (m/s)
ppt 1 (mm/d)
Qsi 1 (W/m^2)
$ea ea(t, rh) (kPa) vapour pressure
2000 1 1 1 0 -15.50 81.50 3.10 0.00 0.00
```

## Module Chain Concept

Pre-built chains by landscape type:

| Landscape | Chain | Key Feature |
|-----------|-------|-------------|
| **Prairie** | basin > global > obs > PBSM > PrairieInfil > Soil > Netroute | Blowing snow transport |
| **Mountain** | basin > global > obs > Slope_Qsi > SnobalCRHM > GreenAmpt > Soil > Netroute | Slope radiation correction |
| **Forest** | basin > global > obs > CRHMCanopy > SnobalCRHM > GreenAmpt > Soil > Netroute | Canopy interception/sublimation |
| **Arctic** | basin > global > obs > PBSM > SnobalCRHM > PrairieInfil > Soil > REWroute | Permafrost + blowing snow |

## Critical Domain Knowledge

### The #1 Silent Error: Humidity Unit Conversion

VIC uses **specific humidity** (kg/kg, values ~0.001-0.02). CRHM expects **relative humidity** (%, values 0-100). If you pass specific humidity directly, CRHM interprets the atmosphere as 0.001-0.02% RH (bone dry). All sublimation goes to zero. SWE accumulates forever. **The model runs to completion with no error.** Always use `convert_vic_to_obs.py` which applies the Tetens formula conversion.

**Detection**: If max(RH) in .obs file < 1.0, the units are wrong.

### Parameter Clamping (Silent)

CRHM clamps parameters to their declared `<min to max>` range WITHOUT warning. You set `fetch=50000` but the model uses `max=10000`. Always run `validate_prj.py` before running CRHM.

### VIC Coupling: Process Ownership

Both VIC and CRHM compute snowmelt, ET, and soil moisture. **Define a process ownership table** before merging outputs. Each process is assigned to exactly one model. Double-counting produces water balance errors >100%.

### Cold Regions Observation Data Quality

Winter weather stations in cold regions (-40C, blizzards, rime icing) frequently fail. Gap-filled data with constant values misrepresents extreme cold events that control frozen soil state. Prefer reanalysis (ERA5, CMFD, MSWX) over gap-filled station data for cold regions.

### Blowing Snow is Landscape-Specific

PBSM is only valid for wind-exposed terrain (prairie, tundra, alpine above treeline). Using it in dense forest produces unrealistic transport. CRHMCanopy handles snow processes in forested landscapes.

## Unit Conversion Table

| Variable | VIC Unit | CRHM Unit | Conversion | Silent if Wrong? |
|----------|----------|-----------|------------|------------------|
| Temperature | C | C | None | No |
| Humidity | kg/kg (specific) | % (relative) | Tetens formula | **YES** |
| Precipitation | mm/timestep | mm/d | *24/timestep_hours | **YES** |
| Wind | m/s | m/s | None | No |
| SW radiation | W/m2 | W/m2 | None | No |
| LW radiation | W/m2 | W/m2 | None | No |
| Pressure | kPa | kPa | None | No |

## Error Handling

See `diagnostics/triplets.yaml` for 18 diagnostic triplets covering:
- **Unit conversion** (dt_001, dt_002, dt_009): humidity, precipitation, VIC-CRHM mismatch
- **Silent errors** (dt_006, dt_010, dt_011, dt_012, dt_016): parameter clamping, double-counting, winter gaps, CRS mismatch, wrong module
- **Format errors** (dt_003, dt_005, dt_013, dt_018): .obs header, parameter count, section delimiters, timestep
- **Runtime errors** (dt_004, dt_007, dt_008, dt_014, dt_017): module deps, paths, crashes, empty output, Boost

**Silent errors account for 7 of 18 triplets (39%)** -- consistent with the 37% rate across all 15 models in the toolkit.

## Quick Start

```bash
# 1. Build CRHM
bash install_crhm.sh

# 2. Create HRUs
python tools/s1_basin_setup/create_hru_config.py --dem_path dem.tif --landcover_path lc.tif --shapefile_path basin.shp --output_dir out/hru

# 3. Convert VIC forcing
python tools/s2_observation_data/convert_vic_to_obs.py --forcing_dir vic_forcing/ --grid_nc grid.nc --output_path out/basin.obs --start_year 2000 --end_year 2010

# 4. Select modules (prairie example)
python tools/s3_module_selection/select_modules.py --basin_type prairie --output_path out/modules.json

# 5. Create .prj file
python tools/s4_parameter_config/create_prj_file.py --hru_config out/hru/hru_config.json --module_chain out/modules.json --obs_path out/basin.obs --start_date "2000 1 1" --end_date "2010 12 31" --output_path out/basin.prj

# 6. Validate
python tools/s4_parameter_config/validate_prj.py --prj_path out/basin.prj

# 7. Run CRHM
python tools/s5_execution/run_crhm.py --crhm_exe model/crhmcode/crhmcode/build/crhm --prj_path out/basin.prj --output_path out/output.txt

# 8. Parse and plot
python tools/s5_execution/parse_crhm_output.py --output_path out/output.txt --output_format both --output_dir out/parsed
python tools/s5_execution/plot_crhm_results.py --csv_path out/parsed/crhm_results.csv --output_dir out/plots --title "My Basin"
```

---

*This knowledge infrastructure package was created using the Knowledge Dissection Toolkit (Zhang et al., Nature, under review).*
*Package: hydrocraft-crhm v1.0.0 | 10 tools | 6 skill documents | 18 diagnostic triplets | 6 pipeline stages*

---

## Validated Module Chain — Mountain Basin (Belly River, Alberta)

**15 modules, tested 2005-2015, KGE=0.65, PBIAS=-3.4%**

```
basin → global → obs → calcsun → Slope_Qsi → walmsley_wind → intcp → pbsm → albedo → ebsm → netall → crack → evap → Soil → Netroute
```

| Module | Purpose | Key Parameters |
|--------|---------|---------------|
| basin | Geometry | basin_area, hru_area |
| global | Global radiation | Time_Offset |
| obs | Read forcing | precip_elev_adj (USE 0.05 for mountains!) |
| calcsun | Solar angles | (uses hru_lat) |
| **Slope_Qsi** | Slope radiation | hru_ASL (aspect), hru_GSL (slope) |
| **walmsley_wind** | Topo wind amplification | A=4.0/3.0/0.5, L=500/800/2000 |
| intcp | Canopy interception | (forest HRUs only) |
| pbsm | Blowing snow | fetch, N_S, distrib |
| albedo | Snow albedo decay | Albedo_bare, Albedo_snow |
| ebsm | Energy balance melt | tfactor, nfactor |
| netall | Net radiation | (computed from Qsi, Qli, albedo) |
| crack | Frozen soil infiltration | fallstat, infDays, Major |
| evap | Evapotranspiration | evap_type, Ht |
| Soil | Soil + GW | gw_K, gw_max, soil_gw_K |
| Netroute | Routing | Kstorage, Lag, gwKstorage, gwLag |

### Critical Lessons from Belly River Validation

1. **.obs header**: NO `####` line before variable declarations — causes infinite loop (dt_v001)
2. **pbsm required**: Without it, CRHM segfaults on wildcard SWE search (dt_v002)
3. **NASA POWER precip ÷24**: Hourly values are mm/day rate, not mm/hr (dt_v004)
4. **Mountain precip scaling**: NASA POWER underestimates by ~40% in Rockies — scale ×1.7
5. **GW parameters**: gwKstorage=50-80, gwLag=500-1000, gw_K=2-5 for sustained winter baseflow
6. **Wind amplification**: Walmsley A=4.0 for alpine ridges (NASA POWER wind is 3.5x too low)
