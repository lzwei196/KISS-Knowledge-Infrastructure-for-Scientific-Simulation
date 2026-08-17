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

# OpenGeoSys 6 (OGS-6) — Knowledge Infrastructure

**Package**: `hydrocraft-ogs-subsurface` v1.0.0
**Model**: OpenGeoSys 6.5.7 — Thermo-Hydro-Mechanical-Chemical simulator
**Domain**: Groundwater / subsurface THMC processes in porous and fractured media
**Created by**: Auto-dissection pipeline
**Last updated**: 2026-03-25
**Stats**: 4 tools | 7 skill documents | 18 diagnostic triplets | ~1,200 lines of validated Python
**Validation status**: `test_validated` (LiquidFlow gravity-driven benchmark)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for recharge forcing documentation.
See `data_ki/GLHYMPS/SKILL.md` for hydrogeology data.
See `data_ki/FanWTD/SKILL.md` for water table depth.
See `data_ki/GRACE/SKILL.md` for GRACE TWS validation data.


## Overview

This knowledge infrastructure enables simulation of subsurface processes using OpenGeoSys 6 (OGS-6), a C++ finite-element simulator for coupled thermo-hydro-mechanical-chemical (THMC) problems in porous and fractured media. The tools replace manual XML editing and VTK post-processing with a Python pipeline that automates project file generation, execution, and output extraction.

**What OGS does**: Multiphysics FEM simulator for subsurface engineering. Simulates:
- Groundwater flow (saturated: LiquidFlow, unsaturated: RichardsFlow)
- Heat transport (HeatConduction, HT advection-diffusion coupling)
- Geomechanics (SmallDeformation, LargeDeformation, HydroMechanics)
- Coupled THMC (ThermoRichardsFlow, ThermoRichardsMechanics, TH2M)
- Reactive transport (ComponentTransport, RichardsComponentTransport)
- Fracture mechanics (PhaseField, LIE lower-dimensional elements)
- Borehole heat exchangers (HeatTransportBHE)
- Wellbore simulation

**Key difference from other HydroCraft models**: OGS solves PDEs on unstructured FEM meshes (VTU format) rather than structured grids. Input is XML-based project files (`.prj`), not namelists or CSV. All units are strict SI (Pa, K, m, s, kg). No unit tolerance — wrong units produce silent garbage.

---

## Installation

### Building from source

```bash
cd KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/OpenGeoSys/source/repo
mkdir -p build && cd build
cmake .. -DOGS_BUILD_CLI=ON -DOGS_BUILD_TESTING=OFF -DOGS_BUILD_UTILS=OFF
make -j$(nproc)
# Binary: build/bin/ogs
```

### Dependencies

```
CMake >= 3.22, C++23 compiler (GCC >= 13, Clang >= 16)
Eigen3, VTK, Boost (header-only), tclap, spdlog, fmt
Optional: PETSc (parallel), MPI, pybind11 (Python bindings)
```

### Python bindings (alternative)

```bash
pip install ogs
# Usage: from ogs import OGSSimulator
```

### Python tool dependencies

```
numpy, pandas, lxml, meshio, matplotlib, pyvista (optional)
```

### Test example

```
Tests/Data/Parabolic/LiquidFlow/GravityDriven/
  gravity_driven.prj          # Project file (XML)
  mesh2D.vtu                  # VTK unstructured mesh
  gravity_driven.gml          # Geometry (boundary definitions)
```

---

## Pipeline (7 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | (manual) | Select process type, domain geometry, simulation period |
| 1 | Domain setup | (mesh tools) | Create/import VTU mesh, define geometry boundaries |
| 2 | Data preparation | `convert_forcing_to_ogs.py` | Convert external data to OGS boundary condition format |
| 3 | Forcing/input | `convert_forcing_to_ogs.py` | Time-dependent BCs: recharge, head, flux (unit conversions) |
| 4 | Parameters | `convert_soil_to_ogs.py` | Material properties: permeability, porosity, density, thermal |
| 5 | Execution | `run_ogs.py` | Generate .prj, run OGS binary, check convergence |
| 6 | Output parsing | `parse_ogs_output.py` | Extract VTU results to CSV time series |

### Parallelism

Stages 1, 2, 3, 4 can run in parallel after stage 0.
Stage 5 depends on 1-4.
Stage 6 depends on 5.

---

## Tools Reference

| Tool | Stage | Script Path | Lines | Purpose |
|------|-------|-------------|------:|---------|
| `convert_forcing_to_ogs` | s2/s3 | `tools/convert_forcing_to_ogs.py` | 280 | External forcing data → OGS boundary condition CSV/VTU |
| `convert_soil_to_ogs` | s4 | `tools/convert_soil_to_ogs.py` | 250 | HWSD/soil database → OGS material properties XML |
| `run_ogs` | s5 | `tools/run_ogs.py` | 320 | Generate .prj, execute OGS, validate output |
| `parse_ogs_output` | s6 | `tools/parse_ogs_output.py` | 290 | Parse VTU output → CSV time series + summary JSON |

**Total**: 4 tools, ~1,140 lines of validated Python code.

---

## Skill Knowledge

| Stage | Topic | Skill Document |
|-------|-------|----------------|
| s0 | Process selection, mesh requirements | `docs/s0_configuration.md` |
| s1 | Mesh formats, VTU structure, boundary submeshes | `docs/s1_domain_setup.md` |
| s2/s3 | Unit conversions (mm→m, °C→K, day→s) | `docs/s2_forcing_input.md` |
| s4 | Permeability, van Genuchten, porosity | `docs/s3_parameters.md` |
| s5 | Project file XML structure, solver config | `docs/s4_execution.md` |
| s6 | VTU parsing, PVD time series, XDMF | `docs/s5_output_parsing.md` |
| all | Coupled processes, staggered vs monolithic | `docs/s6_coupled_processes.md` |

---

## Critical Domain Knowledge

These non-obvious facts cause **silent failures** if violated. Each has a corresponding diagnostic triplet.

### 1. All units are strict SI — no exceptions (dt_001)

OGS uses **SI base units everywhere**: pressure in Pa (not kPa or bar), temperature in Kelvin (not Celsius), length in meters, time in seconds, permeability in m² (not Darcy). There is no unit conversion inside OGS. If you supply permeability in Darcy (1 D = 9.869e-13 m²) without converting, the flow will be wrong by orders of magnitude with no warning.

### 2. Temperature must be in Kelvin (dt_002)

OGS expects temperature in Kelvin. Supplying 20 (meaning 20°C) instead of 293.15 K causes density/viscosity calculations to produce nonsensical results. The Celsius-zero constant is 273.15 K (`PhysicalConstant::CelsiusZeroInKelvin`).

### 3. Permeability is intrinsic (m²), NOT hydraulic conductivity (m/s) (dt_003)

OGS uses intrinsic permeability κ [m²], not hydraulic conductivity K [m/s]. Conversion: `κ = K * μ / (ρ * g)`. For water at 20°C: `κ ≈ K * 1.02e-7`. Supplying K=1e-5 m/s as κ=1e-5 m² makes the medium 10 million times too permeable.

### 4. Time is in seconds in project files (dt_004)

All time values in `.prj` files are in seconds: `t_initial`, `t_end`, `delta_t`. One day = 86400 s, one year ≈ 3.1536e7 s. Setting `t_end=365` (meaning 365 days) actually runs for 365 seconds (6 minutes).

### 5. Mesh boundary conditions require submeshes (dt_005)

OGS-6 applies boundary conditions on **submeshes** (separate `.vtu` files for boundary faces), not on geometry-based selections like OGS-5. Each BC needs a matching submesh file that extracts boundary faces from the bulk mesh. Missing submeshes → crash.

### 6. Body force vector must match mesh dimension (dt_006)

`<specific_body_force>` must have exactly as many components as the mesh dimension. 2D mesh: `"0 -9.81"`, 3D mesh: `"0 0 -9.81"`. Wrong dimension count crashes the parser silently or misaligns gravity direction.

### 7. van Genuchten parameters are model-specific (dt_007)

OGS uses the van Genuchten-Mualem model with parameters: `p_b` (entry pressure, Pa), `S_L_res` (residual saturation), `S_L_max` (max saturation), `m` or `n` where `m = 1 - 1/n`. Literature often reports α [1/cm] which needs conversion: `p_b = ρ*g/α` (with α in 1/m). Off by 100x if α is not converted from 1/cm to 1/m.

### 8. Convergence criterion type matters (dt_008)

`DeltaX` checks solution increment norm, `Residual` checks residual norm. Using wrong type with wrong tolerance causes either non-convergence (too tight) or unconverged garbage (too loose). For pressure problems: `DeltaX` with `abstol=1e-6` is typical. For displacement: `abstol=1e-10` (meters).

### 9. Storage coefficient must be non-zero for transient flow (dt_009)

For transient LiquidFlow, the `storage` property (specific storage, 1/Pa) must be > 0. If set to 0 (steady-state assumption), the mass matrix M=0 and the transient solver degenerates, producing constant pressure at all timesteps.

---

## Input File Format (.prj)

OGS uses XML project files with this top-level structure:

```xml
<OpenGeoSysProject>
  <meshes>                    <!-- VTU mesh files -->
    <mesh>domain.vtu</mesh>
    <mesh>boundary_left.vtu</mesh>
  </meshes>
  <processes>                 <!-- Physics: LIQUID_FLOW, RICHARDS_FLOW, etc. -->
    <process>
      <type>LIQUID_FLOW</type>
      <process_variables><process_variable>pressure</process_variable></process_variables>
      <specific_body_force>0 -9.81</specific_body_force>
    </process>
  </processes>
  <media>                     <!-- Material properties (SI units) -->
    <medium id="0">
      <phases><phase><type>AqueousLiquid</type>...</phase></phases>
      <properties>
        <property><name>permeability</name><value>1e-12</value></property>
        <property><name>porosity</name><value>0.3</value></property>
        <property><name>storage</name><value>1e-9</value></property>
      </properties>
    </medium>
  </media>
  <time_loop>                 <!-- Timestepping and output -->
    <processes><process ref="...">
      <time_stepping><type>FixedTimeStepping</type>
        <t_initial>0</t_initial><t_end>86400</t_end>
      </time_stepping>
    </process></processes>
    <output><type>VTK</type><prefix>result</prefix></output>
  </time_loop>
  <parameters>                <!-- Named constants/functions -->
  <process_variables>         <!-- ICs, BCs, source terms -->
  <nonlinear_solvers>         <!-- Picard or Newton -->
  <linear_solvers>            <!-- Eigen/PETSc solver config -->
</OpenGeoSysProject>
```

---

## Key Variables and Units (ALL SI)

| Variable | Symbol | Unit | Typical Range |
|----------|--------|------|---------------|
| Pressure (hydraulic head) | p | Pa | 0 – 1e7 |
| Temperature | T | K | 273 – 373 |
| Displacement | u | m | 0 – 0.1 |
| Permeability (intrinsic) | κ | m² | 1e-18 – 1e-8 |
| Porosity | φ | – | 0.01 – 0.6 |
| Density (liquid) | ρ_L | kg/m³ | 998 – 1050 |
| Viscosity (dynamic) | μ | Pa·s | 1e-4 – 1e-2 |
| Storage coefficient | S_s | 1/Pa | 1e-12 – 1e-6 |
| Thermal conductivity | λ | W/(m·K) | 0.1 – 5.0 |
| Specific heat capacity | c_p | J/(kg·K) | 800 – 4200 |
| Darcy velocity | v | m/s | 1e-12 – 1e-3 |
| Stress | σ | Pa | 0 – 1e8 |
| Strain | ε | – | 0 – 0.01 |
| Liquid saturation | S_L | – | 0 – 1 |
| Capillary pressure | p_c | Pa | 0 – 1e6 |
| Concentration | c | mol/m³ | 0 – 1e3 |

---

## Unit Trap Table

| External Source | Variable | Source Unit | OGS Unit | Conversion | Trap Severity |
|----------------|----------|------------|----------|------------|---------------|
| HWSD soil data | Permeability | cm/hr (Ksat) | m² | K_sat[m/s] × 1.02e-7 | **silent** |
| Weather station | Temperature | °C | K | T + 273.15 | **silent** |
| Weather station | Precipitation | mm/day | m/s | P / (1000 × 86400) | **silent** |
| MODFLOW | Hydraulic head | m (head) | Pa | h × ρ × g | **silent** |
| Literature | Permeability | Darcy | m² | κ × 9.869e-13 | **silent** |
| Literature | vG alpha | 1/cm | 1/Pa | p_b = ρ·g/(α×100) | **silent** |
| Well test | Transmissivity | m²/s | m² | T / aquifer_thickness × μ/(ρg) | **silent** |
| Time specs | Duration | days/years | seconds | × 86400 or × 3.1536e7 | **silent** |

---

## Supported Process Types

| Process Type Enum | Description | Primary Variables |
|-------------------|-------------|-------------------|
| `LIQUID_FLOW` | Saturated groundwater flow | pressure |
| `RICHARDS_FLOW` | Unsaturated flow | pressure |
| `STEADY_STATE_DIFFUSION` | Steady diffusion (Laplace) | pressure/concentration |
| `HEAT_CONDUCTION` | Pure heat conduction | temperature |
| `HT` | Heat transport (advection-diffusion) | temperature, pressure |
| `HYDRO_MECHANICS` | Coupled flow + deformation | pressure, displacement |
| `THERMO_MECHANICS` | Coupled heat + deformation | temperature, displacement |
| `SMALL_DEFORMATION` | Linear elasticity | displacement |
| `LARGE_DEFORMATION` | Nonlinear elasticity | displacement |
| `RICHARDS_MECHANICS` | Unsaturated flow + deformation | pressure, displacement |
| `THERMO_RICHARDS_FLOW` | Heat + unsaturated flow | temperature, pressure |
| `THERMO_RICHARDS_MECHANICS` | Heat + unsaturated + deformation | T, p, u |
| `TH2M` | Full two-phase THM | gas_p, cap_p, T, u |
| `COMPONENT_TRANSPORT` | Reactive transport | concentration(s), pressure |
| `HEAT_TRANSPORT_BHE` | Borehole heat exchangers | temperature |

---

## Output Format

OGS writes results as VTK Unstructured Grid files:

```
result_ts_0_t_0.000000.vtu          # Initial condition
result_ts_1_t_86400.000000.vtu      # After 1 day (86400 s)
result_ts_2_t_172800.000000.vtu     # After 2 days
result.pvd                          # PVD collection file (time series index)
```

**VTU files contain**: node-based fields (pressure, displacement, temperature) and cell-based fields (velocity, stress, strain). Parse with `meshio`, `pyvista`, or `vtk` Python libraries.

**PVD file**: XML index linking timesteps to VTU files. Use to reconstruct time series.

**Alternative**: XDMF/HDF5 format for large parallel runs (`<type>XDMF_HDF5</type>`).

---

## CLI Usage

```bash
ogs project.prj [options]

Options:
  -o, --output-directory DIR    Output directory for results
  -m, --mesh-input-directory DIR   Directory containing mesh files
  -p, --xml-patch FILE          Apply XML patch to project file (repeatable)
  --write-prj                   Write processed project file to output
  --enable-fpe                  Enable floating-point exceptions
  --unbuffered-std-out          Unbuffered stdout for real-time logging
```

---

## Quick Start

```bash
# 1. Convert soil parameters to OGS format
python tools/convert_soil_to_ogs.py \
  --sand 60 --clay 15 --silt 25 --organic 2.0 --bulk_density 1500 \
  --output soil_params.json

# 2. Convert forcing data (recharge) to OGS format
python tools/convert_forcing_to_ogs.py \
  --source recharge_mm_day.csv --source_format csv \
  --variable recharge --source_unit mm/day --target_unit m/s \
  --start_date 2000-01-01 --end_date 2010-12-31 \
  --output recharge_ogs.csv

# 3. Run OGS simulation
python tools/run_ogs.py \
  --prj_template project_template.prj \
  --mesh domain.vtu --output_dir results/ \
  --ogs_binary /path/to/ogs

# 4. Parse output to CSV
python tools/parse_ogs_output.py \
  --pvd_file results/result.pvd \
  --variables pressure,v \
  --point "50.0,0.0" \
  --output results/timeseries.csv
```

---

## Diagnostic Triplets

18 triplets covering 5 failure domains. See `diagnostics/triplets.yaml` for full details.

| ID | Severity | Domain | Summary |
|----|----------|--------|---------|
| dt_001 | **silent** | unit_conversion | Pressure in kPa instead of Pa |
| dt_002 | **silent** | unit_conversion | Temperature in °C instead of K |
| dt_003 | **silent** | unit_conversion | Permeability in Darcy instead of m² |
| dt_004 | **silent** | unit_conversion | Time in days instead of seconds |
| dt_005 | fatal | mesh_format | Missing boundary submesh for BCs |
| dt_006 | fatal | parameter_format | Body force dimension mismatch |
| dt_007 | **silent** | unit_conversion | van Genuchten α in 1/cm not converted |
| dt_008 | degraded | solver_config | Wrong convergence criterion type/tolerance |
| dt_009 | **silent** | parameter_format | Storage=0 in transient simulation |
| dt_010 | fatal | path_resolution | Mesh file not found (relative path) |
| dt_011 | **silent** | silent_error | Hydraulic conductivity used as permeability |
| dt_012 | degraded | solver_config | Newton diverges — need Picard first |
| dt_013 | **silent** | silent_error | Recharge in mm/day not converted to m/s |
| dt_014 | fatal | parameter_format | XML tag misspelling (case-sensitive) |
| dt_015 | **silent** | unit_conversion | Precipitation mm/day → m/s missing /86400 |
| dt_016 | degraded | mesh_format | Mesh element order mismatch with FE order |
| dt_017 | **silent** | silent_error | Porosity=0 kills transient storage |
| dt_018 | fatal | runtime | NaN from zero viscosity or density |

**Silent error count**: 10/18 (56%) — dominated by unit conversion traps due to strict SI requirement.

---

## File Structure

```
ki/
  SKILL.md                          # This file (agent entry point)
  knowledge_infrastructure.yaml     # Auto-generated schema
  tools/
    convert_forcing_to_ogs.py       # External data → OGS boundary conditions
    convert_soil_to_ogs.py          # HWSD/soil → OGS material properties
    run_ogs.py                      # OGS execution wrapper
    parse_ogs_output.py             # VTU/PVD → CSV time series
  docs/
    s0_configuration.md             # Process selection, mesh requirements
    s1_domain_setup.md              # Mesh formats, boundary submeshes
    s2_forcing_input.md             # Unit conversions, BC types
    s3_parameters.md                # Material properties, constitutive models
    s4_execution.md                 # Project file structure, solver config
    s5_output_parsing.md            # VTU format, time series extraction
    s6_coupled_processes.md         # Multi-physics coupling strategies
  diagnostics/
    triplets.yaml                   # 18 diagnostic triplets
```
