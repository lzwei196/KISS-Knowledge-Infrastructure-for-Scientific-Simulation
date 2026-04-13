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

# ESMF — Knowledge Infrastructure Skill Document

## 1. Overview

**ESMF** (Earth System Modeling Framework) is a production-grade software infrastructure
for building and coupling weather, climate, and related Earth system models. It provides
standardized interfaces for grid/mesh creation, field management, regridding, component
coupling, time management, and parallel I/O across distributed-memory (MPI) systems.

- **Version**: 9.0.0
- **License**: University of Illinois-NCSA
- **Primary Languages**: Fortran (741K lines), C (550K lines), C++ (399K lines), Python (20K lines)
- **Domain**: Earth System Modeling Framework (not a standalone model)
- **Developers**: UCAR, MIT, GFDL, University of Michigan, NCEP, LANL, ANL, NASA GSFC

ESMF is NOT a standalone geophysical model. It is a **framework library** that model
developers link against to build coupled Earth system applications. The primary user-facing
products are:

1. **ESMF Library** — Fortran/C/C++ API for grids, fields, regridding, components
2. **ESMF_RegridWeightGen** — Command-line tool for generating regrid weight files
3. **ESMPy** — Python interface (primarily for regridding)
4. **NUOPC** — Standardized coupling layer on top of ESMF
5. **ESMX** — Earth System Model eXecutable driver

---

## 2. Installation

### 2.1 Prerequisites

| Dependency       | Required | Notes                                    |
|------------------|----------|------------------------------------------|
| Fortran compiler | Yes      | gfortran ≥ 8, ifort, pgfortran          |
| C/C++ compiler   | Yes      | gcc/g++, icc, pgcc                       |
| MPI library      | Yes*     | OpenMPI, MPICH, MVAPICH (*or mpiuni)     |
| NetCDF-C         | Recommended | For I/O of CF-convention files        |
| NetCDF-Fortran   | Recommended | Fortran bindings for NetCDF           |
| GNU Make         | Yes      | NOT standard Unix make                   |
| Python ≥ 3.8     | Optional | For ESMPy                                |
| CMake ≥ 3.12     | Optional | For FindESMF.cmake integration           |

### 2.2 Build from Source

```bash
export ESMF_DIR=/path/to/esmf
export ESMF_COMPILER=gfortran       # gfortran | intel | pgi | nag
export ESMF_COMM=openmpi            # openmpi | mpich | mvapich2 | mpiuni
export ESMF_NETCDF=split            # split | standard (for separate C/Fortran libs)
export ESMF_NETCDF_INCLUDE=/usr/include
export ESMF_NETCDF_LIBPATH=/usr/lib
export ESMF_BOPT=O                  # O=optimized | g=debug

cd $ESMF_DIR
make -j$(nproc) lib                 # Build ESMF library
make install                        # Install to ESMF_INSTALL_PREFIX
```

### 2.3 Pre-built Options

```bash
# Conda
conda install -c conda-forge esmf esmpy

# Docker
docker pull esmf/esmf:latest
```

### 2.4 Verification

```bash
make build_unit_tests
make run_unit_tests
# Or: make check_install
```

---

## 3. Architecture

### 3.1 Layer Model

```
┌─────────────────────────────────────────────┐
│  User Application / Coupled Model           │
├─────────────────────────────────────────────┤
│  ESMX / NUOPC Layer (add-on)               │
├─────────────────────────────────────────────┤
│  Superstructure: Component, State, AttachMethods │
├─────────────────────────────────────────────┤
│  Infrastructure: Grid, Mesh, Field, Array,  │
│  Regrid, TimeMgr, IO, VM, DistGrid, Config  │
├─────────────────────────────────────────────┤
│  MPI / pthreads / OpenACC                   │
└─────────────────────────────────────────────┘
```

### 3.2 Core Abstractions

| Abstraction   | C Type          | Purpose                                      |
|---------------|-----------------|----------------------------------------------|
| Grid          | ESMC_Grid       | Structured logically-rectangular grid         |
| Mesh          | ESMC_Mesh       | Unstructured mesh (triangles, quads, etc.)    |
| LocStream     | ESMC_LocStream  | Collection of unconnected observation points  |
| Field         | ESMC_Field      | Data array bound to a Grid/Mesh/LocStream     |
| FieldBundle   | ESMC_FieldBundle| Collection of related Fields                  |
| Array         | ESMC_Array      | Distributed array with halo support           |
| DistGrid      | ESMC_DistGrid   | Global-to-local index decomposition           |
| GridComp      | ESMC_GridComp   | Gridded component (atmosphere, ocean, land)   |
| CplComp       | ESMC_CplComp    | Coupling component (data exchange/regridding) |
| State         | ESMC_State      | Container for inter-component data exchange   |
| Clock         | ESMC_Clock      | Time management (calendar, timestep)          |
| VM            | ESMC_VM         | Virtual Machine (MPI/thread abstraction)      |

### 3.3 Component Lifecycle

Every ESMF component follows Initialize → Run → Finalize:

```
ESMC_GridCompCreate()
  → ESMC_GridCompSetServices()     # Register user callbacks
  → ESMC_GridCompInitialize()      # Setup grids, fields, connections
  → ESMC_GridCompRun()             # Timestep loop
  → ESMC_GridCompFinalize()        # Cleanup
ESMC_GridCompDestroy()
```

### 3.4 Data Exchange Pattern

Components exchange data through State objects:
```
GridComp_A  →  exportState  →  CplComp  →  importState  →  GridComp_B
                              (regrid)
```

---

## 4. Pipeline Stages

### Stage 0: Configuration (`s0_config`)
Set environment variables, paths, compiler flags, MPI configuration.

### Stage 1: Domain / Grid Setup (`s1_domain`)
Define computational grid (structured Grid or unstructured Mesh) from input data
(DEM, shapefiles, NetCDF grid files, SCRIP format).

### Stage 2: Soil / Physical Parameters (`s2_soil`)
Derive physical parameters for land surface (soil hydraulics, roughness, albedo)
from HWSD, SoilGrids, or other global datasets.

### Stage 3: Vegetation / Land Cover (`s3_vegetation`)
Classify land cover (MODIS, AVHRR, ESA CCI) into model vegetation classes.
Assign leaf area index, canopy properties per grid cell.

### Stage 4: Meteorological Forcing (`s4_forcing`)
Convert external forcing data (CMFD, MSWX, ERA5, NASA POWER) to ESMF-compatible
NetCDF with CF conventions. Handle unit conversions and temporal interpolation.

### Stage 5: Model Parameters (`s5_parameters`)
Set calibration parameters, coupling frequencies, regridding methods,
and time-stepping configuration.

### Stage 6: Model Execution (`s6_run`)
Build and execute the ESMF-based application. Run with MPI launcher.

### Stage 7: Output Parsing (`s7_postprocess`)
Extract fields from NetCDF output. Compute derived quantities
(discharge, ET, soil moisture).

### Stage 8: River Routing (optional) (`s8_routing`)
Route runoff through river network using external routing model if needed.

---

## 5. Critical Domain Knowledge — Unit Trap Table

These are non-obvious unit and format requirements that cause silent failures:

| # | Variable / Parameter        | ESMF Expectation        | Common Source         | Trap                                         | Severity |
|---|----------------------------|-------------------------|-----------------------|----------------------------------------------|----------|
| 1 | Grid coordinates (sphere)  | **Degrees** (0–360 or ±180) | Radians              | 57.3x error in regridding; silent wrong results | silent |
| 2 | Grid cell areas            | **Radians²** for conservative regrid | Degrees² or m²   | Area-weighted integrals wrong by ~3000x      | silent   |
| 3 | Time axis in NetCDF        | CF-convention `units since epoch` | Integer timesteps | ESMF_Clock cannot parse; runtime crash       | fatal    |
| 4 | Field data on Grid         | Must match **stagger location** | Center vs corner mismatch | Array bounds mismatch, segfault        | fatal    |
| 5 | Mesh element connectivity  | **1-based** node indices  | 0-based (C/Python)   | Off-by-one mesh topology; silent wrong regrid | silent  |
| 6 | Mesh element types         | ESMF enum (3=tri, 4=quad) | UGRID integers       | Wrong element type silently accepted          | silent   |
| 7 | DistGrid index space       | **1-based** Fortran convention | 0-based C arrays | MPI decomposition mismatch                    | fatal    |
| 8 | Conservative regrid areas  | Destination cell areas needed | Only source areas provided | Conservation violated silently       | silent   |
| 9 | Masking convention         | 0 = masked out           | 1 = masked (common)  | Inverted mask silently excludes valid data    | silent   |
| 10| SCRIP grid file corners    | **Counter-clockwise** order | Clockwise           | Negative cell areas, wrong interpolation      | silent   |
| 11| NetCDF fill value          | Must match `_FillValue` attribute | NaN vs -9999   | Fill values treated as real data              | silent   |
| 12| MPI decomposition          | regDecomp product = nprocs | Mismatch            | Runtime error: "DELayout mismatch"            | fatal    |
| 13| Calendar type              | Must be set before Clock creation | Default Gregorian assumed | Wrong day counts for 360-day models | silent |
| 14| Longitude wrapping         | Periodic dim needs `ESMF_GRIDCONN_PERIODIC` | Non-periodic default | Seam artifact at 0°/360° boundary | silent |
| 15| Field halo width           | Must match regrid stencil width | Too narrow halo | Stencil reads uninitialized memory            | fatal    |

---

## 6. I/O Formats

### Supported Formats

| Format     | Read | Write | Notes                                    |
|------------|------|-------|------------------------------------------|
| NetCDF-3   | Yes  | Yes   | Classic format, widely supported         |
| NetCDF-4   | Yes  | Yes   | HDF5-based, compression support          |
| SCRIP      | Yes  | Yes   | Grid description for regridding          |
| UGRID      | Yes  | No    | Unstructured grid convention             |
| ESMF native| Yes  | Yes   | ESMF-specific grid/mesh format           |
| GridSpec   | Yes  | No    | GFDL Gridspec convention                 |
| XML        | Yes  | Yes   | Configuration and metadata               |
| YAML       | Yes  | No    | Configuration files                      |

### Key NetCDF Conventions

- All spatial fields should follow **CF-1.6+** conventions
- Coordinate variables must have `units` and `standard_name` attributes
- Time must use `units = "days since YYYY-MM-DD"` format
- Grid mapping variables required for projected coordinates

---

## 7. Regridding Methods

| Method            | Key             | Order | Conservative | Best For                    |
|-------------------|-----------------|-------|--------------|-----------------------------|
| Bilinear          | bilinear        | 1st   | No           | Smooth continuous fields     |
| Patch recovery    | patch           | 2nd   | No           | Better derivative estimation |
| Nearest source    | neareststod     | 0th   | No           | Categorical data            |
| Nearest dest      | nearestdtos     | 0th   | No           | Sparse observational data   |
| 1st-order conserv.| conserve        | 1st   | Yes          | Flux fields (precip, radiation) |
| 2nd-order conserv.| conserve2nd     | 2nd   | Yes          | Flux fields, smoother       |

### ESMF_RegridWeightGen CLI

```bash
ESMF_RegridWeightGen \
  --source source_grid.nc \
  --destination dest_grid.nc \
  --weight weight_file.nc \
  --method conserve \
  --src_missingvalue \
  --ignore_unmapped
```

---

## 8. Command-Line Tools

| Tool                      | Purpose                                      |
|---------------------------|----------------------------------------------|
| ESMF_RegridWeightGen      | Generate interpolation weight files           |
| ESMF_Regrid               | Apply weight file to regrid a data field      |
| ESMF_Scrip2Unstruct       | Convert SCRIP grid to unstructured format     |
| ESMF_PrintInfo            | Print ESMF build configuration info           |

---

## 9. ESMPy (Python Interface)

```python
import esmpy

# Create source and destination grids
srcgrid = esmpy.Grid(np.array([180, 360]), staggerloc=esmpy.StaggerLoc.CENTER)
dstgrid = esmpy.Grid(np.array([90, 180]), staggerloc=esmpy.StaggerLoc.CENTER)

# Create fields on grids
srcfield = esmpy.Field(srcgrid, name="temperature")
dstfield = esmpy.Field(dstgrid, name="temperature")

# Create regrid object
regrid = esmpy.Regrid(srcfield, dstfield,
                       regrid_method=esmpy.RegridMethod.BILINEAR,
                       unmapped_action=esmpy.UnmappedAction.IGNORE)

# Apply regridding
dstfield = regrid(srcfield, dstfield)
```

---

## 10. NUOPC Coupling Layer

NUOPC (National Unified Operational Prediction Capability) standardizes how ESMF
components are assembled into coupled systems:

- **NUOPC_Driver** — Top-level driver managing component execution order
- **NUOPC_Model** — Wrapper for gridded model components
- **NUOPC_Mediator** — Component performing regridding/flux calculations
- **NUOPC_Connector** — Automatic field matching and regridding

### Field Dictionary

NUOPC uses a standard **Field Dictionary** for automatic field matching:
- `air_temperature` (K)
- `surface_net_downward_shortwave_flux` (W/m²)
- `precipitation_flux` (kg/m²/s)
- `sea_surface_temperature` (K)

---

## 11. Calibration and Tuning

Since ESMF is a framework, calibration applies to the **component models** built on ESMF.
Key tunable aspects of ESMF itself include:

| Parameter              | Typical Range    | Impact                              |
|------------------------|------------------|-------------------------------------|
| Regrid method          | bilinear/conserve| Conservation of fluxes              |
| Coupling frequency     | 1–3600 s         | Temporal resolution of coupling     |
| Halo width             | 1–4 cells        | Parallel communication overhead     |
| DE decomposition       | nprocs layout    | Load balancing efficiency           |
| Time step              | Model-dependent  | Stability (CFL condition)           |
| Extrapolation method   | creep/nearest    | Treatment of unmapped cells         |

---

## 12. Tools Reference

| Tool Script                  | Stage | Purpose                                  | Lines |
|------------------------------|-------|------------------------------------------|-------|
| `convert_grid_to_esmf.py`    | s1    | Convert external grid to ESMF NetCDF     | ~220  |
| `convert_forcing_to_esmf.py` | s4    | Convert met forcing to CF-NetCDF         | ~250  |
| `run_esmf_application.py`    | s6    | Build and execute ESMF application       | ~200  |
| `parse_esmf_output.py`       | s7    | Extract fields from ESMF output to CSV   | ~210  |
| `generate_regrid_weights.py` | s1/s7 | Wrapper for ESMF_RegridWeightGen         | ~180  |

---

## 13. File Structure

```
ki/
├── SKILL.md                          # This document
├── knowledge_infrastructure.yaml     # Pipeline schema
├── tools/
│   ├── convert_grid_to_esmf.py       # Grid/mesh converter
│   ├── convert_forcing_to_esmf.py    # Forcing data converter
│   ├── run_esmf_application.py       # Execution wrapper
│   ├── parse_esmf_output.py          # Output parser
│   └── generate_regrid_weights.py    # Regrid weight generator
├── docs/
│   ├── s0_configuration.md           # Environment setup
│   ├── s1_domain_grid_setup.md       # Grid/mesh creation
│   ├── s4_meteorological_forcing.md  # Forcing preparation
│   ├── s6_model_execution.md         # Building and running
│   ├── s7_output_parsing.md          # Output extraction
│   └── s8_regridding.md              # Regridding procedures
├── diagnostics/
│   └── triplets.yaml                 # 20 symptom→diagnosis→remedy
└── workflow/
    └── workflow.md                   # Pipeline overview
```

---

## 14. Common Build Errors

| Error                                         | Cause                              | Fix                                    |
|-----------------------------------------------|------------------------------------|-----------------------------------------|
| `ESMF_COMPILER not set`                       | Missing env var                    | `export ESMF_COMPILER=gfortran`        |
| `cannot find -lnetcdff`                       | NetCDF-Fortran not installed       | Install libnetcdff-dev or set path     |
| `MPI_Init: not initialized`                   | Wrong ESMF_COMM or no MPI          | Set `ESMF_COMM=mpiuni` for serial      |
| `DELayout: PET count mismatch`                | regDecomp × nDE ≠ nprocs          | Adjust decomposition or -np value      |
| `Grid dimension mismatch`                     | Wrong maxIndex/minIndex            | Check grid dimensions match data       |
| `Segfault in regrid`                          | Stagger location mismatch          | Ensure Field stagger matches Grid      |

---

## 15. Performance Tips

1. **Decomposition**: Match regDecomp to your MPI process layout for minimal communication
2. **Halo updates**: Minimize halo width — wider halos = more MPI traffic
3. **I/O**: Use parallel I/O (PIO) for large grids; serial I/O bottlenecks at scale
4. **Regridding**: Pre-compute weight files; do not regenerate each timestep
5. **Field packing**: Use FieldBundle for related fields to batch communication
6. **Tracing**: Enable `ESMF_RUNTIME_TRACE=ON` to profile component timing

---

## 16. Quick Reference Card

```bash
# Check ESMF installation
ESMF_PrintInfo

# Generate regrid weights (bilinear)
ESMF_RegridWeightGen -s src.nc -d dst.nc -w wgt.nc -m bilinear

# Generate regrid weights (conservative)
ESMF_RegridWeightGen -s src.nc -d dst.nc -w wgt.nc -m conserve

# Apply regrid weights
ESMF_Regrid -s src_data.nc -d dst_data.nc -w wgt.nc

# Run ESMF app with MPI
mpirun -np 4 ./esmf_application

# ESMPy quick install
conda install -c conda-forge esmpy
```

---

## 17. References

- ESMF User's Guide: https://earthsystemmodeling.org/docs/release/latest/ESMF_usrdoc/
- ESMF Reference Manual: https://earthsystemmodeling.org/docs/release/latest/ESMF_refdoc/
- NUOPC Layer Reference: https://earthsystemmodeling.org/docs/release/latest/NUOPC_refdoc/
- ESMPy Documentation: https://earthsystemmodeling.org/esmpy_doc/release/latest/html/
- GitHub Repository: https://github.com/esmf-org/esmf
