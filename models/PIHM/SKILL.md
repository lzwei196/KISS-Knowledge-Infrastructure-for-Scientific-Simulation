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

# MM-PIHM Knowledge Infrastructure
**Package**: `pihm-ki` | **Version**: 1.0.0 | **Model**: MM-PIHM v1.0.0
**Domain**: Distributed Hydrology | **Language**: C (gcc) | **Solver**: SUNDIALS CVODE v7.3.0
**License**: MIT | **Repository**: PSUmodeling/MM-PIHM

| Metric | Value |
|--------|-------|
| Pipeline stages | 9 |
| Python tools | 4 |
| Skill documents | 5 |
| Diagnostic triplets | 20 |
| Failure domains | 5 |

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/HWSD/SKILL.md` for soil property documentation.
See `data_ki/ObservedQ/SKILL.md` for observed discharge data.


## 1. Overview

MM-PIHM (Multi-Modular Penn State Integrated Hydrologic Model) is a physically-based,
spatially-distributed watershed model that solves coupled surface–subsurface hydrology
on unstructured triangular meshes using finite-volume methods and the CVODE implicit
ODE solver from SUNDIALS.

**Model Variants:**
- **PIHM** — core hydrology (surface water, unsaturated zone, groundwater, channel flow)
- **Flux-PIHM** — adds Noah Land Surface Model for energy balance, snow, soil temperature
- **Flux-PIHM-BGC** — adds Biome-BGC for carbon/nitrogen cycling
- **Cycles-L** — adds Cycles agroecosystem model for crop growth

**Key Capabilities:**
- Triangular Irregular Network (TIN) mesh for irregular terrain
- Coupled overland flow, vadose zone, saturated zone, and channel routing
- van Genuchten soil hydraulics with macropore flow
- Adaptive implicit time stepping via CVODE
- OpenMP parallelization for large domains
- Spin-up mode for steady-state initialization

**State Variables (ODE system):**
- Surface water depth per element (m)
- Unsaturated zone storage per element (m)
- Groundwater head per element (m)
- River stage per segment (m)
- Total ODEs: `3 * nelem + nriver`

---

## 2. Installation

### 2.1 Dependencies
- GCC with OpenMP support
- CMake >= 3.18 (auto-downloaded if missing)
- SUNDIALS CVODE v7.3.0 (bundled in `cvode/` directory)

### 2.2 Build Steps
```bash
cd MM-PIHM/
make cvode          # Install CVODE library
make pihm           # Compile PIHM (core hydrology)
# OR
make flux-pihm      # Compile Flux-PIHM (with Noah LSM)
# OR
make flux-pihm-bgc  # Compile Flux-PIHM-BGC (with BGC)
```

### 2.3 OpenMP Configuration
```bash
export OMP_NUM_THREADS=12
```

### 2.4 Test Run
```bash
make test   # Compiles Flux-PIHM and runs ShaleHills example
```

---

## 3. Pipeline Stages

| # | Stage | Description | Input | Output | Tool |
|---|-------|-------------|-------|--------|------|
| S1 | Mesh generation | Create TIN from DEM using PIHMgis | DEM, watershed boundary | `.mesh` file | PIHMgis (external) |
| S2 | Attribute assignment | Assign soil/lc/forcing to elements | Soil map, LC map | `.att` file | PIHMgis (external) |
| S3 | Forcing preparation | Convert met data to PIHM format | ERA5/NLDAS/station data | `.meteo` file | `forcing_converter.py` |
| S4 | Soil parameterization | Convert soil database to PIHM format | HWSD/SSURGO | `.soil`, `.geol` files | `soil_converter.py` |
| S5 | Parameter configuration | Set control and calibration params | User choices | `.para`, `.calib` files | Manual / PIHMgis |
| S6 | Initial conditions | Set or generate IC file | Prior run / defaults | `.ic` file | Manual / spin-up |
| S7 | Model execution | Run PIHM binary | All input files | Binary output | `run_pihm.py` |
| S8 | Output analysis | Parse and visualize results | Binary `.dat` files | CSV, plots | `output_parser.py` |
| S9 | Calibration | Adjust multipliers for performance | Observed data | Updated `.calib` | Manual iteration |

**Stage Dependencies:**
- S1 → S2 → S3,S4,S5,S6 (parallel) → S7 → S8 → S9 → S7 (iterate)

---

## 4. Input Files Reference

All input files share a project prefix: `<project>.<ext>`.
For project "ShaleHills", files are in `input/ShaleHills/`.

### 4.1 Mesh File (`.mesh`)
```
NUMELE  535
INDEX  NODE1  NODE2  NODE3  NABR1  NABR2  NABR3
1      1      2      3      0      2      5
...
NUMNODE 293
INDEX  X(m)  Y(m)  ZMIN(m)  ZMAX(m)
1      634595.29  4520225.42  225.13  228.08
```

### 4.2 Attribute File (`.att`)
```
NUMATT  535
INDEX  SOIL  GEOL  LC  METEO  LAI  BC1  BC2  BC3
1      1     1     28  1      0    0    0    0
```
- BC values: 0 = no flow, >0 = boundary condition series index

### 4.3 Soil File (`.soil`)
```
NUMSOIL  5
INDEX SILT(%) CLAY(%) OM(%) BD(g/cm3) KINF(m/s) KSATV(m/s) KSATH(m/s)
      MAXSMC(m3/m3) MINSMC(m3/m3) ALPHA(1/m) BETA(-) MACHF(-) MACVF(-)
      DMAC(m) QTZ(-)
DINF  0.10
KMACV_RO  100.0
KMACH_RO  1000.0
```

### 4.4 Meteorological Forcing (`.meteo`)
```
METEO_TS  1
WIND_LVL  10.0
TIME              PRCP(kg/m2/s)  SFCTMP(K)  RH(%)  SFCSPD(m/s)  SOLAR(W/m2)  LONGWV(W/m2)  PRES(Pa)
2009-01-01 00:00  0.0            271.55     65.0   2.3          0.0          280.5         101325.0
```

### 4.5 River File (`.riv`)
```
NUMRIV  20
INDEX FROM TO DOWN LEFT RIGHT SHAPE MATL BC RES
SHAPE section: INDEX DPTH(m) OINT CWID
MATERIAL section: INDEX ROUGH(s/m^1/3) CWR(-) KH(m/s)
```

### 4.6 Parameter File (`.para`)
Controls simulation mode, time window, time steps, solver tolerances, and output intervals.
- `MODEL_STEPSIZE` — hydrology step (seconds, typically 60)
- `ABSTOL` — CVode absolute tolerance (m)
- `RELTOL` — CVode relative tolerance (dimensionless)

### 4.7 Calibration File (`.calib`)
Global multipliers applied to soil/river/vegetation properties:
- Hydraulic conductivity: `KSATH`, `KSATV`, `KINF` (multiplier, default 1.0)
- Macropore: `KMACSATH`, `KMACSATV`, `DMAC`, `MACVF`, `MACHF`
- Vegetation: `VEGFRAC`, `ALBEDO`, `ROUGH`, `DROOT`
- River: `ROUGH_RIV`, `KRIVH`, `RIV_DPTH`, `RIV_WDTH`
- Forcing: `PRCP` (multiplier), `SFCTMP` (offset in K)

### 4.8 Initial Conditions (`.ic`)
Per-element values for: surface water (m), unsaturated storage (m), groundwater (m), snow (m), canopy storage (m), soil temperature (K).
Per-river: stage (m).

### 4.9 LAI Forcing (`.lai`)
```
LAI_TS  1
TIME           LAI(m2/m2)
2009-01-01     0.5
2009-04-01     3.2
```

### 4.10 Boundary Conditions (`.bc`)
```
BC_TS  1
TYPE  1   (1=Dirichlet head, 2=Neumann flux)
TIME           VALUE(m or m3/s)
```

---

## 5. Unit Trap Table

| Variable | PIHM Internal Unit | Common External Unit | Conversion | Triplet |
|----------|--------------------|---------------------|------------|---------|
| Precipitation | kg/m2/s | mm/hr | ÷ 3600 × 1000^-1 → WRONG! mm/hr ÷ 3.6e6 | dt_001 |
| Precipitation | kg/m2/s | mm/day | mm/day ÷ 86400 ÷ 1000 = kg/m2/s (water density) | dt_001 |
| Temperature | K | °C | +273.15 | dt_002 |
| Pressure | Pa | hPa/mbar | ×100 | dt_003 |
| Humidity | % (RH) | specific humidity (kg/kg) | Requires Clausius-Clapeyron | dt_004 |
| Solar radiation | W/m2 | MJ/m2/day | MJ/m2/day ÷ 0.0864 = W/m2 | dt_005 |
| Longwave radiation | W/m2 | MJ/m2/day | Same as solar | dt_005 |
| Wind speed | m/s | km/hr | ÷ 3.6 | dt_006 |
| Hydraulic conductivity | m/s | cm/hr | cm/hr ÷ 360000 = m/s | dt_007 |
| van Genuchten alpha | 1/m | 1/cm | ×100 | dt_008 |
| Soil depth/elevation | m | cm or ft | ÷ 100 or ÷ 3.281 | dt_009 |
| Bulk density | g/cm3 | kg/m3 | ÷ 1000 | dt_010 |
| River roughness | s/m^(1/3) | Manning's n | Same unit | — |

---

## 6. Tools Reference

| # | Tool | Stage | Purpose | Lines |
|---|------|-------|---------|-------|
| 1 | `forcing_converter.py` | S3 | Convert ERA5/CSV met data → PIHM `.meteo` format | ~280 |
| 2 | `soil_converter.py` | S4 | Convert HWSD/SSURGO → PIHM `.soil` and `.geol` | ~250 |
| 3 | `run_pihm.py` | S7 | Execute PIHM binary with validation | ~200 |
| 4 | `output_parser.py` | S8 | Parse binary output → CSV with headers | ~260 |

---

## 7. Critical Domain Knowledge

### 7.1 Precipitation units are kg/m2/s, NOT mm/hr (dt_001)
PIHM expects precipitation as mass flux (kg/m2/s). Since water density = 1000 kg/m3,
1 kg/m2/s = 1 mm/s = 3600 mm/hr. Passing mm/hr directly without dividing by 3600
produces rainfall 3600× too high, causing immediate flooding and solver crash.

### 7.2 Temperature must be in Kelvin (dt_002)
All temperature fields (SFCTMP, TBOT) use Kelvin. Passing Celsius creates ~273 K offset
that makes snow/ice calculations fail silently — winter snow accumulates all year.

### 7.3 Pressure in Pascals, not hectopascals (dt_003)
Surface pressure uses Pa (e.g., 101325). Passing hPa (1013.25) makes pressure 100× too
low, causing incorrect vapor pressure calculations and unrealistic ET.

### 7.4 van Genuchten alpha is in 1/m, not 1/cm (dt_008)
HWSD/Rosetta typically provide alpha in 1/cm. PIHM needs 1/m. Forgetting the ×100
conversion makes soils appear 100× more permeable, draining unrealistically fast.

### 7.5 Calibration file uses multipliers, not absolute values (dt_011)
KSATH=10 means multiply base Ksat by 10, not set Ksat to 10 m/s. Setting absolute
values (e.g., 1e-5 for Ksat) when the field is a multiplier produces near-zero flow.

### 7.6 Spin-up is essential for groundwater initialization (dt_012)
Running without spin-up (INIT_MODE=0, SIMULATION_MODE=0) starts from arbitrary IC.
Groundwater may take years to equilibrate, producing unrealistic baseflow for the
first several years. Use SIMULATION_MODE=1 for spin-up, then restart with the `.ic` output.

### 7.7 CVODE tolerance controls mass conservation (dt_013)
Setting ABSTOL too loose (>0.01 m) causes mass balance errors that accumulate.
Too tight (<1e-6) causes solver failures. Default ABSTOL=1e-4 m is usually safe.

### 7.8 Output intervals use special codes (dt_014)
Para file output codes: -1=yearly, -2=monthly, -3=daily, -4=hourly, 0=off, or
positive integer for seconds. Confusing -3 (daily) with 3 (every 3 seconds) produces
massive output files that fill disk.

---

## 8. Output Variables

### 8.1 Element-based outputs (per triangular element)
| Variable | File suffix | Unit | Description |
|----------|-------------|------|-------------|
| SURF | `.surf.dat` | m | Surface water depth |
| UNSAT | `.unsat.dat` | m | Unsaturated zone storage |
| GW | `.gw.dat` | m | Groundwater head |
| SNOW | `.snow.dat` | m | Snow water equivalent |
| CMC | `.cmc.dat` | m | Canopy moisture storage |
| INFIL | `.infil.dat` | m/s | Infiltration rate |
| RECHARGE | `.recharge.dat` | m/s | GW recharge rate |
| EC | `.ec.dat` | m/s | Canopy evaporation |
| ETT | `.ett.dat` | m/s | Transpiration |
| EDIR | `.edir.dat` | m/s | Direct soil evaporation |

### 8.2 River-based outputs (per river segment)
| Variable | File suffix | Unit | Description |
|----------|-------------|------|-------------|
| RIVSTG | `.stage.dat` | m | River water stage |
| RIVFLX0-5 | `.rivflx[0-5].dat` | m3/s | River fluxes (up/down/left/right) |

### 8.3 Output File Format
Binary files contain double-precision values. Each record:
`[time_stamp (int)] [value_elem1 (double)] [value_elem2 (double)] ... [value_elemN (double)]`

Use `output_parser.py` or the `PIHM-utils` Python package to convert to CSV/DataFrame.

---

## 9. Execution

### 9.1 Command Line
```bash
./pihm [-b] [-c] [-d] [-f] [-s] [-t] [-V] [-v] [-o output_dir] <project_name>
```

| Flag | Description |
|------|-------------|
| `-b` | Brief mode (minimal screen output) |
| `-c` | Elevation correction (fix surface sinks) |
| `-d` | Debug mode (CVODE log file) |
| `-f` | Fixed-length spin-up (don't stop at equilibrium) |
| `-s` | Silent mode |
| `-t` | Tecplot output format |
| `-v` | Verbose mode |
| `-V` | Print version and exit |
| `-o dir` | Custom output directory name |

### 9.2 Directory Layout
```
MM-PIHM/
  input/<project>/          # All input files
    <project>.mesh
    <project>.att
    <project>.soil
    <project>.geol
    <project>.lc
    <project>.meteo
    <project>.lai
    <project>.bc
    <project>.para
    <project>.calib
    <project>.ic
    <project>.riv
  output/<run_name>/        # Output directory
    <project>.surf.dat
    <project>.gw.dat
    ...
```

### 9.3 Spin-up Workflow
```bash
# Step 1: Run spin-up
# Set SIMULATION_MODE = 1 in .para
./pihm -o spinup_run ShaleHills

# Step 2: Copy IC file
cp output/spinup_run/ShaleHills.ic input/ShaleHills/ShaleHills.ic

# Step 3: Run with restart
# Set SIMULATION_MODE = 0, INIT_MODE = 1 in .para
./pihm -o production_run ShaleHills
```

---

## 10. Calibration Guide

### 10.1 Priority Parameters (sensitivity order)
| Priority | Parameter | Range | Controls |
|----------|-----------|-------|----------|
| 1 | KSATH | 0.01–100 | Lateral groundwater flow, baseflow |
| 2 | KSATV | 0.01–100 | Vertical percolation, recharge |
| 3 | KINF | 0.01–100 | Infiltration rate, surface runoff |
| 4 | KMACSATH | 0.01–100 | Macropore lateral flow |
| 5 | DMAC | 0.1–10 | Macropore depth, preferential flow |
| 6 | ROUGH_RIV | 0.1–10 | Channel flow velocity |
| 7 | PRCP | 0.8–1.2 | Precipitation bias correction |
| 8 | ALPHA | 0.1–10 | Soil water retention curve |
| 9 | POROSITY | 0.5–2.0 | Soil storage capacity |
| 10 | DROOT | 0.1–5.0 | Root zone depth, ET partitioning |

### 10.2 Calibration Strategy
1. Start with spin-up to get realistic IC
2. Adjust KSATH for baseflow recession shape
3. Adjust KINF/KSATV for storm peak magnitude
4. Adjust DMAC/KMACSATH for quick-flow response
5. Adjust PRCP if systematic volume bias exists
6. Fine-tune ROUGH_RIV for peak timing

---

## 11. Validation Reference

**Test Basin:** Shale Hills, Pennsylvania, USA
**Coordinates:** 40.66°N, 77.91°W
**Area:** ~8 ha (0.08 km2)
**Period:** 2009-01-01 to 2009-12-31
**Elements:** 535 triangular elements, 20 river segments
**Data Source:** Bundled ShaleHills example

---

## 12. Quick Start

```bash
# 1. Clone and build
git clone https://github.com/PSUmodeling/MM-PIHM.git
cd MM-PIHM
make cvode
make pihm

# 2. Set OpenMP threads
export OMP_NUM_THREADS=4

# 3. Run ShaleHills example
./pihm -o test_run ShaleHills

# 4. Parse output
python3 ki/tools/output_parser.py \
  --input output/test_run/ \
  --project ShaleHills \
  --variables gw,surf,rivflx1 \
  --output results.csv
```

---

## 13. Diagnostic Triplets Summary

| ID | Stage | Failure Domain | Severity | Brief |
|----|-------|---------------|----------|-------|
| dt_001 | S3 | unit_conversion | silent | Precipitation not in kg/m2/s |
| dt_002 | S3 | unit_conversion | silent | Temperature not in Kelvin |
| dt_003 | S3 | unit_conversion | silent | Pressure not in Pascals |
| dt_004 | S3 | unit_conversion | degraded | RH vs specific humidity confusion |
| dt_005 | S3 | unit_conversion | silent | Radiation MJ/m2/day vs W/m2 |
| dt_006 | S3 | unit_conversion | degraded | Wind speed km/hr vs m/s |
| dt_007 | S4 | unit_conversion | silent | Ksat cm/hr vs m/s |
| dt_008 | S4 | unit_conversion | silent | vG alpha 1/cm vs 1/m |
| dt_009 | S4 | unit_conversion | degraded | Elevation/depth cm vs m |
| dt_010 | S4 | unit_conversion | silent | Bulk density kg/m3 vs g/cm3 |
| dt_011 | S5 | parameter_format | silent | Calib multiplier vs absolute |
| dt_012 | S6 | initialization | degraded | No spin-up for GW |
| dt_013 | S7 | solver_config | degraded | CVODE tolerance too loose |
| dt_014 | S5 | parameter_format | degraded | Output interval code confusion |
| dt_015 | S7 | runtime | fatal | CVODE convergence failure |
| dt_016 | S1 | mesh_quality | degraded | Degenerate triangles in mesh |
| dt_017 | S3 | data_gap | degraded | Missing forcing timesteps |
| dt_018 | S4 | parameter_format | silent | Soil type index mismatch |
| dt_019 | S8 | output_format | degraded | Binary endianness mismatch |
| dt_020 | S7 | runtime | fatal | Negative state variable crash |

---

## 14. File Structure

```
ki/
  SKILL.md                          # This file
  tools/
    forcing_converter.py            # S3: Met data → PIHM .meteo
    soil_converter.py               # S4: Soil DB → PIHM .soil/.geol
    run_pihm.py                     # S7: Execute PIHM binary
    output_parser.py                # S8: Binary output → CSV
  docs/
    s3_forcing_preparation.md       # Forcing preparation skill
    s4_soil_parameterization.md     # Soil parameter skill
    s5_configuration.md             # Parameter configuration skill
    s7_model_execution.md           # Model execution skill
    s8_output_analysis.md           # Output analysis skill
  diagnostics/
    triplets.yaml                   # 20 diagnostic triplets
```
