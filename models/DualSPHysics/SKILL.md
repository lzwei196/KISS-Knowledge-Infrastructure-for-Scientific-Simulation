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
| to run the pipeline stages | `tools/` (5 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (5 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (18 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (23 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/convert_forcing_to_dsph.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing_to_dsph.py --help` |
| `tools/convert_parameters.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_parameters.py --help` |
| `tools/generate_case_xml.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/generate_case_xml.py --help` |
| `tools/parse_dsph_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_dsph_output.py --help` |
| `tools/run_dualsphysics.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_dualsphysics.py --help` |

*5 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# DualSPHysics v5.4 — Knowledge Infrastructure

**Package**: `hydrocraft-dualsphysics-ocean` v1.0.0
**Model**: DualSPHysics v5.4.355 (Smoothed Particle Hydrodynamics)
**Domain**: Coastal/ocean engineering, free-surface flows
**Last updated**: 2026-03-26
**Stats**: 5 tools | 5 skill documents | 18 diagnostic triplets | ~2,000 lines of validated Python
**Validation status**: `example_validated` (DamBreak benchmark, Koshizuka & Oka 1996)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for atmospheric forcing documentation.
See `data_ki/NOAA_Tides/SKILL.md` for tidal observation data.
See `data_ki/NDBC/SKILL.md` for wave buoy observations.


## Overview

This knowledge infrastructure enables fully autonomous simulation of free-surface hydrodynamic flows using DualSPHysics, a meshless Smoothed Particle Hydrodynamics (SPH) solver. The tools replace the manual XML-editing + shell-scripting workflow with a Python pipeline that integrates with HydroCraft's coastal/ocean infrastructure.

**What DualSPHysics does**: 3D meshless particle-based hydrodynamic solver. Simulates:
- Free-surface flows (dam breaks, wave impacts, flooding)
- Wave generation and propagation (piston/flap paddles, spectral)
- Wave-structure interaction (forces on offshore structures)
- Floating body dynamics (6-DOF via Chrono coupling)
- Inlet/outlet boundary conditions (open channel flow)
- Mooring line dynamics (MoorDyn+ coupling)
- Multi-phase flows (liquid-gas, non-Newtonian)
- Variable resolution (VRes) for multi-scale problems

**Key difference from Eulerian HydroCraft models**: DualSPHysics is a Lagrangian particle method — the computational domain is represented by discrete particles, not a fixed grid. This is ideal for violent free-surface flows, wave breaking, and complex moving boundaries where mesh-based methods struggle.

**All units are SI**: meters (m), seconds (s), kilograms per cubic meter (kg/m^3), Pascals (Pa), meters per second (m/s).

---

## 3. Input Requirements

**Exact shapes live in `docs/format_spec.yaml`** (projected from `dag.yaml` + `diagnostics/triplets.yaml`; regenerate it after changing either source, never hand-edit it). This section summarizes the intent; the spec file is the contract.

| Input family | Model unit / format | Prepared by | Notes |
|--------------|---------------------|-------------|-------|
| XML case definition | DualSPHysics XML | `tools/generate_case_xml.py` | Geometry, constants, particle spacing, and execution parameters. |
| Wave forcing | m, s | `tools/convert_forcing_to_dsph.py` | Wave height and water level must be meters; wave period must be seconds. |
| Inlet/current forcing | m/s | `tools/convert_forcing_to_dsph.py` | Convert cm/s, knots, km/h, or ft/s before building inlet/outlet XML. |
| Physical/numerical parameters | SI or dimensionless as specified | `tools/convert_parameters.py` | `Visco` has conditional units depending on `ViscoTreatment`. |
| Initial particle distribution | `.bi4` generated from XML | `GenCase` | Produced from the XML geometry and consumed by the solver. |

---

## 6. Output Description

**Source: `dag.yaml`. If this section and the dag disagree, the dag wins.**

**Headline output** (dag `validation_rank: 1`; this is the variable the model is judged by):

> `water_surface_elevation` - Free-surface elevation derived from particle positions / isosurface or a virtual wave gauge (MeasureTool). (`m`)

Other dag outputs are `pressure`, `force_on_structure`, and `velocity`.

| Output variable (dag `var`) | Rank | Emitted in | Unit | Description |
|-----------------------------|------|------------|------|-------------|
| `water_surface_elevation` | 1 | `Part_XXXX.bi4` via IsoSurface / MeasureTool gauge | m | Free-surface elevation derived from particle positions / isosurface or a virtual wave gauge (MeasureTool). |
| `pressure` | 2 | `Part_XXXX.bi4` press field, exported via PartVTK/MeasureTool | Pa | Per-water-particle pressure from the Tait equation of state; total pressure (hydrostatic + dynamic) unless the rho*g*z component is removed. |
| `force_on_structure` | 3 | CSV via ComputeForces | N | Integrated wave-water force on a given MK boundary structure (via ComputeForces). |
| `velocity` | 4 | `Part_XXXX.bi4` vel field | m/s | Per-water-particle velocity (and magnitude) interpolated to gauges via MeasureTool. |

---

## 8. Unit Conversion Table

**Critical**: Every model-facing value is SI unless the parameter is explicitly dimensionless. Verify source attributes before converting.

| Variable | Source unit | Model unit | Factor / conversion | Type |
|----------|-------------|------------|---------------------|------|
| Wave height / free-surface elevation / water level | cm | m | divide by 100 | multiplicative |
| Particle spacing (`dp`) / geometry position | mm | m | divide by 1000 | multiplicative |
| Particle spacing (`dp`) / geometry position | cm | m | divide by 100 | multiplicative |
| Density (`rhop0`) | g/cm^3 | kg/m^3 | multiply by 1000 | multiplicative |
| Gravity | cm/s^2 | m/s^2 | divide by 100 | multiplicative |
| Inlet/current velocity | cm/s | m/s | divide by 100 | multiplicative |
| Inlet/current velocity | knots | m/s | multiply by 0.5144 | multiplicative |
| Time | minutes | s | multiply by 60 | multiplicative |
| Time | hours | s | multiply by 3600 | multiplicative |
| Pressure output | kPa | Pa | multiply by 1000 | multiplicative |
| Pressure output | bar | Pa | multiply by 100000 | multiplicative |
| Pressure output | atm | Pa | multiply by 101325 | multiplicative |
| Artificial viscosity (`ViscoTreatment=1`) | dimensionless | dimensionless | no conversion needed | none |
| Laminar viscosity (`ViscoTreatment=2` or `3`) | cm^2/s | m^2/s | divide by 10000 | multiplicative |

---

## Installation

### Pre-built Binaries

```
GenCase:         bin/linux/GenCase_linux64          (case generator)
DualSPHysics:   bin/linux/DualSPHysics5.4CPU_linux64  (CPU solver)
DualSPHysics:   bin/linux/DualSPHysics5.4_linux64     (GPU+CPU solver, requires CUDA)
PartVTK:        bin/linux/PartVTK_linux64           (bi4 -> VTK converter)
MeasureTool:    bin/linux/MeasureTool_linux64        (interpolation at points)
IsoSurface:     bin/linux/IsoSurface_linux64         (free-surface extraction)
```

### Compiling from Source (CPU-only)

```bash
cd src/source/
make -f Makefile_cpu
# Output: bin/linux/DualSPHysics5.4CPU_linux64
```

### Compiling from Source (GPU+CPU)

```bash
cd src/source/
# Edit Makefile: set DIRTOOLKIT=/path/to/cuda
make
# Output: bin/linux/DualSPHysics5.4_linux64
```

### Compiling with CMake

```bash
cd src/source/
mkdir build && cd build
cmake ..
make
make install  # copies to bin/linux/
```

### Dependencies

- **Required**: GCC/G++ (compatible with CUDA version if using GPU)
- **Optional**: CUDA toolkit (for GPU acceleration)
- **Optional**: Project Chrono library (for rigid body dynamics)
- **Optional**: OpenMP (for CPU parallelism, typically included with GCC)

### Python dependencies (tools)

```
numpy, pandas, matplotlib, lxml (or xml.etree.ElementTree)
```

---

## Pipeline (7 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | (manual) | Define case geometry, physics, simulation time |
| 1 | XML case definition | `generate_case_xml` | Build XML case definition with geometry and parameters |
| 2 | Case generation | `run_gencase` (wrapper) | GenCase: XML -> initial particle distribution (bi4) |
| 3 | Forcing/BC setup | `convert_forcing_to_dsph` | Convert wave/current data to DualSPHysics inlet XML |
| 4 | Execution | `run_dualsphysics` | Run DualSPHysics solver with preflight checks |
| 5 | Output parsing | `parse_dsph_output` | Extract particle data from bi4 -> CSV time series |
| 6 | Visualization | (external) | PartVTK -> ParaView, or matplotlib from CSV |

### Stage Dependencies

- Stage 1 (XML) is independent
- Stage 2 (GenCase) requires Stage 1 output
- Stage 3 (Forcing) can run in parallel with Stage 2
- Stage 4 (Execution) requires Stages 2 and 3
- Stage 5 (Output) requires Stage 4
- Stage 6 (Visualization) requires Stage 5

---

## Tools Reference

| Tool | Stage | Script Path | Purpose |
|------|-------|-------------|---------|
| `convert_forcing_to_dsph` | s1 | `tools/convert_forcing_to_dsph.py` | Convert wave/current forcing to DualSPHysics XML format |
| `convert_parameters` | s1 | `tools/convert_parameters.py` | Convert physical parameters (soil/material) to XML |
| `run_dualsphysics` | s4 | `tools/run_dualsphysics.py` | Execute DualSPHysics with preflight checks |
| `parse_dsph_output` | s5 | `tools/parse_dsph_output.py` | Parse bi4 output and extract to CSV |
| `generate_case_xml` | s1 | `tools/generate_case_xml.py` | Generate complete XML case definition |

---

## Input Format: XML Case Definition

DualSPHysics uses XML files for case definition. The XML has two main sections:

### `<casedef>` — Case Definition

```xml
<case>
  <casedef>
    <constantsdef>
      <gravity x="0" y="0" z="-9.81" />        <!-- m/s^2 -->
      <rhop0 value="1000" />                     <!-- kg/m^3 -->
      <gamma value="7" />                        <!-- polytropic constant -->
      <coefsound value="20" />                   <!-- speed of sound multiplier -->
      <coefh value="1.0" />                      <!-- smoothing length h = coefh*sqrt(3*dp^2) -->
      <cflnumber value="0.2" />                  <!-- CFL coefficient -->
    </constantsdef>
    <mkconfig boundcount="240" fluidcount="9" />
    <geometry>
      <definition dp="0.01" />                   <!-- particle spacing in meters -->
      <commands>
        <mainlist>
          <setmkfluid mk="0" />
          <drawbox>
            <boxfill>solid</boxfill>
            <point x="0" y="0" z="0" />
            <size x="1" y="1" z="0.5" />
          </drawbox>
          <!-- ... more geometry commands ... -->
        </mainlist>
      </commands>
    </geometry>
  </casedef>
  <execution>
    <parameters>
      <parameter key="TimeMax" value="2.0" />    <!-- seconds -->
      <parameter key="TimeOut" value="0.01" />   <!-- seconds -->
      <!-- ... more parameters ... -->
    </parameters>
  </execution>
</case>
```

### Key Geometry Commands

| Command | Description |
|---------|-------------|
| `setmkfluid mk="N"` | Set material marker for fluid particles |
| `setmkbound mk="N"` | Set material marker for boundary particles |
| `drawbox` | Draw a box with specified fill faces |
| `drawsphere` | Draw a sphere with center and radius |
| `drawcylinder` | Draw a cylinder |
| `drawprism` | Draw a prism |
| `move`, `rotate`, `scale` | Transform geometry |

---

## Execution Parameters

### Key Parameters (in `<execution><parameters>`)

| Parameter | Key | Units | Default | Range | Description |
|-----------|-----|-------|---------|-------|-------------|
| Particle spacing | dp | m | — | 0.001-0.1 | Fundamental resolution |
| Time step algorithm | StepAlgorithm | — | 1 | 1=Verlet, 2=Symplectic | Integration scheme |
| Kernel | Kernel | — | 2 | 1=Cubic, 2=Wendland | SPH kernel function |
| Viscosity type | ViscoTreatment | — | 1 | 1=Artificial, 2=Lam+SPS, 3=Laminar | Viscosity model |
| Viscosity value | Visco | *see below* | 0.01 | varies | Viscosity coefficient |
| Boundary type | Boundary | — | 1 | 1=DBC, 2=mDBC | Boundary condition |
| DDT mode | DensityDT | — | 0 | 0-3 | Density diffusion term |
| DDT value | DensityDTvalue | — | 0.1 | 0.05-0.2 | DDT coefficient |
| Shifting mode | Shifting | — | 0 | 0-3 | Particle shifting |
| Max simulation time | TimeMax | s | — | >0 | Total simulation time |
| Output interval | TimeOut | s | — | >0 | Data save interval |
| Density filter min | RhopOutMin | kg/m^3 | 700 | >0 | Min valid density |
| Density filter max | RhopOutMax | kg/m^3 | 1300 | >0 | Max valid density |
| CFL number | CflNumber | — | 0.2 | 0.001-1 | Courant number |

### Viscosity Units (TRAP!)

| ViscoTreatment | Visco units | Typical value |
|---------------|-------------|---------------|
| 1 (Artificial) | Dimensionless | 0.01 - 0.1 |
| 2 (Laminar+SPS) | m^2/s | 1e-6 (water at 20C) |
| 3 (Laminar) | m^2/s | 1e-6 (water at 20C) |

**TRAP**: Switching from artificial (0.01) to laminar (1e-6) without changing the Visco value gives viscosity that is 10,000x too high. Always check units match the treatment.

---

## Output Formats

### Binary (bi4) — Native format

- `Part_XXXX.bi4`: Particle data per timestep (positions, velocities, density, pressure)
- `Part_XXXX.ibi4`: Text header with metadata
- `PartOut_XXXX.bi4`: Excluded particles

### VTK — Via PartVTK post-processing

```bash
PartVTK -dirdata output/data -savevtk output/particles/PartFluid -onlytype:-all,+fluid
```

### CSV — Via MeasureTool

```bash
MeasureTool -dirdata output/data -points points.txt -savecsv output/results.csv -vars:-all,+vel,+press
```

### Points file format (for MeasureTool)

```
# x y z
0.5 0.3 0.1
0.5 0.3 0.2
0.5 0.3 0.3
```

---

## CLI Reference

### GenCase

```bash
GenCase CaseDef_Def output/CaseName -save:all
```

### DualSPHysics (CPU)

```bash
DualSPHysics5.4CPU_linux64 output/CaseName output/ [options]
```

### Common CLI Options

| Flag | Description |
|------|-------------|
| `-cpu` | CPU execution (default) |
| `-gpu[:id]` | GPU execution |
| `-ompthreads:N` | OpenMP thread count |
| `-stable` | Reproducible results (slower) |
| `-tmax:T` | Override max time (seconds) |
| `-tout:T` | Override output interval (seconds) |
| `-sv:binx,vtk,csv` | Output format selection |
| `-dbc` | Dynamic boundary condition |
| `-mdbc` | Modified DBC (vel=0) |
| `-mdbc_noslip` | mDBC no-slip |
| `-mdbc_freeslip` | mDBC free-slip |
| `-symplectic` | Symplectic time integration |
| `-verlet[:steps]` | Verlet integration |
| `-wendland` | Wendland kernel |
| `-cubic` | Cubic spline kernel |
| `-viscoart:V` | Artificial viscosity |
| `-viscolam:V` | Laminar viscosity |
| `-ddt:mode` | DDT mode (none/1/2/3) |
| `-shifting:mode` | Shifting mode |
| `-cfl:C` | CFL number |
| `-nsteps:N` | Max steps (debug) |
| `-vres` | Variable resolution |

---

## Unit Trap Table

| Variable | DualSPHysics expects | Common source format | Conversion | Severity |
|----------|---------------------|---------------------|------------|----------|
| Gravity | m/s^2 (e.g., -9.81) | Sometimes cm/s^2 | Divide by 100 | CRITICAL |
| Particle spacing (dp) | meters | Sometimes mm or cm | Divide by 1000 or 100 | CRITICAL |
| Density (rhop0) | kg/m^3 (1000 for water) | g/cm^3 (1.0 for water) | Multiply by 1000 | CRITICAL |
| Viscosity (artificial) | Dimensionless (0.01) | — | No conversion needed | — |
| Viscosity (laminar) | m^2/s (1e-6) | cm^2/s (0.01 for water) | Divide by 10000 | HIGH |
| Speed of sound | m/s | — | Usually auto-computed | LOW |
| Time | seconds | minutes or hours | Multiply by 60 or 3600 | HIGH |
| Positions/geometry | meters | feet, cm, mm | Convert to meters | CRITICAL |
| Pressure output | Pascals (Pa) | kPa, bar, atm | Multiply by 1000/1e5/101325 | MEDIUM |
| Velocity output | m/s | cm/s, knots | Divide by 100, multiply by 0.5144 | MEDIUM |
| Wave height | meters | cm, feet | Convert to meters | HIGH |
| Wave period | seconds | — | No conversion typically | LOW |

---

## 9. Diagnostic Triplets (Top 5)

Read `diagnostics/triplets.yaml` before debugging. These are the most likely unit/stability failures to check first; the YAML remains the source of truth.

| ID | Error / symptom | Diagnosis | Remedy |
|----|-----------------|-----------|--------|
| `dt_001` | Billions of particles generated by GenCase; out of memory. | `dp` specified in mm instead of meters. | Verify `dp` is in meters; typical values are 0.001-0.1 m. |
| `dt_002` | Pressure values are 1000x too high or too low; density oscillations. | `rhop0` in g/cm^3 instead of kg/m^3. | Use `rhop0=1000` for fresh water, `1025` for seawater. |
| `dt_003` | Fluid is extremely viscous or has zero viscosity. | `Visco` value does not match `ViscoTreatment`. | Use 0.01-0.1 for artificial viscosity, about 1e-6 m^2/s for laminar. |
| `dt_004` | Waves are invisible or immediately unstable. | Wave height in cm instead of meters. | Ensure all wave heights are in meters. |
| `dt_005` | Inlet velocity is orders of magnitude wrong. | Velocity in cm/s or knots instead of m/s. | Convert velocities to m/s before input. |

---

## Critical Domain Knowledge

### 1. dp determines everything (cost scales as dp^-3 in 3D)

Particle spacing `dp` is the single most important parameter. Halving dp increases particle count by 8x in 3D and runtime by roughly 16x. Start coarse (dp=0.01-0.02m) for testing, then refine.

### 2. Speed of sound is artificial (weakly compressible)

DualSPHysics uses weakly compressible SPH (WCSPH). The speed of sound is set ~10x the maximum expected velocity (via `coefsound`), NOT the real physical speed of sound (~1500 m/s in water). Too high = tiny timesteps. Too low = compressibility artifacts (density fluctuations >1%).

### 3. Smoothing length h controls interaction radius

`h = coefh * sqrt(3 * dp^2)` in 3D. The kernel support is 2h (Wendland) or 3h (Cubic). More neighbors = smoother but slower. Default coefh=1.0 gives h~1.73*dp.

### 4. Boundary particles must surround the domain

GenCase creates boundary particles from the `setmkbound` geometry. Gaps in boundaries cause particle leakage. Always visualize the initial particle distribution.

### 5. RhopOut filters remove unphysical particles

Particles with density outside [RhopOutMin, RhopOutMax] are removed from simulation. If too many particles are removed, the simulation is unstable — reduce dp or increase coefsound.

### 6. DBC vs mDBC boundary conditions

DBC (Dynamic Boundary Condition) is simpler but creates unphysical gaps near walls. mDBC (Modified DBC) is more accurate for pressure near boundaries. Use mDBC for quantitative pressure measurements.

### 7. Inlet/outlet requires careful layer configuration

Inlet/outlet zones need 6-8 particle layers. The velocity profile, density, and refilling mode must be consistent. Mismatched inlet conditions cause pressure waves.

### 8. Density Diffusion Term (DDT) prevents pressure noise

DDT mode 2 (Fourtakas) is recommended for most cases. Without DDT, pressure fields are noisy. DDT value 0.1 is standard.

---

## Post-Processing Tools

### PartVTK — Binary to VTK conversion

```bash
PartVTK -dirdata output/data -savevtk output/PartFluid -onlytype:-all,+fluid
PartVTK -dirdata output/data -savevtk output/PartBound -onlytype:-all,+bound
```

### MeasureTool — Point interpolation

```bash
MeasureTool -dirdata output/data -points points.txt -onlytype:-all,+fluid \
  -vars:-all,+vel.x,+vel.m,+press -savecsv output/measurements.csv
```

### IsoSurface — Free-surface extraction

```bash
IsoSurface -dirdata output/data -saveiso output/Surface \
  -vars:-all,vel,rhop -saveslice output/Slices -slicevec:0:0.5:0:0:1:0
```

### ComputeForces — Force on structures

```bash
ComputeForces -dirdata output/data -onlymk:20 -viscoart:0.1 -savecsv output/forces.csv
```

---

## Example: DamBreak (01_DamBreak)

The canonical validation case:
- Water column: 0.4m x 0.67m x 0.3m (initial)
- Container: 1.6m x 0.67m x 0.4m
- Obstacle at x=0.9m
- dp = 0.0085m, ~500k particles
- TimeMax = 1.6s, TimeOut = 0.01s
- Validation: pressure probes, dam tip position vs Koshizuka & Oka (1996)

### Running the example

```bash
cd examples/main/01_DamBreak/
export dirbin=../../../bin/linux
export LD_LIBRARY_PATH=${LD_LIBRARY_PATH}:${dirbin}

# Step 1: Generate case
${dirbin}/GenCase_linux64 CaseDambreak_Def CaseDambreak_out/CaseDambreak -save:all

# Step 2: Run simulation
${dirbin}/DualSPHysics5.4CPU_linux64 CaseDambreak_out/CaseDambreak CaseDambreak_out

# Step 3: Post-process
${dirbin}/PartVTK_linux64 -dirdata CaseDambreak_out/data -savevtk CaseDambreak_out/PartFluid -onlytype:-all,+fluid
${dirbin}/MeasureTool_linux64 -dirdata CaseDambreak_out/data -points CaseDambreak_PointsVelocity.txt \
  -onlytype:-all,+fluid -vars:-all,+vel.x,+vel.m -savecsv CaseDambreak_out/Velocity.csv
```

---

## 11. Validated Results

### DamBreak Benchmark

- **Case**: 3D dam break with obstacle
- **Reference**: Koshizuka & Oka (1996) experimental data
- **Validation data**: `EXP_X-DamTipPosition_Koshizula&Oka1996.txt`
- **Metrics**: Dam tip position vs time, pressure at probes

### Performance Metrics - judged against the field's bar, not intuition

**Source: `docs/validation_convention.yaml`. Every band below carries the citation key from the convention; a missing/null band would be written as "no cited threshold".**

Headline bar for `water_surface_elevation`:

| Dag variable | Metric | Direction | Very good | Good | Satisfactory | Citation key(s) |
|--------------|--------|-----------|-----------|------|--------------|-----------------|
| `water_surface_elevation` | `normalized_rmse_h` | minimize | <= 0.175 | <= 0.175 | <= 1.0 | `verbrugghe2019` |
| `water_surface_elevation` | `relative_wave_height_error` | minimize | <= 3.0 | <= 5.0 | <= 12.1 | `altomare2018`, `zhan2025` |

Other convention bars stated in this KI:

| Dag variable | Metric | Direction | Very good | Good | Satisfactory | Citation key(s) |
|--------------|--------|-----------|-----------|------|--------------|-----------------|
| `pressure` | `normalized_rmse_total_pressure` | minimize | <= 0.002 | <= 0.008 | <= 0.008 | `verbrugghe2019` |
| `pressure` | `relative_amplitude_error` | minimize | <= 0.04 | <= 0.07 | <= 0.07 | `crespo2011` |
| `pressure` | `relative_amplitude_error` | minimize | <= 0.04 | <= 0.07 | <= 0.07 | `crespo2011` |

---

## Version History

- DualSPHysics v5.4.355 (2025-04-08): Current version
- Features: VRes, FlexStruc, mDBC no-slip, GPU execution, OpenMP
