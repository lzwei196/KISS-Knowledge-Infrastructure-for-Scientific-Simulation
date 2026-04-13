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

# hydrocraft-pyswmm-urban v1.0.0

> PySWMM — Python Wrapper for EPA SWMM5 Stormwater Management Model
> Domain: Urban hydrology / stormwater management
> Engine: EPA SWMM 5.1.14–5.2.4 via swmm-toolkit
> Language: Python 3.10–3.12

---

## 1. Overview

PySWMM is a Python interface to the EPA Storm Water Management Model (SWMM5),
the industry-standard engine for simulating rainfall-runoff, surface runoff,
flow routing through drainage networks, and water quality transport in urban
catchments. PySWMM enables programmatic control of SWMM simulations, real-time
control (RTC) algorithm development, and post-processing of binary output files.

**Core capabilities:**
- Rainfall-runoff generation (Horton, Green-Ampt, Curve Number infiltration)
- Overland flow and subcatchment routing
- Dynamic wave / kinematic wave pipe network routing
- Pump, weir, orifice, and outlet control structures
- Low Impact Development (LID) practices (bioretention, permeable pavement, etc.)
- Water quality (buildup/washoff, treatment)
- Real-time control via Python callbacks
- Binary output file parsing and timeseries extraction

**Key reference:**
McDonnell et al. (2020). PySWMM: The Python Interface to Stormwater
Management Model (SWMM). *Journal of Open Source Software*, 5(52), 2292.

---

## 2. Installation

```bash
# Basic install (uses bundled SWMM engine)
pip install pyswmm

# With specific SWMM engine version
pip install "pyswmm[swmm5.2.4]"

# From source
git clone https://github.com/pyswmm/pyswmm
cd pyswmm
pip install -e .
```

**Dependencies:**
| Package        | Purpose                          |
|----------------|----------------------------------|
| swmm-toolkit   | C-library wrapper for EPA SWMM   |
| julian          | Julian date conversions          |
| packaging       | Version comparison utilities     |

**Binary location:** The SWMM engine is embedded in the `swmm-toolkit` package
as a shared library. No separate binary compilation is needed.

---

## 3. Pipeline Stages

The PySWMM urban stormwater modeling pipeline consists of 8 stages:

| Stage | Name                  | Description                                        | Tool                       |
|-------|-----------------------|----------------------------------------------------|----------------------------|
| s0    | Configuration         | Set site, period, resolution, paths                | Manual / `build_inp.py`    |
| s1    | Domain Setup          | Define subcatchments, nodes, links from GIS        | `convert_domain_to_inp.py` |
| s2    | Soil / Infiltration   | Map soil data to Horton/GA/CN parameters           | `convert_soil_to_inp.py`   |
| s3    | Land Cover            | Set imperviousness, Manning's n, depression storage| `convert_landcover.py`     |
| s4    | Meteorological Forcing| Convert rainfall timeseries to SWMM format         | `convert_forcing_to_inp.py`|
| s5    | Model Parameters      | Set calibration parameters (routing, losses, etc.) | `SimulationPreConfig`      |
| s6    | Model Execution       | Run SWMM simulation via PySWMM API                 | `run_pyswmm.py`           |
| s7    | Output Parsing        | Extract timeseries from binary .out file           | `parse_swmm_output.py`    |

**Stage dependency graph:**
```
s0 ──► s1 ──┬──► s2 ──┐
             │         ├──► s5 ──► s6 ──► s7
             └──► s3 ──┘
        s4 ─────────────────────┘
```

---

## 4. Input Format — SWMM .inp File

The SWMM input file (.inp) is a section-based plain-text file. Each section
starts with `[SECTION_NAME]` and contains whitespace-delimited tabular data.

### 4.1 Critical Sections

| Section          | Purpose                                    | Key Fields                          |
|------------------|--------------------------------------------|-------------------------------------|
| `[OPTIONS]`      | Global simulation settings                 | FLOW_UNITS, INFILTRATION, ROUTING   |
| `[RAINGAGES]`    | Rainfall data sources                      | Type, Interval, DataSource          |
| `[SUBCATCHMENTS]`| Drainage sub-areas                         | Area, %Imperv, Width, Slope         |
| `[SUBAREAS]`     | Surface roughness & depression storage     | N-Imperv, N-Perv, S-Imperv, S-Perv |
| `[INFILTRATION]` | Infiltration model parameters              | MaxRate, MinRate, Decay, DryTime    |
| `[JUNCTIONS]`    | Internal network nodes                     | InvertElev, MaxDepth, InitDepth     |
| `[OUTFALLS]`     | Discharge boundary nodes                   | InvertElev, Type (FREE/FIXED/TIDAL) |
| `[STORAGE]`      | Storage/detention nodes                    | InvertElev, Curve, MaxDepth         |
| `[CONDUITS]`     | Pipes and channels                         | Length, Manning's n, Offsets         |
| `[WEIRS]`        | Weir structures                            | Type, CrestHeight, DischCoeff       |
| `[PUMPS]`        | Pump stations                              | PumpCurve, InitStatus               |
| `[ORIFICES]`     | Orifice flow control                       | Type, Offset, DischCoeff            |
| `[XSECTIONS]`    | Cross-section geometry                     | Shape, Geom1-4, Barrels             |
| `[TIMESERIES]`   | Time-varying data (rain, inflows)          | Date, Time, Value                   |
| `[INFLOWS]`      | External/direct inflows to nodes           | Node, Parameter, TimeSeries         |
| `[DWF]`          | Dry weather flow patterns                  | Node, AverageValue, Patterns        |
| `[LID_CONTROLS]` | LID practice definitions                   | Type, Layer parameters              |
| `[LID_USAGE]`    | LID application to subcatchments           | Subcatch, LID, Number, Area         |
| `[CONTROLS]`     | Real-time control rules                    | IF/THEN/ELSE logic                  |

### 4.2 Flow Unit Systems

| Setting        | US Customary              | SI Metric                 |
|----------------|---------------------------|---------------------------|
| FLOW_UNITS     | CFS, GPM, MGD             | CMS, LPS, MLD             |
| Length         | feet                      | meters                    |
| Area (subcatch)| acres                     | hectares                  |
| Rainfall       | inches/hr                 | mm/hr                     |
| Depth          | feet                      | meters (or mm)            |
| Slope          | percent                   | percent                   |
| Volume         | cubic feet                | cubic meters              |
| Manning's n    | dimensionless             | dimensionless             |
| Evaporation    | inches/day                | mm/day                    |

---

## 5. Unit Trap Table — CRITICAL

These are the most common unit-related errors when preparing SWMM inputs.
Each has caused silent failures in production.

| ID     | Variable         | Expected Unit (US)  | Expected Unit (SI)  | Common Mistake           | Impact     |
|--------|------------------|---------------------|---------------------|--------------------------|------------|
| UT-001 | Rainfall         | inches/hr           | mm/hr               | mm/day or m/hr           | 10-1000x   |
| UT-002 | Subcatchment Area | acres               | hectares             | km² or m²               | 100-1e6x   |
| UT-003 | Elevation        | feet                | meters               | Mixing ft/m             | ~3x bias   |
| UT-004 | Pipe Length       | feet                | meters               | Mixing ft/m             | ~3x        |
| UT-005 | Slope            | percent (e.g. 0.5)  | percent (e.g. 0.5)   | Fraction (0.005)        | 100x       |
| UT-006 | Manning's n      | dimensionless       | dimensionless        | Using Kn (1.49 factor)  | 1.49x      |
| UT-007 | Depression Storage| inches              | mm                   | feet or meters           | 12-1000x  |
| UT-008 | Pipe Diameter    | feet                | meters               | inches or mm             | 12-1000x  |
| UT-009 | Infiltration Rate| inches/hr           | mm/hr                | mm/day                  | 24x        |
| UT-010 | Evaporation      | inches/day          | mm/day               | inches/hr or mm/hr       | 24x       |
| UT-011 | Flow (inflow)    | CFS                 | CMS                  | LPS when CMS expected   | 1000x      |
| UT-012 | Orifice Coeff    | dimensionless       | dimensionless        | Using area instead       | varies     |
| UT-013 | Weir Coeff       | US: ~3.33           | SI: ~1.84            | Using wrong system       | ~1.8x      |

---

## 6. Execution Model

### 6.1 Full Execution (No Intervention)
```python
from pyswmm import Simulation

with Simulation('model.inp') as sim:
    sim.execute()
# Produces model.rpt and model.out
```

### 6.2 Stepped Execution with Real-Time Control
```python
from pyswmm import Simulation, Nodes, Links

with Simulation('model.inp') as sim:
    j1 = Nodes(sim)['J1']
    weir = Links(sim)['W1']

    for step in sim:
        if j1.depth > 5.0:
            weir.target_setting = 0.5
        else:
            weir.target_setting = 1.0
```

### 6.3 Callback-Based Control
```python
from pyswmm import Simulation, Nodes, Links

with Simulation('model.inp') as sim:
    j1 = Nodes(sim)['J1']
    pump = Links(sim)['P1']

    def control():
        if j1.depth > 3.0:
            pump.target_setting = 1.0
        else:
            pump.target_setting = 0.0

    sim.add_before_step(control)

    for step in sim:
        pass  # callbacks fire automatically
```

### 6.4 CRITICAL: Non-Reentrant Engine
Only ONE `Simulation` object can exist at a time in a Python process.
Attempting to create a second raises `MultiSimulationError`. Use
`multiprocessing` for parallel runs, NOT threading.

---

## 7. Output Format

### 7.1 Report File (.rpt)
Plain-text summary: mass balance, peak flows, node flooding, link surcharging.

### 7.2 Binary Output File (.out)
Structured binary with timeseries at every reporting timestep for all elements.

```python
from pyswmm import Output, NodeSeries, LinkSeries, SubcatchSeries, SystemSeries

with Output('model.out') as out:
    # Element inventories
    print(out.subcatchments)  # {'S1': 0, 'S2': 1, ...}
    print(out.nodes)          # {'J1': 0, 'J2': 1, ...}
    print(out.links)          # {'C1': 0, 'C2': 1, ...}
    print(out.times)          # [datetime, datetime, ...]

    # Extract timeseries
    node_depth = NodeSeries(out)['J1'].invert_depth
    link_flow = LinkSeries(out)['C1'].flow_rate
    sub_runoff = SubcatchSeries(out)['S1'].runoff_rate
    sys_rain = SystemSeries(out).rainfall
```

### 7.3 Key Output Variables

| Element      | Variable            | Units (US)   | Units (SI)    |
|-------------|---------------------|--------------|---------------|
| Subcatchment| rainfall            | in/hr        | mm/hr         |
| Subcatchment| runoff              | CFS          | CMS           |
| Subcatchment| infiltration        | in/hr        | mm/hr         |
| Subcatchment| evaporation         | in/day       | mm/day        |
| Node        | depth               | ft           | m             |
| Node        | total_inflow        | CFS          | CMS           |
| Node        | flooding            | CFS          | CMS           |
| Node        | volume              | ft³          | m³            |
| Node        | head                | ft           | m             |
| Link        | flow                | CFS          | CMS           |
| Link        | depth               | ft           | m             |
| Link        | velocity            | ft/s         | m/s           |
| Link        | froude              | —            | —             |
| Link        | setting             | 0–1          | 0–1           |
| System      | total_rainfall      | in/hr        | mm/hr         |
| System      | total_runoff         | CFS          | CMS           |
| System      | total_outflow       | CFS          | CMS           |

---

## 8. Tool Reference

| Tool                       | Lines | Stage | Purpose                                      |
|----------------------------|-------|-------|----------------------------------------------|
| `convert_forcing_to_inp.py`| ~250  | s4    | Convert global met data → SWMM TIMESERIES    |
| `convert_soil_to_inp.py`   | ~200  | s2    | Map HWSD soil → infiltration parameters       |
| `run_pyswmm.py`           | ~200  | s6    | Execute simulation with preflight checks      |
| `parse_swmm_output.py`    | ~250  | s7    | Extract timeseries from .out → CSV            |

---

## 9. Critical Domain Knowledge

These non-obvious facts have caused silent failures:

1. **Rainfall units are INTENSITY not depth**: SWMM expects rain as in/hr or
   mm/hr. Providing cumulative depth (inches or mm) will produce wildly
   incorrect runoff.

2. **Weir discharge coefficients differ between US and SI**: US uses ~3.33,
   SI uses ~1.84 for the same physical weir. Using wrong coefficient → 1.8x
   flow error.

3. **DYNWAVE routing requires small timesteps**: The Courant condition limits
   the routing timestep. If ROUTING_STEP is too large, SWMM silently produces
   incorrect results or becomes unstable.

4. **Subcatchment width controls hydrograph shape**: Width = Area / longest
   overland flow path. Too large → peaky; too small → attenuated. This is the
   single most sensitive subcatchment parameter.

5. **Conduit Manning's n differs by 1.49 factor in US**: The Manning equation
   uses Kn=1.49 in US units vs Kn=1.0 in SI. PySWMM handles this internally,
   but n values must be the same in both systems (dimensionless).

6. **Only ONE Simulation at a time**: The EPA SWMM engine uses global state.
   Multiple Simulation objects → `MultiSimulationError`.

7. **Percent impervious includes directly-connected and disconnected**: The
   `PctZero` parameter in [SUBAREAS] controls how much impervious runoff
   routes to pervious area vs directly to outlet. Default 25% can significantly
   affect runoff volume.

8. **Depression storage is consumed before runoff begins**: Both impervious
   (S-Imperv, ~0.05 in) and pervious (S-Perv, ~0.2 in) depression storage
   must fill before surface runoff starts. Wrong units here delay or eliminate
   runoff peaks.

9. **Hotstart files skip the warmup period**: Use `sim.use_hotstart()` and
   `sim.save_hotstart()` to avoid re-simulating spin-up periods. The hotstart
   file captures all node depths, link flows, and groundwater states.

---

## 10. Calibration Parameters — Priority Order

| Priority | Parameter            | Section         | Effect                    | Range         |
|----------|----------------------|-----------------|---------------------------|---------------|
| 1        | Subcatch Width       | [SUBCATCHMENTS] | Hydrograph peak timing    | A/L to 5×A/L  |
| 2        | % Impervious         | [SUBCATCHMENTS] | Runoff volume             | 0–100%        |
| 3        | N-Imperv             | [SUBAREAS]      | Impervious roughness      | 0.01–0.03     |
| 4        | S-Imperv             | [SUBAREAS]      | Impervious depression stor| 0.02–0.10 in  |
| 5        | Infil. MaxRate       | [INFILTRATION]  | Peak infiltration rate    | 1–5 in/hr     |
| 6        | Infil. MinRate       | [INFILTRATION]  | Steady-state infil rate   | 0.1–1 in/hr   |
| 7        | Infil. Decay         | [INFILTRATION]  | Horton decay constant     | 2–7 hr⁻¹      |
| 8        | Manning's n (pipe)   | [CONDUITS]      | Flow velocity / timing    | 0.01–0.03     |
| 9        | Conduit roughness    | [CONDUITS]      | Routing attenuation       | 0.01–0.03     |
| 10       | N-Perv               | [SUBAREAS]      | Pervious roughness        | 0.05–0.80     |

---

## 11. Data Requirements

| Data Type          | Source Options                           | Format           |
|--------------------|------------------------------------------|------------------|
| Rainfall           | Rain gages, CMFD, GPM, ERA5             | TIMESERIES in .inp|
| Subcatchment GIS   | Catchment delineation, DEM, land use    | Shapefile → .inp |
| Drainage network   | As-built plans, GIS pipe layer          | [CONDUITS/JUNCTIONS]|
| Soil properties    | HWSD, SSURGO, SoilGrids                | [INFILTRATION]   |
| Land cover         | NLCD, Sentinel-2, manual mapping        | %Imperv, Manning's n|
| Evaporation        | Station data, PET models                | [EVAPORATION]    |
| Control structures | Design drawings, operations manuals     | [WEIRS/PUMPS/ORIFICES]|

---

## 12. Quick Start Example

```python
from pyswmm import Simulation, Nodes, Links, Subcatchments, Output, NodeSeries
import csv

# 1. Run simulation
with Simulation('my_model.inp') as sim:
    node = Nodes(sim)['Outfall1']
    results = []

    for step in sim:
        results.append({
            'time': sim.current_time,
            'outflow': node.total_inflow
        })

    print(f"Runoff error: {sim.runoff_error}%")
    print(f"Routing error: {sim.flow_routing_error}%")

# 2. Write results to CSV
with open('results.csv', 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=['time', 'outflow'])
    w.writeheader()
    w.writerows(results)

# 3. Post-process binary output
with Output('my_model.out') as out:
    flow_ts = NodeSeries(out)['Outfall1'].total_inflow
    for t, q in flow_ts.items():
        print(f"{t}: {q:.3f}")
```

---

## 13. File Structure

```
ki/
├── SKILL.md                          # This file
├── knowledge_infrastructure.yaml     # Machine-readable package definition
├── tools/
│   ├── convert_forcing_to_inp.py     # Met data → SWMM timeseries
│   ├── convert_soil_to_inp.py        # Soil data → infiltration params
│   ├── run_pyswmm.py                # Simulation execution wrapper
│   └── parse_swmm_output.py         # Binary .out → CSV extraction
├── docs/
│   ├── s0_configuration.md           # Site and simulation setup
│   ├── s2_soil_infiltration.md       # Soil parameter mapping
│   ├── s4_meteorological_forcing.md  # Rainfall data preparation
│   ├── s6_model_execution.md         # Running the simulation
│   └── s7_output_parsing.md          # Post-processing results
└── diagnostics/
    └── triplets.yaml                 # Symptom → diagnosis → remedy
```

---

## 14. Coupling Points

| Partner Model | Direction | Interface Variable        | Tool                      |
|---------------|-----------|---------------------------|---------------------------|
| CaMa-Flood    | SWMM→CaMa| Outfall discharge (CMS)   | `parse_swmm_output.py`   |
| MODFLOW       | Bi-dir    | GW head ↔ node depth      | PySWMM callback API       |
| EPA SWMM-CAT  | Pre       | Climate-adjusted rainfall | `convert_forcing_to_inp.py`|
| HEC-RAS       | SWMM→RAS | Outfall hydrograph        | `parse_swmm_output.py`   |

---

## 15. Validation

Test case: Built-in weir_setting model (3 subcatchments, 4 junctions, 1 outfall,
3 conduits, 1 weir, 3-day SCS Type I storm).

Expected behavior:
- Peak runoff occurs ~10 hours into storm (SCS Type I distribution)
- Continuity errors < 1% for both runoff and routing
- Node J1 depth peaks when weir is partially closed
- Outfall flow tracks network routing with ~30 min lag
