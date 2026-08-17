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

# SUMMA Knowledge Infrastructure

**SUMMA** (Structure for Unifying Multiple Modeling Alternatives) is a flexible multi-physics hydrologic modeling framework developed by NCAR (Clark et al., 2015a,b). Unlike traditional hydrologic models that hardcode one set of process representations, SUMMA lets you **choose** which physics to use for each process via "model decisions" -- then systematically compare alternatives. This knowledge infrastructure enables autonomous AI operation of SUMMA.

**Model**: SUMMA (CH-Earth/summa), Fortran 90, NetCDF I/O
**Domain**: Multi-physics distributed hydrology
**Key Feature**: Model decisions -- 35 categories of physics options (snow, soil, vegetation, radiation, groundwater)
**Executable**: `model/summa/bin/summa.exe`
**Configuration**: `fileManager.txt` (master config pointing to all other files)

---

## Pipeline Overview (7 Stages)

| Stage | Name | Key Tool | Output |
|-------|------|----------|--------|
| s1 | Domain Setup (GRU/HRU) | `create_gru_hru.py`, `create_local_attributes.py` | `attributes.nc` |
| s2 | Forcing Preparation | `convert_vic_forcing_to_summa.py` | `forcing_YYYY.nc` |
| s3 | Model Decisions | `configure_decisions.py` | `decisions.txt` |
| s4 | Parameter Configuration | `set_trial_parameters.py` | `trialParams.nc` |
| s5 | Initial Conditions | `create_initial_conditions.py` | `coldState.nc` |
| s6 | Execution | `create_file_manager.py`, `validate_file_manager.py`, `run_summa.py`, `parse_summa_output.py` | SUMMA output NetCDF |
| s7 | Physics Comparison | `compare_physics.py`, `plot_summa_results.py` | Comparison CSV + plots |

**Dependencies**: s1 -> s2, s4, s5; s3 is independent; s1+s2+s3+s4+s5 -> s6 -> s7

---

## Tools Reference

| Stage | Tool | Script | Purpose |
|-------|------|--------|---------|
| s1 | create_gru_hru | `tools/s1_domain_setup/create_gru_hru.py` | Create GRU/HRU structure from shapefile + DEM |
| s1 | create_local_attributes | `tools/s1_domain_setup/create_local_attributes.py` | Generate SUMMA attributes NetCDF |
| s2 | convert_vic_forcing_to_summa | `tools/s2_forcing_prep/convert_vic_forcing_to_summa.py` | VIC forcing -> SUMMA NetCDF with unit conversions |
| s3 | configure_decisions | `tools/s3_decisions/configure_decisions.py` | Generate decisions file with validation |
| s4 | set_trial_parameters | `tools/s4_parameters/set_trial_parameters.py` | Generate trial parameters NetCDF |
| s5 | create_initial_conditions | `tools/s5_initial_conditions/create_initial_conditions.py` | Generate cold-start initial conditions |
| s6 | create_file_manager | `tools/s6_execution/create_file_manager.py` | Generate fileManager.txt with absolute paths |
| s6 | validate_file_manager | `tools/s6_execution/validate_file_manager.py` | Check all paths and dimensions before running |
| s6 | run_summa | `tools/s6_execution/run_summa.py` | Execute SUMMA with progress monitoring |
| s6 | parse_summa_output | `tools/s6_execution/parse_summa_output.py` | Extract variables from output NetCDF |
| s7 | compare_physics | `tools/s7_physics_comparison/compare_physics.py` | Run multiple decision variants and compare |
| s7 | plot_summa_results | `tools/s7_physics_comparison/plot_summa_results.py` | Publication-quality result plots |

---

## Critical Domain Knowledge

### 1. fileManager.txt -- The Master Config

fileManager.txt is SUMMA's single entry point. It references all other config files. **Every path MUST be absolute** -- SUMMA Fortran resolves from the executable's CWD. controlVersion MUST be `'SUMMA_FILE_MANAGER_V3.0.0'`. Paths must end with `/` for directories. Always run `validate_file_manager.py` before running SUMMA.

### 2. Decisions -- SUMMA's Unique Feature

Unlike VIC/CaMa-Flood/SWAT+ which have fixed physics, SUMMA lets you choose. 35 decision categories control which equations are solved. Example: `snowLayers jrdn1991` vs `snowLayers CLM_2010` selects different snow layer management algorithms. Some decision names use intentional abbreviations: `itertive` (not `iterative`), `numericl` (not `numerical`).

### 3. Unit Conversions (Silent Error Zone)

| Variable | VIC Unit | SUMMA Unit | Conversion | If wrong |
|----------|----------|------------|------------|----------|
| Precipitation | mm/3hr | kg m-2 s-1 | / 10800 | Runoff 8x wrong |
| Temperature | C | K | + 273.15 | Energy balance fails |
| Pressure | kPa | Pa | * 1000 | ET 100x wrong |

### 4. Fortran Path Truncation

SUMMA uses CHARACTER(256) for file paths. Paths exceeding 256 characters are silently truncated, causing "file not found" or reading the wrong file. Use symlinks for deep directory structures. This is the same trap as DSSAT, VIC routing, and RZWQM2 (cross-model triplet cm_008).

### 5. Spinup Required

Cold-start initial conditions produce 1-2 years of unrealistic output as the model equilibrates. Always add extra years at the start and discard them in analysis. For groundwater-dominated basins, use 3-5 years of spinup.

### 6. HRU ID Consistency

ALL NetCDF files (attributes, forcing, coldState, trialParams) must have identical hruId values in identical order. Regenerating any one file without the others causes immediate crashes.

---

## VIC Coupling

SUMMA can share forcing data with VIC through the `convert_vic_forcing_to_summa.py` tool. This enables head-to-head comparison of VIC vs SUMMA for the same basin, forcing, and period -- isolating the effect of model structure.

**Coupling workflow**:
1. Run HydroCraft VIC workflow (Steps 1-7) as usual
2. After VIC forcing is prepared, run `convert_vic_forcing_to_summa.py`
3. Configure SUMMA domain from the same basin shapefile
4. Run SUMMA with decisions that approximate VIC's physics
5. Compare outputs (runoff, ET, soil moisture)

---

## Diagnostic Triplets Summary

| ID | Stage | Domain | Severity | Description |
|----|-------|--------|----------|-------------|
| dt_001 | s6 | path_resolution | fatal | Missing file in fileManager |
| dt_002 | s6 | path_resolution | fatal | Path exceeds CHARACTER(256) |
| dt_003 | s2 | unit_conversion | **silent** | Precip divisor wrong (8x error) |
| dt_004 | s2 | unit_conversion | fatal | Pressure in kPa not Pa |
| dt_005 | s2 | dependency_mismatch | fatal | HRU ID mismatch forcing/attributes |
| dt_006 | s5 | parameter_format | fatal | Soil layer count mismatch |
| dt_007 | s6 | runtime | fatal | Convergence failure |
| dt_008 | s6 | runtime | fatal | NetCDF dimension error (STOP 20) |
| dt_009 | s3 | parameter_format | fatal | Invalid decision option (STOP 30) |
| dt_010 | s1 | dependency_mismatch | fatal | Inconsistent IDs across files |
| dt_011 | s6 | **silent_error** | silent | All runoff is zero |
| dt_012 | s2 | **silent_error** | silent | ET unrealistically high |
| dt_013 | s6 | runtime | degraded | NaN for some HRUs |
| dt_014 | s4 | **silent_error** | silent | Trial params silently ignored |
| dt_015 | s5 | **silent_error** | silent | Spinup artifacts in output |
| dt_016 | s6 | environment | fatal | Missing shared library |
| dt_017 | s7 | dependency_mismatch | silent | Identical results for different physics |
| dt_018 | s1 | **silent_error** | silent | CRS mismatch -> all HRUs identical |

**5 silent errors** (28%) -- the most dangerous. See `diagnostics/triplets.yaml` for full details.

---

## Installation

### Dependencies
- gfortran (GCC 6+)
- NetCDF-Fortran (libnetcdff-dev)
- LAPACK/BLAS (liblapack-dev)

### Build (Makefile method)
```bash
cd model/summa/build
export F_MASTER=KISSPATH_BINARIES/summa
export FC=gfortran
export FC_EXE=gfortran
export INCLUDES='-I/usr/include'
export LIBRARIES='-L/usr/lib/x86_64-linux-gnu -lnetcdff -llapack -lblas'
make
```

### Verify
```bash
model/summa/bin/summa.exe
# Should print usage information with -m, -s, -r, -p flags
```

---

## Quick Start

```bash
# 1. Create domain
python tools/s1_domain_setup/create_gru_hru.py --basin_shp ... --dem ... --output_dir ...
python tools/s1_domain_setup/create_local_attributes.py --gru_hru_csv ... --output_nc ...

# 2. Convert forcing
python tools/s2_forcing_prep/convert_vic_forcing_to_summa.py --vic_forcing_dir ... --attributes_nc ...

# 3. Configure decisions
python tools/s3_decisions/configure_decisions.py --output ... --use_defaults

# 4. Set parameters
python tools/s4_parameters/set_trial_parameters.py --attributes_nc ... --output_nc ... --parameters '{}'

# 5. Create initial conditions
python tools/s5_initial_conditions/create_initial_conditions.py --attributes_nc ... --output_nc ...

# 6. Run
python tools/s6_execution/create_file_manager.py --settings_path ... --forcing_path ... --output_path ...
python tools/s6_execution/validate_file_manager.py --file_manager ...
python tools/s6_execution/run_summa.py --summa_exe ... --file_manager ...

# 7. Compare physics (optional)
python tools/s7_physics_comparison/compare_physics.py --file_manager ... --summa_exe ... --variations '...'
```

---

*This knowledge infrastructure was built using the knowledge dissection methodology (Zhang et al., Nature, under review).*
*Package: hydrocraft-summa v1.0.0 | 12 tools (~2,826 LOC) | 7 skill documents (~5,158 words) | 18 diagnostic triplets | 7 failure domains*
