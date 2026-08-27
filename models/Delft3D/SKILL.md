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
| before running a stage | `docs/s*_*.md` (7 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (16 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (16 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/convert_bathymetry.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_bathymetry.py --help` |
| `tools/convert_boundary_conditions.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_boundary_conditions.py --help` |
| `tools/convert_forcing_to_delft3d.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing_to_delft3d.py --help` |
| `tools/parse_delft3d_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_delft3d_output.py --help` |
| `tools/run_delft3d.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_delft3d.py --help` |

*5 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# Delft3D — Knowledge Infrastructure

**Package**: `hydrocraft-delft3d-ocean` v1.0.0
**Model**: Delft3D (D-Flow FM + Delft3D-FLOW) — Deltares
**Created by**: Jianyun Zhang Research Group, Hohai University
**Last updated**: 2026-03-26
**Stats**: 5 tools | 6 skill documents | 16 diagnostic triplets | ~2,000 lines of validated Python
**Validation status**: `example_validated` (F34 test case, structured + unstructured grids)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for atmospheric forcing documentation.
See `data_ki/NOAA_Tides/SKILL.md` for tidal observation data.
See `data_ki/NDBC/SKILL.md` for wave buoy observations.


## Overview

This knowledge infrastructure enables fully autonomous setup and execution of Delft3D
coastal, estuarine, and river hydrodynamic simulations using both the legacy Delft3D-FLOW
(structured grids) and the modern D-Flow FM (Flexible Mesh, unstructured grids) engines.
The 5 validated Python tools replace manual GUI-based workflows with a scripted pipeline
that integrates with HydroCraft's forcing, bathymetry, and output analysis infrastructure.

**What Delft3D does**: 2D/3D hydrodynamic model for coastal and inland waters. Simulates:
- Tidal and wind-driven flows (shallow water equations, sigma/z-layers)
- Salinity and temperature transport (advection-diffusion)
- Sediment transport and morphodynamics (bedload + suspended load)
- Wave-current interaction (SWAN coupling via D-Waves)
- Water quality (D-Water Quality / DELWAQ, BLOOM eutrophication)
- Particle tracking (oil spill, tracer advection)
- Real-time control (pumps, gates, weirs via D-RTC)
- Domain decomposition and parallel MPI execution

**Key difference from other HydroCraft models**: Delft3D operates on 2D/3D spatial grids
(structured or unstructured) for coastal/estuarine domains, not 1D vertical (GLM) or
lumped basins (VIC/SWAT). It couples with CaMa-Flood (upstream river discharge as
boundary inflow) and can receive VIC meteorological forcing with unit conversions.

---

## Installation

### Binary (Docker-based, recommended)

```
Delft3D FM:     Built via Docker (Intel oneAPI 2024 + third-party libs)
DIMR:           dimr (Deltares Integrated Model Runner) — main executable
D-Flow FM:      dflowfm (unstructured hydrodynamics)
Delft3D-FLOW:   flow2d3d (structured hydrodynamics)
Source:         github.com/Deltares/Delft3D
Platform:       Linux x86-64 (Docker container)
```

### Build from source (Linux)

```bash
# Prerequisites: Docker Engine, Git
# Step 1: Build third-party-libs Docker image
docker build . -f doc/third-party-libs.Dockerfile \
    -t localhost/third-party-libs:oneapi-2024

# Step 2: Build Delft3D Docker image
docker build . -f doc/delft3d.Dockerfile \
    -t localhost/delft3d:oneapi-2024

# Step 3: OR build manually inside container
docker run -it -v .:/delft3d localhost/third-party-libs:oneapi-2024 bash
cd /delft3d
./build.sh all --build --build_type Release

# Produces: install_all/lnx64/bin/{dimr,dflowfm,flow2d3d,dwaq,dwaves,...}
```

### Dependencies

```
Compilers:      Intel oneAPI 2024 (ifx, icx, icpx)
CMake:          >= 3.30
MPI:            Intel MPI
PETSc:          3.24.5
NetCDF:         4.9.2 + NetCDF-Fortran 4.6.1
HDF5:           1.14.2 (parallel)
Proj:           9.7.1
METIS:          Graph partitioning
Expat:          2.6.2 (XML)
Xerces-C:       3.2.5 (XML)
SQLite3:        3.46.0
```

### Python dependencies (for KI tools)

```
netCDF4, numpy, pandas, xarray, matplotlib, pyyaml
```

### Test example

```
source/repo/examples/dflowfm/01_dflowfm_sequential/
  dimr_config.xml               # DIMR orchestrator config
  dflowfm/f34.mdu              # D-Flow FM master definition
  dflowfm/f34_net.nc           # Unstructured grid (258 nodes)
  dflowfm/f34_bnd.ext          # Boundary condition spec
  dflowfm/f34_001.bc           # Tidal boundary (harmonic)
  dflowfm/f34_obs.xyn          # Observation points
  dflowfm/f34.wnd              # Wind forcing (uniform)
```

---

## Pipeline (8 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | (manual) | Domain selection, grid type, period, physics modules |
| 1 | Grid generation | (external: MeshKernel/RGFGRID) | Structured .grd or unstructured _net.nc |
| 2 | Bathymetry | `convert_bathymetry` | GEBCO/ETOPO → model depth file (.dep or in _net.nc) |
| 3 | Met forcing | `convert_forcing_to_delft3d` | ERA5/CMFD/VIC → wind, pressure, heat flux files |
| 4 | Boundary conditions | `convert_boundary_conditions` | Tide/river/open-sea → .bc/.bch/.bnd files |
| 5 | Configuration | (manual + templates) | Assemble .mdu/.mdf + dimr_config.xml |
| 6 | Execution | `run_delft3d` | Run DIMR with preflight checks and monitoring |
| 7 | Output analysis | `parse_delft3d_output` | Parse _map.nc/_his.nc, compute metrics, plots |

### Parallelism

Stages 2, 3, 4 can run in parallel after stage 1 (grid generation).
Stage 5 depends on stages 1-4 (all inputs ready).
Stage 6 depends on stage 5.
Stage 7 depends on stage 6.

---

## Input File Formats

### D-Flow FM (Unstructured Grid)

| File | Extension | Format | Purpose |
|------|-----------|--------|---------|
| Master Definition | .mdu | INI-style text | Main configuration (all settings) |
| Grid | _net.nc | NetCDF4 (UGRID) | Unstructured mesh topology + bathymetry |
| External forcing spec | .ext | INI-style text | Links boundaries to data files |
| Boundary location | .pli | Polyline text | Boundary point coordinates |
| Boundary data | .bc | INI-style text | Time series or harmonic components |
| Observation points | .xyn | XYZ text | Monitoring locations (x, y, name) |
| Wind | .wnd | Space-separated text | Time, speed, direction |
| Thin dams | _thd.pli | Polyline text | Barrier structures |
| Dry points | _dry.xyz | XYZ text | Permanently dry cells |
| DIMR config | .xml | XML | Component orchestration |

### Delft3D-FLOW (Structured Grid)

| File | Extension | Format | Purpose |
|------|-----------|--------|---------|
| Master Definition | .mdf | Key=value text | Main configuration |
| Grid coordinates | .grd | Fortran free-format | Structured grid (M x N) |
| Grid enclosure | .enc | Index pairs | Domain boundary |
| Bathymetry | .dep | Grid-aligned values | Depth at grid points (m) |
| Boundary definition | .bnd | Text | Boundary locations + types |
| Boundary data | .bca/.bch | Text | Tidal components / time series |
| Discharge locations | .src | Grid indices | Source/sink positions |
| Discharge data | .dis | Table format | Flux time series (m³/s) |
| Observation points | .obs | Grid indices | Monitoring locations |
| Cross-sections | .crs | Grid paths | Discharge measurement lines |
| Wind | .wnd | Text | Wind forcing |

---

## Key Variables and Units

### Input Variables

| Variable | Symbol | Units | Source | Trap |
|----------|--------|-------|--------|------|
| Water level (boundary) | s1 | m (MSL) | Tide gauge / model | Sign convention! |
| Velocity (boundary) | u, v | m/s | Upstream model | — |
| Wind speed | Ws | m/s at 10m | ERA5 / station | Height adjustment |
| Wind direction | Wd | degrees from N | ERA5 / station | Convention: FROM |
| Atmospheric pressure | P_atm | Pa (not hPa!) | ERA5 / reanalysis | ×100 if hPa |
| Air temperature | T_air | °C | ERA5 / station | — |
| Relative humidity | RH | % (0-100) | ERA5 / station | NOT fraction 0-1 |
| Cloud cover | Fc | fraction (0-1) | ERA5 / station | NOT percentage |
| Shortwave radiation | Q_sw | W/m² | ERA5 / station | — |
| Precipitation | Rain | mm/hr | ERA5 / station | NOT m/day |
| River discharge | Q | m³/s | Gauge / CaMa-Flood | — |
| Salinity | S | PSU (≈ g/kg) | Measurement / model | — |
| Temperature | T | °C | Measurement / model | — |
| Bathymetry | z_b | m (positive down) | GEBCO / survey | Sign convention! |
| Manning friction | n | s/m^(1/3) | Literature / calibration | Chezy = 1/n × R^(1/6) |
| Chezy friction | C | m^(1/2)/s | Literature / calibration | Typically 40-70 |

### Output Variables (NetCDF)

| Variable | Symbol | Units | File | Description |
|----------|--------|-------|------|-------------|
| Water level | s1 | m | _map.nc, _his.nc | Sea surface elevation |
| Velocity (x) | ucx | m/s | _map.nc | East-west flow |
| Velocity (y) | ucy | m/s | _map.nc | North-south flow |
| Water depth | waterdepth | m | _map.nc | Depth at cell center |
| Discharge | q1 | m³/s | _map.nc | Through cell edges |
| Salinity | sa1 | PSU | _map.nc | Salt concentration |
| Temperature | tem1 | °C | _map.nc | Water temperature |
| Density | rho | kg/m³ | _map.nc | Water density |
| TKE | turkin1 | m²/s² | _map.nc | Turbulent kinetic energy |
| Bed shear stress | taus | N/m² | _map.nc | Bottom stress |
| Sig. wave height | hwav | m | _map.nc | From D-Waves |
| Sediment conc. | sed | kg/m³ | _map.nc | Suspended load |
| Bedload transport | sbcx, sbcy | kg/(m·s) | _map.nc | Bed sediment flux |

---

## Output Description

This section restates `dag.yaml`. The dag is the source of truth for model
outputs, validation rank, units, and medium-named descriptions. If this section
and `dag.yaml` ever disagree, `dag.yaml` wins.

**Headline output**: `water_level` is the dag's rank-1 output variable and is
the variable this model is judged by.

> `water_level` -- Sea surface elevation (s1) at cell centres (m)

| Output variable (dag `var`) | Validation rank | Unit | Description |
|-----------------------------|-----------------|------|-------------|
| `water_level` | 1 | m | Sea surface elevation (s1) at cell centres |

Other dag outputs are: `velocity`, `salinity`, `temperature`,
`bed_shear_stress`, `bed_level_change`, and `significant_wave_height`.

---

## Validated Results

**Validation status**: `example_validated` using the F34 test case with
structured and unstructured grids.

Judgement uses `docs/validation_convention.yaml`, not intuition. The convention
defines metric direction and cited pass-bands per dag variable. Bands that the
convention records as null are written here as `no cited threshold`.

### Performance Metrics -- Convention Bars

| Dag variable | Metric | Direction | Very good band | Good band | Satisfactory band |
|--------------|--------|-----------|----------------|-----------|-------------------|
| `water_level` | rmse | minimize | <= 0.1 (whitehouse2017) | <= 0.2 (whitehouse2017) | <= 0.3 (whitehouse2017) |
| `water_level` | bias | zero_centered | abs(bias) <= 0.1 (whitehouse2017) | abs(bias) <= 0.1 (whitehouse2017) | abs(bias) <= 0.2 (whitehouse2017) |
| `water_level` | csi | maximize | no cited threshold | no cited threshold | no cited threshold |
| `velocity` | rmse | minimize | <= 0.05 (whitehouse2017) | <= 0.1 (whitehouse2017) | <= 0.2 (whitehouse2017) |
| `velocity` | bias | zero_centered | abs(bias) <= 0.1 (whitehouse2017, mohid2019) | abs(bias) <= 0.1 (whitehouse2017, mohid2019) | abs(bias) <= 0.2 (whitehouse2017, mohid2019) |

No run-specific achieved metric values are embedded in this skill document.
Compute achieved values from model outputs and observations with
`parse_delft3d_output`, then grade them against the cited convention bars above.

---

## Unit Trap Table

These are the most common unit conversion errors encountered when setting up Delft3D.
Each corresponds to a diagnostic triplet.

| # | Variable | Delft3D expects | Common source | Error factor | Symptom |
|---|----------|----------------|---------------|--------------|---------|
| 1 | Pressure | Pa | hPa (ERA5) | ×100 | Wrong water level offset (~10 cm) |
| 2 | Bathymetry sign | Positive down (D-Flow FM default) | Positive up (GEBCO) | ×(-1) | Model sees mountains as ocean |
| 3 | Wind direction | FROM (nautical) | TO (math) | +180° | Reversed storm surge |
| 4 | Rel. Humidity | % (0-100) | fraction (0-1) | ×100 | Extreme evaporation/condensation |
| 5 | Cloud cover | fraction (0-1) | % (0-100) | ÷100 | Incorrect heat budget |
| 6 | Precipitation | mm/hr | m/day (GLM) | conversion | Freshwater flux mismatch |
| 7 | Chezy vs Manning | context-dependent | confusion | inverse | Friction totally wrong |
| 8 | Time | seconds since refdate | minutes (MDU Tunit) | ×60 | Wrong simulation duration |
| 9 | Coordinates | projected (m) | geographic (deg) | — | Grid size 10^5x wrong |
| 10 | Salinity | PSU (≈ g/kg) | g/L | ~1.0 | Small density error |

---

## Tools Reference

| Tool | Stage | Script Path | Lines | Purpose |
|------|-------|-------------|------:|---------|
| `convert_forcing_to_delft3d` | s3 | `tools/convert_forcing_to_delft3d.py` | 380 | ERA5/CMFD → wind, meteo, heat flux files |
| `convert_boundary_conditions` | s4 | `tools/convert_boundary_conditions.py` | 350 | Tide/discharge → .bc/.bnd/.pli files |
| `convert_bathymetry` | s2 | `tools/convert_bathymetry.py` | 280 | GEBCO/ETOPO → model depth format |
| `run_delft3d` | s6 | `tools/run_delft3d.py` | 300 | Execute DIMR with preflight + monitoring |
| `parse_delft3d_output` | s7 | `tools/parse_delft3d_output.py` | 350 | Parse NetCDF output → CSV + metrics |

**Total**: 5 tools, ~1,660 lines of Python code.

---

## Configuration File Structure

### MDU File (D-Flow FM) — Key Sections

```ini
[General]
Program    = D-Flow FM
AutoStart  = 1                    # 1 = auto-start simulation

[geometry]
NetFile    = domain_net.nc        # Unstructured grid (UGRID NetCDF)
BathymetryFile = ...              # Optional separate bathymetry
AngLat     = 52.0                 # Latitude for Coriolis (degrees)
Kmx        = 0                    # Number of vertical layers (0 = 2D)

[numerics]
CFLMax     = 0.7                  # Max Courant number
Icgsolver  = 4                    # Linear solver type
Teta0      = 0.55                 # Time integration parameter

[physics]
UnifFrictCoef = 65                # Chezy coefficient (if FrictType=0)
UnifFrictType = 0                 # 0=Chezy, 1=Manning, 2=White-Colebrook
Vicouv     = 2                    # Horizontal eddy viscosity [m²/s]
Dicouv     = 10                   # Horizontal diffusivity [m²/s]
Salinity   = 0                    # 0=off, 1=on
Temperature = 0                   # 0=off, 1=on, 3=excess model, 5=heat flux

[wind]
ICdtyp     = 2                    # Wind drag model
Cdbreakpoints = 0.00063 0.00723   # Drag coefficient breakpoints
Windspeedbreakpoints = 0.0 100.0  # Wind speed breakpoints [m/s]

[time]
RefDate    = 20200101             # YYYYMMDD reference date
Tunit      = S                    # Time unit: S(seconds), M(minutes), H(hours)
DtUser     = 300                  # User timestep [Tunit]
DtMax      = 30                   # Max computational timestep [seconds]
TStart     = 0                    # Start time [Tunit since RefDate]
TStop      = 86400                # Stop time [Tunit since RefDate]

[external forcing]
ExtForceFileNew = boundaries.ext  # New-format external forcing

[output]
OutputDir  = output               # Output directory
HisFile    = model_his.nc         # History file name
HisInterval = 600                 # History output interval [s]
MapFile    = model_map.nc         # Map file name
MapInterval = 3600                # Map output interval [s]
```

### MDF File (Delft3D-FLOW) — Key Parameters

```
Ident  = #Delft3D-FLOW .03.02 3.39.29.52817#
Runtxt = #Example run                       #
Filcco = #domain.grd#          # Grid coordinates
Fildep = #domain.dep#          # Bathymetry
Filbnd = #domain.bnd#          # Boundary locations
FilbcH = #domain.bch#          # Boundary data (time series)
Itdate = #2020-01-01#          # Reference date
Tunit  = #M#                   # Time unit (M=minutes)
Tstart = 0.0                   # Start [Tunit]
Tstop  = 1440.0                # Stop [Tunit] (= 1 day)
Dt     = 1.0                   # Timestep [minutes]
Ag     = 9.81                  # Gravitational acceleration [m/s²]
Rhow   = 1025.0                # Water density [kg/m³]
Ccofu  = 65.0                  # Chezy friction U [m^0.5/s]
Ccofv  = 65.0                  # Chezy friction V [m^0.5/s]
```

### DIMR Configuration (dimr_config.xml)

```xml
<?xml version="1.0" encoding="utf-8" standalone="yes"?>
<dimrConfig>
  <documentation>
    <fileVersion>1.3</fileVersion>
    <createdBy>KI tools</createdBy>
  </documentation>
  <control>
    <parallel>
      <startGroup>
        <time>0 60 9999999</time>   <!-- start dt stop -->
        <start name="DFlowFM"/>
        <coupler name="flow_to_wave"/>
        <start name="DWaves"/>
      </startGroup>
    </parallel>
  </control>
  <component name="DFlowFM">
    <library>dflowfm</library>
    <workingDir>dflowfm</workingDir>
    <inputFile>model.mdu</inputFile>
  </component>
</dimrConfig>
```

---

## Critical Domain Knowledge

These non-obvious facts cause **silent failures** if violated. Each has a
corresponding diagnostic triplet.

### 1. Bathymetry sign convention differs between engines (dt_001)

D-Flow FM default: depth positive downward (bed level = negative elevation).
GEBCO/ETOPO: elevation positive upward (ocean depth = negative).
Delft3D-FLOW: depth positive downward in .dep files.
**Always negate** GEBCO values for Delft3D input. If not negated, the model
sees ocean as mountains and land as canyons — it will crash or produce nonsense.

### 2. Atmospheric pressure must be in Pascals (dt_002)

ERA5 provides surface pressure in Pa, but mean sea level pressure is often in
hPa. Delft3D expects Pa. If you supply hPa (e.g., 1013.25 instead of 101325),
the inverse barometer effect is 100x too small, producing ~10 cm water level
error. The model will not crash — the error is silent.

### 3. Wind direction convention: FROM, not TO (dt_003)

Delft3D uses nautical convention: wind direction is the direction the wind blows
**from** (0°=North, 90°=East). ERA5 uses the same convention, but some datasets
use mathematical convention (direction wind blows **to**). A 180° error reverses
the storm surge direction.

### 4. RefDate + Tunit determines all timing (dt_008)

All times in MDU/MDF are relative to RefDate in units of Tunit. If Tunit=M
(minutes), TStop=1440 means 1 day. If Tunit=S, TStop=1440 means 24 minutes.
Mixing up Tunit causes the simulation to be 60x too short or 60x too long.

### 5. Chezy vs Manning: know which you're using (dt_007)

Chezy C ≈ 40-70 m^(1/2)/s (higher = smoother).
Manning n ≈ 0.01-0.05 s/m^(1/3) (higher = rougher).
They are inversely related: C = R^(1/6) / n.
Setting UnifFrictType=0 (Chezy) with a Manning value of 0.025 gives extreme
friction (Chezy=0.025 means nearly solid wall). The model will barely flow.

### 6. Grid coordinates must be consistent with CRS (dt_009)

If the grid is in geographic coordinates (lon/lat in degrees), Delft3D interprets
distances in degrees, not meters. A cell of 0.01° ≈ 1.1 km, but Delft3D may
compute cell area as 0.01² = 0.0001 "units²". Use projected coordinates (UTM)
for proper area/volume computations, or ensure the MDU specifies the correct CRS.

### 7. NetCDF output uses CF + UGRID conventions (dt_010)

Output files follow CF (Climate and Forecast) conventions for structured grids
and UGRID conventions for unstructured grids. Tools like `ncdump`, `xarray`,
and `dfm_tools` can read them. Do NOT try to parse binary .dat output files
from legacy Delft3D-FLOW — always enable NetCDF output (FlNcdf=MAP HIS).

---

## Quick Start

```bash
# 1. Prepare forcing from ERA5 (converts units, generates .wnd + meteo files)
python ki/tools/convert_forcing_to_delft3d.py \
  --era5_file era5_hourly.nc \
  --domain_bounds "1.0 51.0 4.0 53.0" \
  --start_date 2020-01-01 --end_date 2020-02-01 \
  --output_dir forcing/

# 2. Convert bathymetry from GEBCO
python ki/tools/convert_bathymetry.py \
  --gebco_file GEBCO_2023.nc \
  --grid_file domain_net.nc \
  --output domain_depth.xyz \
  --negate_depth

# 3. Generate boundary conditions from tide model
python ki/tools/convert_boundary_conditions.py \
  --tide_model FES2014 \
  --boundary_pli boundaries.pli \
  --start_date 2020-01-01 --end_date 2020-02-01 \
  --output_bc boundaries.bc

# 4. Run the model via DIMR
python ki/tools/run_delft3d.py \
  --dimr_config dimr_config.xml \
  --binary_dir /path/to/install_all/lnx64/bin \
  --nproc 4

# 5. Parse and analyze output
python ki/tools/parse_delft3d_output.py \
  --his_file output/model_his.nc \
  --map_file output/model_map.nc \
  --obs_file observed_waterlevel.csv \
  --output_csv results.csv \
  --plot results_plot.png
```

---

## Coupling Points

| # | Source | Target | Variable | Tool |
|---|--------|--------|----------|------|
| 1 | ERA5 / CMFD | Delft3D | Wind, pressure, heat flux | `convert_forcing_to_delft3d` |
| 2 | CaMa-Flood | Delft3D | River discharge at boundaries | `convert_boundary_conditions` |
| 3 | GEBCO / ETOPO | Delft3D | Bathymetry | `convert_bathymetry` |
| 4 | Tide model (FES/TPXO) | Delft3D | Tidal boundary | `convert_boundary_conditions` |
| 5 | D-Flow FM | D-Waves | Water levels, currents | DIMR coupling |
| 6 | D-Waves | D-Flow FM | Wave forces, radiation stress | DIMR coupling |
| 7 | D-Flow FM | D-WAQ | Hydrodynamics → water quality | DIMR coupling |

---

## Data Requirements

| Data | Source | Status | Purpose |
|------|--------|--------|---------|
| Delft3D binaries | Docker build | Build required | Simulation engines |
| Grid file | MeshKernel / RGFGRID | User-provided | Model domain |
| GEBCO bathymetry | gebco.net | Download ~8 GB | Ocean depth |
| ERA5 forcing | Copernicus CDS | Download | Meteo + wind |
| Tide constituents | FES2014 / TPXO | Download | Open boundaries |
| River discharge | CaMa-Flood / gauges | From pipeline | Upstream inflow |
| Observation data | CMEMS / tide gauges | Download | Validation |

---

## Example Cases

### Built-in examples (source/repo/examples/)

**D-Flow FM:**
1. `01_dflowfm_sequential` — Basic sequential run (F34 estuary)
2. `02_dflowfm_parallel` — MPI parallel (Westerscheldt)
3. `03-06_dflowfm_dwaq*` — Coupled with water quality
4. `07_dwaves` — Wave-only simulation
5. `08-11_dflowfm*dwaves*` — Flow-wave coupling

**Delft3D-FLOW:**
1. `01_standard` — Standard structured grid (F34)
2. `02_domaindecomposition` — Multi-domain parallel
3. `03_flow-wave` — Coupled flow + wave
4. `04_fluidmud` — Sediment/mud
5. `06_delwaq` — Water quality
6. `08-10_part*` — Particle tracking (tracer, oil)

### Running examples

```bash
# Sequential D-Flow FM (simplest)
cd examples/dflowfm/01_dflowfm_sequential
./run.sh  # or: dimr dimr_config.xml

# Parallel D-Flow FM
cd examples/dflowfm/02_dflowfm_parallel
mpirun -np 4 dimr dimr_config.xml

# Delft3D-FLOW
cd examples/delft3d4/01_standard
./run.sh
```
