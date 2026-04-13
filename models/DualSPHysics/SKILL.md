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

# DualSPHysics v5.4 — Knowledge Infrastructure

**Package**: `hydrocraft-dualsphysics-ocean` v1.0.0
**Model**: DualSPHysics v5.4.355 (Smoothed Particle Hydrodynamics)
**Domain**: Coastal/ocean engineering, free-surface flows
**Last updated**: 2026-03-26
**Stats**: 5 tools | 5 skill documents | 18 diagnostic triplets | ~2,000 lines of validated Python
**Validation status**: `example_validated` (DamBreak benchmark, Koshizuka & Oka 1996)

---

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

## Validated Results

### DamBreak Benchmark

- **Case**: 3D dam break with obstacle
- **Reference**: Koshizuka & Oka (1996) experimental data
- **Validation data**: `EXP_X-DamTipPosition_Koshizula&Oka1996.txt`
- **Metrics**: Dam tip position vs time, pressure at probes

---

## Version History

- DualSPHysics v5.4.355 (2025-04-08): Current version
- Features: VRes, FlexStruc, mDBC no-slip, GPU execution, OpenMP
