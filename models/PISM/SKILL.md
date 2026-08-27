> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model.
>
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

<!-- KI-MAP:BEGIN (projected by generate_skill_map.py — edit the KI, not this table) -->
## KI map — what to read, and when

| when you need | read | why |
|---|---|---|
| FIRST, always | `preflight_check.py` | run it (`python preflight_check.py`): proves env/binary/data are usable and emits a machine-readable `PREFLIGHT_REPORT=` line. Do not debug a run that never had a healthy environment. |
| to run the pipeline stages | `tools/` (4 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (7 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (24 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (28 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/convert_climate_forcing.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_climate_forcing.py --help` |
| `tools/convert_geometry.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_geometry.py --help` |
| `tools/parse_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_output.py --help` |
| `tools/run_pism.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_pism.py --help` |

*4 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# PISM — Parallel Ice Sheet Model: Knowledge Infrastructure

## Overview

PISM (Parallel Ice Sheet Model) is an open-source, parallel, high-resolution ice sheet model
written in C++ with MPI parallelism via PETSc. It simulates ice sheet and glacier dynamics
using a hierarchy of stress balance approximations (SIA, SSA, Blatter), polythermal enthalpy-based
thermodynamics, subglacial hydrology, marine ice sheet physics with dynamic calving fronts,
and extensible coupling to atmospheric and ocean models. PISM uses CF-compliant NetCDF files
for all input and output. It is jointly developed at the University of Alaska Fairbanks (UAF)
and the Potsdam Institute for Climate Impact Research (PIK).

**Domain**: Cryosphere (ice sheets, glaciers, ice shelves)
**Language**: C++ (with Python utilities and optional Python bindings)
**Build System**: CMake
**Parallelism**: MPI via PETSc
**I/O Format**: NetCDF (CF-compliant)
**License**: GPL-3.0

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for atmospheric forcing documentation.
See `data_ki/SNOTEL/SKILL.md` for snow observations.
See `data_ki/BedMachine/SKILL.md` for ice topography.
See `data_ki/MEaSUREs/SKILL.md` for ice velocity.


## Installation

### Required Dependencies

| Dependency | Minimum Version | Purpose |
|-----------|----------------|---------|
| CMake | 3.20 | Build system |
| C++11 compiler | GCC 9+ / Clang 14+ | Compilation |
| MPI | Any (OpenMPI, MPICH) | Parallel communication |
| PETSc | 3.15+ | Parallel linear algebra |
| NetCDF | 4.7+ | Data I/O |
| GSL | 1.15+ | Scientific computing |
| FFTW3 | 3.1+ | Fourier transforms (bed deformation) |
| UDUNITS2 | Any | Unit conversion |

### Optional Dependencies

| Dependency | Purpose | CMake Flag |
|-----------|---------|------------|
| PROJ 6.0+ | Coordinate transformations | `-DPism_USE_PROJ=ON` |
| PnetCDF | Parallel NetCDF-3 I/O | `-DPism_USE_PNETCDF=ON` |
| YAC 3.4+ | Interpolation / async output | `-DPism_USE_YAC=ON` |
| Python3 + SWIG | Python bindings | `-DPism_BUILD_PYTHON_BINDINGS=ON` |
| PETSc4Py | Python PETSc interface | Required if Python bindings |

### Build Steps (Ubuntu/Debian)

```bash
# Install system dependencies
sudo apt-get install -y build-essential cmake git \
  libfftw3-dev libgsl-dev libnetcdf-dev libudunits2-dev \
  libopenmpi-dev petsc-dev libproj-dev nco netcdf-bin \
  python3-netcdf4 python3-numpy python3-scipy python3-matplotlib

# Set PETSc environment
export PETSC_DIR="/usr/lib/petsc"

# Build PISM
cd /path/to/pism
mkdir build && cd build
cmake -DCMAKE_INSTALL_PREFIX=$HOME/pism \
      -DPism_USE_PROJ=ON \
      ..
make -j$(nproc)
make install

# Verify
$HOME/pism/bin/pism -help
```

### Quick Smoke Test

```bash
# EISMINT II Experiment A (no input data needed)
mpiexec -n 4 pism -eisII A -Mx 61 -My 61 -Mz 61 -Lz 5000 -y 1000 -o test_eisII_A.nc
```

---

## Pipeline Stages

The PISM modeling pipeline has 9 stages from data acquisition to post-processing:

```
S1: Domain Setup           → Define grid, projection, domain extent
        │
S2: Input Preparation      → Bootstrap file with geometry + climate
        │
S3: Climate Forcing        → Atmospheric forcing (temp, precip)
        │
S4: Ocean Forcing          → Ocean boundary conditions (melt, temp)
        │
S5: Configuration          → pism_config overrides, physics choices
        │
S6: Spinup                 → Long equilibrium run (10k–200k years)
        │
S7: Transient Run          → Forward simulation with time-varying forcing
        │
S8: Diagnostics            → Extract scalar/spatial time series
        │
S9: Post-Processing        → Visualization, comparison, validation
```

### Stage Dependencies

- S3 and S4 can run in parallel (independent forcing preparation)
- S6 requires S1–S5 complete
- S7 uses S6 output as initial state
- S8–S9 run after S7

---

## Critical Input Variables (NetCDF Bootstrap File)

| Variable | Standard Name | Units | Description |
|----------|--------------|-------|-------------|
| `topg` | bedrock_altitude | m | Bedrock surface elevation |
| `thk` | land_ice_thickness | m | Ice thickness |
| `ice_surface_temp` | — | kelvin or degC | Near-surface air temperature |
| `precipitation` | — | kg m^-2 year^-1 | Mean annual precipitation |
| `climatic_mass_balance` | land_ice_surface_specific_mass_balance_flux | kg m^-2 year^-1 | Surface mass balance |
| `bheatflx` | — | W m^-2 | Basal (geothermal) heat flux |
| `longitude` | longitude | degrees_east | Longitude |
| `latitude` | latitude | degrees_north | Latitude |

### Optional Input Variables

| Variable | Units | Description |
|----------|-------|-------------|
| `land_ice_area_fraction_retreat` | 1 | Mask for ice extent limitation |
| `tillwat` | m | Till water layer thickness |
| `enthalpy` | J kg^-1 | Ice enthalpy (3D field) |
| `bc_mask` | 1 | Dirichlet BC mask for SSA |
| `u_bc`, `v_bc` | m s^-1 | Prescribed SSA velocities |

---

## Key Output Variables

### Spatial Diagnostics (2D/3D fields)

| Variable | Units | Description |
|----------|-------|-------------|
| `thk` | m | Ice thickness |
| `usurf` | m | Ice surface elevation |
| `topg` | m | Bed topography (may deform) |
| `velsurf_mag` | m year^-1 | Surface ice speed |
| `velbase_mag` | m year^-1 | Basal sliding speed |
| `mask` | — | Cell type (grounded, floating, ocean) |
| `tauc` | Pa | Basal yield stress |
| `tillwat` | m | Till water thickness |
| `bmelt` | m year^-1 | Basal melt rate |
| `diffusivity` | m^2 s^-1 | SIA diffusivity |
| `temppabase` | K | Pressure-adjusted basal temperature |

### Scalar Diagnostics (time series)

| Variable | Units | Description |
|----------|-------|-------------|
| `ice_volume_glacierized` | m^3 | Total ice volume |
| `ice_area_glacierized` | m^2 | Total ice-covered area |
| `ice_mass` | kg | Total ice mass |
| `max_hor_vel` | m year^-1 | Maximum horizontal velocity |
| `dt` | year | Adaptive time step |
| `tendency_of_ice_mass` | Gt year^-1 | Ice mass change rate |
| `tendency_of_ice_mass_due_to_discharge` | Gt year^-1 | Calving + frontal melt |

---

## 6. Output Description

This section restates `dag.yaml`. If this section and `dag.yaml` disagree, `dag.yaml` wins.

**Headline output** (dag `validation_rank: 1`):

> `velsurf_mag` -- Surface ice speed magnitude (`m year-1`)

| Output variable (dag `var`) | Rank | Unit | Description |
|-----------------------------|------|------|-------------|
| `velsurf_mag` | 1 | `m year-1` | Surface ice speed magnitude |
| `thk` | not stated in extracted facts | not stated in extracted facts | not stated in extracted facts |
| `usurf` | not stated in extracted facts | not stated in extracted facts | not stated in extracted facts |
| `velbase_mag` | not stated in extracted facts | not stated in extracted facts | not stated in extracted facts |
| `mask` | not stated in extracted facts | not stated in extracted facts | not stated in extracted facts |
| `ice_volume_glacierized` | not stated in extracted facts | not stated in extracted facts | not stated in extracted facts |
| `tendency_of_ice_mass` | not stated in extracted facts | not stated in extracted facts | not stated in extracted facts |
| `tendency_of_ice_mass_due_to_discharge` | not stated in extracted facts | not stated in extracted facts | not stated in extracted facts |
| `tillwat` | not stated in extracted facts | not stated in extracted facts | not stated in extracted facts |
| `temppabase` | not stated in extracted facts | not stated in extracted facts | not stated in extracted facts |

Other dag outputs: `thk`, `usurf`, `velbase_mag`, `mask`, `ice_volume_glacierized`,
`tendency_of_ice_mass`, `tendency_of_ice_mass_due_to_discharge`, `tillwat`, `temppabase`.

---

## Execution Model

PISM is run from the command line with MPI:

```bash
mpiexec -n <NPROCS> pism [options]
```

### Run Modes

| Mode | Flag | Description |
|------|------|-------------|
| Bootstrap | `-i FILE -bootstrap` | Initialize from incomplete data |
| Restart | `-i FILE` | Continue from full PISM output |
| EISMINT II | `-eisII <EXP>` | Synthetic experiments A–L |
| Verification | `-test <CODE>` | Analytical tests A–V |
| Regional | `-regional` | Outlet glacier modeling |

### Key Command-Line Options

```bash
# Grid
-Mx 301 -My 561              # Horizontal grid points
-Mz 201 -Lz 4000             # Vertical layers, domain height (m)
-dx 5km -dy 5km              # Grid spacing with units

# Time
-ys -125000 -ye 0            # Start/end year
-y 10000                     # Run length

# Physics
-stress_balance ssa+sia       # Stress balance choice
-sia_e 3.0                    # SIA enhancement factor
-pseudo_plastic               # Pseudo-plastic sliding
-pseudo_plastic_q 0.25        # Sliding exponent
-topg_to_phi ...              # Till friction angle parameterization
-bed_def lc                   # Lingle-Clark bed deformation
-pik                          # PIK physics extensions
-subgl                        # Sub-grid grounding line

# Atmosphere/Surface
-atmosphere given              # Read forcing from file
-atmosphere_given_file F.nc    # Forcing file
-surface pdd                   # Positive degree-day scheme
-surface given                 # Directly prescribe SMB

# Ocean
-ocean constant                # Constant ocean forcing
-ocean pico                    # PICO ocean model

# Output
-o output.nc                   # Main output file
-spatial_file spatial.nc       # Spatial diagnostics
-spatial_times 0:100:10000     # Output times (start:step:end)
-spatial_vars thk,usurf,...    # Variables to save
-scalar_file scalar.nc         # Scalar time series
-scalar_times 0:1:10000        # Scalar output frequency
```

### Configuration Override

Override any parameter from `pism_config.cdl` via the command line:

```bash
-constants.ice.density 917          # Override ice density
-ocean.constant.melt_rate 10        # Set melt rate (m/year)
```

Or create a NetCDF override file:

```bash
ncgen -o my_config.nc my_config.cdl
pism -config_override my_config.nc ...
```

---

## 8. Unit Conversion Table

This table records the unit conversions already called out by this KI for PISM input and forcing
preparation. Verify source data attributes before each run; do not rely on filename or dataset
memory when deciding whether a conversion applies.

| Variable | Source unit / common source unit | Model unit | Conversion | Type |
|----------|----------------------------------|------------|------------|------|
| `precipitation` | `m w.e. year^-1` | `kg m^-2 year^-1` | x 1000 (water density) | multiplicative |
| `climatic_mass_balance` | `m w.e. year^-1` | `kg m^-2 year^-1` | x 1000 | multiplicative |
| `ice_surface_temp` | degC | kelvin | + 273.15 | additive |
| `bheatflx` | `mW m^-2` | `W m^-2` | x 0.001 | multiplicative |
| `topg` | cm or mm | m above sea level | / 100 or / 1000 | multiplicative |
| `thk` | km | m | x 1000 | multiplicative |
| `air_temp` | degC | kelvin | + 273.15 | additive |
| `delta_T` | degC anomaly | kelvin anomaly | no conversion needed; both are relative | identity |
| ocean melt rate | `m day^-1` | `m year^-1` | x 365.25 | multiplicative |
| time coordinate | various calendars / time units | UDUNITS-compatible time string | use a UDUNITS-compatible string | format |
| projection coordinates | km | m | x 1000 | multiplicative |

---

## Unit Trap Table

These are the most dangerous unit conversion errors when preparing PISM input data.

| Variable | PISM Expects | Common Source Units | Conversion | Trap Severity |
|----------|-------------|-------------------|------------|---------------|
| `precipitation` | kg m^-2 year^-1 | m w.e. year^-1 | × 1000 (water density) | **FATAL** — 1000× error |
| `climatic_mass_balance` | kg m^-2 year^-1 | m w.e. year^-1 | × 1000 | **FATAL** — 1000× error |
| `ice_surface_temp` | kelvin | °C | + 273.15 | **FATAL** — negative values crash |
| `bheatflx` | W m^-2 | mW m^-2 | × 0.001 | **SILENT** — 1000× too high |
| `topg` | m (above sea level) | cm or mm | ÷ 100 or ÷ 1000 | **SILENT** — unrealistic geometry |
| `thk` | m | km | × 1000 | **FATAL** — CFL violation |
| `air_temp` (forcing) | kelvin | °C | + 273.15 | **FATAL** — no ice forms |
| `delta_T` (anomaly) | kelvin | °C | No conversion needed (both relative) | **TRAP** — easy to double-convert |
| `ocean melt rate` | m year^-1 | m day^-1 | × 365.25 | **SILENT** — extreme melt |
| Time coordinate | depends on calendar | various | Use UDUNITS-compatible string | **FATAL** — wrong forcing timing |
| Projection coordinates | m | km | × 1000 | **FATAL** — grid mismatch |

---

## Tools Reference

| Tool | Stage | Purpose |
|------|-------|---------|
| `convert_climate_forcing.py` | S3 | Convert global reanalysis data to PISM climate forcing format |
| `convert_geometry.py` | S2 | Convert ice geometry data (BedMachine, SeaRISE) to PISM bootstrap format |
| `run_pism.py` | S6/S7 | Execute PISM with validated configuration |
| `parse_output.py` | S8/S9 | Extract PISM output to CSV for analysis |

---

## Calibration Parameters (by sensitivity)

| Parameter | Option | Default | Typical Range | Sensitivity |
|-----------|--------|---------|--------------|-------------|
| SIA enhancement factor | `-sia_e` | 3.0 | 1.0–5.0 | **HIGH** |
| SSA enhancement factor | `-ssa_e` | 1.0 | 0.5–1.5 | **HIGH** |
| Pseudo-plastic sliding q | `-pseudo_plastic_q` | 0.25 | 0.1–1.0 | **HIGH** |
| Till effective fraction overburden | `-till_effective_fraction_overburden` | 0.02 | 0.01–0.05 | **MEDIUM** |
| Till friction angle φ | `-topg_to_phi` | 15,40,-300,700 | Varies | **HIGH** |
| PDD factor for ice | config | 0.008 m/°C/day | 0.005–0.015 | **HIGH** |
| PDD factor for snow | config | 0.003 m/°C/day | 0.001–0.006 | **MEDIUM** |
| Ocean melt rate | `-ocean.constant.melt_rate` | 0 m/year | 0–50 | **HIGH** (marine) |
| Geothermal heat flux | input field | ~50 mW/m² | 40–100 | **LOW** |

---

## Examples Included in Repository

| Example | Directory | Complexity | Data Required |
|---------|-----------|-----------|---------------|
| EISMINT II | `examples/eismintII/` | Low | None (synthetic) |
| Standard Greenland | `examples/std-greenland/` | Medium | SeaRISE 5km dataset |
| Ross Ice Shelf | `examples/ross/` | Medium | ALBMAP dataset |
| Jakobshavn | `examples/jako/` | High | SeaRISE + regional |
| MISMIP | `examples/mismip/` | Low | None (synthetic) |
| Storglaciären | `examples/storglaciaren/` | Low | Included CDL |
| Antarctica | `examples/antarctica/` | High | ALBMAP + climate data |

---

## File Structure

```
ki/
├── SKILL.md                          ← This file (agent entry point)
├── tools/
│   ├── convert_climate_forcing.py    ← Reanalysis → PISM forcing
│   ├── convert_geometry.py           ← Geometry data → bootstrap file
│   ├── run_pism.py                   ← Execution wrapper
│   └── parse_output.py              ← Output extraction to CSV
├── docs/
│   ├── s1_domain_setup.md           ← Grid and projection setup
│   ├── s2_input_preparation.md      ← Bootstrap file creation
│   ├── s3_climate_forcing.md        ← Atmospheric forcing preparation
│   ├── s4_ocean_forcing.md          ← Ocean boundary conditions
│   ├── s5_configuration.md          ← Physics and solver configuration
│   ├── s6_spinup.md                 ← Equilibrium spinup procedure
│   └── s7_transient_run.md          ← Forward simulation
├── diagnostics/
│   └── triplets.yaml                ← Symptom → diagnosis → remedy
└── workflow/
    └── (pipeline orchestration)
```

---

## Quick Start: EISMINT II Experiment A

```bash
# No input data needed — fully synthetic
mpiexec -n 4 pism -eisII A \
  -Mx 61 -My 61 -Mz 61 -Lz 5000 \
  -y 200000 \
  -skip -skip_max 5 \
  -o eisIIA.nc \
  -scalar_file scalar_eisIIA.nc \
  -scalar_times 0:100:200000 \
  -spatial_file spatial_eisIIA.nc \
  -spatial_times 1000:1000:200000 \
  -spatial_vars thk,temppabase,velsurf_mag,bmelt
```

## Quick Start: Standard Greenland

```bash
# Step 1: Preprocess SeaRISE data
cd examples/std-greenland
./preprocess.sh

# Step 2: Run 1000-year constant-climate spinup at 20km
./spinup.sh 8 const 1000 20 sia
```

---

## Diagnostic Triplets Summary

| ID | Failure Domain | Symptom | Severity |
|----|---------------|---------|----------|
| dt_001 | unit_conversion | Precipitation 1000× too high | fatal |
| dt_002 | unit_conversion | Temperature in °C not K | fatal |
| dt_003 | unit_conversion | Geothermal heat flux in mW not W | silent |
| dt_004 | parameter_format | Missing projection info | degraded |
| dt_005 | unit_conversion | SMB in m w.e. not kg m^-2 | fatal |
| dt_006 | runtime | CFL violation / tiny timestep | fatal |
| dt_007 | silent_error | No ice forms in simulation | silent |
| dt_008 | dependency | PETSc version mismatch | fatal |
| dt_009 | parameter_format | Wrong calendar in forcing | silent |
| dt_010 | runtime | SSA solver divergence | fatal |
| dt_011 | unit_conversion | Ocean melt rate units wrong | silent |
| dt_012 | silent_error | Bed deformation not enabled | silent |
| dt_013 | parameter_format | Grid registration mismatch | degraded |
| dt_014 | runtime | Memory exhaustion | fatal |
| dt_015 | unit_conversion | Coordinate units km not m | fatal |
| dt_016 | silent_error | Ice-free SMB not set | silent |
| dt_017 | dependency | NetCDF version incompatible | fatal |

---

## 11. Validated Results

No achieved calibration, validation, or full-period metric values are stated in the extracted
sourced facts for this update. Use the convention bars below to judge runs only after real PISM
outputs have been produced and compared to observations.

### Performance Metrics -- Convention Bars

`docs/validation_convention.yaml` is the source of the field bars. The convention wins over
remembered thresholds.

| Dag variable | Metric | Direction | Convention bar, cited |
|--------------|--------|-----------|-----------------------|
| `thk` | `rmse` | minimize | very_good <= 59 (`bedmap2_2013`); good <= 149 (`bedmap2_2013`); satisfactory <= 300 (`bedmap2_2013`) |
| `thk` | `nse` | maximize | satisfactory: no cited threshold |
| `usurf` | `rmse` | minimize | very_good <= 30 (`bedmap2_2013`); good <= 30 (`bedmap2_2013`); satisfactory <= 130 (`bedmap2_2013`) |

### Data Replacement Tracking

| Component | Source | Status | Notes |
|-----------|--------|--------|-------|
| Forcing | Pipeline | Pending | Validate with actual PISM runs and observations before reporting achieved metrics. |
| Geometry / thickness (`thk`) | Pipeline | Pending | Judge `rmse` against the cited `thk` convention bars above. |
| Surface elevation (`usurf`) | Pipeline | Pending | Judge `rmse` against the cited `usurf` convention bars above. |
| Surface speed (`velsurf_mag`) | Pipeline | Pending | Rank-1 dag output; no convention bar was included in the extracted facts for this update. |
