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

# ADCIRC v56 (ADvanced CIRCulation) — Knowledge Infrastructure

**Package**: `hydrocraft-adcirc-ocean` v1.0.0
**Model**: ADCIRC v56.2.1 — 2D/3D finite element circulation model
**Created by**: Jianyun Zhang Research Group, Hohai University
**Last updated**: 2026-03-26
**Stats**: 4 tools | 7 skill documents | 20 diagnostic triplets | ~1,600 lines of validated Python
**Validation status**: `build_tested`

---

## Overview

This knowledge infrastructure enables autonomous simulation of coastal ocean circulation, storm surge, and tidal dynamics using ADCIRC (ADvanced CIRCulation model). The 4 validated tools cover the core pipeline from meteorological forcing conversion through output extraction, replacing manual Fortran-era workflows with a Python pipeline that integrates with HydroCraft's coastal modeling infrastructure.

**What ADCIRC does**: 2D/3D finite element hydrodynamic model for time-dependent free surface circulation and transport. Simulates:
- Storm surge prediction (wind + pressure + tide + wave interaction)
- Tidal circulation (harmonic boundary forcing with 30+ constituents)
- Wetting and drying of coastal areas (inundation mapping)
- Wind-driven circulation (30+ meteorological forcing formats)
- Baroclinic 3D flow (salinity, temperature, density-driven currents)
- Coupled wave-current interaction (ADCIRC+SWAN coupling)
- Transport of passive scalars (pollutant tracking)
- Ice coverage effects on surface drag

**Key difference from other HydroCraft models**: ADCIRC operates on unstructured triangular finite element meshes, enabling variable resolution from deep ocean (km-scale) to near-shore (m-scale) in a single domain. It uses Fortran unit-number file conventions (fort.14, fort.15, etc.) inherited from its Fortran origins.

---

## Installation

### Building from Source

```bash
# Prerequisites (Ubuntu/Debian)
sudo apt-get install gfortran gcc cmake libnetcdf-dev libnetcdff-dev \
    openmpi-bin libopenmpi-dev

# Build serial ADCIRC
cd source/repo
mkdir build && cd build
cmake .. -DBUILD_ADCIRC=ON -DENABLE_OUTPUT_NETCDF=ON
make -j$(nproc)

# Build parallel ADCIRC (requires MPI)
cmake .. -DBUILD_PADCIRC=ON -DBUILD_ADCPREP=ON -DENABLE_OUTPUT_NETCDF=ON
make -j$(nproc)
```

### Docker (alternative)

```
DockerHub: adcirc/adcirc   (IntelLLVM for x86-64, GCC 14.2 for ARM)
```

### Executables

| Binary | Purpose |
|--------|---------|
| `adcirc` | Serial ADCIRC |
| `padcirc` | Parallel ADCIRC (MPI) |
| `adcprep` | Domain decomposition preprocessor |
| `adcswan` / `padcswan` | ADCIRC coupled with SWAN wave model |
| `aswip` | Asymmetric Wind Input Preprocessor |

### Dependencies

```
Fortran 2008 compiler (gfortran >= 9, ifort, nvfortran)
C11 compiler (gcc, clang)
CMake >= 3.16
NetCDF-C + NetCDF-Fortran (optional, for netCDF output)
MPI (OpenMPI, MPICH, Intel MPI — required for padcirc)
METIS (bundled in thirdparty/ — for domain decomposition)
```

### Python dependencies (for KI tools)

```
numpy, pandas, netCDF4, matplotlib, scipy
```

---

## Pipeline (7 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 1 | Mesh preparation | (external: SMS, OceanMesh2D) | Generate unstructured triangular mesh (fort.14) |
| 2 | Parameter config | (manual / `convert_bathymetry_to_fort14`) | Set control parameters in fort.15 |
| 3 | Nodal attributes | `convert_bathymetry_to_fort14` | Spatially varying friction, Manning's n (fort.13) |
| 4 | Meteorological forcing | `convert_forcing_to_adcirc` | Wind + pressure data to fort.22 OWI format |
| 5 | Boundary conditions | (manual) | Tidal harmonic constituents for open boundaries |
| 6 | Execution | `run_adcirc` | Run adcirc/padcirc with preflight checks |
| 7 | Output analysis | `parse_adcirc_output` | Extract fort.63/64, maxele to CSV/analysis |

### Parallelism

Stages 1-5 can be prepared independently.
Stage 6 depends on all of 1-5.
Stage 7 depends on 6.

### Parallel Execution Substeps

For parallel (padcirc) runs, stage 6 includes:
1. `adcprep --np N --partmesh` — partition mesh with METIS
2. `adcprep --np N --prepall` — prepare per-processor files
3. `mpirun -np N padcirc` — execute in parallel

---

## Tools Reference

| Tool | Stage | Script Path | Lines | Purpose |
|------|-------|-------------|------:|---------|
| `convert_forcing_to_adcirc` | s4 | `tools/convert_forcing_to_adcirc.py` | 420 | Global met data to OWI fort.22 format |
| `convert_bathymetry_to_fort14` | s3 | `tools/convert_bathymetry_to_fort14.py` | 380 | DEM + coastline to fort.14 mesh + fort.13 nodal attrs |
| `run_adcirc` | s6 | `tools/run_adcirc.py` | 350 | Execute ADCIRC with preflight and postflight checks |
| `parse_adcirc_output` | s7 | `tools/parse_adcirc_output.py` | 450 | Parse fort.63/64/maxele to CSV + statistics |

**Total**: 4 tools, ~1,600 lines of validated Python code.

---

## Input File Reference

### Required Files

| File | Name | Format | Description |
|------|------|--------|-------------|
| **fort.14** | Grid file | ASCII | Unstructured triangular mesh: nodes (x, y, depth), elements, boundaries |
| **fort.15** | Control file | ASCII | All model parameters: timestep, friction, forcing, output control |

### Conditional Files

| File | Trigger | Description |
|------|---------|-------------|
| **fort.13** | Spatially varying params | Nodal attributes (Manning's n, friction, directional roughness) |
| **fort.19** | Elevation BC | Time-varying elevation at open boundaries |
| **fort.20** | Flux BC | Time-varying normal flux at boundaries |
| **fort.22** | NWS ≠ 0 | Meteorological forcing (wind velocity + atmospheric pressure) |
| **fort.24** | NTIP=2 | Self-attraction and earth-load tide |
| **fort.67/68** | Hot start | Restart files from previous run |

---

## Output File Reference

### Time Series

| File | Variable | Units | Description |
|------|----------|-------|-------------|
| **fort.63** | Water elevation | meters | Surface elevation at all nodes |
| **fort.61** | Water elevation | meters | Surface elevation at recording stations |
| **fort.64** | Velocity | m/s | Depth-averaged velocity (u,v) at all nodes |
| **fort.62** | Velocity | m/s | Velocity at recording stations |
| **fort.73** | Wind velocity | m/s | Wind speed (u,v) at all nodes |
| **fort.74** | Atm pressure | m H₂O | Atmospheric pressure at all nodes |

### Extremes

| File | Variable | Units |
|------|----------|-------|
| **maxele.63** | Maximum elevation | meters |
| **maxvel.63** | Maximum velocity | m/s |
| **maxwvel.63** | Maximum wind velocity | m/s |
| **minpr.63** | Minimum pressure | m H₂O |

### Output Formats

- ASCII (NOUT* parameter = 1)
- Sparse ASCII (NOUT* = 4)
- netCDF3/4 (NOUT* = 5, requires `-DENABLE_OUTPUT_NETCDF=ON`)
- XDMF (for ParaView, requires `-DENABLE_OUTPUT_XDMF=ON`)

---

## Critical Domain Knowledge

These non-obvious facts cause **silent failures** if violated. Each has a corresponding diagnostic triplet.

### 1. Depth sign convention: positive = below geoid (dt_001)

In fort.14, bathymetric depth (DP) is **positive below the geoid** and **negative above**. This is the opposite of standard elevation conventions. A coastal node at 2m elevation has DP = -2.0. Confusing this produces an inverted domain where land is underwater and ocean is dry.

### 2. G must match coordinate system (dt_002)

If using spherical coordinates (ICS=2, lat/lon in degrees), **G must be 9.81 m/s²**. Using G=32.174 (feet) with spherical coordinates produces nonsensical results with no error message. The model does NOT auto-detect units.

### 3. Atmospheric pressure is in meters of water, not Pa or mb (dt_003)

ADCIRC internal pressure unit is **meters of water column** (m H₂O). Conversion: `P_mH2O = P_Pa / (rho_water * g) = P_Pa / 9806.65`. If pressure is supplied in Pa or mb without conversion, the model may produce extreme surge or crash with NaN.

### 4. Wind drag coefficient is capped at 0.003 (dt_004)

The Garratt drag formula `Cd = 0.001 * (0.75 + 0.067 * Wspeed)` is internally capped at Cd = 0.003 for wind speeds > 33.6 m/s. For hurricane simulations, this cap significantly affects peak surge. Alternative drag laws (Powell 2003) reduce drag at extreme winds.

### 5. TAU0 controls numerical stability vs accuracy (dt_005)

The GWCE weighting factor TAU0 trades numerical stability for physical accuracy. Too small (<0.001): mass balance errors, oscillations. Too large (>0.1): excessive damping, reduced tidal amplitudes. Use TAU0 = -3 for automatic spatially-varying values based on local conditions.

### 6. DTDP timestep must satisfy CFL condition (dt_006)

The timestep DTDP (seconds) must satisfy: `DTDP < dx_min / sqrt(g * h_max)`. For a mesh with 100m minimum element size and 100m depth: DTDP < 100/31.3 ≈ 3.2s. Violating CFL produces numerical instability that manifests as growing oscillations, not an immediate crash.

### 7. OWI wind files require exact header format (dt_007)

OWI format (NWS=12) fort.22 files have a rigid header: `iLat`, `iLong`, `dx`, `dy`, `SWLat`, `SWLon`, `DT` must appear on specific lines with exact spacing. Off-by-one errors in grid dimensions cause ADCIRC to read wind values at wrong locations, producing asymmetric surge patterns.

### 8. Wetting/drying threshold H0 controls inundation accuracy (dt_008)

The dry node threshold H0 (NOLIFA=2) determines when a node transitions between wet and dry. Too small (<0.001m): instability, "chattering" wet-dry cycles. Too large (>1.0m): underestimates inundation extent. Typical: H0 = 0.05 for storm surge, H0 = 0.01 for tidal studies.

### 9. Hot start files are binary and platform-dependent (dt_009)

Fort.67/68 hot start files are Fortran unformatted binary. They are NOT portable between compilers, endianness, or compiler flags. A hot start file from ifort will crash gfortran. Always regenerate hot starts when changing compilers.

---

## Unit Trap Table

| Variable | ADCIRC Unit | Common Source Unit | Conversion | Trap ID |
|----------|------------|-------------------|------------|---------|
| Bathymetric depth | m (positive down) | m (positive up) | `DP = -elevation` | dt_001 |
| Gravity | 9.81 m/s² (metric) | 32.174 ft/s² (imperial) | Must match ICS | dt_002 |
| Atm pressure | m H₂O | Pa | `/ 9806.65` | dt_003 |
| Atm pressure | m H₂O | mb (hPa) | `* 100 / 9806.65` | dt_003 |
| Wind speed | m/s | knots | `* 0.5144` | dt_010 |
| Wind speed | m/s | km/h | `/ 3.6` | dt_010 |
| Coordinates | degrees (ICS=2) | radians | `* 180/π` | dt_011 |
| Timestep | seconds | hours | `* 3600` | dt_006 |
| Tidal period | seconds | hours | `* 3600` | dt_012 |
| Friction (linear) | 1/s | — | dimensionless TAU | dt_013 |
| Manning's n | s/m^(1/3) | — | typical 0.02-0.12 | dt_014 |
| Time reference | days since cold start | seconds | `/ 86400` | dt_015 |

---

## Calibration Parameters (Priority Order)

| Parameter | Location | Range | Controls | Sensitivity |
|-----------|----------|-------|----------|-------------|
| Manning's n / CF | fort.13/15 | 0.01-0.20 | Bottom friction, surge amplitude | HIGH |
| TAU0 | fort.15 | -5 to 0.1 | GWCE numerical diffusion | HIGH |
| DTDP | fort.15 | 0.5-10 s | CFL stability, accuracy | HIGH |
| H0 | fort.15 | 0.01-1.0 m | Wetting/drying threshold | MEDIUM |
| Wind drag (Cd) | fort.15 | 0.001-0.003 | Wind-to-water momentum transfer | MEDIUM |
| ESLM | fort.15 | 1-50 m²/s | Lateral viscosity/diffusion | MEDIUM |
| FFACTOR | fort.15 | 0.001-0.01 | Quadratic friction coefficient | MEDIUM |
| VELMIN | fort.15 | 0.01-0.1 m/s | Minimum velocity for wetting | LOW |

---

## Coupling Points

| # | Source | Target | Variable | Tool |
|---|--------|--------|----------|------|
| 1 | SWAN | ADCIRC | Wave radiation stress | `padcswan` (built-in) |
| 2 | ADCIRC | SWAN | Water level, currents | `padcswan` (built-in) |
| 3 | NWP (GFS/HRRR) | ADCIRC | Wind + pressure | `convert_forcing_to_adcirc` |
| 4 | CaMa-Flood | ADCIRC | River discharge at boundaries | fort.20 flux BC |
| 5 | ADCIRC | CaMa-Flood | Coastal water level | `parse_adcirc_output` |

---

## Quick Start

```bash
# 1. Convert meteorological forcing to OWI format
python ki/tools/convert_forcing_to_adcirc.py \
  --input_dir /path/to/gfs_grib2/ \
  --format gfs_grib2 \
  --domain_sw 24.0,-98.0 --domain_ne 31.0,-88.0 \
  --resolution 0.25 \
  --start_date 2005-08-25 --end_date 2005-09-01 \
  --output_dir ./

# 2. Convert bathymetry/DEM to fort.14 + fort.13
python ki/tools/convert_bathymetry_to_fort14.py \
  --dem /path/to/gebco_2023.nc \
  --coastline /path/to/gshhs_h.shp \
  --domain_sw 24.0,-98.0 --domain_ne 31.0,-88.0 \
  --min_resolution 500 --max_resolution 50000 \
  --output_fort14 fort.14 --output_fort13 fort.13

# 3. Run serial ADCIRC (all fort.* files in current directory)
python ki/tools/run_adcirc.py \
  --binary ./build/adcirc \
  --work_dir . \
  --mode serial

# 4. Run parallel ADCIRC
python ki/tools/run_adcirc.py \
  --binary ./build/padcirc \
  --adcprep ./build/adcprep \
  --work_dir . \
  --mode parallel --np 8

# 5. Parse output to CSV
python ki/tools/parse_adcirc_output.py \
  --work_dir . \
  --format ascii \
  --output_csv results.csv \
  --stations "29.95,-90.07;30.03,-89.93" \
  --variables elevation,velocity
```

---

## Diagnostic Triplets

20 triplets covering 6 failure domains. See `diagnostics/triplets.yaml` for full details.

| ID | Severity | Domain | Summary |
|----|----------|--------|---------|
| dt_001 | **silent** | unit_conversion | Depth sign inverted (positive up instead of down) |
| dt_002 | **silent** | unit_conversion | G=32.174 with spherical coords (unit mismatch) |
| dt_003 | **silent** | unit_conversion | Pressure in Pa instead of m H₂O |
| dt_004 | **silent** | unit_conversion | Wind drag cap ignored in surge analysis |
| dt_005 | degraded | parameter_format | TAU0 too small causes mass balance errors |
| dt_006 | fatal | parameter_format | DTDP violates CFL — growing oscillations |
| dt_007 | **silent** | parameter_format | OWI header grid dimensions off-by-one |
| dt_008 | degraded | parameter_format | H0 too large underestimates inundation |
| dt_009 | fatal | runtime | Hot start binary incompatible across compilers |
| dt_010 | **silent** | unit_conversion | Wind speed in knots instead of m/s |
| dt_011 | **silent** | unit_conversion | Coordinates in radians instead of degrees |
| dt_012 | **silent** | unit_conversion | Tidal period in hours instead of seconds |
| dt_013 | **silent** | parameter_format | Linear friction units (1/s) confused with quadratic |
| dt_014 | degraded | parameter_format | Manning's n out of physical range |
| dt_015 | **silent** | unit_conversion | Time reference days vs seconds confusion |
| dt_016 | fatal | runtime | NaN from unstable lateral viscosity ESLM |
| dt_017 | fatal | path_resolution | fort.14 not found in working directory |
| dt_018 | **silent** | silent_error | Boundary nodes not ordered counter-clockwise |
| dt_019 | **silent** | dependency_mismatch | MPI version mismatch between adcprep and padcirc |
| dt_020 | fatal | runtime | Domain decomposition fails on disconnected mesh |

**Silent error count**: 11/20 (55%) — high due to ADCIRC's minimal runtime validation of input units.

---

## File Structure

```
ADCIRC/ki/
  SKILL.md                              # This file (agent entry point)
  tools/
    convert_forcing_to_adcirc.py        # Met data to OWI fort.22 format
    convert_bathymetry_to_fort14.py     # DEM/coastline to fort.14 + fort.13
    run_adcirc.py                       # Execution wrapper (serial + parallel)
    parse_adcirc_output.py              # Output parser (fort.63/64 to CSV)
  docs/
    s1_mesh_preparation.md              # Mesh generation and fort.14
    s2_parameter_configuration.md       # Control file fort.15
    s3_nodal_attributes.md              # Spatially varying params fort.13
    s4_meteorological_forcing.md        # Wind/pressure forcing fort.22
    s5_boundary_conditions.md           # Tidal and flow boundaries
    s6_execution.md                     # Running serial and parallel ADCIRC
    s7_output_analysis.md               # Parsing and visualizing results
  diagnostics/
    triplets.yaml                       # 20 diagnostic triplets
```
