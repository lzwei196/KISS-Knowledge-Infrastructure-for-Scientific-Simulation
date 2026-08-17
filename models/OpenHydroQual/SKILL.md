---
name: openhydroqual
description: >-
  OpenHydroQual 2.0.4. Covers Water flow, storage, and head in interconnected control
  volumes (ponds, aquifer cells…; Solute / water-quality constituent transport (advection
  + diffusion) across a block-link network; Biogeochemical reactions (Monod /
  Arrhenius-corrected kinetics; nutrient cycling; ASM-style…. Use when the task involves
  running, configuring, calibrating or interpreting OpenHydroQual.
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

# OpenHydroQual Knowledge Infrastructure

- **Package**: OpenHydroQual (OHQ)
- **Version**: 2.0.4
- **Domain**: Water quality / Environmental simulation
- **Engine**: Aquifolium simulation framework
- **Language**: C++14 (Qt6 Core, Armadillo, LAPACK, GSL)
- **Created**: 2026-03-26
- **Validation**: Wet pond example (DOM, O2, NH3, NOx reactive transport)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for meteorological forcing documentation.
See `data_ki/WQP/SKILL.md` for water quality observations.
See `data_ki/HydroLAKES/SKILL.md` for lake morphometry.


## 1. Overview

OpenHydroQual is an open-source environmental simulation platform for modeling
water flow, solute transport, and biogeochemical processes in interconnected
hydrological systems. Built on the Aquifolium engine, it uses a block-and-link
graph topology where:

- **Blocks** represent control volumes (ponds, aquifer cells, river segments,
  sediment layers, pipes, tanks)
- **Links** represent hydraulic connections (channels, weirs, pipes, Darcy flow)
- **Sources** represent external inputs (atmospheric exchange, constant sources,
  evapotranspiration)
- **Constituents** track water quality species (DOM, O2, NH3, NOx, metals, etc.)
- **Reactions** define biogeochemical transformations via rate expressions

The model supports groundwater, surface water, wastewater treatment, green
infrastructure (bioretention, bioswales, permeable pavement), and coupled
multi-domain simulations.

### Key Capabilities
- Activated Sludge Models (ASM1/ASM3/ASM5) for wastewater
- Nutrient cycling (N, P, S) in rivers and wetlands
- Sorption, mass transfer, buildup/washoff for contaminants
- Evapotranspiration (Penman, simple models)
- Parameter estimation via Genetic Algorithm and MCMC
- Multi-threaded parallel solving with OpenMP
- Python bindings via pybind11

---

## 2. Installation

### 2.1 Dependencies (Linux)

```bash
sudo apt install -y \
  qt6-base-dev \
  libarmadillo-dev \
  liblapack-dev libblas-dev \
  libgsl-dev \
  libomp-dev \
  cmake build-essential
```

### 2.2 Build from Source

```bash
cd OpenHydroQual/OHQLib
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . --parallel $(nproc)
```

This produces `libOHQLib.so` (shared library). The test executable must be
built separately:

```bash
cd OpenHydroQual/OHQLibTest
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release \
  -DOHQLIB_BUILD_DIR=../../OHQLib/build
cmake --build . --parallel
```

### 2.3 Running

```bash
./OHQLibTest /path/to/model.ohq
```

The binary expects:
- Template path at `../../../resources/` relative to the binary
- Working folder derived from the input file path
- Settings file at `../../../resources/settings.json`

---

## 3. Pipeline Stages

| Stage | Name                    | Description                                          | Tool                    |
|-------|-------------------------|------------------------------------------------------|-------------------------|
| S1    | Data preparation        | Gather and convert forcing/time-series data          | `convert_forcing.py`    |
| S2    | Template configuration  | Select and load JSON component templates             | (manual)                |
| S3    | Parameter setup         | Define hydraulic, reaction, and soil parameters      | `convert_parameters.py` |
| S4    | Model construction      | Write .ohq script (blocks, links, sources, rxns)     | (manual / script gen)   |
| S5    | Pre-flight validation   | Check .ohq syntax, file paths, unit consistency      | `validate_ohq.py`       |
| S6    | Model execution         | Run OHQLibTest binary                                | `run_ohq.py`            |
| S7    | Output parsing          | Extract CSV from model output                        | `parse_output.py`       |
| S8    | Post-processing         | Compute metrics, generate figures                    | `parse_output.py`       |
| S9    | Calibration             | GA / MCMC parameter estimation (optional)            | `run_ohq.py`            |
| S10   | Validation              | Compare to observations, compute NSE/KGE/RMSE        | `parse_output.py`       |

---

## 4. Input Format

### 4.1 OHQ Script File (.ohq)

The primary input is a text-based script with semicolon-separated commands:

```
loadtemplate; filename=resources/main_components.json
addtemplate; filename=resources/river_processes.json
setvalue; object=system, quantity=simulation_end_time, value=100
setvalue; object=system, quantity=initial_time_step, value=0.001
setvalue; object=system, quantity=c_n_weight, value=1
create block; type=Pond, name=Pond (1), Storage=357.6[m~^3], ...
create link; from=Pond (1), to=Pond (2), type=wide_channel, ...
create source; type=atmospheric exchange, name=aeration, ...
create constituent; type=Constituent, name=O2, concentration=0[g/m~^3], ...
create reaction; type=Reaction, name=Nitrification, rate_expression=(...), ...
create observation; type=Observation, object=Pond (6), expression=O2:concentration, ...
solve
```

### 4.2 Time Series Files (CSV)

Comma-separated, first column is time (day number or date), second is value:

```
0,0.5
1,0.6
2,0.45
```

Climate forcing files (Temperature, Wind, Solar radiation, Humidity) use the
same CSV format with headers. Time is in days from simulation start.

### 4.3 JSON Component Templates

Located in `resources/`. Define block types, link types, source types,
and their properties. Key templates:

| Template                        | Purpose                              |
|---------------------------------|--------------------------------------|
| main_components.json            | Core blocks, links, sources (26 KB)  |
| settings.json                   | Solver and MCMC configuration        |
| unconfined_groundwater.json     | Aquifer cells and connections        |
| pipe_pump_tank.json             | Water distribution networks          |
| open_channel.json               | River/canal flow                     |
| unsaturated_soil*.json          | Vadose zone transport                |
| Sewer_system.json               | Municipal wastewater systems         |
| wastewater.json                 | Treatment reactors (ASM1)            |
| river_processes.json            | Reactive transport in streams        |
| mass_transfer.json              | Sorption and immobile constituents   |
| buildup_washoff.json            | Pollutant accumulation/removal       |
| evapotranspiration_models.json  | ET calculation methods               |
| Bioretention.json               | Green infrastructure BMPs            |
| StormwaterPond*.json            | Surface water detention              |

---

## 5. Output Format

Model output is written as CSV to `output.txt` (default) with:
- First column: time (days)
- Subsequent columns: selected quantities marked `includeinoutput: true`
- Column headers identify block/link name and variable

Observation output goes to `observedoutput.txt` for model-data comparison.

---

## 6. Unit Trap Table

**CRITICAL**: OHQ uses internally consistent units. Mismatch causes silent errors.

| Variable               | OHQ Internal Unit     | Common Trap (Wrong Unit)      | Impact            |
|------------------------|-----------------------|-------------------------------|--------------------|
| Flow                   | m^3/day               | m^3/s (factor 86400x)        | Storage blowup     |
| Concentration          | g/m^3 (= mg/L)       | mg/m^3 (factor 1000x)        | Reaction rate off  |
| Hydraulic conductivity | m/day                 | m/s (factor 86400x)          | Aquifer drains     |
| Storage                | m^3                   | L (factor 1000x)             | Mass balance error |
| Head / elevation       | m                     | cm or ft                     | Flow direction     |
| Area                   | m^2                   | ha (factor 10000x)           | ET wrong           |
| Length / width          | m                     | km (factor 1000x)            | Travel time error  |
| Temperature            | Celsius (in CSV)      | Kelvin (+273.15 offset)      | ET and reaction    |
| Solar radiation        | W/m^2 (in CSV)        | MJ/m^2/day (factor ~11.6x)   | ET calculation     |
| Wind speed             | m/s (in CSV)          | km/h (factor 3.6x)           | Aeration wrong     |
| Relative humidity      | fraction (0-1)        | percentage (0-100)           | ET wrong           |
| Diffusion coefficient  | m^2/day               | m^2/s (factor 86400x)        | Transport error    |
| Reaction rate          | 1/day                 | 1/s or 1/hr                  | Kinetics wrong     |
| Manning's n            | dimensionless         | (no trap but range 0.01-0.1) | Flow resistance    |
| Porosity               | dimensionless (0-1)   | percentage (0-100)           | Volume error       |

---

## 7. Key Variables Reference

### 7.1 Solver Settings

| Parameter                              | Default  | Description                         |
|----------------------------------------|----------|-------------------------------------|
| c_n_weight                             | 1        | Crank-Nicholson weight (0=explicit, 1=implicit) |
| nr_tolerance                           | 0.001    | Newton-Raphson convergence          |
| nr_timestep_reduction_factor           | 0.75     | Step reduction on slow convergence  |
| nr_timestep_reduction_factor_fail      | 0.2      | Step reduction on NR failure        |
| minimum_timestep                       | 1e-6     | Smallest allowed timestep (days)    |
| initial_time_step                      | 0.001    | Starting timestep (days)            |
| maximum_time_allowed                   | 86400    | Max CPU time (seconds)              |
| maximum_number_of_matrix_inversions    | 200000   | Max NR iterations total             |
| n_threads                              | 8        | OpenMP thread count                 |

### 7.2 Block Types

| Type                          | Key Properties                                    |
|-------------------------------|---------------------------------------------------|
| Pond                          | Storage, alpha, beta, bottom_elevation, inflow     |
| fixed_head                    | head, Storage (large dummy volume)                 |
| Bed_sediment                  | depth, porosity, hydraulic_conductivity, length    |
| Unconfined Groundwater cell   | area, piezometric_head, hydraulic_conductivity     |
| Darcy                         | hydraulic_conductivity, area, length               |
| Storage                       | bottom_area, head                                  |

### 7.3 Link Types

| Type                        | Key Properties                              |
|-----------------------------|---------------------------------------------|
| wide_channel                | ManningCoeff, length, width                 |
| wier (weir)                 | alpha, beta, crest_elevation                |
| River_bed_sediment_link     | (inherits from connected blocks)            |
| bed_sediment_to_fixedhead   | hydraulic_conductivity, length              |
| pipe                        | diameter, ManningCoeff, length              |
| Darcy_link                  | hydraulic_conductivity, area, length        |

### 7.4 Reaction Parameters (ASM1-style)

| Parameter | Description                           | Typical Value | Unit     |
|-----------|---------------------------------------|---------------|----------|
| mu_H      | Max heterotrophic growth rate         | 6.0           | 1/day    |
| K_s       | Substrate half-saturation             | 20            | g/m^3    |
| K_o       | O2 half-saturation (heterotrophs)     | 0.2           | g/m^3    |
| mu_N      | Max nitrifier growth rate             | 0.8           | 1/day    |
| K_n       | NH3 half-saturation (nitrifiers)      | 1.0           | g/m^3    |
| K_on      | O2 half-saturation (nitrifiers)       | 0.4           | g/m^3    |
| mu_dn     | Max denitrification rate              | 3.0           | 1/day    |
| K_dn      | NOx half-saturation (denitrifiers)    | 0.5           | g/m^3    |
| eta_on    | NH3 yield from organic N              | 0.08          | g/g      |
| eta_n     | NOx consumption stoichiometry         | 0.5           | g/g      |
| b_H       | Heterotrophic decay rate              | 0.62          | 1/day    |
| Y_H       | Heterotrophic yield                   | 0.67          | gCOD/gCOD|

---

## 8. Critical Domain Knowledge

### 8.1 Template Path Resolution (dt_001)
The OHQLibTest binary resolves template paths relative to its own location
(`../../../resources/`). If the binary is moved or symlinked, template loading
silently fails. Always ensure the binary can reach the `resources/` directory.

### 8.2 Hardcoded Absolute Paths in .ohq Files (dt_002)
Example .ohq files contain absolute paths from the developer's machine
(`/home/arash/Projects/...`). These MUST be replaced with paths valid for your
system before running.

### 8.3 Unit Bracket Syntax (dt_003)
OHQ uses `[unit]` suffix notation: `Storage=357.6[m~^3]`. The `~^` represents
superscript. Omitting the unit bracket does NOT cause an error but may result
in wrong unit interpretation. Always include unit brackets.

### 8.4 Semicolon vs Comma Delimiter (dt_004)
In .ohq files, semicolons separate command fields and commas separate
key=value pairs within a field. Mixing them up causes silent parse failures
where parameters are ignored without warning.

### 8.5 Time Unit is Days (dt_005)
ALL time values in OHQ are in **days**. Simulation start/end, timestep,
reaction rates, flow rates -- all per-day. Inputting hourly rates without
conversion gives results off by 24x.

### 8.6 Concentration Unit is g/m^3 (dt_006)
This equals mg/L. Using ug/L values without dividing by 1000 inflates
concentrations by 1000x, causing reactions to saturate immediately.

### 8.7 Fixed Head Blocks Need Large Storage (dt_007)
Fixed-head boundary blocks (type=fixed_head) require artificially large
Storage values (e.g., 100000 m^3) to act as infinite reservoirs. Too-small
values cause the boundary to behave as a finite tank.

### 8.8 Crank-Nicholson Weight Affects Stability (dt_008)
`c_n_weight=1` (fully implicit) is stable but diffusive. `c_n_weight=0`
(explicit) is accurate but can oscillate. Default of 1 is safe; changing
without understanding causes instability.

### 8.9 Newton-Raphson Tolerance and Timestep (dt_009)
If `nr_tolerance` is too tight (e.g., 1e-10) with `minimum_timestep` too
large, the solver stalls in infinite reduction loops. Use nr_tolerance=0.001
as starting point.

---

## 9. Tool Reference

| Tool                  | Lines | Stage | Purpose                                     |
|-----------------------|-------|-------|---------------------------------------------|
| convert_forcing.py    | ~200  | S1    | Convert met data CSV to OHQ time series     |
| convert_parameters.py | ~180  | S3    | Convert soil/hydraulic params to OHQ format |
| run_ohq.py            | ~160  | S6    | Execute OHQ binary with preflight checks    |
| parse_output.py       | ~200  | S7-S8 | Parse output.txt, compute metrics, plot     |

---

## 10. Calibration Parameters (Priority Order)

| Parameter              | Range       | Sensitivity | Controls                  |
|------------------------|-------------|-------------|---------------------------|
| Manning's n            | 0.01-0.15   | High        | Flow velocity and depth   |
| hydraulic_conductivity | 0.001-100   | High        | GW-SW exchange            |
| mu_H (growth rate)     | 1-10        | High        | DOM removal rate          |
| K_s (half-sat)         | 5-40        | Medium      | Substrate limitation      |
| mu_N (nitrification)   | 0.1-2.0     | Medium      | NH3 to NOx conversion     |
| K_o (O2 half-sat)      | 0.1-0.5     | Medium      | Aerobic/anoxic switching  |
| diffusion_coefficient  | 0.0001-0.01 | Low         | Constituent mixing        |
| porosity               | 0.2-0.6     | Low         | Sediment storage volume   |
| c_n_weight             | 0.5-1.0     | Low         | Numerical diffusion       |

---

## 11. Quick Start

```bash
# 1. Build the library and test binary
cd OpenHydroQual/OHQLib && mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release && make -j$(nproc)

# 2. Prepare forcing data
python3 ki/tools/convert_forcing.py \
  --input-dir Examples/Wet_pond/ \
  --output-dir run/forcing/ \
  --temp-file Temp_wetland.csv \
  --wind-file Wind_wetland.csv \
  --solar-file Solar_wetland.csv \
  --humidity-file Humidity_wetland.csv

# 3. Run the model
python3 ki/tools/run_ohq.py \
  --binary OHQLib/build/OHQLibTest \
  --input Examples/Wet_pond/Wet_pond.ohq \
  --resources resources/

# 4. Parse and analyze output
python3 ki/tools/parse_output.py \
  --input Examples/Wet_pond/output.txt \
  --output results.csv \
  --plot results.png
```

---

## 12. Diagnostic Triplets Summary

| ID     | Severity | Domain           | Summary                                    |
|--------|----------|------------------|--------------------------------------------|
| dt_001 | fatal    | path_resolution  | Template path not found                    |
| dt_002 | fatal    | path_resolution  | Hardcoded absolute paths in .ohq           |
| dt_003 | silent   | parameter_format | Missing unit brackets on values            |
| dt_004 | silent   | parameter_format | Semicolon/comma delimiter confusion        |
| dt_005 | silent   | unit_conversion  | Time not in days                           |
| dt_006 | silent   | unit_conversion  | Concentration not in g/m^3                 |
| dt_007 | degraded | parameter_format | Fixed head block with small Storage        |
| dt_008 | degraded | runtime          | Wrong Crank-Nicholson weight               |
| dt_009 | fatal    | runtime          | NR tolerance/timestep deadlock             |
| dt_010 | silent   | unit_conversion  | Flow rate not in m^3/day                   |
| dt_011 | silent   | unit_conversion  | Hydraulic conductivity not in m/day        |
| dt_012 | silent   | unit_conversion  | Solar radiation units mismatch             |
| dt_013 | degraded | runtime          | NaN in solution (negative concentration)   |
| dt_014 | silent   | unit_conversion  | Relative humidity as % instead of fraction |
| dt_015 | fatal    | dependency       | Missing Qt6 or GSL at runtime              |

---

## 13. File Structure

```
ki/
  SKILL.md                          # This file
  tools/
    convert_forcing.py              # S1: Met data converter
    convert_parameters.py           # S3: Hydraulic/soil param converter
    run_ohq.py                      # S6: Execution wrapper
    parse_output.py                 # S7: Output parser and metrics
  docs/
    s1_data_preparation.md          # Forcing data pipeline
    s2_template_configuration.md    # JSON template selection
    s3_model_construction.md        # Building the .ohq script
    s4_model_execution.md           # Running and monitoring
    s5_output_analysis.md           # Parsing, metrics, visualization
  diagnostics/
    triplets.yaml                   # 15+ diagnostic triplets
```

---

## 14. Coupling Points

| Source System | Target        | Variable        | Format       |
|---------------|---------------|-----------------|--------------|
| ERA5 / GLDAS  | OHQ forcing   | T, Wind, SW, RH | CSV          |
| HWSD          | OHQ params    | K_sat, porosity | JSON → .ohq  |
| DEM           | OHQ blocks    | elevation       | Raster → CSV |
| SWAT / MODFLOW| OHQ inflow    | Q, concentrations| CSV time series|
| OHQ output    | Downstream    | flow, WQ        | CSV          |

---

## 15. Validation Summary

### Test Case: Wet Pond (6-cell reactive transport)

- **Domain**: Constructed wetland with 6 pond cells + 6 sediment cells
- **Constituents**: DOM, O2, NH3, NOx
- **Processes**: Aerobic decomposition, nitrification, denitrification
- **Forcing**: Evapotranspiration (Penman), atmospheric O2 exchange
- **Duration**: 100 days, dt=0.001 day initial

### Key Findings

1. DOM decreases along the treatment train (aerobic decomposition)
2. O2 maintained by atmospheric exchange source
3. NH3 removed via nitrification (converted to NOx)
4. NOx removed via denitrification under low-O2 conditions
5. Sediment-water exchange modeled via River_bed_sediment_link
6. Weir outflow from final cell to fixed-head boundary
