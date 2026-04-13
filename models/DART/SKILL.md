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

# DART — Data Assimilation Research Testbed

**Package**: DART Knowledge Infrastructure
**Model**: DART (Data Assimilation Research Testbed)
**Version**: Manhattan Release
**Domain**: Ensemble Data Assimilation
**Language**: Fortran 90+ with NetCDF I/O
**Created by**: auto_dissect pipeline
**Tools**: 4 | **Docs**: 5 | **Diagnostics**: 20 | **Lines**: ~3000
**Validation**: Lorenz 63 OSSE

---

## Overview

DART is an open-source community facility for ensemble data assimilation (DA)
developed by the Data Assimilation Research Section (DAReS) at NSF NCAR.
It provides a modular, flexible framework for combining observations with
numerical models to estimate the state of physical systems.

DART supports 50+ models spanning atmosphere, ocean, land, ice, and idealized
dynamical systems. It implements multiple assimilation algorithms including
the Ensemble Adjustment Kalman Filter (EAKF), Ensemble Kalman Filter (EnKF),
and the Quantile-Conserving Ensemble Filtering Framework (QCEFF) for
non-Gaussian distributions.

Key capabilities include:
- Generating initial conditions for forecasts
- Producing reanalyses (retrospective state estimates)
- Conducting observing system experiments (OSEs)
- Conducting observing system simulation experiments (OSSEs)
- Diagnosing model error and observation impact

DART reads observations from obs_seq files (ASCII or binary), state vectors
from NetCDF, and configuration from Fortran namelists (input.nml). All
output is NetCDF (state diagnostics) or obs_seq format (observation diagnostics).

---

## Installation

### Dependencies

| Dependency | Purpose | Required |
|---|---|---|
| gfortran >= 9 or Intel ifort | Fortran compiler | Yes |
| NetCDF-Fortran + NetCDF-C | I/O for state files | Yes |
| MPI (mpif90) | Parallel execution | Optional (for large models) |
| Perl | mkmf build tool | Yes |
| Make | Build system | Yes |
| Python 3 | pytools, diagnostics | Optional |
| MATLAB | Traditional diagnostics | Optional |
| NCO (ncdump, ncview) | NetCDF inspection | Optional |

### Build Steps

```bash
# 1. Clone repository
git clone https://github.com/NCAR/DART.git

# 2. Configure compiler template
cd DART/build_templates
cp mkmf.template.gfortran mkmf.template
# Edit mkmf.template: set NETCDF path, compiler flags

# 3. Build the simplest model (Lorenz 63)
cd ../models/lorenz_63/work
./quickbuild.sh nompi

# 4. Quick validation
./perfect_model_obs    # generates obs_seq.out
./filter               # runs ensemble assimilation
```

### Quick Validation

After building, run `perfect_model_obs` then `filter` in `models/lorenz_63/work/`.
Filter should complete without errors. If using MATLAB, run `plot_total_err` —
the RMSE should stay around 2.0 and not grow unbounded.

### Build System

DART uses `mkmf` (a Perl script) to generate Makefiles from Fortran source
dependencies. Each model has a `work/` directory with:
- `quickbuild.sh` — automated build script
- `input.nml` — Fortran namelist configuration
- `path_names_*` — source file lists for each executable

The `quickbuild.sh` script:
1. Sets DART root directory
2. Sources `build_templates/buildfunctions.sh`
3. Runs `preprocess` to generate obs_def_mod.f90 and obs_kind_mod.f90
4. Builds all executables via mkmf + make

---

## Pipeline

DART operates through a staged pipeline. Each stage has specific executables,
input files, and output files.

| # | Stage | Executable | Input | Output | Description |
|---|---|---|---|---|---|
| 1 | Preprocess | `preprocess` | DEFAULT_obs_def_mod.F90, obs type files | obs_def_mod.f90, obs_kind_mod.f90 | Generate observation type modules |
| 2 | Build | `quickbuild.sh` | path_names_*, mkmf.template | Executables | Compile all programs |
| 3 | Obs Definition | `create_obs_sequence` | interactive / stdin | obs_seq.in (template) | Define observation types and locations |
| 4 | Obs Replication | `create_fixed_network_seq` | obs_seq.in, input.nml | obs_seq.in (time series) | Replicate obs template across time |
| 5 | Obs Conversion | obs converters | Raw data (HDF/BUFR/CSV) | obs_seq.out | Convert real observations to DART format |
| 6 | Truth Run | `perfect_model_obs` | obs_seq.in, initial state | obs_seq.out, true state | Generate synthetic observations (OSSE) |
| 7 | Assimilation | `filter` | obs_seq.out, ensemble states | analysis states, obs_seq.final | Run ensemble DA |
| 8 | Diagnostics | `obs_diag` | obs_seq.final | obs_diag_output.nc | Compute observation-space statistics |
| 9 | Visualization | MATLAB/Python | NetCDF output files | Plots | Analyze and visualize results |

**Dependencies**: Stage 1 must precede Stage 2. Stages 3-4 (synthetic) OR Stage 5
(real) feed into Stage 6 or 7. Stage 8 requires Stage 7 output.

---

## Tools Reference

| Tool | Stage | Script | Lines | Purpose |
|---|---|---|---|---|
| convert_obs_to_dart | s5 | tools/convert_obs_to_dart.py | ~250 | Convert CSV observations to DART obs_seq text format |
| generate_input_nml | s2-s7 | tools/generate_input_nml.py | ~350 | Generate input.nml namelist for any DART program |
| run_dart | s6-s7 | tools/run_dart.py | ~200 | Execute DART programs with validation |
| parse_dart_output | s8-s9 | tools/parse_dart_output.py | ~250 | Extract NetCDF output to CSV for analysis |

---

## Critical Domain Knowledge

### #1 — Observation Sequence File Format

DART observations are stored in `obs_seq` files — a custom format that is
either ASCII (human-readable) or binary (machine-dependent). The file
contains:
- **Header**: number of copies, QC fields, observation count
- **Copy metadata**: labels like "observations", "truth", "prior ensemble mean"
- **Observations**: location, time, type, error variance, values, QC

**CRITICAL**: The error variance field stores the **variance** (sigma^2),
NOT the standard deviation. If you provide standard deviation instead of
variance, assimilation weights will be wrong — observations will be
trusted sqrt(sigma) times too much or too little.

**CRITICAL**: Time in obs_seq files is stored as (days, seconds) pairs
relative to a base calendar. The `advance_time` utility converts between
human-readable dates and DART time format.

### #2 — Namelist Configuration (input.nml)

All DART programs read from `input.nml` using Fortran namelist I/O. Key
namelists include:

| Namelist | Program | Key Parameters |
|---|---|---|
| `&filter_nml` | filter | ens_size, inf_flavor, cutoff, stages_to_write |
| `&perfect_model_obs_nml` | perfect_model_obs | obs_seq_in/out, async |
| `&preprocess_nml` | preprocess | obs_type_files, quantity_files |
| `&assim_tools_nml` | filter | cutoff, sort_obs_inc, sampling_error_correction |
| `&obs_sequence_nml` | all | write_binary_obs_sequence |
| `&model_nml` | model-specific | varies per model |
| `&location_nml` | filter | varies per location module |
| `&cov_cutoff_nml` | filter | select_localization (1=Gaspari-Cohn) |

**CRITICAL**: Fortran namelist format requires:
- Ampersand prefix: `&namelist_name`
- Slash terminator: `/`
- Boolean values: `.true.` / `.false.` (with dots)
- Strings: single-quoted `'value'`
- Arrays: comma-separated `1.0, 1.0`

### #3 — Ensemble Size and Inflation

The ensemble size (`ens_size`) controls the number of model realizations.
Typical values: 20-80 for low-order models, 40-100 for GCMs.

**Inflation** counteracts ensemble collapse (filter divergence) by
artificially increasing ensemble spread. Options (inf_flavor):
- 0: No inflation
- 2: Spatially/temporally varying (Anderson 2009) — most common
- 3: Spatially uniform, temporally varying
- 4: Relaxation to Prior Spread (RTPS) — posterior only
- 5: Enhanced with Inverse Gamma (El Gharamti 2018)

**CRITICAL**: inf_flavor is a 2-element array: `[prior, posterior]`.
Setting `inf_flavor = 2, 0` applies adaptive prior inflation only.
The inflation restart files (`prior_inf_mean.nc`, `prior_inf_sd.nc`)
must be present if `inf_initial_from_restart = .true.`.

### #4 — Localization

Localization reduces spurious long-range correlations by tapering the
ensemble covariance with distance. The `cutoff` parameter in
`&assim_tools_nml` defines the half-width of the Gaspari-Cohn function.

**CRITICAL**: The cutoff units depend on the location module:
- `oned`: fraction of unit circle [0, 1]
- `threed_sphere`: **radians** (NOT degrees). 0.2 rad ≈ 1146 km.
  To convert: cutoff_rad = cutoff_km / 6371.0
- `threed_cartesian`: same units as the coordinate system

**CRITICAL**: Setting cutoff too large (e.g., 1000000.0) effectively
disables localization. This works for small models (Lorenz 63) but
causes filter divergence for realistic models.

### #5 — Vertical Coordinate Handling

For 3D models on the sphere, observations and state variables may use
different vertical coordinates:

| which_vert | Coordinate | Units |
|---|---|---|
| -2 | Undefined | N/A (column-integrated) |
| -1 | Surface | N/A |
| 1 | Model level | Integer level number |
| 2 | Pressure | Pascals (Pa) |
| 3 | Height | Meters (m) |
| 4 | Scale height | Unitless (-ln(p/p0)) |

**CRITICAL**: Pressure must be in **Pascals**, not hPa or mb.
1 hPa = 100 Pa. If observations provide pressure in hPa,
multiply by 100 before ingestion.

### #6 — NetCDF State File Format

DART state files are NetCDF with dimensions matching the model grid.
For simple models (Lorenz), the state is a 1D vector. For complex models
(CAM, WRF), the state includes multiple variables on structured grids.

Output stages controlled by `stages_to_write`:
- `preassim`: After prior inflation, before assimilation
- `analysis`: After assimilation + posterior inflation
- `output`: Final restart state for next cycle

Each stage produces:
- `{stage}_mean.nc` — Ensemble mean
- `{stage}_sd.nc` — Ensemble standard deviation
- `{stage}_member_NNNN.nc` — Individual members (if output_members=.true.)

### #7 — Observation Quality Control

DART assigns QC values to observations during assimilation:

| QC Value | Meaning |
|---|---|
| 0 | Assimilated successfully |
| 1 | Evaluated only (not assimilated) |
| 2 | Posterior forward operator failed |
| 3 | Not used (outside time window) |
| 4 | Prior forward operator failed |
| 5 | Not used (not selected in obs_kind_nml) |
| 6 | Incoming QC rejected |
| 7 | Outlier rejected (failed outlier_threshold test) |
| 8 | Vertical conversion failed |

**CRITICAL**: A high fraction of QC > 0 usually indicates:
- Forward operator bugs (QC 4) — check model_mod interpolation
- Wrong obs locations (QC 8) — verify vertical coordinates
- Overly tight outlier threshold — increase outlier_threshold in filter_nml

### #8 — Missing Data Convention

DART uses a sentinel value for missing data:
- `MISSING_R8 = -888888.0` (double precision)
- `MISSING_R4 = -888888.0` (single precision)
- `MISSING_I = -888888` (integer)

**CRITICAL**: Do NOT use NaN, -9999, or other conventions. DART
checks for exact equality with -888888.0. Using a different sentinel
will cause silent data corruption.

### #9 — Model Async Modes

The `async` parameter in `&filter_nml` controls how filter advances the model:

| async | Mode | Description |
|---|---|---|
| 0 | Synchronous | filter calls model adv_1step() directly (Fortran subroutine) |
| 2 | Shell command | filter writes state, calls adv_ens_command, reads result |
| 4 | Parallel shell | Like 2, but launches multiple model advances |

**CRITICAL**: For built-in models (Lorenz, simple_advection), use `async = 0`.
For external models (WRF, CAM), use `async = 2` or `async = 4` with a
shell script that reads filter output, runs the model, and writes DART input.

---

## Unit Trap Table

| Variable | DART Expected | Common Source | Conversion | Trap |
|---|---|---|---|---|
| Obs error | Variance (σ²) | Std dev (σ) | Square it | Wrong assimilation weights |
| Localization cutoff | Radians (3D sphere) | Degrees or km | deg × π/180 or km/6371 | Spurious correlations |
| Pressure (vertical) | Pascals (Pa) | hPa / mb | × 100 | Wrong vertical localization |
| Longitude | Radians [0, 2π] internal | Degrees [-180, 360] | × π/180 | Wrong obs locations |
| Latitude | Radians [-π/2, π/2] internal | Degrees [-90, 90] | × π/180 | Wrong obs locations |
| Time | (days, seconds) pair | ISO datetime | advance_time utility | Time mismatch |
| Temperature | Kelvin (model-dependent) | Celsius | + 273.15 | Bias in assimilation |
| Wind speed | m/s | knots or km/h | × 0.5144 or / 3.6 | Wind obs rejected |
| Missing data | -888888.0 | NaN, -9999 | Replace with -888888.0 | Silent corruption |
| Inflation | 2-element array | Scalar | [prior, posterior] | Only prior inflated |
| Ensemble spread | From ensemble SD | From variance | sqrt(variance) | Wrong spread diagnostics |
| Rain rate | Model-dependent | mm/day vs m/day | Check model docs | 1000x error possible |

---

## Validation Results

### Lorenz 63 OSSE

**Model**: Lorenz 63 (3-variable chaotic system)
**Parameters**: σ=10.0, r=28.0, b=8/3
**Ensemble size**: 20 members
**Observations**: All 3 state variables observed every hour
**Observation error**: σ = sqrt(8.0)
**Assimilation**: EAKF, no inflation, no localization
**Duration**: 1000 assimilation cycles

| Metric | Value | Expected | Status |
|---|---|---|---|
| RMSE (total) | ~2.0 | < 4.0 | PASS |
| Filter divergence | None | None | PASS |
| Ensemble spread | ~2.0 | ~RMSE | PASS |
| Build time | < 30s | < 60s | PASS |
| Runtime | < 5s | < 30s | PASS |

### Key Findings

1. The Lorenz 63 OSSE validates that the build system, preprocess,
   perfect_model_obs, and filter are all functioning correctly.
2. RMSE stabilizes around 2.0 after initial spinup, confirming
   proper ensemble initialization and assimilation.
3. No inflation is needed for this simple model — ensemble spread
   is maintained by model nonlinearity.

---

## Calibration Parameters

For realistic models, the key tuning parameters in priority order:

| Priority | Parameter | Namelist | Range | Controls |
|---|---|---|---|---|
| 1 | ens_size | filter_nml | 20-100 | Sampling error, computational cost |
| 2 | cutoff | assim_tools_nml | 0.01-1.0 rad | Localization radius |
| 3 | inf_flavor(1) | filter_nml | 0,2,3,4,5 | Prior inflation scheme |
| 4 | inf_initial(1) | filter_nml | 1.0-1.2 | Initial inflation magnitude |
| 5 | inf_damping(1) | filter_nml | 0.5-1.0 | Inflation persistence |
| 6 | outlier_threshold | filter_nml | 2.0-5.0 | Observation rejection |
| 7 | sampling_error_correction | assim_tools_nml | .true./.false. | Small-ensemble bias fix |
| 8 | inf_flavor(2) | filter_nml | 0,4 | Posterior inflation |

---

## Data Requirements

| Data | Source | Format | Purpose |
|---|---|---|---|
| Model state | Model output | NetCDF | Ensemble initial conditions |
| Observations | Converters | obs_seq (ASCII/binary) | Assimilation input |
| NetCDF library | System package | Library | Required for I/O |
| mkmf.template | build_templates/ | Text | Compiler configuration |
| input.nml | User-created | Fortran namelist | Runtime configuration |

---

## Quick Start (Lorenz 63 OSSE)

```bash
# 1. Configure compiler
cd DART/build_templates
cp mkmf.template.gfortran mkmf.template
export NETCDF=/usr   # or wherever NetCDF is installed

# 2. Build Lorenz 63
cd ../models/lorenz_63/work
./quickbuild.sh nompi

# 3. Generate synthetic observations
./perfect_model_obs

# 4. Run ensemble assimilation
./filter

# 5. Examine output
ncdump -h preassim_mean.nc
ncdump -h analysis_mean.nc

# 6. Run observation diagnostics
./obs_diag
ncdump -h obs_diag_output.nc
```

---

## Diagnostic Triplets Summary

20 diagnostic triplets covering 6 failure domains:

| Domain | Count | Silent |
|---|---|---|
| unit_conversion | 5 | 5 |
| namelist_format | 4 | 2 |
| file_format | 3 | 2 |
| runtime | 3 | 0 |
| ensemble_config | 3 | 2 |
| observation_handling | 2 | 1 |
| **Total** | **20** | **12 (60%)** |

See `diagnostics/triplets.yaml` for full details.

---

## Supported Models (50+)

| Category | Models |
|---|---|
| Atmospheric | CAM-FV, CAM-SE, WRF, MPAS-ATM, ECHAM, LMDZ, pangu |
| Oceanic | MOM6, POP, ROMS, MITgcm, MPAS-OCN, FESOM |
| Land/Hydro | CLM, Noah, wrf_hydro, pywatershed |
| Coupled | CESM, CICE |
| Idealized | Lorenz 63/84/96, 9var, bgrid_solo, ikeda, sqg, seir |

---

## File Structure

```
ki/
├── SKILL.md                          # This file — consolidated knowledge
├── tools/
│   ├── convert_obs_to_dart.py        # CSV → obs_seq converter
│   ├── generate_input_nml.py         # Namelist generator
│   ├── run_dart.py                   # Execution wrapper
│   └── parse_dart_output.py          # NetCDF → CSV parser
├── docs/
│   ├── s1_preprocessing_and_build.md # Build system documentation
│   ├── s2_observation_preparation.md # Observation ingestion
│   ├── s3_ensemble_initialization.md # Ensemble setup
│   ├── s4_assimilation_execution.md  # Running filter
│   └── s5_diagnostics.md            # Output analysis
└── diagnostics/
    └── triplets.yaml                 # 20 symptom→diagnosis→remedy entries
```
