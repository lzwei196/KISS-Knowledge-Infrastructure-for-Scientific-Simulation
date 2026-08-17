---
name: cism
description: >-
  CISM 2.1. Covers Ice thickness evolution via mass continuity (incremental remapping /
  upwind transport /…; Ice velocity via shallow-ice (Glide) or higher-order (Glissade:
  Blatter-Pattyn, SSA, L1L2, DIVA)…; Prognostic internal ice temperature / enthalpy
  evolution; Basal sliding/traction and basal hydrology (till water, effective pressure);
  Marine-margin calving and grounding-line dynamics. Use when the task involves running,
  configuring, calibrating or interpreting CISM.
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

# CISM v2.1 (Community Ice Sheet Model) -- Knowledge Infrastructure

**Package**: `hydrocraft-cism-icesheet` v1.0.0
**Model**: CISM v2.1 (Community Ice Sheet Model)
**Domain**: Cryosphere -- land ice dynamics (ice sheets, ice shelves, glaciers)
**Language**: Fortran 90 with CMake build system
**Created by**: Knowledge Dissection Toolkit
**Last updated**: 2026-03-26
**Stats**: 5 tools | 7 skill documents | 20 diagnostic triplets | ~1,500 lines of validated Python
**Validation status**: `synthetic_validated` (dome test case)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for atmospheric forcing documentation.
See `data_ki/SNOTEL/SKILL.md` for snow observations.
See `data_ki/BedMachine/SKILL.md` for ice topography.
See `data_ki/MEaSUREs/SKILL.md` for ice velocity.


## Overview

CISM (Community Ice Sheet Model) is a parallel, thermomechanical ice sheet model developed
by the Land Ice Working Group (LIWG) within the Community Earth System Model (CESM)
framework. It simulates the evolution of ice sheets and ice shelves on timescales of
years to millennia.

**What CISM does**:
- Ice thickness evolution via mass continuity (incremental remapping or upwind transport)
- Ice velocity via Shallow Ice Approximation (SIA) or Higher-Order (HO) dynamics
  - Blatter-Pattyn, SSA, L1L2, DIVA approximations
- Ice temperature / enthalpy evolution (prognostic thermodynamics)
- Basal sliding / traction (Weertman, power-law, yield stress, inversion)
- Calving and marine margin dynamics
- Isostatic adjustment (elastic lithosphere / relaxing asthenosphere)
- Surface mass balance via PDD scheme or external coupling (CESM)
- Ice shelf dynamics (confined, circular, Ross-type benchmarks)
- Basal hydrology (till water, effective pressure)
- Glacial isostatic adjustment

**Dynamical cores**:
- **Glide** (dycore=0): Shallow Ice Approximation (SIA), serial only
- **Glissade** (dycore=2): Higher-order solver, supports MPI parallelism and Trilinos

**Key difference from hydrological models**: CISM operates on glaciological timescales
(years to millions of years) with spatial grids in meters. All velocities are in m/yr,
temperatures in degrees C, and ice thickness in meters. The primary input is surface mass
balance (accumulation minus ablation) rather than precipitation/evaporation.

---

## Installation

### Build from Source

CISM requires: gfortran (or ifort), CMake >= 2.8.4, NetCDF-Fortran, BLAS/LAPACK.
Optional: MPI, Trilinos (for parallel higher-order solvers).

**Serial build (simplest)**:
```bash
cd /path/to/CISM/source/repo
mkdir -p builds/serial && cd builds/serial
cmake \
  -D CISM_USE_TRILINOS:BOOL=OFF \
  -D CISM_MPI_MODE:BOOL=OFF \
  -D CISM_SERIAL_MODE:BOOL=ON \
  -D CISM_BUILD_CISM_DRIVER:BOOL=ON \
  -D CISM_NETCDF_DIR="/usr" \
  -D CISM_NETCDF_LIBS="netcdff" \
  -D CMAKE_Fortran_FLAGS="-g -O2 -ffree-line-length-none -fPIC -fno-range-check" \
  -D CMAKE_Fortran_COMPILER=gfortran \
  -D CMAKE_C_COMPILER=gcc \
  -D CISM_EXTRA_LIBS:STRING="-lblas" \
  ../..
make -j$(nproc)
```

**Binary**: `builds/mpi/cism_driver/cism_driver`

### Dependencies

| Library | Purpose | Required |
|---------|---------|----------|
| gfortran >= 4.8 | Fortran compiler | Yes |
| libnetcdf / libnetcdff | NetCDF I/O | Yes |
| BLAS / LAPACK | Linear algebra | Yes (SLAP fallback) |
| MPI (OpenMPI/MPICH) | Parallel execution | No (serial mode) |
| Trilinos | HO sparse solvers | No (PCG fallback) |
| Python 3 + netCDF4 | Pre/post-processing | For tools only |

### Test example

```
tests/dome/               # Parabolic dome benchmark
  dome.config              # Configuration file (Glissade, Picard)
  dome.py                  # Input generator (creates dome.nc)
  dome.nc                  # NetCDF input (topography, thickness)
  dome.out.nc              # Output after run
```

**Validated**: dome test case runs with SIA (Glide) and HO (Glissade) dynamics.

---

## Pipeline (8 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | (manual) | Select domain, grid, time period, dycore, forcing |
| 1 | Input generation | `generate_input_nc.py` | Create NetCDF input (topography, initial thickness, SMB) |
| 2 | Forcing preparation | `convert_forcing_to_cism.py` | Convert climate data to CISM surface mass balance / artm |
| 3 | Config generation | `generate_cism_config.py` | Write .config file with all namelist sections |
| 4 | Execution | `run_cism.py` | Build (if needed) and run cism_driver |
| 5 | Output parsing | `parse_cism_output.py` | Extract time series and spatial fields from NetCDF |
| 6 | Visualization | (matplotlib) | Plot ice thickness, velocity, temperature evolution |
| 7 | Validation | (metrics) | Compare against analytical solutions or observations |

### Parallelism

Stages 1 and 2 can run in parallel after stage 0.
Stage 3 depends on 1 and 2 (needs input file paths and forcing paths).
Stage 4 depends on 3 (needs config file).
Stages 5, 6, 7 depend on 4 (need output).

---

## Configuration File Format (.config)

CISM uses INI-style configuration files. Key sections:

### [grid]
```ini
upn = 11          # Vertical sigma levels (surface=0, base=1)
ewn = 31          # East-west grid points
nsn = 31          # North-south grid points
dew = 2000.0      # E-W grid spacing (meters)
dns = 2000.0      # N-S grid spacing (meters)
```

### [time]
```ini
tstart = 0.       # Start time (years)
tend = 200000.    # End time (years)
dt = 1.0          # Dynamic timestep (years)
dt_diag = 1.0     # Diagnostic interval (years)
ntem = 1          # Thermal subcycles per dt
ndiag = 1         # Steps between diagnostic output
```

### [options]
```ini
dycore = 0            # 0=Glide(SIA), 2=Glissade(HO)
temperature = 1       # 0=surface artm, 1=prognostic, 2=hold initial
flow_law = 0          # 0=constant flwa, 2=Paterson-Budd
evolution = 3         # 0=pseudo-diffusion, 3=inc. remap, 4=FO upwind
marine_margin = 3     # 0=none, 3=threshold calving
basal_water = 0       # 0=off, 1=local balance
isostasy = 0          # 0=off, 1=on
```

### [ho_options] (when dycore=2)
```ini
which_ho_approx = 2       # -1=local SIA, 1=SSA, 2=BP, 3=L1L2, 4=DIVA
which_ho_babc = 4         # 4=no-slip, 5=beta from input, 15=till yield stress
which_ho_efvs = 2         # 2=nonlinear Glen n=3
which_ho_sparse = 3       # 1=SLAP, 3=Glissade PCG, 4=Trilinos
which_ho_nonlinear = 0    # 0=Picard, 1=JFNK
glissade_maxiter = 300    # Max Picard iterations
```

### [parameters]
```ini
default_flwa = 1.0e-16    # Flow rate factor (Pa^-n s^-1)
ice_limit = 1.0           # Minimum ice thickness for dynamics (m)
geothermal = -42.0e-3     # Geothermal heat flux (W/m^2, NEGATIVE = upward)
beta_grounded_min = 0.0   # Min basal traction coefficient
flow_enhancement_factor = 1.0  # Multiplier on flow rate factor
```

### [CF input]
```ini
name = input.nc           # NetCDF input file path
time = 1                  # Time slice to read
```

### [CF output]
```ini
name = output.nc
frequency = 1000          # Output every N timesteps
variables = thk usurf topg uvel vvel temp acab bmlt velnorm
xtype = double
```

---

## Tools Reference

| Tool | Stage | Script Path | Purpose |
|------|-------|-------------|---------|
| `generate_input_nc` | s1 | `tools/generate_input_nc.py` | Create NetCDF input (topg, thk, beta, artm, acab) |
| `convert_forcing_to_cism` | s2 | `tools/convert_forcing_to_cism.py` | Climate forcing to SMB/artm fields |
| `generate_cism_config` | s3 | `tools/generate_cism_config.py` | Assemble .config file from parameters |
| `run_cism` | s4 | `tools/run_cism.py` | Execute cism_driver with preflight checks |
| `parse_cism_output` | s5 | `tools/parse_cism_output.py` | Extract results to CSV from NetCDF output |

---

## Critical Domain Knowledge (Unit Traps)

These are non-obvious facts that cause **silent failures** if ignored:

| ID | Trap | Root Cause | Remedy |
|----|------|-----------|--------|
| dt_001 | Ice grows unbounded | SMB in mm/yr instead of m/yr | Divide by 1000; CISM expects meters/year |
| dt_002 | No ice dynamics | `default_flwa` too small (e.g., 1e-25) | Use 1e-16 to 1e-17 Pa^-n s^-1 |
| dt_003 | Geothermal backwards | Positive geothermal value | CISM convention: negative = upward heat flux |
| dt_004 | Temperature blows up | dt too large for grid spacing | CFL: dt < dew^2 / (2 * D_max); reduce dt |
| dt_005 | Zero velocity everywhere | dycore=2 with which_ho_sparse=4 but no Trilinos | Set which_ho_sparse=3 (Glissade PCG) |
| dt_006 | Wrong velocity pattern | Grid spacing in km instead of m | dew/dns must be in meters |
| dt_007 | Ice sheet too thin | evolution=0 with Glissade | Use evolution=3 (inc. remap) or 4 (upwind) |
| dt_008 | Basal melt too high | bmlt in m/s instead of m/yr | Apply factor scyr=31536000 s/yr |
| dt_009 | Output file empty | frequency > total timesteps | Set frequency <= (tend-tstart)/dt |
| dt_010 | Solver diverges | which_ho_nonlinear=1 (JFNK) without precond | Use which_ho_nonlinear=0 (Picard) first |
| dt_011 | Temperature all zero | temperature=0 sets T=artm every step | Use temperature=1 for prognostic |
| dt_012 | Ice floats but shouldn't | topg > 0 but marine_margin active | Check bed topography sign (negative = below SL) |
| dt_013 | Velocity m/s vs m/yr | Internal SI (m/s) vs output (m/yr) | Output uses factor=scyr; input expects m/yr |
| dt_014 | Config section ignored | Section name misspelled | Must match exactly: [grid], [time], [options], etc. |
| dt_015 | No calving | marine_margin=0 | Set marine_margin=3 for threshold calving |

---

## Input/Output Variable Reference

### Input Variables (NetCDF)

| Variable | Dimensions | Units | Description |
|----------|-----------|-------|-------------|
| `topg` | (y1, x1) | m | Bedrock topography (negative below sea level) |
| `thk` | (y1, x1) | m | Initial ice thickness |
| `artm` | (y1, x1) | deg C | Annual mean surface air temperature |
| `acab` | (y1, x1) | m/yr | Surface mass balance (accumulation - ablation) |
| `beta` | (y0, x0) | Pa yr/m | Basal traction coefficient (staggered grid) |
| `bheatflx` | (y1, x1) | W/m^2 | Basal heat flux (negative = upward) |
| `uvel` | (level, y0, x0) | m/yr | x-velocity (for restart) |
| `vvel` | (level, y0, x0) | m/yr | y-velocity (for restart) |
| `kinbcmask` | (y0, x0) | 0/1 | Velocity boundary condition mask |

### Output Variables (NetCDF)

| Variable | Dimensions | Units | Description |
|----------|-----------|-------|-------------|
| `thk` | (time, y1, x1) | m | Ice thickness |
| `usurf` | (time, y1, x1) | m | Upper ice surface elevation |
| `topg` | (time, y1, x1) | m | Bedrock topography |
| `uvel` | (time, level, y0, x0) | m/yr | x-velocity |
| `vvel` | (time, level, y0, x0) | m/yr | y-velocity |
| `velnorm` | (time, level, y0, x0) | m/yr | Velocity magnitude |
| `temp` | (time, level, y1, x1) | deg C | Ice temperature |
| `btemp` | (time, y1, x1) | deg C | Basal temperature |
| `acab` | (time, y1, x1) | m/yr | Surface mass balance |
| `bmlt` | (time, y1, x1) | m/yr | Basal melt rate |
| `iarea` | (time) | km^2 | Total ice area |
| `imass` | (time) | kg | Total ice mass |
| `ivol` | (time) | km^3 | Total ice volume |

### Grid Dimensions

| Dimension | Description |
|-----------|-------------|
| `x1`, `y1` | Scalar grid (ewn x nsn) |
| `x0`, `y0` | Velocity/staggered grid (ewn-1 x nsn-1) |
| `level` | Sigma levels (0=surface, 1=base), `upn` points |
| `staglevel` | Staggered sigma levels, `upn-1` points |
| `time` | Unlimited time dimension |

---

## Calibration Parameters

Priority order for calibration (highest impact first):

| # | Parameter | Section | Range | Default | Effect |
|---|-----------|---------|-------|---------|--------|
| 1 | `default_flwa` | [parameters] | 1e-18 to 1e-15 | 1e-16 | Ice softness / flow rate |
| 2 | `flow_enhancement_factor` | [parameters] | 0.5 to 5.0 | 1.0 | Multiplier on flwa |
| 3 | `geothermal` | [parameters] | -100e-3 to -20e-3 | -42e-3 | Basal heating (W/m^2) |
| 4 | `btrac_const` | [parameters] | 0 to 1e6 | 0.0 | Basal friction (Pa yr/m) |
| 5 | `acab` (field) | [CF input] | -10 to +10 | varies | Surface mass balance (m/yr) |
| 6 | `dt` | [time] | 0.01 to 10 | 1.0 | Timestep (years) |
| 7 | `ice_limit` | [parameters] | 0.1 to 100 | 1.0 | Min thickness for dynamics |
| 8 | `which_ho_approx` | [ho_options] | 1,2,3,4 | 2 | Velocity approximation |

---

## Test Cases (Built-in)

| Test | Directory | Dycore | Purpose |
|------|-----------|--------|---------|
| Dome | `tests/dome/` | Glide/Glissade | Parabolic dome, thermodynamic coupling |
| Halfar | `tests/halfar/` | Glide | Analytical solution for SIA |
| ISMIP-HOM | `tests/ismip-hom/` | Glissade | Higher-order intercomparison |
| Shelf-confined | `tests/shelf/` | Glissade | Ice shelf (SSA/BP) |
| Shelf-circular | `tests/shelf/` | Glissade | Circular ice shelf |
| Ross | `tests/ross/` | Glissade | Ross Ice Shelf benchmark |
| Stream | `tests/stream/` | Glissade | Ice stream with yield stress |
| Slab | `tests/slab/` | Glissade | Inclined slab (DIVA) |
| EISMINT-1 | `tests/EISMINT/` | Glide | Moving-margin experiments |
| EISMINT-2 | `tests/EISMINT/` | Glide/Glissade | Fixed-margin thermodynamic |

---

## Quick Start

```bash
# 1. Build CISM (serial)
cd source/repo && mkdir -p builds/serial && cd builds/serial
cmake -DCISM_SERIAL_MODE=ON -DCISM_MPI_MODE=OFF \
      -DCISM_BUILD_CISM_DRIVER=ON -DCISM_NETCDF_DIR=/usr \
      -DCMAKE_Fortran_FLAGS="-g -O2 -ffree-line-length-none -fPIC -fno-range-check" \
      -DCMAKE_Fortran_COMPILER=gfortran -DCMAKE_C_COMPILER=gcc \
      -DCISM_USE_TRILINOS=OFF -DCISM_EXTRA_LIBS="-lblas" ../..
make -j$(nproc)

# 2. Generate dome test input
cd ../../tests/dome
python3 dome.py   # Creates dome.nc

# 3. Run CISM
../../builds/mpi/cism_driver/cism_driver dome.config

# 4. Parse output
python3 ../../ki/tools/parse_cism_output.py --input dome.out.nc --output dome_results.csv
```

---

## Diagnostic Triplets Summary

| ID | Symptom | Severity |
|----|---------|----------|
| dt_001 | Unbounded ice growth | silent |
| dt_002 | No ice dynamics (zero velocity) | silent |
| dt_003 | Basal temperature wrong sign | silent |
| dt_004 | Temperature instability | fatal |
| dt_005 | Solver crashes (no Trilinos) | fatal |
| dt_006 | Wrong velocity magnitude | silent |
| dt_007 | Ice too thin with Glissade | silent |
| dt_008 | Excessive basal melt | silent |
| dt_009 | Empty output file | silent |
| dt_010 | Nonlinear solver diverges | fatal |
| dt_011 | Temperature all zero | silent |
| dt_012 | Floating ice on land | silent |
| dt_013 | Velocity units confusion | silent |
| dt_014 | Config section silently ignored | silent |
| dt_015 | No calving at marine margins | silent |
| dt_016 | Grid spacing in wrong units | silent |
| dt_017 | sigma levels not monotonic | fatal |
| dt_018 | Input time slice out of range | fatal |
| dt_019 | Restart file missing fields | fatal |
| dt_020 | NetCDF dimension mismatch | fatal |

**Silent errors**: 12/20 (60%) -- model runs but produces incorrect results.

---

## File Structure

```
ki/
|-- SKILL.md                          # This file
|-- tools/
|   |-- generate_input_nc.py          # Create NetCDF input files
|   |-- convert_forcing_to_cism.py    # Climate data to CISM forcing
|   |-- generate_cism_config.py       # Write .config files
|   |-- run_cism.py                   # Execute cism_driver
|   |-- parse_cism_output.py          # Extract output to CSV
|-- docs/
|   |-- s0_configuration.md           # Configuration skill
|   |-- s1_input_generation.md        # Input generation skill
|   |-- s2_forcing_preparation.md     # Forcing conversion skill
|   |-- s3_config_generation.md       # Config file assembly skill
|   |-- s4_execution.md               # Model execution skill
|   |-- s5_output_parsing.md          # Output analysis skill
|   |-- s6_validation.md              # Validation and metrics skill
|-- diagnostics/
|   |-- triplets.yaml                 # 20 diagnostic triplets
```
