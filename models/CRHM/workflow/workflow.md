# CRHM Pipeline Workflow

## Overview

6-stage pipeline for CRHM cold regions hydrological modelling with VIC coupling.

```
s1_basin_setup ──┐
                 ├── s3_module_selection ── s4_parameter_config ──┐
s2_obs_data ─────┘                                                ├── s5_execution ── s6_vic_coupling
                                                                  │
s2_obs_data ──────────────────────────────────────────────────────┘
```

## Pipeline Stages

### Stage 1: HRU Basin Setup (s1_basin_setup)
- **Input**: DEM, land cover raster, basin shapefile
- **Output**: `hru_config.json` (HRU definitions with areas, elevations, land cover)
- **Tool**: `create_hru_config.py`
- **Key decision**: Number of elevation bands, aspect stratification
- **Milestone**: nhru > 0, total area matches basin area

### Stage 2: Observation Data (s2_observation_data)
- **Input**: VIC forcing files or weather station data
- **Output**: `.obs` file with CRHM-format header and data
- **Tools**: `convert_vic_to_obs.py`, `validate_obs_file.py`
- **Key decision**: Humidity conversion (specific -> relative), timestep
- **Milestone**: .obs validates with no errors, no datetime gaps
- **CRITICAL**: Humidity unit conversion (dt_001) -- #1 silent error

### Stage 3: Module Selection (s3_module_selection)
- **Input**: Basin landscape type, HRU config
- **Output**: `modules.json` (ordered module chain)
- **Tool**: `select_modules.py`
- **Key decision**: Landscape type determines chain (prairie/mountain/forest/arctic)
- **Milestone**: Chain validates, all dependencies resolved

### Stage 4: Parameter Configuration (s4_parameter_config)
- **Input**: HRU config, module chain, obs file, dates
- **Output**: `.prj` project file
- **Tools**: `create_prj_file.py`, `validate_prj.py`
- **Key decision**: Fetch distances, soil properties, routing order
- **Milestone**: .prj validates, no parameter range violations
- **CRITICAL**: Silent parameter clamping (dt_006)

### Stage 5: Execution (s5_execution)
- **Input**: CRHM executable, .prj file
- **Output**: Tab-delimited output -> CSV -> NetCDF -> plots
- **Tools**: `run_crhm.py`, `parse_crhm_output.py`, `plot_crhm_results.py`
- **Key decision**: Output variable selection, result interpretation
- **Milestone**: Exit code 0, output non-empty, SWE has seasonal cycle

### Stage 6: VIC Coupling (s6_vic_coupling)
- **Input**: CRHM results, VIC results, grid NC
- **Output**: Merged comparison CSV and plots
- **Tool**: `merge_crhm_vic.py`
- **Key decision**: Process ownership table (which model owns which process)
- **Milestone**: Water balance closes, no double-counting
- **CRITICAL**: Double-counting snow processes (dt_010)

## Coverage Summary

| Category | Count |
|----------|-------|
| Pipeline stages | 6 |
| Validated tools | 10 |
| Skill documents | 6 |
| Diagnostic triplets | 18 |
| Silent error triplets | 7 (39%) |
| Failure domains | 7 |

## Critical Path

The critical path is: s2 (obs data) -> s5 (execution) because observation data quality directly determines simulation quality, and the humidity unit conversion (dt_001) is the most dangerous silent error.

## Parallelism

- s1 (HRU setup) and s2 (obs data) can run in parallel
- s3 (module selection) requires s1 but not s2
- s4 (parameter config) requires s1 + s3
- s5 (execution) requires s2 + s4
- s6 (VIC coupling) requires s5

## Known Gaps

1. **Calibration**: No automated calibration tool yet. CRHM parameters (fetch, Ht, soil_K) require manual tuning or external optimization.
2. **Multi-HRU spatial mapping**: The VIC-CRHM spatial mapping (HRU to grid cell) is simplified. A proper area-weighted mapping tool is needed for >10 HRUs.
3. **Glacier module**: ICEflow module exists in CRHM source but is not yet integrated into the knowledge infrastructure.
4. **Water quality**: CRHM has water quality modules (waterquality/) that are not covered.
