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

# EPANET 2.2 — Knowledge Infrastructure

**Package**: `hydrocraft-epanet-wds` v1.0.0
**Model**: EPANET 2.2.0 (Water Distribution System Simulator)
**Source**: https://github.com/USEPA/EPANET2.2
**Language**: C (cmake build)
**License**: MIT
**Last updated**: 2026-03-25
**Stats**: 4 tools | 5 skill documents | 15+ diagnostic triplets

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for rainfall forcing documentation.
See `data_ki/SWMM_Benchmarks/SKILL.md` for drainage test cases.


## Overview

EPANET performs extended-period simulation of hydraulic and water quality behavior within pressurized drinking water distribution pipe networks. It models pipes, nodes (junctions), pumps, valves, storage tanks, and reservoirs. EPANET tracks:

- **Flow rate** in each pipe
- **Pressure** at each node
- **Water level** in each tank
- **Chemical concentration** throughout the network
- **Water age** at each node
- **Source tracing** from any node
- **Energy consumption** and cost for each pump

**Key difference from other HydroCraft models**: EPANET operates on a pressurized pipe network (graph topology of nodes and links), not a gridded basin or 1D water body. It does not model open-channel flow, rainfall-runoff, or groundwater — it starts where water enters the distribution system from reservoirs.

---

## Installation

### Building from Source (cmake)

```bash
cd SRC_engines
mkdir -p build && cd build
cmake .. -DBUILD_SHARED_LIBS=ON
make -j$(nproc)
# Produces:
#   build/src/run/runepanet          (CLI executable)
#   build/src/solver/libepanet2.so   (shared library for API usage)
```

### Dependencies

- C compiler (gcc/clang)
- cmake >= 3.9
- No external library dependencies (self-contained)

### Python dependencies (for KI tools)

```
pandas, numpy, matplotlib, struct (stdlib), re (stdlib)
```

### Test example

```
User_Manual/docs/tutorial.inp    # 7-node tutorial network
User_Manual/docs/tutorial.out    # Expected report output
```

### CLI Usage

```bash
runepanet <input_file.inp> <report_file.rpt> [binary_output.out]
```

- `input_file.inp` — Text file defining the network (required)
- `report_file.rpt` — Text report of simulation results (required)
- `binary_output.out` — Binary file with all time-step results (optional)

---

## Pipeline (9 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Network design | (manual/GIS) | Define topology: junctions, pipes, tanks, reservoirs, pumps, valves |
| 1 | Demand preparation | `convert_demands_to_inp` | Convert demand data to EPANET [JUNCTIONS]/[DEMANDS] format |
| 2 | Network parameterization | `convert_network_params` | Set pipe diameters, lengths, roughness; tank geometry; pump curves |
| 3 | Water quality config | (manual) | Set reaction coefficients, source nodes, quality type |
| 4 | Operational rules | (manual) | Define [CONTROLS], [RULES], [PATTERNS], [ENERGY] |
| 5 | Options & times | (manual) | Set [OPTIONS] (units, headloss formula), [TIMES] (duration, timestep) |
| 6 | INP assembly | `convert_demands_to_inp` | Assemble complete .inp file from component sections |
| 7 | Execution | `run_epanet` | Run runepanet with preflight checks and output validation |
| 8 | Output analysis | `parse_epanet_output` | Parse report/binary output, extract to CSV, generate plots |

### Parallelism

Stages 1-5 can proceed in parallel (independent data preparation).
Stage 6 depends on 1-5.
Stage 7 depends on 6.
Stage 8 depends on 7.

---

## Input File Format (.inp)

The EPANET input file is a text file organized into bracketed sections. Sections can appear in any order, but nodes and links must be defined before they are referenced.

### Required Sections

| Section | Purpose | Key Fields |
|---------|---------|------------|
| `[TITLE]` | Project description | Free text (up to 3 lines) |
| `[JUNCTIONS]` | Junction nodes | ID, Elevation, Demand, Pattern |
| `[RESERVOIRS]` | Source/sink nodes | ID, Head, Pattern |
| `[TANKS]` | Storage tanks | ID, Elevation, InitLevel, MinLevel, MaxLevel, Diameter, MinVolume |
| `[PIPES]` | Pipe links | ID, Node1, Node2, Length, Diameter, Roughness, MinorLoss, Status |
| `[PUMPS]` | Pump links | ID, Node1, Node2, HEAD CurveID / POWER value / SPEED value |
| `[VALVES]` | Valve links | ID, Node1, Node2, Diameter, Type, Setting, MinorLoss |

### Operational Sections

| Section | Purpose |
|---------|---------|
| `[PATTERNS]` | Time-varying multiplier patterns |
| `[CURVES]` | Pump head, efficiency, volume, headloss curves |
| `[CONTROLS]` | Simple on/off controls (level, pressure, time) |
| `[RULES]` | Rule-based controls (IF/THEN/ELSE logic) |
| `[ENERGY]` | Pump energy parameters and pricing |
| `[STATUS]` | Initial link status overrides |
| `[DEMANDS]` | Multiple demand categories per junction |
| `[EMITTERS]` | Sprinkler/orifice flow coefficients |

### Water Quality Sections

| Section | Purpose |
|---------|---------|
| `[QUALITY]` | Initial quality at nodes |
| `[REACTIONS]` | Bulk and wall reaction coefficients |
| `[SOURCES]` | Quality source nodes (concentration, mass, setpoint) |
| `[MIXING]` | Tank mixing model (MIXED, 2COMP, FIFO, LIFO) |

### Configuration Sections

| Section | Purpose |
|---------|---------|
| `[OPTIONS]` | Units, headloss formula, quality type, solver parameters |
| `[TIMES]` | Duration, timestep, pattern step, report step |
| `[REPORT]` | What to include in the report file |

### Map Sections (optional, not used in CLI mode)

`[COORDINATES]`, `[VERTICES]`, `[LABELS]`, `[BACKDROP]`, `[TAGS]`

---

## Unit Trap Table

**Critical**: Flow unit choice determines ALL other units. US Customary units apply when flow is CFS/GPM/MGD/IMGD/AFD. SI Metric units apply when flow is LPS/LPM/MLD/CMH/CMD.

| Parameter | US Customary | SI Metric | Trap |
|-----------|-------------|-----------|------|
| **Flow** | CFS, GPM, MGD, IMGD, AFD | LPS, LPM, MLD, CMH, CMD | Unit choice cascades to ALL other parameters |
| **Pipe Diameter** | inch | millimeter | 12 in ≠ 12 mm — off by 25.4× |
| **Tank Diameter** | foot | meter | 70 ft ≠ 70 m |
| **Elevation** | foot | meter | 700 ft ≈ 213 m — major pressure error |
| **Pressure (output)** | psi | meter (head) | 1 psi ≈ 0.703 m — not interchangeable |
| **Hydraulic Head** | foot | meter | Head = elevation + pressure head |
| **Pipe Length** | foot | meter | 3000 ft ≈ 914 m |
| **Velocity** | ft/s | m/s | 1 ft/s ≈ 0.305 m/s |
| **Volume** | cubic foot | cubic meter | 1 ft³ ≈ 0.0283 m³ |
| **Power** | horsepower | kilowatt | 1 hp ≈ 0.746 kW |
| **Roughness (D-W)** | 10⁻³ foot | millimeter | Darcy-Weisbach only |
| **Roughness (H-W/C-M)** | unitless | unitless | Same in both systems |
| **Reaction Coeff (Bulk)** | 1/day | 1/day | Same in both systems |
| **Reaction Coeff (Wall 1st)** | ft/day | m/day | Length-dependent |
| **Water Age** | hour | hour | Same in both systems |
| **Concentration** | mg/L or µg/L | mg/L or µg/L | Same in both systems |

### Common Unit Mistakes

1. **Mixing unit systems**: Specifying `Units LPS` but entering elevations in feet
2. **Pipe vs Tank diameter units**: Pipes use inches/mm, tanks use feet/meters
3. **Roughness interpretation**: Hazen-Williams C-factor (100-150 typical) vs Darcy-Weisbach roughness height (0.001-0.01 mm typical) — completely different scales
4. **Demand sign convention**: Positive = withdrawal FROM network; Negative = injection INTO network
5. **Head vs Pressure**: Head = Elevation + Pressure/γ. Head is absolute; pressure is relative to elevation.
6. **Pattern multipliers**: Dimensionless factors applied to base values. A multiplier of 1.3 means 130% of base demand.

---

## Output Format

### Report File (.rpt)

Text file containing:
- Network summary (counts of components, options used)
- Energy usage summary per pump
- Node results per time step: Demand, Head, Pressure, Quality
- Link results per time step: Flow, Velocity, Headloss

### Binary Output File (.out)

4-byte aligned binary file with sections:
1. **Prolog**: Network metadata, node/link IDs, topology
2. **Energy Use**: Pump efficiency, power, cost per pump
3. **Extended Period**: Per-timestep arrays of node demands, heads, pressures, quality; link flows, velocities, headloss, quality, status, settings, reaction rates, friction factors
4. **Epilog**: Reaction rates, period count, warning flag, magic number (516114521)

---

## Head Loss Formulas

| Formula | Keyword | Roughness Meaning | Typical Range |
|---------|---------|-------------------|---------------|
| Hazen-Williams | `H-W` | C-factor (dimensionless) | 100-150 (new pipe ~140, old pipe ~100) |
| Darcy-Weisbach | `D-W` | Roughness height | US: 10⁻³ ft; SI: mm |
| Chezy-Manning | `C-M` | Manning's n (dimensionless) | 0.011-0.017 |

---

## Demand Models

| Model | Keyword | Behavior |
|-------|---------|----------|
| Demand Driven (DDA) | `DDA` | Full demand supplied regardless of pressure; can produce negative pressures |
| Pressure Driven (PDA) | `PDA` | Demand is a power function of pressure: d = D × ((p - Pmin)/(Preq - Pmin))^Pexp |

---

## API Reference (C Library)

The EPANET toolkit provides a C API via `libepanet2.so`. Key function groups:

| Group | Functions | Purpose |
|-------|-----------|---------|
| Project | `ENepanet`, `ENopen`, `ENclose`, `ENinit` | Open/run/close projects |
| Hydraulics | `ENsolveH`, `ENopenH`, `ENinitH`, `ENrunH`, `ENnextH` | Run hydraulic simulation |
| Quality | `ENsolveQ`, `ENopenQ`, `ENinitQ`, `ENrunQ`, `ENnextQ` | Run quality simulation |
| Nodes | `ENgetnodevalue`, `ENsetnodevalue`, `ENgetnodetype` | Get/set node properties |
| Links | `ENgetlinkvalue`, `ENsetlinkvalue`, `ENgetlinktype` | Get/set link properties |
| Patterns | `ENaddpattern`, `ENsetpattern`, `ENgetpatternvalue` | Manage time patterns |
| Curves | `ENaddcurve`, `ENsetcurve`, `ENgetcurvevalue` | Manage data curves |
| Controls | `ENaddcontrol`, `ENgetcontrol`, `ENaddrule` | Manage controls/rules |
| Options | `ENgetoption`, `ENsetoption`, `ENgetflowunits` | Simulation options |
| Reporting | `ENreport`, `ENsetreport`, `ENgetstatistic` | Output reporting |

### Simple workflow (CLI equivalent)

```c
ENepanet("network.inp", "report.rpt", "output.out", NULL);
```

### Step-by-step workflow

```c
ENopen("network.inp", "report.rpt", "output.out");
ENsolveH();   // Solve hydraulics for all time periods
ENsolveQ();   // Solve water quality for all time periods
ENreport();   // Write report file
ENclose();
```

---

## Tools Reference

| Tool | Stage | Script Path | Purpose |
|------|-------|-------------|---------|
| `convert_demands_to_inp` | s1-s2 | `tools/convert_demands_to_inp.py` | Convert external demand/network data to EPANET .inp format |
| `convert_network_params` | s2 | `tools/convert_network_params.py` | Convert pipe/tank parameters with unit validation |
| `run_epanet` | s7 | `tools/run_epanet.py` | Execute runepanet with preflight checks |
| `parse_epanet_output` | s8 | `tools/parse_epanet_output.py` | Parse binary .out file to CSV and DataFrames |

---

## Quick Start Example

```bash
# 1. Build EPANET
cd SRC_engines && mkdir -p build && cd build
cmake .. && make -j$(nproc)

# 2. Run tutorial network
./src/run/runepanet ../../User_Manual/docs/tutorial.inp tutorial.rpt tutorial.out

# 3. Parse results with Python tool
python3 tools/parse_epanet_output.py tutorial.out --csv results/
```

---

## Water Quality Analysis Types

| Type | Keyword | Description |
|------|---------|-------------|
| None | `NONE` | No quality analysis |
| Chemical | `CHEMICAL name units` | Fate and transport of a chemical (e.g., chlorine) |
| Age | `AGE` | Water age tracking (hours) |
| Trace | `TRACE nodeID` | Percentage of water from a specific source node |

---

## Valve Types

| Type | Code | Description | Setting Unit |
|------|------|-------------|-------------|
| PRV | 3 | Pressure Reducing Valve | psi or m |
| PSV | 4 | Pressure Sustaining Valve | psi or m |
| PBV | 5 | Pressure Breaker Valve | psi or m |
| FCV | 6 | Flow Control Valve | flow units |
| TCV | 7 | Throttle Control Valve | unitless (loss coeff.) |
| GPV | 8 | General Purpose Valve | headloss curve ID |

---

## Tank Mixing Models

| Model | Keyword | Description |
|-------|---------|-------------|
| Complete Mix | `MIXED` | Instantaneous complete mixing (default) |
| Two-Compartment | `2COMP` | Inlet/outlet compartment + dead zone |
| Plug Flow | `FIFO` | First-in, first-out |
| Stacked Plug Flow | `LIFO` | Last-in, first-out |
