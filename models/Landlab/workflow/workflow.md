# Landlab — Workflow

7-stage landscape-evolution pipeline. Stage IDs and tool bindings match the
canonical table in `SKILL.md` (§ Pipeline). This KI is for landscape
evolution / sediment-yield benchmarks only — see `SKILL.md` § Applicability.
It does NOT produce a daily discharge hydrograph and is NOT applicable to
gauge-discharge tests (Bengbu, Wangjiaba, etc.).

## Pipeline Stages

### Stage 1: Grid Setup (`s1_grid`)
- **Description**: Create model grid with DEM or synthetic topography.
- **Tool**: — (in-script `RasterModelGrid` / `read_esri_ascii`)
- **Dependencies**: none

### Stage 2: Input Preparation (`s2_input`)
- **Description**: Load DEM, set boundary conditions, add fields.
- **Tool**: `tools/convert_dem_to_grid.py`
- **Dependencies**: s1_grid

### Stage 3: Soil/Parameter Setup (`s3_params`)
- **Description**: Map HWSD or other soil data to grid fields (K_sp, D, etc.).
- **Tool**: `tools/convert_soil_params.py`
- **Dependencies**: s1_grid (parallel with s2_input)

### Stage 4: Component Assembly (`s4_assembly`)
- **Description**: Instantiate and couple Landlab components
  (FlowAccumulator, StreamPowerEroder, LinearDiffuser, …).
- **Tool**: — (in-script)
- **Dependencies**: s2_input, s3_params

### Stage 5: Execution (`s5_run`)
- **Description**: Time-stepping loop calling `run_one_step()` over geologic
  timescales. No daily forcing ingestion.
- **Tool**: `tools/run_landlab.py`
- **Dependencies**: s4_assembly

### Stage 6: Output Extraction (`s6_output`)
- **Description**: Extract grid fields (topographic__elevation,
  drainage_area, slope, sediment_flux) to CSV/NetCDF; compute metrics.
- **Tool**: `tools/parse_landlab_output.py`
- **Dependencies**: s5_run

### Stage 7: Diagnostics (`s7_diag`)
- **Description**: Validate against analytical solutions (Whipple-Tucker,
  slope-area concavity) or basin sediment-yield observations.
- **Tool**: `diagnostics/` validation scripts
  (`dissect_loess_plateau_slope_area.py`,
  `dissect_loess_plateau_sediment_yield.py`,
  `dissect_atchafalaya_ssc_q_surrogate.py`)
- **Dependencies**: s6_output
