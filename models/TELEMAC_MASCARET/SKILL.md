---
name: telemac-mascaret
description: >-
  TELEMAC-2D depth-averaged shallow-water (Saint-Venant) hydrodynamics; openTELEMAC
  consortium release v9.1.0. Covers Depth-averaged (2D) free-surface flow via the
  Saint-Venant / shallow-water equations; Long-wave propagation including non-linear
  effects; Bed (bottom) friction; Coriolis force; Meteorological forcing: atmospheric
  pressure, wind, rain, evaporation. Use when the task involves running, configuring,
  calibrating or interpreting TELEMAC_MASCARET.
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

# TELEMAC-MASCARET Knowledge Infrastructure

| Field              | Value                                                       |
|--------------------|-------------------------------------------------------------|
| Package            | `telemac-mascaret-ki`                                       |
| Model              | TELEMAC-MASCARET v9.1.0                                     |
| Domain             | Free-surface flow, wave propagation, sediment transport     |
| Language           | Fortran 90 / Python 3                                       |
| Build System       | CMake >= 3.18                                               |
| License            | GPL-3.0                                                     |
| Validation Status  | analytic (bump test, subcritical/transcritical flow)         |
| Tools              | 4 Python scripts                                            |
| Skill Documents    | 6 markdown files                                            |
| Diagnostic Triplets| 18 symptom-diagnosis-remedy entries                         |

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for atmospheric forcing documentation.
See `data_ki/NOAA_Tides/SKILL.md` for tidal observation data.
See `data_ki/NDBC/SKILL.md` for wave buoy observations.


## 1. Overview

TELEMAC-MASCARET is an integrated suite of finite-element / finite-volume
solvers for free-surface hydrodynamics, managed by a European consortium
(EDF, BAW, CEREMA, HR Wallingford, IMDC, Artelia). It is used worldwide
for river flooding, coastal engineering, estuarine dynamics, sediment
transport, and water quality modelling.

### Core Modules

| Module       | Purpose                                    | Equation Type            |
|--------------|--------------------------------------------|--------------------------|
| **telemac2d**| 2D shallow-water hydrodynamics             | Saint-Venant (SWE)       |
| **telemac3d**| 3D hydrodynamics                           | Reynolds-averaged N-S    |
| **tomawac**  | Spectral wave modelling                    | Action balance           |
| **artemis**  | Harbour wave agitation                     | Mild-slope equation      |
| **gaia**     | Sediment transport & morphodynamics        | Exner equation           |
| **mascaret** | 1D river hydrodynamics                     | 1D Saint-Venant          |
| **khione**   | Ice dynamics                               | Ice thermodynamics       |
| **waqtel**   | Water quality / ecology                    | Advection-diffusion      |
| **nestor**   | Dredging operations                        | Volume management        |
| **postel3d** | 3D post-processing                         | Interpolation            |
| **stbtel**   | Mesh conversion                            | Format translation       |

### Key Differentiators

- Unstructured triangular meshes (variable resolution)
- Both finite-element (FE) and finite-volume (FV) solvers
- Coupled multi-physics (hydro + waves + sediment + quality)
- MPI parallelism with METIS domain decomposition
- Python API (TelApy) for scripting and coupling

---

## 2. Installation

### Prerequisites

- **Mandatory**: Fortran compiler (gfortran >= 8), Python >= 3.8, NumPy, SciPy
- **Optional**: MPI (OpenMPI/MPICH), METIS 5.1, MED 4.1 (HDF5), MUMPS, AED2, GOTM
- **Post-processing**: Matplotlib >= 3.5

### Build (minimal, sequential)

```bash
export HOMETEL=/path/to/telemac-mascaret
export PATH=$HOMETEL/scripts/python3:$PATH

# Option A: helper script
build_telemac.py --deps "" -j 8

# Option B: direct CMake
mkdir -p $HOMETEL/build && cd $HOMETEL/build
cmake -S $HOMETEL -B . -G "Unix Makefiles" \
  -DCMAKE_BUILD_TYPE=Release \
  -DUSE_MPI=OFF -DUSE_MED=OFF -DUSE_MUMPS=OFF
cmake --build . --parallel 8
```

### Quick Smoke Test

```bash
cd $HOMETEL/examples/telemac2d/gouttedo
telemac2d.py t2d_gouttedo.cas
```

---

## 3. File Formats

### 3.1 Steering File (.cas)

The CAS file is a keyword-value text file that controls the simulation.
Comments begin with `/`. Multi-valued keywords use `;` as separator.

```
TITLE = 'My simulation'
GEOMETRY FILE            = mesh.slf
BOUNDARY CONDITIONS FILE = mesh.cli
RESULTS FILE             = results.slf
TIME STEP                = 0.5
NUMBER OF TIME STEPS     = 7200
VARIABLES FOR GRAPHIC PRINTOUTS = 'U,V,H,S,B'
LAW OF BOTTOM FRICTION   = 4
FRICTION COEFFICIENT     = 0.025
```

Keywords are defined in dictionary files (`telemac2d.dico`, `telemac3d.dico`, etc.).
Each keyword has a type (INTEGER, REAL, STRING, LOGICAL), default value, and valid choices.

### 3.2 SELAFIN / SERAFIN (.slf)

Binary unstructured mesh + time-series format. Big-endian by default.

| Section        | Content                                                 |
|----------------|---------------------------------------------------------|
| Header         | 80-char title, variable names (32 chars each)           |
| Integer params | 10 integers: NPLAN, NPTFR, date flag, etc.              |
| Mesh topology  | NELEM, NPOIN, NDP, connectivity (IKLE), boundary IPOBO  |
| Coordinates    | X, Y arrays (NPOIN floats each)                         |
| Data frames    | Per timestep: time value + NVAR arrays of NPOIN floats  |

Precision: SERAFIN (single/R4) or SERAFIND (double/R8).

### 3.3 Boundary Conditions (.cli)

Text file specifying boundary type per edge node.
Each line: `LIHBOR LIUBOR LIVBOR HBOR UBOR VBOR ... global_node_number`.

Boundary types:
- 1 = Prescribed value (Dirichlet)
- 2 = Free / zero-flux (Neumann)
- 4 = Velocity imposed
- 5 = Elevation imposed

### 3.4 MED Format (.med)

HDF5-based mesh format (optional). Requires MED library >= 4.1.

---

## 4. Pipeline Stages

| # | Stage              | Tool                     | Key Action                              |
|---|--------------------|--------------------------|-----------------------------------------|
| 0 | Configuration      | (manual)                 | Select module, define simulation scope  |
| 1 | Domain Setup       | stbtel / BlueKenue / SMS | Create mesh (.slf) + boundary (.cli)    |
| 2 | Forcing Prep       | `convert_forcing.py`     | Convert met/tidal data to SELAFIN       |
| 3 | Bathymetry/Params  | `convert_bathymetry.py`  | Interpolate depth onto mesh nodes       |
| 4 | Steering File      | (manual / text editor)   | Write .cas with all keywords            |
| 5 | Execution          | `run_telemac.py`         | Run telemac2d.py / telemac3d.py         |
| 6 | Output Parsing     | `parse_selafin.py`       | Extract time series to CSV              |

---

## 5. Unit Trap Table

These are the most common unit-conversion pitfalls when setting up TELEMAC simulations.

| Variable               | TELEMAC Unit    | Common Source Unit  | Factor          | Trap ID |
|------------------------|-----------------|---------------------|-----------------|---------|
| Gravity                | m/s^2           | cm/s^2 (CGS)        | x 0.01          | dt_001  |
| Friction (Manning)     | s/m^(1/3)       | 1/n (Strickler)     | 1/n             | dt_002  |
| Friction (Strickler)   | m^(1/3)/s       | Manning n           | 1/n             | dt_002  |
| Wind speed             | m/s             | knots               | x 0.5144        | dt_003  |
| Atmospheric pressure   | Pa              | mbar / hPa          | x 100           | dt_004  |
| Water density          | kg/m^3          | g/cm^3              | x 1000          | dt_005  |
| Coordinates            | m (metric)      | degrees (WGS84)     | project first   | dt_006  |
| Elevation (bathymetry) | m (above datum) | depth below surface | negate          | dt_007  |
| Discharge              | m^3/s           | L/s                 | x 0.001         | dt_008  |
| Time step              | s               | min or hr           | x60 or x3600    | dt_009  |
| Tidal constituents     | m, degrees      | cm, radians         | /100, x180/pi   | dt_010  |
| Rain intensity         | mm/s            | mm/hr               | /3600           | dt_011  |
| Velocity diffusivity   | m^2/s           | cm^2/s              | x 0.0001        | dt_012  |

---

## 6. Tools Reference

| Tool                    | Lines | Stage | Purpose                                    |
|-------------------------|-------|-------|--------------------------------------------|
| `convert_forcing.py`    | ~220  | s2    | Convert met/tidal ASCII to SELAFIN forcing  |
| `convert_bathymetry.py` | ~200  | s3    | Interpolate bathymetry onto mesh nodes      |
| `run_telemac.py`        | ~180  | s5    | Execute TELEMAC binary with env setup       |
| `parse_selafin.py`      | ~250  | s6    | Parse SELAFIN results to CSV time-series    |

All tools follow the **validate -> process -> validate** pattern:
1. Check input file existence and format
2. Perform the conversion / action
3. Verify output correctness (checksums, ranges, shapes)

---

## 7. Critical Domain Knowledge

### 7.1 Manning vs Strickler Confusion (dt_002)
TELEMAC supports both Manning (n, s/m^1/3) and Strickler (K = 1/n, m^1/3/s)
friction laws. LAW OF BOTTOM FRICTION = 3 is Strickler, = 4 is Manning.
Supplying a Manning coefficient (e.g. 0.025) when Strickler is selected
(expecting ~40) causes extreme friction, often crashing or producing unrealistic
water levels.

### 7.2 Bathymetry Sign Convention (dt_007)
TELEMAC uses **bottom elevation** (positive upward from datum), not depth.
Survey charts typically provide depth below surface (positive downward).
Forgetting to negate produces inverted topography: hills become trenches.

### 7.3 Coordinate System Mismatch (dt_006)
TELEMAC meshes must use **metric coordinates** (UTM, Lambert, etc.).
Loading WGS84 degree coordinates into the mesh produces a domain of ~1m x 1m
with catastrophic CFL violations. Always project before meshing.

### 7.4 Big-Endian Binary (dt_013)
SELAFIN files are big-endian by default (`-fconvert=big-endian` compiler flag).
Reading on little-endian systems without byte-swapping produces garbage values.
The HERMES library handles this internally, but custom parsers must swap bytes.

### 7.5 Tidal Flats (dt_014)
Setting `TIDAL FLATS = YES` enables wetting/drying. Without it, cells that go
dry produce negative depths and numerical instability. For coastal/estuarine
simulations, this keyword is almost always required.

### 7.6 CFL Condition and Time Step (dt_015)
The Courant number must remain < 1 (FE) or the simulation becomes unstable.
CFL = U * dt / dx. For typical coastal meshes with dx ~ 100m and currents
~ 1 m/s, dt should be < 100s. Adaptive time stepping is available via the
`VARIABLE TIME-STEP` keyword.

### 7.7 Parallel Decomposition (dt_016)
Running in parallel requires METIS for domain decomposition. The number of
subdomains must equal the number of MPI processes. Mismatches cause silent
hangs or segfaults with no error message.

### 7.8 User Fortran Compilation (dt_017)
User Fortran subroutines must be compiled with the same compiler and flags
used for the main TELEMAC build. Mixing compilers (e.g. gfortran vs ifort)
produces undefined symbol errors at link time.

### 7.9 SELAFIN Variable Order (dt_018)
Output variables in `VARIABLES FOR GRAPHIC PRINTOUTS` must match the order
expected by post-processing tools. Custom variables (T1, T2, ...) are
appended after standard variables.

---

## 8. Output Variables

### Standard 2D Variables

| Code | Name                       | Unit       |
|------|----------------------------|------------|
| U    | Velocity along X           | m/s        |
| V    | Velocity along Y           | m/s        |
| H    | Water depth                | m          |
| S    | Free surface elevation     | m          |
| B    | Bottom elevation           | m          |
| Q    | Scalar discharge           | m^2/s      |
| F    | Froude number              | -          |
| M    | Velocity magnitude         | m/s        |
| C    | Wave celerity              | m/s        |
| K    | Turbulent kinetic energy   | J/kg       |
| E    | Turbulent dissipation      | W/kg       |
| D    | Turbulent viscosity        | m^2/s      |
| W    | Bottom friction coeff      | -          |
| X    | Wind velocity X            | m/s        |
| Y    | Wind velocity Y            | m/s        |
| P    | Atmospheric pressure       | Pa         |
| T*   | All tracers                | varies     |
| L    | Courant number             | -          |

---

## 9. Validation Results

### Bump Test Case (Subcritical Flow)

The classic 1D bump test validates the Saint-Venant solver against an
analytic solution for steady flow over a parabolic bottom obstacle.

- **Test**: `examples/telemac2d/bump/t2d_bump_FE.cas`
- **Analytic**: `examples/telemac2d/bump/analytic_sol.py`
- **Flow**: Q = 1.5 m^2/s, downstream depth = 0.8 m
- **Bottom**: Parabolic bump, peak 0.2 m at x = 10 m
- **Domain**: 0-20 m channel, 2 m wide

The analytic solution solves the cubic polynomial from Bernoulli's equation:
h^3 + (z_b - q^2/(2gH^2) - H) * h^2 + q^2/(2g) = 0

Subcritical: largest real root everywhere.
Critical: transition at bump crest (Fr = 1).
Transcritical: hydraulic jump downstream of bump.

---

## 10. Calibration Parameters

| Parameter              | Keyword                    | Range        | Sensitivity |
|------------------------|----------------------------|--------------|-------------|
| Bottom friction coeff  | FRICTION COEFFICIENT       | 0.01-0.10 (M)| High       |
| Turbulent viscosity    | VELOCITY DIFFUSIVITY       | 0.01-10.0    | Medium      |
| Wind drag coefficient  | COEFFICIENT OF WIND...     | 0.001-0.003  | Medium      |
| Coriolis coefficient   | CORIOLIS COEFFICIENT       | varies w/lat | Low         |
| Implicitation (depth)  | IMPLICITATION FOR DEPTH    | 0.5-1.0      | Medium      |
| Implicitation (vel)    | IMPLICITATION FOR VELOCITY | 0.5-1.0      | Medium      |
| Time step              | TIME STEP                  | 0.01-100.0   | High        |

---

## 11. Quick Start (telemac2d bump test)

```bash
# 1. Set environment
export HOMETEL=/path/to/telemac-mascaret
export PATH=$HOMETEL/scripts/python3:$PATH

# 2. Build (minimal sequential)
build_telemac.py --deps "" -m telemac2d -j 8

# 3. Run bump test case
cd $HOMETEL/examples/telemac2d/bump
telemac2d.py t2d_bump_FE.cas

# 4. Parse output
python3 parse_selafin.py r2d_bump.slf --variables U,V,H,S --output results.csv

# 5. Compare with analytic solution
python3 analytic_sol.py
```

---

## 12. File Structure

```
ki/
  SKILL.md                          # This file
  knowledge_infrastructure.yaml     # Package manifest
  tools/
    convert_forcing.py              # Met/tidal forcing converter
    convert_bathymetry.py           # Bathymetry interpolation
    run_telemac.py                  # Execution wrapper
    parse_selafin.py                # SELAFIN output parser
  docs/
    s1_domain_setup.md              # Mesh and domain setup
    s2_mesh_generation.md           # Mesh creation procedures
    s3_forcing_preparation.md       # Forcing data conversion
    s4_steering_file.md             # CAS file configuration
    s5_execution.md                 # Running TELEMAC
    s6_output_analysis.md           # Post-processing results
  diagnostics/
    triplets.yaml                   # 18 diagnostic triplets
```
