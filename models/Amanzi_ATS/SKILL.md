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

# Amanzi / ATS (Advanced Terrestrial Simulator) — Knowledge Infrastructure

**Package**: `hydrocraft-amanzi-ats` v1.0.0
**Model**: Amanzi + ATS (Advanced Terrestrial Simulator)
**Domain**: Groundwater flow, reactive transport, integrated surface-subsurface hydrology
**Created by**: Auto-dissection pipeline
**Last updated**: 2026-03-25
**Stats**: 4 tools | 5 skill documents | 18 diagnostic triplets | ~1,200 lines of validated Python
**Validation status**: `demo_validated` (Richards steady-state, 1D column)

---

## Overview

This knowledge infrastructure enables autonomous simulation of subsurface flow and reactive transport using Amanzi/ATS. The 4 validated tools replace manual XML editing and HDF5 parsing with a Python pipeline that integrates directly with HydroCraft's forcing, soil, and output infrastructure.

**What Amanzi/ATS does**: Multi-physics framework for environmental subsurface simulation:
- Variably saturated flow (Richards equation with van Genuchten/Brooks-Corey)
- Reactive transport (advection-dispersion with Alquimia chemistry interface)
- Energy transport (conduction, advection, phase change)
- Surface-subsurface coupling (overland flow, infiltration/exfiltration)
- Discrete fracture networks (DFN-matrix coupling)
- Contaminant migration (sorption, decay chains, mineral precipitation)
- Integrated hydrology (ATS: coupled surface/subsurface thermal hydrology)

**Key difference from other HydroCraft models**: Amanzi/ATS is a DOE-developed C++ framework that uses XML ParameterList input files, Exodus II meshes, and HDF5/XDMF output. It requires MPI and multiple third-party libraries (Trilinos, Hypre, MSTK, PETSc). ATS extends Amanzi with permafrost, surface flow, and snow physics.

---

## Installation

### Prerequisites

```
cmake >= 3.23
C++17 compiler (g++, clang++, icc)
MPI (OpenMPI or MPICH)
BLAS/LAPACK
Python 3.x
```

### Build from Source (bootstrap method)

```bash
# Set environment
export ATS_BASE=/path/to/ats
export ATS_BUILD_TYPE=Release
export ATS_VERSION=master
export OPENMPI_DIR=/path/to/mpi

export AMANZI_SRC_DIR=${ATS_BASE}/repos/amanzi
export AMANZI_BUILD_DIR=${ATS_BASE}/amanzi-build-${ATS_VERSION}-${ATS_BUILD_TYPE}
export AMANZI_DIR=${ATS_BASE}/amanzi-install-${ATS_VERSION}-${ATS_BUILD_TYPE}
export AMANZI_TPLS_DIR=${ATS_BASE}/amanzi_tpls-install-${ATS_VERSION}-${ATS_BUILD_TYPE}
export AMANZI_TPLS_BUILD_DIR=${ATS_BASE}/amanzi_tpls-build-${ATS_VERSION}-${ATS_BUILD_TYPE}

# Clone and build
git clone -b master http://github.com/amanzi/amanzi $AMANZI_SRC_DIR
. ${AMANZI_SRC_DIR}/build_ATS_generic.sh
# Takes 10-60 minutes; downloads ~3.5 GB of TPLs

# Binary at ${AMANZI_DIR}/bin/amanzi (or ats)
export PATH=${AMANZI_DIR}/bin:${PATH}
```

### Third-Party Libraries (TPLs)

| TPL | Purpose | Required |
|-----|---------|----------|
| Trilinos | Linear/nonlinear solvers (ML, AztecOO, Belos, Ifpack) | Yes |
| Hypre | Algebraic multigrid (BoomerAMG) | Yes |
| MSTK | Polyhedral mesh infrastructure | Yes |
| HDF5 | Parallel checkpoint and visualization I/O | Yes |
| NetCDF | Data I/O (with Fortran interface) | Yes |
| ExodusII | Mesh file format (via Trilinos/SEACAS) | Yes |
| Boost | C++ utilities (1.61.0+) | Yes |
| PETSc | Optional advanced solvers | Optional |
| Alquimia | Chemistry interface (PFloTran, CrunchFlow) | Optional |
| Silo | Visualization alternative to HDF5 | Optional |

### Python Dependencies

```
h5py, numpy, pandas, matplotlib, lxml
```

### Test Example

```bash
cd ats-demos/01_richards_steadystate
mkdir run && cd run
ats --xml_file=../richards_steadystate.xml &> out.log
```

---

## Pipeline (7 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 1 | Forcing preparation | `convert_forcing_to_amanzi` | Met/recharge data to Amanzi XML boundary conditions |
| 2 | Soil/material parameterization | `convert_soil_to_amanzi` | HWSD/SOILGRIDS to van Genuchten/Brooks-Corey params |
| 3 | Mesh generation | (external: MSTK/Exodus tools) | Generate or obtain Exodus II mesh |
| 4 | XML input assembly | (manual or template-based) | Assemble complete XML ParameterList input file |
| 5 | Execution | `run_amanzi` | Run Amanzi/ATS with preflight checks |
| 6 | Output parsing | `parse_amanzi_output` | Extract HDF5/XDMF results to CSV |
| 7 | Validation & analysis | (downstream) | Compare to observations, compute metrics |

### Parallelism

Stages 1 and 2 can run in parallel.
Stage 4 depends on 1, 2, and 3.
Stage 5 depends on 4.
Stages 6 and 7 depend on 5.

---

## Tools Reference

| Tool | Stage | Script Path | Purpose |
|------|-------|-------------|---------|
| `convert_forcing_to_amanzi` | s1 | `tools/convert_forcing_to_amanzi.py` | Global forcing → Amanzi XML BC (mm→m, K→C) |
| `convert_soil_to_amanzi` | s2 | `tools/convert_soil_to_amanzi.py` | HWSD soil → van Genuchten params (cm→m, cm/day→m/s) |
| `run_amanzi` | s5 | `tools/run_amanzi.py` | Execute Amanzi/ATS with validation |
| `parse_amanzi_output` | s6 | `tools/parse_amanzi_output.py` | HDF5/observation → CSV extraction |

**Total**: 4 tools, ~1,200 lines of validated Python code.

---

## Input Format: XML ParameterList

Amanzi uses Teuchos XML ParameterList format. Two schema versions exist:

### Version 1.x (ParameterList style)
```xml
<ParameterList name="Main">
  <Parameter name="Amanzi Input Format Version" type="string" value="1.2.2"/>
  <ParameterList name="Execution Control">
    <Parameter name="Flow Model" type="string" value="Richards"/>
    <Parameter name="Transport Model" type="string" value="On"/>
  </ParameterList>
  <ParameterList name="Mesh">...</ParameterList>
  <ParameterList name="Regions">...</ParameterList>
  <ParameterList name="Material Properties">...</ParameterList>
  <ParameterList name="Initial Conditions">...</ParameterList>
  <ParameterList name="Boundary Conditions">...</ParameterList>
  <ParameterList name="Output">...</ParameterList>
</ParameterList>
```

### Version 2.x (amanzi_input style)
```xml
<amanzi_input version="2.3.2" type="unstructured">
  <model_description name="Problem Name">
    <units>
      <length_unit>m</length_unit>
      <time_unit>s</time_unit>
      <mass_unit>kg</mass_unit>
      <conc_unit>molar</conc_unit>
    </units>
  </model_description>
  <process_kernels>
    <flow state="on" model="richards"/>
    <transport state="on"/>
    <chemistry engine="amanzi" state="off"/>
  </process_kernels>
  <mesh framework="mstk">
    <dimension>3</dimension>
    <generate>
      <number_of_cells nx="100" ny="1" nz="50"/>
      <box low_coordinates="0.0,0.0,0.0" high_coordinates="100.0,1.0,50.0"/>
    </generate>
  </mesh>
  <regions>...</regions>
  <materials>...</materials>
  <initial_conditions>...</initial_conditions>
  <boundary_conditions>...</boundary_conditions>
  <output>...</output>
</amanzi_input>
```

### Key XML Blocks

| Block | Purpose | Critical Parameters |
|-------|---------|-------------------|
| `mesh` | Mesh definition (generate or read .exo file) | framework=mstk, dimension, nx/ny/nz |
| `regions` | Named spatial regions for BCs/ICs | box, plane, labeled_set (from Exodus) |
| `materials` | Porosity, permeability, retention curves | van Genuchten α, n, Sr; K_sat |
| `initial_conditions` | Starting pressure/concentration/temperature | linear_pressure, uniform |
| `boundary_conditions` | Fluxes, pressures, concentrations | mass_flux, uniform_pressure, seepage_face |
| `output` | Visualization, checkpoint, observations | vis (HDF5), checkpoint, obs points |
| `execution_control` | Time stepping, steady/transient modes | start, end, init_dt, max_dt |
| `numerical_controls` | Linear/nonlinear solver settings | gmres, hypre_amg, NKA |

---

## Unit System

**Amanzi uses SI units internally:**

| Quantity | Unit | Notes |
|----------|------|-------|
| Length | m (meters) | All spatial dimensions |
| Time | s (seconds) | Internal timestep; input can use y, d, hr |
| Mass | kg | |
| Pressure | Pa (Pascals) | Atmospheric = 101325 Pa |
| Temperature | K (Kelvin) | For energy equation |
| Concentration | mol/L (molar) | Default; can switch to mol/m³ |
| Permeability | m² | Intrinsic permeability (NOT hydraulic conductivity) |
| Viscosity | Pa·s | Water ≈ 0.001 Pa·s |
| Density | kg/m³ | Water ≈ 998.2 kg/m³ |
| Flux | kg/m²/s | Mass flux for BCs |
| Porosity | dimensionless | 0–1 |
| Saturation | dimensionless | 0–1 |
| Darcy velocity | m/s | |

### Unit Trap Table (CRITICAL)

| Trap | Source Unit | Amanzi Unit | Factor | Silent? |
|------|-----------|-------------|--------|---------|
| Precipitation mm→m | mm/hr | m/s | ÷3.6e6 | Yes |
| Hydraulic conductivity → permeability | m/s (K) | m² (k) | k = K·μ/(ρg) ≈ K × 1.02e-7 | Yes |
| Temperature C→K | °C | K | +273.15 | Yes |
| Pressure head → Pa | m (head) | Pa | ×ρg ≈ ×9806.65 | Yes |
| Recharge cm/yr → kg/m²/s | cm/yr | kg/m²/s | ×998.2/(100×3.156e7) | Yes |
| van Genuchten α cm⁻¹→m⁻¹ | 1/cm | 1/m | ×100 | Yes |
| Time yr→s | years | seconds | ×3.156e7 | No |
| Kd mL/g → m³/kg | mL/g | m³/kg | ×0.001 | Yes |

---

## Output Format

### Visualization (HDF5/XDMF)
- Files: `{base_name}_data.h5` + `{base_name}_mesh.h5` + `{base_name}.xmf`
- Contains: pressure, saturation, velocity, concentration fields on mesh
- Viewable in: ParaView, VisIt

### Checkpoint (HDF5)
- Full state for restart capability
- Files: `checkpoint{NNNNN}.h5`

### Observations (text or HDF5)
- Point-wise time series at specified regions
- Types: aqueous_pressure, hydraulic_head, drawdown, aqueous_conc, volumetric_flux, water_table
- Format: ASCII columns (time | var1 | var2 | ...)

### Output Configuration
```xml
<output>
  <vis>
    <base_filename>plot</base_filename>
    <num_digits>5</num_digits>
    <time_macros>Every_year</time_macros>
  </vis>
  <checkpoint>
    <base_filename>checkpoint</base_filename>
    <num_digits>5</num_digits>
    <cycle_macros>Every_1000_steps</cycle_macros>
  </checkpoint>
  <observations>
    <filename>observations.out</filename>
    <liquid_phase name="water">
      <aqueous_pressure>
        <assigned_regions>Well_1</assigned_regions>
        <functional>point</functional>
        <time_macros>Observation_Times</time_macros>
      </aqueous_pressure>
    </liquid_phase>
  </observations>
</output>
```

---

## Critical Domain Knowledge

### 1. Permeability ≠ Hydraulic Conductivity (dt_001)
Amanzi uses intrinsic permeability k [m²], NOT hydraulic conductivity K [m/s]. Conversion: k = K·μ/(ρ·g). For water at 20°C: k ≈ K × 1.02e-7. Using K directly as k gives permeability 7 orders of magnitude too high — water flows unrealistically fast with no error message.

### 2. Pressure in Pascals, NOT Head in Meters (dt_002)
Initial and boundary conditions specify pressure in Pa, not hydraulic head in meters. Hydrostatic pressure: P = P_atm + ρ·g·(z_wt - z). The reference gradient for gravity is -9806.65 Pa/m (= -ρ·g). Specifying head values (e.g., 10) as pressure gives essentially zero pressure.

### 3. Concentration in mol/L (molar), NOT mg/L (dt_003)
Default concentration unit is mol/L. Using mg/L values without conversion gives concentrations off by molecular_weight/1000. For uranium (MW=238): 1 mg/L = 4.2e-6 mol/L.

### 4. van Genuchten α in 1/Pa (internally) (dt_004)
Literature often reports α in 1/cm. Amanzi expects α in 1/Pa. Conversion: α_Pa = α_cm / (ρ·g·100) ≈ α_cm / 980665. Using α_cm directly gives extremely high α, meaning the soil drains instantly.

### 5. Exodus II Mesh Labeling Must Match Regions (dt_005)
Region definitions reference labeled sets in the Exodus mesh file by integer ID. A mismatch between the XML label ID and the mesh's sideset/nodeset IDs causes silent assignment of zero boundary conditions.

### 6. Time Units in XML Can Vary (dt_006)
The `<time_unit>` in model_description sets the display unit, but execution_control attributes can use suffixed units (e.g., "0.1 y", "86400.0"). Internal time is always seconds. Mixing conventions without explicit suffixes leads to simulations running 3.156e7× too long or too short.

### 7. MPI Rank Count Affects Mesh Partitioning (dt_007)
Running with different MPI rank counts can change mesh partitioning and slightly alter results due to solver convergence paths. Always document the rank count used for reproducibility.

### 8. Gravity Vector Must Be Negative Z (dt_008)
Gravity is specified as a 3D vector, typically (0, 0, -9.81). A positive Z gravity or incorrect magnitude silently produces upward flow or wrong pressure gradients.

---

## Calibration Parameters (Priority Order)

| Parameter | Block | Range | Controls | Sensitivity |
|-----------|-------|-------|----------|-------------|
| K_sat (via permeability) | materials | 1e-16 – 1e-9 m² | Flow rate, water table | HIGH |
| van Genuchten α | materials | 1e-5 – 1e-2 1/Pa | Capillary pressure, drainage | HIGH |
| van Genuchten n | materials | 1.1 – 3.0 | Retention curve shape | HIGH |
| Porosity | materials | 0.01 – 0.6 | Storage, velocity | MEDIUM |
| Residual saturation | materials | 0.01 – 0.3 | Minimum water content | MEDIUM |
| Recharge rate | boundary_conditions | 0 – 500 mm/yr | Water input | MEDIUM |
| Dispersivity | transport | 0.1 – 100 m | Plume spreading | MEDIUM |
| Kd (sorption) | chemistry | 0 – 1000 mL/g | Retardation | HIGH (transport) |

---

## Coupling Points

| # | Source | Target | Variable | Conversion |
|---|--------|--------|----------|------------|
| 1 | ERA5/CMFD | Amanzi | Recharge flux | mm/hr → kg/m²/s |
| 2 | HWSD/SoilGrids | Amanzi | K_sat, porosity, vG params | cm/day→m², texture→vG |
| 3 | Amanzi | VIC/SWAT | Water table depth | Pa → m head |
| 4 | Amanzi | CaMa-Flood | Baseflow discharge | m³/s |
| 5 | MODFLOW | Amanzi | Head boundary conditions | m → Pa |

---

## Diagnostic Triplets Summary

18 triplets covering 5 failure domains. See `diagnostics/triplets.yaml` for full details.

| ID | Severity | Domain | Summary |
|----|----------|--------|---------|
| dt_001 | **silent** | unit_conversion | Permeability vs hydraulic conductivity (7 orders of magnitude) |
| dt_002 | **silent** | unit_conversion | Pressure in Pa vs head in meters |
| dt_003 | **silent** | unit_conversion | Concentration mol/L vs mg/L |
| dt_004 | **silent** | unit_conversion | van Genuchten α: 1/cm vs 1/Pa |
| dt_005 | **silent** | mesh_region | Exodus label ID mismatch with XML regions |
| dt_006 | **silent** | unit_conversion | Time unit mixing (years vs seconds) |
| dt_007 | degraded | runtime | MPI rank count affects partitioning |
| dt_008 | **silent** | parameter_format | Gravity vector sign/magnitude wrong |
| dt_009 | fatal | parameter_format | Mesh dimension mismatch (2D input, 3D mesh) |
| dt_010 | fatal | path_resolution | Exodus mesh file not found |
| dt_011 | **silent** | unit_conversion | Recharge cm/yr → kg/m²/s conversion |
| dt_012 | **silent** | unit_conversion | Kd mL/g → m³/kg conversion |
| dt_013 | fatal | runtime | NaN from extreme permeability values |
| dt_014 | degraded | runtime | Solver non-convergence from stiff vG params |
| dt_015 | **silent** | parameter_format | Residual saturation ≥ 1.0 |
| dt_016 | fatal | parameter_format | Missing required XML block |
| dt_017 | **silent** | silent_error | Zero-flux BC applied where recharge intended |
| dt_018 | degraded | runtime | Timestep collapse from sharp wetting front |

**Silent error count**: 10/18 (56%) — dominated by unit conversion traps.

---

## File Structure

```
ki/
  SKILL.md                              # This file (agent entry point)
  knowledge_infrastructure.yaml         # Schema-compliant package definition
  tools/
    convert_forcing_to_amanzi.py        # Met/recharge → Amanzi XML BCs
    convert_soil_to_amanzi.py           # HWSD → van Genuchten parameters
    run_amanzi.py                       # Execution wrapper with validation
    parse_amanzi_output.py              # HDF5/observation → CSV
  docs/
    s1_forcing_preparation.md           # Forcing data conversion skill
    s2_soil_parameterization.md         # Soil parameter estimation skill
    s3_mesh_generation.md               # Mesh creation and formatting skill
    s4_xml_input_assembly.md            # XML input file construction skill
    s5_execution_and_output.md          # Running and parsing output skill
  diagnostics/
    triplets.yaml                       # 18 diagnostic triplets
```

---

## Quick Start

```bash
# 1. Convert soil parameters
python ki/tools/convert_soil_to_amanzi.py \
  --texture "sandy loam" --ksat_cm_day 106.1 \
  --porosity 0.41 --residual_sat 0.065 \
  --output soil_params.json

# 2. Convert forcing/recharge
python ki/tools/convert_forcing_to_amanzi.py \
  --recharge_mm_yr 300 --start_year 2000 --end_year 2010 \
  --output recharge_bc.json

# 3. Run Amanzi (requires compiled binary + XML input)
python ki/tools/run_amanzi.py \
  --xml_file input.xml --np 4 --run_dir ./run

# 4. Parse output
python ki/tools/parse_amanzi_output.py \
  --obs_file run/observations.out \
  --vis_file run/plot_data.h5 \
  --output results.csv
```
