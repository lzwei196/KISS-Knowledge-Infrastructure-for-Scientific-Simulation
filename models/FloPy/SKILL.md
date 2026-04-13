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

# FloPy v3.11.0 — Knowledge Infrastructure

**Package**: `flopy-groundwater-ki` v1.0.0
**Model**: FloPy v3.11.0 (Python interface to MODFLOW 6, MODFLOW-2005, MODFLOW-NWT, MODFLOW-USG, MT3DMS, SEAWAT, MODPATH)
**Domain**: Groundwater flow and transport modeling
**Last updated**: 2026-03-25
**Stats**: 5 tools | 7 skill documents | 20 diagnostic triplets | ~1,800 lines of validated Python
**Validation status**: `validated` (Freyberg aquifer, steady-state + transient)

---

## Overview

This knowledge infrastructure enables autonomous construction, execution, and post-processing of MODFLOW-based groundwater models using FloPy. FloPy is a Python package that provides a scripting interface to create, run, and post-process models for the MODFLOW family of groundwater codes developed by the U.S. Geological Survey.

**What FloPy does**: FloPy generates MODFLOW input files from Python objects, invokes the MODFLOW executable, and reads binary/text output files back into Python arrays and DataFrames. It supports:

- **MODFLOW 6** (MF6): Latest modular groundwater flow model (GWF, GWT, GWE)
- **MODFLOW-2005**: Classic structured grid groundwater flow
- **MODFLOW-NWT**: Newton-Raphson formulation for unconfined flow
- **MODFLOW-USG**: Unstructured grid support
- **MT3DMS / MT3D-USGS**: Solute transport
- **SEAWAT**: Variable-density flow + transport
- **MODPATH 6/7**: Particle tracking

**Key architecture**: FloPy is a *pre/post-processor*, not a numerical solver. It writes input files, calls the MODFLOW binary, and reads output. The MODFLOW binary must be installed separately via `get-modflow :`.

**Execution pattern**:
```python
import flopy
# 1. Build model objects
sim = flopy.mf6.MFSimulation(sim_name='mymodel', sim_ws='./workspace')
# 2. Write input files
sim.write_simulation()
# 3. Run MODFLOW binary
sim.run_simulation()
# 4. Read output
head = gwf.output.head().get_data()
budget = gwf.output.budget()
```

---

## Installation

### Python Package

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install FloPy with core dependencies
pip install flopy

# Required dependencies (auto-installed):
#   numpy >=1.20.3, <3.0
#   matplotlib >=1.4.0
#   pandas >=2.0.0

# Optional dependencies for full functionality:
pip install flopy[optional]
# Includes: scipy, shapely, geopandas, netcdf4, pyproj, rasterio, h5py, vtk, pyvista
```

### MODFLOW Binaries

```bash
# Install MODFLOW 6 and related executables
# This downloads pre-compiled binaries to ~/.local/share/flopy/bin/
get-modflow :

# Or install to a specific directory:
get-modflow /path/to/bin

# Verify:
mf6 --version
```

### Binary locations (after get-modflow)

| Binary | Description | Default path |
|--------|-------------|--------------|
| `mf6` | MODFLOW 6 | `~/.local/share/flopy/bin/mf6` |
| `mf2005` | MODFLOW-2005 | `~/.local/share/flopy/bin/mf2005` |
| `mfnwt` | MODFLOW-NWT | `~/.local/share/flopy/bin/mfnwt` |
| `mp7` | MODPATH 7 | `~/.local/share/flopy/bin/mp7` |
| `mt3dms` | MT3DMS | `~/.local/share/flopy/bin/mt3dms` |
| `mt3dusgs` | MT3D-USGS | `~/.local/share/flopy/bin/mt3dusgs` |

---

## MODFLOW Input/Output System

### Input File Structure (MODFLOW 6)

MODFLOW 6 uses a hierarchical file structure:

```
workspace/
  mfsim.nam          # Simulation name file (master control)
  model.tdis         # Temporal discretization
  model.ims          # Iterative model solution (solver)
  model.nam          # Model name file (lists packages)
  model.dis          # Spatial discretization (grid)
  model.ic           # Initial conditions (starting heads)
  model.npf          # Node property flow (K, storage)
  model.sto          # Storage (Ss, Sy for transient)
  model.chd          # Constant head boundaries
  model.wel          # Well package (pumping)
  model.rch          # Recharge package
  model.riv          # River package
  model.drn          # Drain package
  model.ghb          # General head boundary
  model.oc           # Output control
  model.hds          # Binary head output (written by MODFLOW)
  model.bud          # Binary budget output (written by MODFLOW)
  model.lst          # Listing file (text log, written by MODFLOW)
```

### Input File Format (MODFLOW 6)

MODFLOW 6 uses a block-based text format:
```
BEGIN OPTIONS
  LENGTH_UNITS  METERS
  TIME_UNITS  DAYS
END OPTIONS

BEGIN DIMENSIONS
  NLAY  3
  NROW  40
  NCOL  20
END DIMENSIONS

BEGIN GRIDDATA
  DELR
    CONSTANT 250.0
  DELC
    CONSTANT 250.0
  TOP
    CONSTANT 35.0
  BOTM LAYERED
    CONSTANT 25.0
    CONSTANT 15.0
    CONSTANT 0.0
END GRIDDATA
```

### Input File Format (MODFLOW-2005)

MODFLOW-2005 uses fixed-format or free-format text files, controlled by a `.nam` file:
```
LIST   2  model.list
DIS   11  model.dis
BAS6  13  model.bas
LPF   15  model.lpf
WEL   20  model.wel
RCH   22  model.rch
PCG   27  model.pcg
OC    14  model.oc
DATA(BINARY) 50  model.hds
DATA(BINARY) 51  model.cbc
```

---

## Unit System — Critical Traps

MODFLOW is unit-agnostic — the user must ensure all inputs use consistent units. FloPy does NOT perform automatic unit conversion. This is the #1 source of silent errors.

### Unit Convention Table

| Variable | Common Source Unit | MODFLOW Convention | Conversion | Trap ID |
|----------|-------------------|-------------------|------------|---------|
| Hydraulic conductivity (K) | m/day | Length/Time (must match DIS) | None if L=meters, T=days | dt_001 |
| Recharge | mm/day | Length/Time (e.g., m/day) | mm/day ÷ 1000 = m/day | dt_002 |
| Well pumping rate | L/s or m³/hr | Length³/Time (e.g., m³/day) | L/s × 86.4 = m³/day | dt_003 |
| Specific storage (Ss) | 1/m | 1/Length | Must match length unit | dt_004 |
| Specific yield (Sy) | dimensionless | dimensionless (0-1) | None | — |
| River conductance | m²/day | Length²/Time | K × L × W / bed_thickness | dt_005 |
| Head / elevation | m ASL | Length (same as grid) | Must match grid datum | dt_006 |
| Layer thickness | m | Length | Top - Bottom for each cell | — |
| Time (stress period) | days | Time (must match ITMUNI) | Depends on ITMUNI setting | dt_007 |
| Evapotranspiration | mm/day | Length/Time (e.g., m/day) | mm/day ÷ 1000 = m/day | dt_008 |
| General Head conductance | m²/day | Length²/Time | Similar to river conductance | dt_005 |

### ITMUNI (Time Unit Codes)

| Code | Unit | Notes |
|------|------|-------|
| 0 | undefined | Dangerous — no unit checking |
| 1 | seconds | |
| 2 | minutes | |
| 3 | hours | |
| 4 | days | **Most common** |
| 5 | years | |

### LENUNI (Length Unit Codes)

| Code | Unit | Notes |
|------|------|-------|
| 0 | undefined | Dangerous — no unit checking |
| 1 | feet | US customary |
| 2 | meters | **Most common (SI)** |
| 3 | centimeters | |

---

## Pipeline (7 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | (manual) | Define study area, grid, periods, packages |
| 1 | Grid & discretization | `build_grid_from_dem` | DEM to model grid (DIS package) |
| 2 | Aquifer properties | `convert_soil_to_aquifer` | HWSD/soil data to K, Ss, Sy (NPF/LPF) |
| 3 | Forcing / boundaries | `convert_forcing_to_modflow` | Recharge, rivers, wells, ET (RCH/WEL/RIV/EVT) |
| 4 | Model assembly | (FloPy API) | Combine packages, write input files |
| 5 | Execution | `run_modflow` | Run MODFLOW binary with pre/post checks |
| 6 | Output analysis | `parse_modflow_output` | Extract heads, budgets, drawdown to CSV/arrays |

### Stage Dependencies

```
Stage 0 (config) ──→ Stage 1 (grid)
                  ──→ Stage 2 (properties)   ──→ Stage 4 (assembly) ──→ Stage 5 (run) ──→ Stage 6 (output)
                  ──→ Stage 3 (forcing)       ↗
```

Stages 1, 2, 3 can run in parallel after Stage 0. Stage 4 depends on 1+2+3.

---

## Tools Reference

| Tool | Stage | Script Path | Lines | Purpose |
|------|-------|-------------|------:|---------|
| `build_grid_from_dem` | s1 | `tools/build_grid_from_dem.py` | 320 | DEM → MODFLOW DIS grid (structured) |
| `convert_soil_to_aquifer` | s2 | `tools/convert_soil_to_aquifer.py` | 280 | HWSD soil → K, Ss, Sy arrays |
| `convert_forcing_to_modflow` | s3 | `tools/convert_forcing_to_modflow.py` | 350 | Climate/hydro data → recharge, boundaries |
| `run_modflow` | s5 | `tools/run_modflow.py` | 250 | Execute MODFLOW with error handling |
| `parse_modflow_output` | s6 | `tools/parse_modflow_output.py` | 400 | Binary output → CSV, arrays, plots |

**Total**: 5 tools, ~1,600 lines of validated Python code.

---

## Skill Documents

| Stage | Document | Topic |
|-------|----------|-------|
| s1 | `docs/s1_grid_discretization.md` | Grid creation from DEM, cell sizing |
| s2 | `docs/s2_aquifer_properties.md` | Soil-to-aquifer property mapping |
| s3 | `docs/s3_forcing_boundaries.md` | Recharge, wells, rivers, ET |
| s4 | `docs/s4_model_assembly.md` | FloPy model assembly workflow |
| s5 | `docs/s5_execution.md` | Running MODFLOW, convergence |
| s6 | `docs/s6_output_analysis.md` | Head, budget, water balance parsing |
| s7 | `docs/s7_calibration.md` | Parameter estimation, PEST integration |

---

## Critical Domain Knowledge

### 1. Unit Consistency is YOUR Responsibility (dt_001, dt_002, dt_003)

MODFLOW is unit-agnostic. If you set LENUNI=2 (meters) and ITMUNI=4 (days), then:
- K must be in m/day
- Recharge must be in m/day (NOT mm/day)
- Well rates must be in m³/day (NOT L/s)
- Conductances must be in m²/day

FloPy does NOT warn about unit mismatches. A recharge of 3.0 (meaning 3 mm/day) entered as 3.0 m/day gives 1000x too much water. The model may still converge but heads will be wrong.

### 2. Zero-Based Indexing (dt_009)

FloPy uses zero-based indexing: Layer 0, Row 0, Column 0 is the first cell. MODFLOW documentation and many references use 1-based. A well at "layer 1, row 5, col 10" in MODFLOW docs should be `(0, 4, 9)` in FloPy. Off-by-one errors silently place boundaries in wrong cells.

### 3. Stress Period Data Dictionaries (dt_010)

Boundary conditions (WEL, CHD, RIV, etc.) use dictionaries keyed by stress period number (zero-based). If the dictionary has fewer entries than stress periods, the last entry repeats. An empty list `[]` means "turn off all boundaries for this period." Missing keys repeat the previous period — they do NOT default to zero.

### 4. MODFLOW 6 vs MODFLOW-2005 Package Names (dt_011)

MODFLOW 6 uses different package names than MF2005:
- MF2005 `LPF` → MF6 `NPF` (Node Property Flow)
- MF2005 `PCG` → MF6 `IMS` (Iterative Model Solution)
- MF2005 `BAS` → MF6 `IC` (Initial Conditions) + model options
- MF2005 fixed-format → MF6 block-based free-format

Mixing conventions crashes with cryptic errors.

### 5. Dry Cells and HDRY (dt_012)

Cells that go dry during simulation get head value HDRY (-1e30 by default). If you compute drawdown or gradients without filtering HDRY values, you get nonsense results. Always mask: `head[head < -1e29] = np.nan`.

### 6. Binary Output File Precision (dt_013)

MODFLOW binary output (.hds, .bud) defaults to single precision (float32). Some models use double precision. Using the wrong precision setting in FloPy's HeadFile/CellBudgetFile reader produces garbage data without errors. Check with: `flopy.utils.HeadFile(path, precision='single')` vs `precision='double'`.

### 7. Layered vs Constant Arrays (dt_014)

For multi-layer models, the `LAYERED` keyword means data is provided per-layer. Without it, a single array covers all layers. Omitting `LAYERED` in MF6 when you have per-layer data silently uses only the first layer's values for all layers.

### 8. Steady-State vs Transient (dt_015)

In MODFLOW-2005, steady-state is set per stress period in the DIS package (`steady=[True, False, ...]`). In MF6, it's in the TDIS package. If a transient period is accidentally set as steady-state, storage terms are ignored, and heads jump instantaneously. The model converges but results are physically wrong.

### 9. Conductance Calculation (dt_005)

River and GHB conductance = K_bed × Area / bed_thickness. Common mistakes:
- Using aquifer K instead of riverbed K (10-100x too high)
- Forgetting to multiply by cell width and river length
- Using thickness of aquifer layer instead of riverbed thickness

---

## Quick Start: MODFLOW 6 Steady-State Example

```python
import flopy
import numpy as np

# Workspace
ws = './mymodel'
name = 'mymodel'

# Create simulation
sim = flopy.mf6.MFSimulation(sim_name=name, sim_ws=ws, exe_name='mf6')

# Time discretization (1 steady-state period)
tdis = flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(1.0, 1, 1.0)])

# Solver
ims = flopy.mf6.ModflowIms(sim, complexity='SIMPLE')

# Groundwater flow model
gwf = flopy.mf6.ModflowGwf(sim, modelname=name, save_flows=True)

# Grid: 10x10, 1 layer, 100m cells, 50m thick
dis = flopy.mf6.ModflowGwfdis(gwf, nlay=1, nrow=10, ncol=10,
                                delr=100.0, delc=100.0,
                                top=50.0, botm=[0.0])

# Initial conditions
ic = flopy.mf6.ModflowGwfic(gwf, strt=40.0)

# Hydraulic properties (K = 10 m/day)
npf = flopy.mf6.ModflowGwfnpf(gwf, k=10.0, save_specific_discharge=True)

# Constant head boundaries (west=50m, east=40m)
chd_data = [[(0, i, 0), 50.0] for i in range(10)]
chd_data += [[(0, i, 9), 40.0] for i in range(10)]
chd = flopy.mf6.ModflowGwfchd(gwf, stress_period_data=chd_data)

# Recharge (0.001 m/day = 1 mm/day)
rch = flopy.mf6.ModflowGwfrcha(gwf, recharge=0.001)

# Output control
oc = flopy.mf6.ModflowGwfoc(gwf,
    head_filerecord=f'{name}.hds',
    budget_filerecord=f'{name}.bud',
    saverecord=[('HEAD', 'ALL'), ('BUDGET', 'ALL')])

# Write and run
sim.write_simulation()
success, buff = sim.run_simulation()

# Read results
head = gwf.output.head().get_data()
bud = gwf.output.budget()
```

---

## Output Files Reference

| File | Format | Reader | Contents |
|------|--------|--------|----------|
| `.hds` | Binary | `flopy.utils.HeadFile` | Head values per layer/time |
| `.bud` / `.cbc` | Binary | `flopy.utils.CellBudgetFile` | Cell-by-cell flow budgets |
| `.ddn` | Binary | `flopy.utils.HeadFile` | Drawdown values |
| `.ucn` | Binary | `flopy.utils.UcnFile` | Concentration (MT3D) |
| `.lst` | Text | Direct read | Listing file with water balance |
| `.obs.csv` | CSV | `pandas.read_csv` | Observation output |
| `.hds.ts` | Binary | `flopy.utils.HeadFile` | Head time series at obs points |
| `.mp7.pathline` | Binary | `flopy.utils.PathlineFile` | Particle pathlines (MODPATH) |
| `.mp7.endpoint` | Binary | `flopy.utils.EndpointFile` | Particle endpoints (MODPATH) |

### Reading Binary Output

```python
# Head file
hds = flopy.utils.HeadFile(f'{ws}/{name}.hds')
head = hds.get_data(kstpkper=(0, 0))    # Step 0, Period 0
times = hds.get_times()
all_heads = hds.get_alldata()            # (ntimes, nlay, nrow, ncol)

# Budget file
cbb = flopy.utils.CellBudgetFile(f'{ws}/{name}.bud')
records = cbb.get_unique_record_names()  # Available budget terms
rch_budget = cbb.get_data(text='RCH')    # Recharge budget
spdis = cbb.get_data(text='DATA-SPDIS')  # Specific discharge vectors

# Water balance from listing file
mfl = flopy.utils.MfListBudget(f'{ws}/{name}.lst')
df_flux, df_vol = mfl.get_dataframes()
```

---

## Visualization

```python
import matplotlib.pyplot as plt
import flopy.plot

# Map view
fig, ax = plt.subplots(figsize=(10, 10))
pmv = flopy.plot.PlotMapView(model=gwf, ax=ax)
pmv.plot_grid(colors='grey', linewidths=0.5)
pmv.plot_array(head, cmap='viridis')
pmv.plot_bc('WEL', color='red')
pmv.plot_bc('RIV', color='blue')
pmv.contour_array(head, levels=10, linewidths=1.)
plt.colorbar(pmv.plot_array(head), ax=ax, label='Head (m)')

# Cross-section
fig, ax = plt.subplots(figsize=(12, 4))
pxs = flopy.plot.PlotCrossSection(model=gwf, line={'row': 5}, ax=ax)
pxs.plot_array(head, cmap='viridis')
pxs.plot_grid(colors='grey', linewidths=0.5)
```

---

## Diagnostics Summary

20 diagnostic triplets in `diagnostics/triplets.yaml` covering:
- **Unit conversion** (dt_001 — dt_008): Recharge mm→m, well L/s→m³/day, K consistency
- **Indexing** (dt_009 — dt_010): Zero-based, stress period dictionaries
- **Package configuration** (dt_011 — dt_015): MF6 vs MF2005, dry cells, precision, layered arrays
- **Solver convergence** (dt_016 — dt_018): Non-convergence, oscillation, outer/inner iterations
- **Boundary conditions** (dt_019 — dt_020): Conductance, head-dependent boundaries
