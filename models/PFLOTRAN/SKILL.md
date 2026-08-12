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

# PFLOTRAN Knowledge Infrastructure

**Package**: hydrocraft-pflotran-subsurface v1.1.0
**Domain**: Groundwater flow and reactive transport; 1D vadose zone soil moisture
**Model**: PFLOTRAN (Parallel Flow and Transport)
**Stats**: 4 tools, 5 skill documents, 26 diagnostic triplets
**Last updated**: 2026-04-30 — added 1D vadose zone / FLUXNET SWC validation workflow
  (3-site campaign: CN-Din, CN-Qia, CN-HaM; best result NSE=0.471 at CN-HaM v2)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for recharge forcing documentation.
See `data_ki/GLHYMPS/SKILL.md` for hydrogeology data.
See `data_ki/FanWTD/SKILL.md` for water table depth.
See `data_ki/GRACE/SKILL.md` for GRACE TWS validation data.


## 1. Model Overview

PFLOTRAN is a massively parallel, open-source simulator for modeling
multiphase flow, reactive multicomponent transport, and geomechanics
in the subsurface. Developed primarily at Los Alamos, Sandia, and Oak Ridge
National Laboratories, it solves the Richards equation, variably saturated
flow, and fully coupled reactive transport using PETSc for parallel
scalability.

### Key Capabilities

| Capability | Description |
|---|---|
| Richards Equation | Variably saturated single-phase groundwater flow |
| General Mode | Multiphase (water + gas) flow with phase transitions |
| TH Mode | Coupled thermal-hydrologic (heat + flow) |
| Reactive Transport | Aqueous, mineral, sorption, gas-phase chemistry |
| Geomechanics | Poromechanical coupling (experimental) |
| Structured Grid | Cartesian (IJK) grids with dx/dy/dz specification |
| Unstructured Grid | Implicit/explicit formats, Exodus II, ASCII meshes |

### Architecture

PFLOTRAN is written in Fortran 90/95 and depends on:
- **PETSc** (Portable, Extensible Toolkit for Scientific Computation) — solver framework
- **MPI** — message passing for parallel execution
- **HDF5** — hierarchical data format for I/O
- **BLAS/LAPACK** — linear algebra

Execution model: `mpirun -n <nproc> pflotran -pflotranin <input_file.in>`

---

## 2. Installation

### 2.1 Prerequisites

```bash
# Ubuntu/Debian
sudo apt-get install -y build-essential gfortran cmake \
  libopenmpi-dev openmpi-bin libhdf5-openmpi-dev \
  liblapack-dev libblas-dev python3-dev git

# PETSc (required, v3.18+ recommended)
export PETSC_DIR=/opt/petsc
export PETSC_ARCH=linux-gnu-opt
git clone -b release https://gitlab.com/petsc/petsc.git $PETSC_DIR
cd $PETSC_DIR
./configure --with-cc=mpicc --with-cxx=mpicxx --with-fc=mpif90 \
  --with-debugging=0 --download-fblaslapack --download-hdf5 \
  --download-metis --download-parmetis
make all
```

### 2.2 Building PFLOTRAN

```bash
git clone https://bitbucket.org/pflotran/pflotran.git
cd pflotran/src/pflotran
make pflotran
# Binary at: pflotran/src/pflotran/pflotran
```

### 2.3 Docker Alternative

```bash
docker pull pflotran/pflotran:latest
docker run -v $(pwd):/work pflotran/pflotran -pflotranin /work/input.in
```

### 2.4 Verification

```bash
cd pflotran/regression_tests/default/543
mpirun -n 1 pflotran -pflotranin 543_flow.in
# Should produce 543_flow.h5 and 543_flow-obs-0.tec
```

---

## 3. Pipeline Stages

PFLOTRAN simulation pipeline has 8 stages:

```
s0_domain_setup ──┐
s1_grid_generation ──┤
s2_material_properties ──┤
s3_forcing_boundary ──┼──→ s5_input_deck_assembly ──→ s6_execution ──→ s7_output_analysis
s4_initial_conditions ──┤
                        └──→ s8_coupling (optional)
```

| Stage | Tool | Description |
|---|---|---|
| s0 | manual | Define domain extent, geology, aquifer properties |
| s1 | `convert_grid_to_pflotran.py` | Generate structured/unstructured mesh |
| s2 | `convert_soil_to_pflotran.py` | Map HWSD/GLHYMPS to material properties |
| s3 | `convert_forcing_to_pflotran.py` | Convert recharge/BC from global datasets |
| s4 | manual | Set initial head/concentration conditions |
| s5 | `generate_pflotran_input.py` | Assemble complete .in input deck |
| s6 | `run_pflotran.py` | Execute PFLOTRAN binary |
| s7 | `parse_pflotran_output.py` | Extract results to CSV/figures |
| s8 | manual | Couple to surface water / land surface models |

### Parallelism

Stages s1, s2, s3, s4 can run in parallel after s0 (domain definition).
Stage s5 depends on all of s1–s4.
Stage s6 depends on s5.
Stages s7, s8 depend on s6.

---

## 4. Input Format

PFLOTRAN uses a keyword-based input deck (`.in` file) with hierarchical blocks.
Blocks are delimited by keywords and `END` or `/` terminators.

### 4.1 Block Structure

```
SIMULATION
  SIMULATION_TYPE SUBSURFACE
  PROCESS_MODELS
    SUBSURFACE_FLOW flow
      MODE RICHARDS
    /
  /
END

SUBSURFACE

GRID
  TYPE STRUCTURED
  NXYZ 100 100 10
  BOUNDS
    0.d0 0.d0 0.d0
    1000.d0 1000.d0 100.d0
  /
END

MATERIAL_PROPERTY soil
  ID 1
  POROSITY 0.35
  TORTUOSITY 0.5
  PERMEABILITY
    PERM_ISO 1.d-12
  /
  CHARACTERISTIC_CURVES cc1
END

CHARACTERISTIC_CURVES cc1
  SATURATION_FUNCTION VAN_GENUCHTEN
    ALPHA 1.d-4
    M 0.5
    LIQUID_RESIDUAL_SATURATION 0.1
  /
  PERMEABILITY_FUNCTION MUALEM_VG_LIQ
    M 0.5
    LIQUID_RESIDUAL_SATURATION 0.1
  /
END

FLUID_PROPERTY
  DIFFUSION_COEFFICIENT 1.d-9
END

OUTPUT
  TIMES y 0.25 0.5 1.0 2.0 5.0 10.0
  FORMAT HDF5
  VELOCITY_AT_CENTER
  VARIABLES
    LIQUID_PRESSURE
    LIQUID_SATURATION
  /
END

TIME
  FINAL_TIME 10.d0 y
  INITIAL_TIMESTEP_SIZE 1.d-3 y
  MAXIMUM_TIMESTEP_SIZE 0.1 y
END

REGION all
  COORDINATES
    0.d0 0.d0 0.d0
    1000.d0 1000.d0 100.d0
  /
END

REGION top
  FACE TOP
  COORDINATES
    0.d0 0.d0 100.d0
    1000.d0 1000.d0 100.d0
  /
END

FLOW_CONDITION initial
  TYPE
    LIQUID_PRESSURE HYDROSTATIC
  /
  DATUM 0.d0 0.d0 90.d0
  LIQUID_PRESSURE 101325.d0
END

FLOW_CONDITION recharge
  TYPE
    LIQUID_FLUX NEUMANN
  /
  LIQUID_FLUX 3.17d-9   ! ~100 mm/yr in m/s
END

INITIAL_CONDITION
  FLOW_CONDITION initial
  REGION all
END

BOUNDARY_CONDITION
  FLOW_CONDITION recharge
  REGION top
END

STRATA
  REGION all
  MATERIAL soil
END

END_SUBSURFACE
```

### 4.2 Units System

**PFLOTRAN uses SI units internally.** Unit conversion keywords are available
but the default expectation is SI:

| Variable | Internal Unit | Common Source Unit | Conversion |
|---|---|---|---|
| Permeability | m^2 | Darcy (D) | 1 D = 9.869233e-13 m^2 |
| Permeability | m^2 | milliDarcy (mD) | 1 mD = 9.869233e-16 m^2 |
| Hydraulic conductivity | m/s | m/day | 1 m/day = 1.1574e-5 m/s |
| Hydraulic conductivity | m/s | cm/hr | 1 cm/hr = 2.778e-6 m/s |
| Pressure | Pa | atm | 1 atm = 101325 Pa |
| Pressure | Pa | bar | 1 bar = 1e5 Pa |
| Pressure | Pa | psi | 1 psi = 6894.76 Pa |
| Recharge/flux | m/s | mm/yr | 1 mm/yr = 3.171e-11 m/s |
| Recharge/flux | m/s | mm/day | 1 mm/day = 1.1574e-8 m/s |
| Temperature | C | K | T(C) = T(K) - 273.15 |
| Concentration | mol/L | mg/L | depends on molar mass |
| Time | s | yr | 1 yr = 3.15576e7 s |
| Time | s | day | 1 day = 86400 s |
| Length | m | cm | 1 cm = 0.01 m |
| Diffusion coeff | m^2/s | cm^2/s | 1 cm^2/s = 1e-4 m^2/s |
| Porosity | - (0–1) | % | divide by 100 |
| van Genuchten alpha | 1/Pa | 1/cm (water) | 1/cm * 1/(rho*g) |

**CRITICAL**: PFLOTRAN supports inline unit specification via keywords:

```
LIQUID_FLUX 100.d0 mm/yr    ! PFLOTRAN converts internally
PERMEABILITY
  PERM_ISO 1.d0 darcy       ! PFLOTRAN converts internally
/
FINAL_TIME 10.d0 y           ! years
INITIAL_TIMESTEP_SIZE 1.d0 h ! hours
```

Supported time units: `s`, `min`, `h`, `d`, `w`, `mo`, `y`
Supported length units: `m`, `cm`, `km`
Supported pressure units: `Pa`, `kPa`, `MPa`, `atm`, `bar`
Supported flux units: `m/s`, `m/d`, `m/yr`, `mm/yr`, `cm/yr`

### 4.3 Unit Trap Table

| Trap ID | Variable | Wrong Unit | Correct Unit | Error Factor | Symptom |
|---|---|---|---|---|---|
| dt_001 | Permeability | Darcy (1.0) | m^2 (9.87e-13) | 1e12 | Unrealistic flow, instant drainage |
| dt_002 | Recharge | mm/yr (100) | m/s (3.17e-9) | 3.15e10 | Domain floods or dries instantly |
| dt_003 | Pressure | atm (1.0) | Pa (101325) | 1e5 | Near-zero head, no flow gradient |
| dt_004 | Hyd. conductivity | m/day | m/s | 86400 | Flow too fast by 5 orders |
| dt_005 | Porosity | % (35) | fraction (0.35) | 100 | >1.0 porosity, negative saturation |
| dt_006 | vG alpha | 1/cm | 1/Pa | ~10000 | Wrong capillary curve, instant drainage |
| dt_007 | Diffusion | cm^2/s | m^2/s | 10000 | Solute spreads 100x too fast |
| dt_008 | Temperature | K (293) | C (20) | offset | Wrong density, affects buoyancy |
| dt_009 | Concentration | mg/L | mol/L | MW | Wrong reaction rates |
| dt_010 | Time | yr (10) | s (3.15e8) | 3.15e7 | Simulation ends in seconds |

---

## 5. Output Format

### 5.1 HDF5 Output (`.h5`)

Primary output format. Contains:
- `/Coordinates/X`, `/Coordinates/Y`, `/Coordinates/Z` — cell centers
- `/Time:X.XXXXe+XX y/Liquid_Pressure` — pressure field per snapshot
- `/Time:X.XXXXe+XX y/Liquid_Saturation` — saturation field
- `/Time:X.XXXXe+XX y/Material_ID` — material zones
- `/Time:X.XXXXe+XX y/Liquid_Velocity_X,Y,Z` — Darcy velocity

### 5.2 Observation Files (`.tec`)

TecPlot-format time series at observation points:
```
TITLE = ""
VARIABLES = "Time [y]","Liq. Pressure [Pa]","Liq. Saturation [-]"
ZONE T="Observation: well_1"
1.000000e-03  2.058000e+05  9.876543e-01
2.000000e-03  2.059100e+05  9.877654e-01
```

### 5.3 VTK Output (`.vtk` / `.pvd`)

For ParaView visualization:
```
OUTPUT
  FORMAT VTK
  ...
END
```

### 5.4 Mass Balance (`.massbal`)

Tracks fluid/solute mass in/out of domain. Critical for verification.

---

## 6. Tools Reference

### 6.1 convert_forcing_to_pflotran.py

Converts meteorological / recharge data from global datasets (CMFD, ERA5, MSWX)
to PFLOTRAN boundary condition format.

**Key conversions**:
- Precipitation (mm/day) → recharge flux (m/s): multiply by 1.1574e-8
- Adjust for infiltration fraction (typically 10–30% of precipitation)
- Account for ET if not modeled explicitly

### 6.2 convert_soil_to_pflotran.py

Converts HWSD soil data and GLHYMPS hydrogeology to PFLOTRAN material properties.

**Key conversions**:
- HWSD texture class → van Genuchten parameters (Carsel & Parrish 1988)
- GLHYMPS log(K) → permeability in m^2
- GLHYMPS porosity (%) → fraction (0–1)

### 6.3 run_pflotran.py

Execution wrapper with pre-flight checks, timeout management, and output validation.

### 6.4 parse_pflotran_output.py

Reads HDF5 and TecPlot observation files, extracts time series to CSV,
computes water balance, and generates summary statistics.

---

## 7. Critical Domain Knowledge

### 7.1 Permeability vs Hydraulic Conductivity

PFLOTRAN uses **intrinsic permeability** (m^2), NOT hydraulic conductivity (m/s).
The relationship is: K = k * rho * g / mu

Where:
- K = hydraulic conductivity (m/s)
- k = intrinsic permeability (m^2)
- rho = fluid density (~998 kg/m^3)
- g = gravitational acceleration (9.8067 m/s^2)
- mu = dynamic viscosity (~1.002e-3 Pa.s at 20C)

For water at 20C: k (m^2) = K (m/s) * 1.024e-7

### 7.2 Pressure-Based vs Head-Based

PFLOTRAN solves for **liquid pressure** (Pa), not hydraulic head (m).
Conversion: P = rho * g * h + P_atm

Where h is the hydraulic head above the datum.
For initial conditions, use HYDROSTATIC with a datum point.

### 7.3 van Genuchten Parameters

The `ALPHA` parameter in PFLOTRAN is in units of **1/Pa**, NOT 1/cm.
Literature values are almost always in 1/cm (water column).

Conversion: alpha_Pa = alpha_cm / (rho * g) = alpha_cm / 9804.139

| Soil Texture | alpha (1/cm) | alpha (1/Pa) | n | m=1-1/n | theta_r |
|---|---|---|---|---|---|
| Sand | 0.145 | 1.479e-5 | 2.68 | 0.627 | 0.045 |
| Loamy Sand | 0.124 | 1.265e-5 | 2.28 | 0.561 | 0.057 |
| Sandy Loam | 0.075 | 7.651e-6 | 1.89 | 0.471 | 0.065 |
| Loam | 0.036 | 3.671e-6 | 1.56 | 0.359 | 0.078 |
| Silt Loam | 0.020 | 2.040e-6 | 1.41 | 0.291 | 0.067 |
| Clay Loam | 0.019 | 1.938e-6 | 1.31 | 0.237 | 0.095 |
| Silty Clay Loam | 0.010 | 1.020e-6 | 1.23 | 0.187 | 0.089 |
| Clay | 0.008 | 8.161e-7 | 1.09 | 0.083 | 0.068 |

### 7.4 Boundary Condition Types

| BC Type | PFLOTRAN Keyword | Use Case |
|---|---|---|
| Constant head | LIQUID_PRESSURE DIRICHLET | River/lake boundary |
| Recharge | LIQUID_FLUX NEUMANN | Top surface infiltration |
| No flow | (default) | Impermeable boundaries |
| Seepage face | LIQUID_PRESSURE SEEPAGE | Outcrop, drain |
| Well | SOURCE_SINK | Pumping/injection |

### 7.5 Steady-State vs Transient

For steady-state solutions, use `STEADY_STATE` in the `SIMULATION` block:
```
SIMULATION
  SIMULATION_TYPE SUBSURFACE
  PROCESS_MODELS
    SUBSURFACE_FLOW flow
      MODE RICHARDS
      OPTIONS
        STEADY_STATE
      /
    /
  /
END
```

### 7.6 Common Grid Configurations

For Bengbu-basin-scale (catchment) simulations:
- Horizontal resolution: 100–500 m
- Vertical layers: 5–20 layers, thinner near surface
- Total cells: 10,000–1,000,000
- Use STRUCTURED grid for regular domains
- Use UNSTRUCTURED for irregular boundaries or local refinement

---

## 8. Calibration Parameters (Priority Order)

| Priority | Parameter | Block | Range | Effect |
|---|---|---|---|---|
| 1 | PERM_ISO | MATERIAL_PROPERTY | 1e-16 to 1e-10 m^2 | Controls flow magnitude |
| 2 | POROSITY | MATERIAL_PROPERTY | 0.01 to 0.60 | Storage, transport velocity |
| 3 | vG ALPHA | CHARACTERISTIC_CURVES | 1e-7 to 1e-3 1/Pa | Capillary pressure curve |
| 4 | vG M | CHARACTERISTIC_CURVES | 0.05 to 0.80 | Retention curve shape |
| 5 | LIQUID_RESIDUAL_SATURATION | CHARACTERISTIC_CURVES | 0.0 to 0.40 | Irreducible water content |
| 6 | RECHARGE_FLUX | FLOW_CONDITION | site-specific | Water input magnitude |
| 7 | TORTUOSITY | MATERIAL_PROPERTY | 0.1 to 1.0 | Diffusive transport |
| 8 | LONGITUDINAL_DISPERSIVITY | MATERIAL_PROPERTY | 1 to 100 m | Solute spreading |

---

## 9. Validation Metrics

For groundwater models, use:
- **NSE** (Nash-Sutcliffe Efficiency): >0.5 acceptable, >0.7 good
- **KGE** (Kling-Gupta Efficiency): >0.5 acceptable, >0.7 good
- **PBIAS** (Percent Bias): |PBIAS| < 25% acceptable, < 10% good
- **RMSE** of hydraulic head: site-specific, typically < 1–2 m
- **Water balance error**: must be < 1% for numerical accuracy

---

## 10. 1D Vadose Zone Column — FLUXNET SWC Validation Workflow

Use this workflow to validate PFLOTRAN Richards-equation physics against
FLUXNET tower soil moisture observations (SWC_F_MDS_1). Validated against
3 Chinese FLUXNET sites (CN-Din, CN-Qia, CN-HaM).

### 10.1 Site Pre-screening (run before any model setup)

```python
import csv, numpy as np
from datetime import datetime

rows = list(csv.DictReader(open('FULLSET_DD.csv')))
sub  = [r for r in rows if start_year <= int(r['TIMESTAMP'][:4]) <= end_year]

p_vals  = [float(r['P_F']) for r in sub]
et_vals = [max(0, float(r['LE_F_MDS'])*86400/2.45e6) for r in sub]
ta_vals = [float(r['TA_F_MDS']) for r in sub if float(r['TA_F_MDS']) > -9990]
swc_valid = [float(r['SWC_F_MDS_1']) for r in sub if float(r['SWC_F_MDS_1']) > -9990]

# Screening criteria:
swc_coverage = len(swc_valid) / len(sub)       # must be > 0.90
p_mean = np.mean(p_vals)                        # must be > ET mean
min_ta = min(ta_vals) if ta_vals else -99       # freeze risk if < -5°C
neg_months = sum(
    np.mean([p for p,d in zip(p_vals,sub) if int(d['TIMESTAMP'][4:6])==m]) <
    np.mean([e for e,d in zip(et_vals,sub) if int(d['TIMESTAMP'][4:6])==m])
    for m in range(1,13))
phi_est = np.percentile(swc_valid, 95) / 0.95 / 100.0   # porosity estimate

# Max consecutive dry days (crash risk predictor for shallow root zone)
max_dry = 0; cur = 0
for p in p_vals:
    cur = (cur+1) if p < 0.1 else 0
    max_dry = max(max_dry, cur)
```

**Site suitability table:**

| Criterion | Suitable | Marginal | Unsuitable |
|-----------|----------|----------|------------|
| SWC coverage | > 90% | 70–90% | < 70% |
| Neg P-ET months | ≤ 3 | 4–6 | > 6 |
| Min temperature | > -5°C | -5 to -20°C | < -20°C |
| P/ET annual ratio | > 1.5 | 1.0–1.5 | < 1.0 |
| Max monsoon P / mean ET | < 2 | 2–3 | > 3 (see dt_026) |
| phi_est vs HWSD phi | within 15% | 15–30% diff | > 30% (override) |

**Pre-screened Chinese sites:**

| Site | Ecosystem | Suitability | Notes |
|------|-----------|-------------|-------|
| CN-HaM | Alpine meadow, Qinghai | ✅ Suitable | Override phi→0.60; NSE=0.47 achieved |
| CN-Din | Subtropical forest | ⚠️ Marginal | RZ=2.0m; NSE=-0.17 (bias from P-ET deficit treatment) |
| CN-Qia | Plantation forest | ❌ Unsuitable | Monsoon regime; structural +54% wet bias (dt_026) |
| CN-Cha | Temperate forest, Jilin | ❌ Unsuitable | 9/12 months ET>P; min T=-25.7°C |

### 10.2 Soil Properties (HWSD lookup + corrections)

```python
# Run the KI tool first
run_cmd(
    f"python {KI_TOOLS}/convert_soil_to_pflotran.py "
    f"--hwsd-csv {HWSD_CSV} --glhymps-shp {GLHYMPS_SHP} "
    f"--lat {lat} --lon {lon} --output {mat_json}",
    "convert_soil"
)

# MANDATORY post-processing patches:
with open(mat_json) as f:
    data = json.load(f)

# Patch 1: alpha unit correction (tool divides by 9804, should be 98.04)
if not data.get("alpha_unit_patch_v1"):
    for mat in data["materials"]:
        mat["vg_alpha_Pa"] *= 100.0
    data["alpha_unit_patch_v1"] = True   # idempotency guard (dt_023)

# Patch 2: bedrock K floor
for mat in data["materials"]:
    if mat["name"] == "bedrock" and mat["permeability_m2"] < 1e-20:
        mat["permeability_m2"] = 1e-14

with open(mat_json, "w") as f:
    json.dump(data, f, indent=2)

# Patch 3: organic soil porosity override (dt_024)
# If site is alpine meadow > 2500m AND phi_est > HWSD phi * 1.1:
if phi_est > top["porosity"] * 1.10:
    print(f"WARNING: Overriding HWSD phi={top['porosity']:.3f} → {phi_est:.3f}")
    top["porosity"] = min(phi_est, 0.70)   # cap at physical maximum
    # Do NOT save override back to materials.json — document it in the run log
```

### 10.3 Forcing and ET Sink Deck Setup

```python
# Forcing from FLUXNET daily:
for row in csv.DictReader(open(FLUXNET_DD)):
    p_mm   = float(row["P_F"])              # mm/day
    le_wm2 = float(row["LE_F_MDS"])         # W/m²
    et_mm  = max(0.0, le_wm2 * 86400.0 / 2.45e6)  # mm/day

    # Top BC: precipitation only (ALWAYS positive — no P-ET)
    net_ms = max(0.0, p_mm) / (1000.0 * 86400.0)   # m/s

    # ET sink rate (positive value; negate when writing to deck)
    et_ms  = et_mm / (1000.0 * 86400.0)             # m/s = m³/s for 1m² col
```

**COLD-SEASON / WINTER WINDOWS — gate precip by temperature (dt_027).**
RICHARDS mode is isothermal: NO snowpack, NO soil-freeze. If the scoring window
is sub-zero (high-altitude or winter), feeding precip straight to the top BC
applies SNOW as liquid recharge → a spurious SWC rise that anti-correlates with
the (frozen, slowly-draining) obs. Add a degree-day snow gate BEFORE building
the top-BC LIST, and wire the hydrostatic DATUM so the top cell starts at the
observed wetness (removes the cold-start transient):

```python
snowpack = 0.0
for date, p_mm, t in zip(dates, precip, tmean):
    if t < 0.0:                                   # snow: no infiltration
        snowpack += p_mm; infil_mm = 0.0
    else:                                         # rain + melt infiltrate
        melt = min(snowpack, 2.0*max(0.0, t)); snowpack -= melt
        infil_mm = p_mm + melt
    net_ms = infil_mm / (1000.0 * 86400.0)
# Initial datum for target top-cell SWC = s*phi (vG inverse):
#   Pc = ((Se**(-1/m))-1)**(1/n)/alpha ; head=Pc/9804 ; DATUM = z_top - head
```

Validated: SMAP L4 sm_rootzone at CN-HaM 2019 (obs only 2019-01-01..01-19, a
deep-winter window). Snow gating + IC datum 0.645 m flipped r from -0.83 to
+0.84, PBIAS -11% → +0.8%. NOTE the obs over a frozen window is near-constant
(std 0.107% VWC), so NSE is denominator-collapsed and STRUCTURALLY INVALID —
score with magnitude_accuracy (PBIAS), not NSE (dt_027).

**Root zone depth selection** (dt_020):

```python
# Choose ROOT_ZONE_DEPTH based on site hydrology:
if max_dry_days > 20:
    ROOT_ZONE_DEPTH = 2.0   # full column; very dry site
elif max_dry_days > 10:
    ROOT_ZONE_DEPTH = 1.5   # subtropical/temperate forest default
else:
    ROOT_ZONE_DEPTH = 1.0   # alpine meadow or mild dry season
```

**Characteristic curves** — SMOOTH placement is CRITICAL (dt_019):

```
CHARACTERISTIC_CURVES cc_soil
  SATURATION_FUNCTION VAN_GENUCHTEN      ← NO SMOOTH here
    ALPHA {alpha:.6e}
    M {m:.4f}d0
    LIQUID_RESIDUAL_SATURATION {Sr:.3f}d0
  /
  PERMEABILITY_FUNCTION MUALEM_VG_LIQ
    M {m:.4f}d0
    LIQUID_RESIDUAL_SATURATION {Sr:.3f}d0
    SMOOTH                                ← ONLY here
  /
END
```

### 10.4 HDF5 Extraction

```python
# ALWAYS import in this order (dt_025):
import netCDF4   # first — initializes HDF5 in compatible state
import h5py      # second

# Shape handling (dt_022):
with h5py.File(h5_file, "r") as f:
    for key in sorted(f.keys()):
        if not key.startswith("Time:"): continue
        day = float(key.replace("Time:","").replace("d","").strip())
        sat = np.array(f[key]["Liquid_Saturation"], dtype=float).flatten()
        top_swc = float(sat[-1]) * phi   # top cell = last index = highest z
```

### 10.5 Metrics and Interpretation

```python
R    = float(np.corrcoef(obs, sim)[0, 1])
NSE  = float(1 - np.sum((obs-sim)**2) / np.sum((obs-np.mean(obs))**2))
RMSE = float(np.sqrt(np.mean((obs-sim)**2)))
PBIAS= float(100 * (np.sum(sim) - np.sum(obs)) / np.sum(obs))

# If R > 0.6 but NSE < 0 — decompose:
sigma_obs = np.std(obs); mu_obs = np.mean(obs); mu_sim = np.mean(sim)
alpha = np.std(sim) / sigma_obs
beta  = (mu_sim - mu_obs) / sigma_obs
print(f"NSE = 2αR - α² - β² = {2*alpha*R:.3f} - {alpha**2:.3f} - {beta**2:.3f} = {NSE:.3f}")
# β² > 0.5 → bias dominates; fix PBIAS before re-running
```

**NSE < 0 diagnosis decision tree:**
- |PBIAS| > 25% → fix bias first (root zone depth, phi override)
- |PBIAS| < 10% but NSE < 0 → variability mismatch (α far from 1.0)
- Site is subtropical monsoon → structural bias, see dt_026

## 11. Coupling Points

| Coupled Model | Interface | Direction |
|---|---|---|
| VIC / SWAT+ | Recharge flux from land surface | LSM → PFLOTRAN (top BC) |
| CaMa-Flood | River stage as head BC | CaMa → PFLOTRAN (lateral BC) |
| MODFLOW | Head/flux exchange | Bidirectional |
| CLM / ELM | Root uptake as sink term | LSM ↔ PFLOTRAN |
| Reactive transport | Geochemistry within PFLOTRAN | Internal coupling |

---

## 11. Quick Start Example

### Minimal 1D Column (Richards Equation)

```bash
# 1. Create input file
cat > column.in << 'EOF'
SIMULATION
  SIMULATION_TYPE SUBSURFACE
  PROCESS_MODELS
    SUBSURFACE_FLOW flow
      MODE RICHARDS
    /
  /
END

SUBSURFACE

GRID
  TYPE STRUCTURED
  NXYZ 1 1 100
  BOUNDS
    0.d0 0.d0 0.d0
    1.d0 1.d0 10.d0
  /
END

MATERIAL_PROPERTY soil
  ID 1
  POROSITY 0.35d0
  TORTUOSITY 0.5d0
  PERMEABILITY
    PERM_ISO 1.d-12
  /
  CHARACTERISTIC_CURVES cc1
END

CHARACTERISTIC_CURVES cc1
  SATURATION_FUNCTION VAN_GENUCHTEN
    ALPHA 1.d-4
    M 0.5d0
    LIQUID_RESIDUAL_SATURATION 0.1d0
  /
  PERMEABILITY_FUNCTION MUALEM_VG_LIQ
    M 0.5d0
    LIQUID_RESIDUAL_SATURATION 0.1d0
  /
END

FLUID_PROPERTY
  DIFFUSION_COEFFICIENT 1.d-9
END

OUTPUT
  TIMES y 0.1 0.5 1.0 5.0 10.0
  FORMAT HDF5
  VARIABLES
    LIQUID_PRESSURE
    LIQUID_SATURATION
  /
END

TIME
  FINAL_TIME 10.d0 y
  INITIAL_TIMESTEP_SIZE 1.d-3 y
  MAXIMUM_TIMESTEP_SIZE 0.1 y
END

REGION all
  COORDINATES
    0.d0 0.d0 0.d0
    1.d0 1.d0 10.d0
  /
END

REGION top
  FACE TOP
  COORDINATES
    0.d0 0.d0 10.d0
    1.d0 1.d0 10.d0
  /
END

REGION bottom
  FACE BOTTOM
  COORDINATES
    0.d0 0.d0 0.d0
    1.d0 1.d0 0.d0
  /
END

FLOW_CONDITION initial
  TYPE
    LIQUID_PRESSURE HYDROSTATIC
  /
  DATUM 0.d0 0.d0 5.d0
  LIQUID_PRESSURE 101325.d0
END

FLOW_CONDITION recharge
  TYPE
    LIQUID_FLUX NEUMANN
  /
  LIQUID_FLUX 3.171d-9
END

FLOW_CONDITION drain
  TYPE
    LIQUID_PRESSURE SEEPAGE
  /
  LIQUID_PRESSURE 101325.d0
END

INITIAL_CONDITION
  FLOW_CONDITION initial
  REGION all
END

BOUNDARY_CONDITION top_bc
  FLOW_CONDITION recharge
  REGION top
END

BOUNDARY_CONDITION bottom_bc
  FLOW_CONDITION drain
  REGION bottom
END

STRATA
  REGION all
  MATERIAL soil
END

END_SUBSURFACE
EOF

# 2. Run PFLOTRAN
mpirun -n 1 pflotran -pflotranin column.in

# 3. Check output
h5ls column.h5
```

---

## 12. Data Sources for China Basins

| Dataset | Variable | Resolution | Path |
|---|---|---|---|
| GLHYMPS v2.0 | Permeability, Porosity | ~1 km polygons | `/data/groundwater/glhymps/` |
| Fan et al. WTD | Water table depth | 30 arc-sec | `/data/groundwater/fan_wtd/` |
| GLiM | Lithology class | 0.5 deg | `/data/groundwater/glim/` |
| HWSD | Soil texture, OC | 30 arc-sec | `/data/soil/HWSD_China_*.img` |
| CMFD | Precipitation, T | 0.1 deg, 3-hourly | `/data/forcing/Data_forcing_*` |
| ERA5 | Full met variables | 0.25 deg, hourly | External |

---

## 13. File Naming Conventions

```
<site>_<mode>.in           # Input deck (e.g., bengbu_richards.in)
<site>_<mode>.h5           # HDF5 output
<site>_<mode>-obs-0.tec    # Observation file (0-indexed)
<site>_<mode>-mas.dat      # Mass balance
<site>_<mode>.out          # Screen output log
```

---

## 14. Troubleshooting Quick Reference

| Symptom | Likely Cause | Fix |
|---|---|---|
| `PETSC ERROR` at startup | PETSc version mismatch | Rebuild with matching PETSc |
| Simulation stalls at t=0 | Bad initial condition | Use HYDROSTATIC, check datum |
| Time step cut to minimum | Nonlinear convergence failure | Reduce max dt, check BCs |
| All cells fully saturated | Recharge too high | Check flux units (m/s not mm/yr) |
| Negative saturation | Bad vG parameters | Check ALPHA units (1/Pa not 1/cm) |
| HDF5 file empty | OUTPUT block missing VARIABLES | Add explicit variable list |
| Mass balance error > 1% | Grid too coarse or dt too large | Refine grid/reduce dt |
| `Allocated memory exceeded` | Grid too large for RAM | Use more MPI processes |

---

*Generated by HydroCraft Knowledge Dissection Toolkit v1.0.0*
*Model: PFLOTRAN | Domain: Groundwater | Date: 2026-03-25*
