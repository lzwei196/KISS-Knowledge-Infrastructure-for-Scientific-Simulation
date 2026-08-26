---
name: gifmod
description: >-
  GIFMod. Covers Hydraulic and water-quality performance of stormwater green
  infrastructure and urban/agricultural…; Variably-saturated flow from surface water
  through the vadose zone to groundwater across an…; Particle/colloid transport across
  mobile and attached phases; Dissolved and particle-bound reactive constituent fate and
  transport with user-defined…. Use when the task involves running, configuring,
  calibrating or interpreting GIFMod.
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

# GIFMod Knowledge Infrastructure

| Field              | Value                                              |
|--------------------|----------------------------------------------------|
| Package            | gifmod-ki                                          |
| Version            | 0.1.0                                              |
| Model              | GIFMod 0.1.26                                      |
| Domain             | Urban water quality / green infrastructure         |
| Language           | C++14 (Qt5 GUI)                                    |
| License            | GPL-3.0                                            |
| Repository         | https://github.com/USEPA/GIFMod                   |
| Authors            | US EPA                                             |
| Validation         | synthetic (pipeline test)                          |

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for meteorological forcing documentation.
See `data_ki/WQP/SKILL.md` for water quality observations.
See `data_ki/HydroLAKES/SKILL.md` for lake morphometry.


## 1. Overview

GIFMod (Green Infrastructure Flexible Model) is a physically-based, block-structured
water quality and hydrodynamic modeling system developed by the US EPA. It simulates
flow, constituent transport, and biogeochemical reactions through interconnected
spatial units representing green infrastructure components such as bioretention
cells, constructed wetlands, porous pavements, and urban drainage networks.

The model uses a mass-balance block approach where each block (Soil, Pond, Storage,
Catchment, Manhole, Darcy, Stream, Plant) solves the Richards equation for unsaturated
flow and advection-dispersion-reaction (ADR) equations for constituent transport.
Blocks are connected by flow paths (Pipe, Porous, Non-Porous, Rating Curve,
Prescribed Flow, Controlled) that govern inter-block water and solute exchange.

GIFMod solves the coupled system using an adaptive-timestep Newton-Raphson scheme
with Jacobian-based iteration. It supports multi-phase transport (dissolved, sorbed,
colloidal, gaseous), user-defined reaction networks in Petersen matrix format, and
optimization via genetic algorithms (GA) or MCMC sampling.

The model is primarily a Qt5 GUI application. There is no standalone CLI executable;
automation is achieved through the built-in JavaScript scripting engine (Duktape).
Input is specified through project files (.GIFMod format) containing block/connector
definitions and parameter tables. Output is columnar time series of head, flow,
concentration, and mass balance at each block.

---

## 2. Installation

### 2.1 Dependencies

| Dependency   | Purpose                     | Linux Package        |
|--------------|-----------------------------|----------------------|
| Qt 5.x       | GUI framework               | qt5-default          |
| LAPACK       | Linear algebra backend      | liblapack-dev        |
| BLAS         | Basic linear algebra        | libblas-dev          |
| OpenMP       | Parallel processing         | libgomp1             |
| GCC/G++      | C++14 compiler              | g++                  |
| Armadillo    | Linear algebra (bundled)    | (included in source) |
| Duktape      | JavaScript engine (bundled) | (included in source) |

### 2.2 Build from Source (Linux)

```bash
cd /path/to/GIFMod/source/repo
# Install dependencies
sudo apt-get install qt5-default liblapack-dev libblas-dev libgomp1-dev

# Build with qmake
qmake GIFMod.pro CONFIG+=release
make -j$(nproc)

# Binary output
./builds/release/GIFMod
```

### 2.3 Build from Source (Windows)

The project includes Visual Studio 2015 project files (GIFMod.vcxproj) and
pre-compiled LAPACK/BLAS DLLs in `libs/lapack-blas_lib_win64/`.

```bat
vs2015.bat
msbuild GIFMod.vcxproj /p:Configuration=Release
```

### 2.4 Test Command

```bash
# GIFMod is GUI-only; verify build succeeded:
./builds/release/GIFMod --help 2>&1 || echo "GUI app, no CLI help"
```

---

## 3. Pipeline Stages

| # | Stage              | Tool(s)                         | Description                                        |
|---|--------------------|---------------------------------|----------------------------------------------------|
| 0 | Configuration      | `configure_gifmod.py`           | Set domain extents, period, output paths           |
| 1 | Domain Setup       | (manual / GUI)                  | Define block layout and connectivity               |
| 2 | Soil Parameters    | `convert_soil_params.py`        | Convert HWSD/SoilGrids to GIFMod soil properties   |
| 3 | Land Cover         | (manual / GUI)                  | Assign block types and vegetation properties       |
| 4 | Forcing            | `convert_forcing.py`            | Convert met data to GIFMod time series format      |
| 5 | Model Parameters   | `configure_gifmod.py`           | Set hydraulic conductivity, porosity, dispersivity |
| 6 | Execution          | `run_gifmod.py`                 | Build and execute GIFMod binary                    |
| 7 | Output Parsing     | `parse_gifmod_output.py`        | Extract time series to CSV                         |
| 8 | Validation         | (external)                      | Compare with observations                          |

---

## 4. Unit Trap Table

GIFMod uses mixed SI and non-SI units internally. These are the critical unit
conversions that cause silent failures if wrong:

| Variable                  | GIFMod Internal Unit | Common Source Unit | Conversion Factor | Trap ID |
|---------------------------|----------------------|--------------------|--------------------|---------|
| Hydraulic conductivity    | m/day                | cm/s               | x 864.0            | dt_001  |
| Precipitation             | m/day                | mm/hr              | x 0.024            | dt_002  |
| Area                      | m^2                  | ft^2               | x 0.0929           | dt_003  |
| Depth/Elevation           | m                    | cm                 | x 0.01             | dt_004  |
| Manning roughness         | s/m^(1/3)            | s/m^(1/3)          | 1.0 (no trap)      | --      |
| Bulk density              | kg/m^3               | g/cm^3             | x 1000.0           | dt_005  |
| Dispersivity              | m                    | cm                 | x 0.01             | dt_006  |
| Vapor diffusion coeff     | m^2/day              | m^2/s              | x 86400.0          | dt_007  |
| Temperature               | Celsius              | Fahrenheit         | (F-32)*5/9         | dt_008  |
| Concentration             | user-defined         | varies             | check units match  | dt_009  |
| Reaction rate constants   | 1/day                | 1/hr               | x 24.0             | dt_010  |
| Settling velocity         | m/day                | m/s                | x 86400.0          | dt_011  |
| Porosity                  | fraction (0-1)       | percent (0-100)    | x 0.01             | dt_012  |
| Partition coefficient Kd  | L/kg                 | mL/g               | 1.0 (same)         | --      |

**Critical**: GIFMod uses **m/day** as the base hydraulic unit (not m/s). Failing to
convert from cm/s to m/day is the #1 cause of unrealistic flow predictions.

---

## 5. Tools Reference

| Tool                      | Stage | Script                        | Lines | Purpose                                           |
|---------------------------|-------|-------------------------------|-------|----------------------------------------------------|
| convert_forcing.py        | s4    | tools/convert_forcing.py      | ~200  | Convert met forcing to GIFMod CSV time series      |
| convert_soil_params.py    | s2    | tools/convert_soil_params.py  | ~180  | Convert HWSD soil data to GIFMod block properties  |
| run_gifmod.py             | s6    | tools/run_gifmod.py           | ~160  | Build and execute GIFMod, manage output            |
| parse_gifmod_output.py    | s7    | tools/parse_gifmod_output.py  | ~180  | Parse GIFMod columnar output to CSV                |

---

## 6. Critical Domain Knowledge

### dt_001: Hydraulic Conductivity in m/day Not cm/s

GIFMod expects hydraulic conductivity (Ks) in **m/day**. Most soil databases
(HWSD, SoilGrids, USDA) report Ks in cm/s. The conversion factor is:

    Ks_m_per_day = Ks_cm_per_s * 864.0

If Ks is entered in cm/s without conversion, it will be ~864x too low, causing
near-zero infiltration and unrealistic surface ponding. The model will run without
error. See diagnostic triplet dt_001.

### dt_002: Precipitation Must Be m/day

GIFMod requires precipitation in **m/day**. Global forcing products typically
provide mm/hr or mm/day. Common conversions:

    P_m_per_day = P_mm_per_day * 0.001
    P_m_per_day = P_mm_per_hr * 0.024

Entering mm/day directly as m/day inflates precipitation by 1000x. See dt_002.

### dt_003: Area Units Must Be m^2

Block areas must be in m^2. If working with imperial data (ft^2), convert:

    A_m2 = A_ft2 * 0.09290304

### dt_005: Bulk Density kg/m^3 Not g/cm^3

GIFMod expects bulk density in kg/m^3 (typical range 1200-1800). Soil databases
often report in g/cm^3 (typical range 1.2-1.8). Forgetting to multiply by 1000
yields unrealistic sorption calculations. See dt_005.

### dt_007: Diffusion Coefficients in m^2/day

Vapor and molecular diffusion coefficients must be in m^2/day. Literature values
are almost always in m^2/s or cm^2/s. Convert:

    D_m2_per_day = D_m2_per_s * 86400
    D_m2_per_day = D_cm2_per_s * 8.64

### dt_012: Porosity as Fraction Not Percent

GIFMod expects porosity as a decimal fraction (0.0-1.0). Some databases report
porosity as percent (0-100). Entering 40% as 40.0 instead of 0.40 causes
immediate numerical instability or grossly wrong water balance. See dt_012.

### dt_009: Constituent Concentration Units Must Be Consistent

GIFMod allows user-defined concentration units, but ALL inflow concentrations,
initial conditions, and boundary conditions must use the SAME unit system. Mixing
mg/L with ug/L in different blocks produces silently wrong mass balances.

### dt_010: Reaction Rate Constants in 1/day

All reaction rate constants in the Petersen matrix must be in **1/day**. Literature
often reports rates in 1/hr or 1/s. Failing to convert yields reaction rates
that are 24x or 86400x too slow/fast. See dt_010.

---

## 7. Input Format Specification

### 7.1 Project File (.GIFMod)

GIFMod project files are text-based configuration files containing:

```
# Block definitions
Block: Soil_Layer_1
  Type: Soil
  Area: 100.0           # m^2
  Depth: 1.5            # m
  Bottom_Elevation: 0.0 # m
  Porosity: 0.40        # fraction
  Ks: 5.0               # m/day
  ...

# Connector definitions
Connector: Pipe_1
  Source: Soil_Layer_1
  Target: Storage_1
  Type: Pipe
  Diameter: 0.15        # m
  Manning: 0.013        # s/m^(1/3)
  ...
```

### 7.2 Time Series Input (CSV)

Forcing data (precipitation, temperature, etc.) is provided as CSV:

```csv
Time,Precipitation,Temperature,Humidity,WindSpeed
0.0,0.005,20.0,0.65,3.2
0.0417,0.005,20.5,0.63,3.1
0.0833,0.0,21.0,0.60,2.8
```

- Time is in **days** from simulation start
- Precipitation in **m/day**
- Temperature in **Celsius**
- Humidity as **fraction** (0-1)
- Wind speed in **m/s**

### 7.3 Property Catalog (GIFModGUIPropList.csv)

The internal property catalog defines all model parameters with:
- Name, Code, Unit, Default Unit
- Valid ranges and defaults
- GUI delegate type
- Category and subcategory

---

## 8. Output Format Specification

### 8.1 Time Series Output

GIFMod produces columnar text output:

```
Time        Block1_Head  Block1_Conc  Block2_Head  Block2_Conc
0.000       1.200        50.30        1.500        45.20
0.042       1.250        50.50        1.480        45.10
0.083       1.300        50.80        1.460        45.05
```

- Time in **days**
- Head in **m**
- Concentration in user-defined units
- Flow (Q) in **m^3/day**

### 8.2 Output Variables

| Variable       | Symbol | Unit      | Description                      |
|----------------|--------|-----------|----------------------------------|
| Head           | H      | m         | Water level in block             |
| Flow           | Q      | m^3/day   | Flow between blocks              |
| Velocity       | v      | m/day     | Flow velocity in connector       |
| Area           | A      | m^2       | Cross-sectional flow area        |
| Moisture       | theta  | fraction  | Volumetric water content         |
| Concentration  | C      | user      | Constituent concentration        |
| Mass Balance   | MB     | user      | Cumulative mass balance error    |
| Storage        | S      | m^3       | Water storage in block           |

### 8.3 Mass Balance Output

GIFMod tracks cumulative mass balance for all blocks and constituents.
Non-zero mass balance error (> 1e-6) indicates numerical issues.

---

## 9. Solver Configuration

### 9.1 Time Stepping

| Parameter              | Default     | Unit   | Description                    |
|------------------------|-------------|--------|--------------------------------|
| dt_initial             | 0.001       | day    | Initial timestep               |
| dt_min                 | 1e-8        | day    | Minimum allowed timestep       |
| dt_max                 | 0.1         | day    | Maximum allowed timestep       |
| simulation_duration    | user        | day    | Total simulation time          |
| write_interval         | 0.0417      | day    | Output write interval (~1 hr)  |

### 9.2 Solver Parameters

| Parameter              | Default     | Description                          |
|------------------------|-------------|--------------------------------------|
| max_iterations         | 20          | Max Newton-Raphson iterations/step   |
| tolerance              | 1e-6        | Convergence tolerance                |
| n_threads              | auto        | OpenMP threads for Jacobian calc     |

---

## 10. Block Types

| Block Type  | Description                        | Key Properties                     |
|-------------|------------------------------------|------------------------------------|
| Soil        | Unsaturated soil column            | Ks, porosity, theta_r, theta_s     |
| Pond        | Open water body / retention pond   | Area, depth, evaporation           |
| Storage     | Underground storage / cistern      | Volume, inflow/outflow             |
| Catchment   | Surface catchment area             | Area, impervious fraction          |
| Manhole     | Urban drainage junction            | Diameter, invert elevation         |
| Darcy       | Saturated porous medium            | K, porosity, dispersivity          |
| Stream      | Open channel / stream reach        | Width, slope, Manning n            |
| Plant       | Vegetation/root zone               | LAI, root depth, transpiration     |

---

## 11. Connector Types

| Connector Type     | Description                    | Key Properties                |
|--------------------|--------------------------------|-------------------------------|
| Pipe               | Pressurized/gravity pipe       | Diameter, Manning n, length   |
| Porous             | Porous media flow              | K, area, length               |
| Non-Porous         | Impervious boundary            | Overflow elevation            |
| Rating Curve       | Stage-discharge relationship   | Q = f(H) table               |
| Prescribed Flow    | Fixed time-varying flow        | Q(t) time series              |
| Controlled         | Actuated flow control          | Sensor, controller, setpoint  |

---

## 12. Calibration Parameters

| Priority | Parameter            | Block Type | Range          | Controls              |
|----------|----------------------|------------|----------------|-----------------------|
| 1        | Ks (hyd. cond.)      | Soil/Darcy | 0.01-100 m/day | Infiltration rate     |
| 2        | Porosity             | Soil/Darcy | 0.20-0.60      | Water storage         |
| 3        | Manning n            | Pipe/Stream| 0.010-0.035    | Flow velocity         |
| 4        | Dispersivity         | All        | 0.01-10 m      | Solute spreading      |
| 5        | Kd (partition coeff) | All        | 0.1-1000 L/kg  | Sorption              |
| 6        | Reaction rates       | Reaction   | 0.001-100 1/d  | WQ transformation     |
| 7        | Depression storage   | Catchment  | 0.001-0.01 m   | Surface retention     |
| 8        | Evaporation coeff    | Pond/Soil  | 0.5-1.5        | Water loss            |

---

## 13. Diagnostic Triplets Summary

| ID     | Severity | Domain          | Summary                                    |
|--------|----------|-----------------|--------------------------------------------|
| dt_001 | silent   | unit_conversion | Ks in cm/s instead of m/day (864x error)   |
| dt_002 | silent   | unit_conversion | Precip in mm/day instead of m/day (1000x)  |
| dt_003 | silent   | unit_conversion | Area in ft^2 instead of m^2                |
| dt_004 | silent   | unit_conversion | Depth in cm instead of m                   |
| dt_005 | silent   | unit_conversion | Bulk density g/cm^3 instead of kg/m^3      |
| dt_006 | silent   | unit_conversion | Dispersivity in cm instead of m            |
| dt_007 | silent   | unit_conversion | Diffusion in m^2/s instead of m^2/day      |
| dt_008 | degraded | unit_conversion | Temperature in Fahrenheit instead of C     |
| dt_009 | silent   | parameter_format| Mixed concentration units across blocks    |
| dt_010 | silent   | unit_conversion | Rate constants in 1/hr instead of 1/day    |
| dt_011 | silent   | unit_conversion | Settling velocity m/s instead of m/day     |
| dt_012 | fatal    | unit_conversion | Porosity as percent instead of fraction     |
| dt_013 | fatal    | runtime         | Negative Ks causes solver divergence       |
| dt_014 | degraded | dependency      | Qt version mismatch in build               |
| dt_015 | fatal    | path_resolution | LAPACK/BLAS not found at link time         |

See `diagnostics/triplets.yaml` for full symptom-diagnosis-remedy details.

---

## 14. File Structure

```
ki/
  SKILL.md                          # This file
  knowledge_infrastructure.yaml     # Machine-readable package definition
  tools/
    convert_forcing.py              # Met forcing converter
    convert_soil_params.py          # Soil parameter converter
    run_gifmod.py                   # Build/execution wrapper
    parse_gifmod_output.py          # Output parser
  docs/
    s0_configuration.md             # Configuration skill
    s2_soil_parameters.md           # Soil parameter setup
    s4_forcing.md                   # Meteorological forcing
    s6_execution.md                 # Model execution
    s7_output_parsing.md            # Output parsing
  diagnostics/
    triplets.yaml                   # Diagnostic triplets
```

---

## 15. Quick Start

```bash
# 1. Build GIFMod
cd /path/to/GIFMod/source/repo
sudo apt-get install qt5-default liblapack-dev libblas-dev
qmake GIFMod.pro CONFIG+=release
make -j$(nproc)

# 2. Convert soil parameters
python3 ki/tools/convert_soil_params.py \
  --input hwsd_extract.csv \
  --output soil_params.json

# 3. Convert forcing data
python3 ki/tools/convert_forcing.py \
  --input met_station.csv \
  --output gifmod_forcing.csv \
  --precip-unit mm/hr \
  --temp-unit celsius

# 4. Build and run model (GUI-based)
./builds/release/GIFMod

# 5. Parse output
python3 ki/tools/parse_gifmod_output.py \
  --input model_output.txt \
  --output results.csv \
  --variables Head,Flow,Concentration
```

---

## 16. Coupling Points

| Source Model | Target Model | Variable        | Unit    | Notes                      |
|-------------|--------------|-----------------|---------|----------------------------|
| SWMM        | GIFMod       | Drainage flow   | m^3/day | Prescribed inflow          |
| GIFMod      | SWMM         | Outflow         | m^3/day | Return flow to sewer       |
| ERA5/CMFD   | GIFMod       | Met forcing     | mixed   | Use convert_forcing.py     |
| HWSD        | GIFMod       | Soil properties | mixed   | Use convert_soil_params.py |
| GIFMod      | Post-proc    | Time series     | mixed   | Use parse_gifmod_output.py |
| MODFLOW     | GIFMod       | GW head         | m       | Bottom boundary condition  |

---

## 17. Governing Equations

### 17.1 Flow Equations

**Richards Equation (Soil blocks)**:
```
dθ/dt = d/dz [K(θ) (dh/dz + 1)] - S(z)
```
where θ = volumetric water content, K = hydraulic conductivity, h = pressure head,
S = root water uptake.

**Manning Equation (Pipe/Stream connectors)**:
```
Q = (1/n) * A * R^(2/3) * S^(1/2)
```
where n = Manning roughness, A = cross-section area, R = hydraulic radius, S = slope.

### 17.2 Transport Equations

**Advection-Dispersion-Reaction (ADR)**:
```
d(θC)/dt = d/dz [θD dC/dz] - d(qC)/dz + r(C,T)
```
where C = concentration, D = dispersion coefficient, q = Darcy flux,
r = reaction rate (from Petersen matrix).

### 17.3 Sorption

**Linear isotherm**: S = Kd * C
where Kd = partition coefficient (L/kg), S = sorbed concentration (mg/kg).

---

## 18. Known Limitations

1. **GUI-only**: No command-line interface for batch processing; scripting via Duktape JS
2. **No parallel domain decomposition**: Single-node only (OpenMP for linear algebra)
3. **1D blocks**: Each block is 0D or 1D; no full 2D/3D spatial resolution
4. **No built-in GIS**: Block geometry must be defined manually or via scripts
5. **Windows-primary**: Linux build requires manual Qt5 configuration
6. **No built-in calibration CLI**: GA/MCMC optimization is GUI-driven
