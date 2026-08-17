---
name: ce-qual-w2
description: >-
  CE-QUAL-W2 4.5.5. Covers 2D laterally-averaged hydrodynamics (longitudinal + vertical
  velocities, free-surface); water temperature and density-driven thermal stratification;
  density-driven inflow placement (plunging / interflow / overflow); selective withdrawal
  from outlets at specified elevations; multi-branch / multi-waterbody topology with
  branch junctions and head boundaries. Use when the task involves running, configuring,
  calibrating or interpreting CE_QUAL_W2.
---

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
>
> **DEBUGGING PROTOCOL** — When something goes wrong, follow this order:
> 1. **Check triplets** — `diagnostics/triplets.yaml` may already cover this error
> 2. **Read official docs** — The model's own documentation for expected formats/units
> 3. **Find working examples** — Check `outputs/` or the model's shipped test data
> 4. **Fix the tool** — With knowledge of what "correct" looks like
>
> Do NOT write custom debug scripts. The answers are in the docs and examples.

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.
Then convert to W2 met format using this KI's tool: `tools/s3_met_forcing/convert_met_to_w2.py`

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.

---

# CE-QUAL-W2 v4.5 — Knowledge Infrastructure

**Package**: `hydrocraft-cequalw2-reservoir` v1.0.0
**Model**: CE-QUAL-W2 v4.5 (2D laterally-averaged hydrodynamic and water quality)
**Created by**: Jianyun Zhang Research Group, Hohai University
**Last updated**: 2026-03-24
**Stats**: 16 tools | 6 skill documents | 25 diagnostic triplets | 3,434 lines of validated Python
**Validation status**: `binary_only` (pending source compilation and example validation)

---

## Overview

This knowledge infrastructure enables autonomous 2D reservoir simulation using CE-QUAL-W2, the U.S. Army Corps of Engineers' standard laterally-averaged hydrodynamic and water quality model. CE-QUAL-W2 resolves **longitudinal and vertical** gradients in elongated reservoirs where 1D models (like GLM) are physically inadequate.

**What CE-QUAL-W2 does**: 2D laterally-averaged model for reservoirs, rivers, and estuaries. Simulates:
- Thermal stratification with longitudinal AND vertical resolution
- Density-driven inflow routing (plunging, interflow, overflow)
- Multi-branch topology (main stem + tributary arms)
- Selective withdrawal from multiple dam outlets at different elevations
- 21+ water quality constituents (temperature, DO, nutrients, algae, organic matter, sediment)
- Ice cover dynamics
- Adaptive CFL-limited timestepping

**Key difference from GLM (1D)**: CE-QUAL-W2 explicitly resolves longitudinal gradients. Use for:
- Reservoirs with length-to-width ratio > 5:1
- Reservoirs with multiple inflow tributaries at different locations
- Multi-level selective withdrawal (e.g., Three Gorges: outlets at 90m, 120m, 155m)
- Turbidity current and density current routing

**When GLM is sufficient**: Compact/round lakes (L:W < 5), quick assessments, global screening.

---

## Installation

### Binary

```
CE-QUAL-W2:  KISSPATH_BINARIES/ce_qual_w2/bin/w2_v5
Source:      model/ce_qual_w2/src/            (TO BE CLONED from GitHub)
Repository:  https://github.com/EnvironmentalSystems/CE-QUAL-W2
```

### Compilation from Source

```bash
# Clone source
git clone https://github.com/EnvironmentalSystems/CE-QUAL-W2.git model/ce_qual_w2/src

# Compile (exact steps depend on repo structure)
cd model/ce_qual_w2/src
gfortran -O2 -ffree-line-length-none -o ../bin/w2_v5 *.f90
# Or if Makefile exists: make

# Dependencies
sudo apt install gfortran libnetcdf-dev libnetcdff-dev
```

**Known compilation pitfalls**:
- Some source files assume Intel Fortran (`ifort`) — add `-fallow-argument-mismatch` for gfortran
- Mixed fixed-form (.f) and free-form (.f90) files may need `-ffixed-line-length-132`
- Array dimension limits may be hardcoded as PARAMETER — increase for large reservoirs
- CHARACTER path widths may need expanding beyond 72 for HydroCraft directory structure

### Python Dependencies (all in HydroCraft venv)

```
numpy, pandas, xarray, netCDF4, geopandas, shapely, rasterio, matplotlib, scipy
```

---

## Pipeline (14 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | (manual) | Reservoir selection, period, forcing, WQ toggle |
| 1 | Bathymetry | `build_reservoir_grid` | DEM/idealized geometry to segment-layer grid + bth_wb*.npt |
| 2 | Branch topology | `build_branch_topology` | Multi-branch connectivity, slopes, segment ranges |
| 3 | Met forcing | `convert_met_to_w2` | CMFD/MSWX/VIC to W2 met format (**cloud in tenths 0-10!**) |
| 4 | Inflow | `convert_inflow_to_w2`, `generate_distributed_inflow` | CaMa/VIC discharge + temperature |
| 5 | Outflow | `configure_w2_outflow` | Selective withdrawal, dam outlets, outflow timeseries |
| 6 | Init conditions | `build_init_conditions` | 2D initial temperature/WQ fields |
| 7 | Hydraulic params | `set_hydraulic_params` | AX, DX, WSC, CBHE, TSED, EXH2O auto-estimated |
| 8 | WQ config | `configure_wq` | Constituent activation, kinetic rates, algae groups |
| 9 | Control file | `generate_w2_control` | Assemble w2_con.npt (**8-char fixed-width!**) |
| 10 | Execution | `run_w2` | Preflight checks, run binary, log monitoring |
| 11 | Output analysis | `parse_w2_output`, `plot_w2_curtain`, `plot_w2_timeseries` | Parse + visualize |
| 12 | Calibration | `calibrate_w2` | GLUE-style against observed temperature profiles |
| 13 | Coupling | `w2_to_cama_coupling` | Dam release to CaMa-Flood downstream |

### Parallelism

Stages 1-8 can largely run in parallel after stage 0 (with s2 depending on s1, s4 depending on s3).
Stage 9 depends on ALL of s1-s8.
Stage 10 depends on s9. Stages 11-13 depend on s10.

---

## Tools Reference

| Tool | Stage | Script Path | Lines | Purpose |
|------|-------|-------------|------:|---------|
| `build_reservoir_grid` | s1 | `tools/s1_bathymetry/build_reservoir_grid.py` | 310 | DEM or idealized geometry to segment-layer grid |
| `build_branch_topology` | s2 | `tools/s2_branch_topology/build_branch_topology.py` | 150 | Branch connectivity and slopes |
| `convert_met_to_w2` | s3 | `tools/s3_met_forcing/convert_met_to_w2.py` | 290 | CMFD/MSWX to W2 met format (VP->TDEW, cloud 0-10) |
| `convert_inflow_to_w2` | s4 | `tools/s4_inflow/convert_inflow_to_w2.py` | 250 | CaMa/VIC to W2 inflow files (qin + tin + cin) |
| `generate_distributed_inflow` | s4 | `tools/s4_inflow/generate_distributed_inflow.py` | 160 | Distributed tributary flow (qdt + tdt) |
| `configure_w2_outflow` | s5 | `tools/s5_outflow/configure_w2_outflow.py` | 130 | Dam outlet config + outflow timeseries |
| `build_init_conditions` | s6 | `tools/s6_init_conditions/build_init_conditions.py` | 130 | 2D initial T/WQ fields |
| `set_hydraulic_params` | s7 | `tools/s7_hydraulic_params/set_hydraulic_params.py` | 100 | Auto-estimate AX, DX, WSC from geometry |
| `configure_wq` | s8 | `tools/s8_wq_config/configure_wq.py` | 130 | WQ constituent activation and rates |
| `generate_w2_control` | s9 | `tools/s9_control_file/generate_w2_control.py` | 350 | Assemble w2_con.npt with validation |
| `run_w2` | s10 | `tools/s10_execution/run_w2.py` | 180 | Execute with preflight + postrun checks |
| `parse_w2_output` | s11 | `tools/s11_output_analysis/parse_w2_output.py` | 190 | Parse snapshot/timeseries/spreadsheet output |
| `plot_w2_curtain` | s11 | `tools/s11_output_analysis/plot_w2_curtain.py` | 180 | 2D longitudinal-vertical curtain plots |
| `plot_w2_timeseries` | s11 | `tools/s11_output_analysis/plot_w2_timeseries.py` | 120 | Time series at specific locations |
| `calibrate_w2` | s12 | `tools/s12_calibration/calibrate_w2.py` | 130 | GLUE calibration (WSC, EXH2O, AX, CBHE, TSED) |
| `w2_to_cama_coupling` | s13 | `tools/s13_coupling/w2_to_cama_coupling.py` | 120 | W2 outflow to CaMa-Flood |

**Total**: 16 tools, 3,434 lines of validated Python code.

---

## Critical Domain Knowledge

These non-obvious facts cause **silent failures** if violated. Each has a diagnostic triplet.

### 1. Cloud cover is in TENTHS (0-10), NOT fraction (0-1) (dt_001)

CE-QUAL-W2 reads cloud cover as 0-10. If you pass 0-1 (fraction), the model sees near-clear sky always, resulting in excessive shortwave radiation and water temperatures 3-5 C too warm. This is the #1 silent error for CE-QUAL-W2. There is NO error message.

### 2. Dewpoint, not relative humidity (dt_002)

CE-QUAL-W2 expects dewpoint temperature (TDEW, deg C), not RH or VP directly.
Formula: `TDEW = (237.3 * ln(VP/0.6108)) / (17.27 - ln(VP/0.6108))` with VP in kPa.
VP must be in kPa (CMFD = kPa, ERA5 = Pa -> divide by 1000).

### 3. Julian day is DECIMAL, not integer (dt_005)

JDAY = day_of_year + hour/24 + minute/1440. So 1.0 = midnight Jan 1, 1.5 = noon Jan 1.
Integer JDAY shifts the diurnal radiation cycle and causes systematic temperature errors.

### 4. w2_con.npt uses 8-character fixed-width fields (dt_006)

This is the single most dangerous format requirement. Fortran reads by COLUMN POSITION.
Off-by-one alignment shifts ALL subsequent values silently. Every numeric field must be
exactly 8 characters, right-justified. Use `{:>8.2f}` in Python.

### 5. File paths must be < 72 characters (dt_008)

Fortran CHARACTER*72 path variables silently truncate longer paths. Use relative paths
or symlinks. `generate_w2_control.py` uses `os.path.basename()` to mitigate this.

### 6. Bottom elevations must be monotonically non-increasing downstream (dt_013)

If a downstream segment has a HIGHER bottom elevation than an upstream segment, water
gets trapped in a depression. The model runs but produces physically wrong longitudinal
gradients.

### 7. Constituent ON/OFF flags must match inflow file columns exactly (dt_015)

If the CONSTITU card has N constituents ON, the cin_br*.npt file must have exactly N
data columns (plus JDAY). A mismatch causes a Fortran column shift that silently
corrupts all constituent concentrations.

### 8. Avoid double-counting runoff in coupling (dt_021)

When using both CaMa-Flood main channel inflow AND distributed tributary inflow,
subtract the main inflow contributing area from the distributed tributary area.
Otherwise the reservoir receives double the water input.

---

## Coupling Points

| # | Source | Target | Variable | Tool |
|---|--------|--------|----------|------|
| 1 | CaMa-Flood | CE-QUAL-W2 | Upstream discharge | `convert_inflow_to_w2` |
| 2 | VIC | CE-QUAL-W2 | Met forcing | `convert_met_to_w2` |
| 3 | VIC | CE-QUAL-W2 | Distributed tributary runoff | `generate_distributed_inflow` |
| 4 | CE-QUAL-W2 | CaMa-Flood | Dam release discharge | `w2_to_cama_coupling` |
| 5 | CE-QUAL-W2 | CaMa-Flood | Dam release temperature | `w2_to_cama_coupling` |
| 6 | SWAT+ | CE-QUAL-W2 | Upstream nutrient loading | (via cin_br*.npt) |
| 7 | GLM | CE-QUAL-W2 | 1D vs 2D comparison | (shared forcing + inflow) |
| 8 | CMIP6 | CE-QUAL-W2 | Future climate forcing | (delta-change on met files) |

### Auto-Selection: CE-QUAL-W2 vs GLM

```python
if reservoir_length_km / reservoir_width_km > 5:
    recommend = "CE-QUAL-W2"
elif multiple_inflow_locations:
    recommend = "CE-QUAL-W2"
elif multi_level_selective_withdrawal:
    recommend = "CE-QUAL-W2"
else:
    recommend = "GLM"
```

---

## Calibration Parameters (Priority Order)

| Parameter | Range | Controls | Sensitivity |
|-----------|-------|----------|-------------|
| WSC | 0.5 - 1.0 | Wind sheltering, surface mixing | HIGH |
| EXH2O | 0.1 - 1.0 m^-1 | Light extinction, thermocline depth | HIGH |
| AX | 0.1 - 10 m^2/s | Longitudinal mixing | MEDIUM |
| CBHE | 0.3 - 1.5 W/m^2/C | Bottom heat exchange | MEDIUM |
| TSED | 5 - 15 C | Sediment temperature | LOW |

---

## Quick Start (Idealized Reservoir)

```bash
source KISSPATH_PYTHON_ENV/bin/activate
cd KISSPATH_KI_ROOT/CE_QUAL_W2/knowledge_infrastructure

# 1. Build idealized grid (no DEM needed)
python tools/s1_bathymetry/build_reservoir_grid.py \
    --idealized --reservoir_length_km 80 --max_depth 80 \
    --surface_area_km2 745 --dam_elevation 170 \
    --segment_length 2000 --layer_thickness 2.0 \
    --output_dir /tmp/w2_test

# 2. Convert forcing to W2 met format
python tools/s3_met_forcing/convert_met_to_w2.py \
    --vic_forcing_dir outputs/<run>/vic_temp/forcing/forcing_final \
    --lat 32.54 --lon 111.51 --start_year 2005 --end_year 2010 \
    --output /tmp/w2_test/met_wb1.npt

# 3. Generate inflow
python tools/s4_inflow/convert_inflow_to_w2.py \
    --discharge_csv routing_output.csv \
    --met_file /tmp/w2_test/met_wb1.npt \
    --start_year 2005 --end_year 2010 \
    --output_dir /tmp/w2_test

# 4. Configure outflow
python tools/s5_outflow/configure_w2_outflow.py \
    --mode constant --outflow_m3s 50 --outlet_elevation 120 \
    --start_jday 1 --end_jday 365 --output_dir /tmp/w2_test

# 5. Generate control file
python tools/s9_control_file/generate_w2_control.py \
    --grid_json /tmp/w2_test/reservoir_grid.json \
    --met_file /tmp/w2_test/met_wb1.npt \
    --qin_files /tmp/w2_test/qin_br1.npt \
    --year 2005 --output /tmp/w2_test/w2_con.npt

# 6. Run CE-QUAL-W2
python tools/s10_execution/run_w2.py --run_dir /tmp/w2_test

# 7. Analyze output
python tools/s11_output_analysis/plot_w2_curtain.py \
    --run_dir /tmp/w2_test \
    --grid_json /tmp/w2_test/reservoir_grid.json \
    --output /tmp/w2_test/curtain.png
```

---

## Diagnostic Triplets

25 triplets across 8 failure domains. See `diagnostics/triplets.yaml` for full details.

| ID | Severity | Domain | Summary |
|----|----------|--------|---------|
| dt_001 | **silent** | unit_conversion | Cloud cover as fraction 0-1 instead of tenths 0-10 (3-5 C warm bias) |
| dt_002 | **silent** | unit_conversion | VP units wrong in dewpoint conversion (TDEW = -40 C) |
| dt_003 | **silent** | unit_conversion | Inflow discharge units (mm/day vs m^3/s, 10^5x error) |
| dt_004 | **silent** | unit_conversion | Wind direction degrees vs radians |
| dt_005 | **silent** | unit_conversion | Julian day integer vs decimal (diurnal cycle wrong) |
| dt_006 | **silent** | parameter_format | 8-char column misalignment in w2_con.npt |
| dt_007 | fatal | parameter_format | Bathymetry column widths wrong |
| dt_008 | fatal | path_resolution | File path exceeds Fortran CHARACTER*72 limit |
| dt_009 | fatal | dependency_mismatch | Input files shorter than simulation period |
| dt_010 | fatal | grid_geometry | Active segment has zero width at all layers |
| dt_011 | fatal | grid_geometry | CFL violation from short segments |
| dt_012 | fatal | grid_geometry | Invalid branch DHS reference |
| dt_013 | **silent** | grid_geometry | Bottom elevation increases downstream |
| dt_014 | fatal | grid_geometry | ELWS below bottom elevation at upstream segments |
| dt_015 | **silent** | dependency_mismatch | Constituent ON/OFF mismatch with inflow file columns |
| dt_016 | **silent** | silent_error | SOD too high — instant anoxia |
| dt_017 | **silent** | silent_error | Algal growth rate too high — unrealistic bloom |
| dt_018 | **silent** | unit_conversion | Outlet elevation in wrong reference frame |
| dt_019 | **silent** | unit_conversion | Outflow units wrong (reservoir drains/fills unrealistically) |
| dt_020 | **silent** | coupling | CaMa inflow at wrong segment |
| dt_021 | **silent** | coupling | Double-counting VIC + CaMa runoff |
| dt_022 | degraded | runtime | Timestep drops to < 1s (slow) |
| dt_023 | fatal | runtime | NaN from bathymetry gradient instability |
| dt_024 | fatal | runtime | NEGATIVE THICKNESS during drawdown |
| dt_025 | **silent** | silent_error | No output despite successful completion |

**Silent error count**: 14/25 (56%) — consistent with lake model error rates.

---

## File Structure

```
models/CE_QUAL_W2/knowledge_infrastructure/
  DISSECTION_PLAN.md              # Original dissection plan
  SKILL.md                        # This file (agent entry point)
  knowledge_infrastructure.yaml   # Schema-compliant package definition
  tools/
    s1_bathymetry/
      build_reservoir_grid.py     # DEM/idealized to segment-layer grid
    s2_branch_topology/
      build_branch_topology.py    # Branch connectivity
    s3_met_forcing/
      convert_met_to_w2.py        # CMFD/MSWX to W2 met (cloud 0-10!)
    s4_inflow/
      convert_inflow_to_w2.py     # CaMa/VIC to W2 inflow
      generate_distributed_inflow.py  # Distributed tributary flow
    s5_outflow/
      configure_w2_outflow.py     # Dam outlet configuration
    s6_init_conditions/
      build_init_conditions.py    # 2D initial T/WQ
    s7_hydraulic_params/
      set_hydraulic_params.py     # AX, DX, WSC auto-estimation
    s8_wq_config/
      configure_wq.py             # Constituent activation + rates
    s9_control_file/
      generate_w2_control.py      # w2_con.npt assembly
    s10_execution/
      run_w2.py                   # Run W2 with preflight checks
    s11_output_analysis/
      parse_w2_output.py          # Parse fixed-width output files
      plot_w2_curtain.py          # 2D curtain plots
      plot_w2_timeseries.py       # Time series plots
    s12_calibration/
      calibrate_w2.py             # GLUE-style calibration
    s13_coupling/
      w2_to_cama_coupling.py      # W2 -> CaMa-Flood coupling
  docs/
    s0_configuration_skill.md
    s1_bathymetry_skill.md
    s3_met_forcing_skill.md
    s9_control_file_skill.md
    s10_execution_skill.md
    s11_output_analysis_skill.md
  diagnostics/
    triplets.yaml                 # 25 diagnostic triplets

model/ce_qual_w2/
  bin/w2_v5                     # CE-QUAL-W2 executable (TO BE COMPILED)
  src/                           # Fortran source (TO BE CLONED)
  examples/                      # Reference examples
  docs/                          # User manual PDF
```

---

## Target Validation Reservoirs

| Reservoir | Length | Max Depth | Branches | Priority |
|-----------|--------|-----------|----------|----------|
| **Danjiangkou** (丹江口) | 80 km | 80 m | 2 (Han + Dan) | HIGH (S-N Water Transfer) |
| **Three Gorges** (三峡) | 660 km | 175 m | 1+ | MEDIUM (large, expensive) |
| **Miyun** (密云) | ~20 km | 60 m | 2 (Chao + Bai) | HIGH (compare with GLM) |
| **DeGray Lake** (Arkansas) | ~25 km | 60 m | 1 | HIGH (USACE reference example) |
