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
| to run the pipeline stages | `tools/` (6 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (5 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (24 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (22 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/convert_fuel_params.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_fuel_params.py --help` |
| `tools/convert_landscape_to_nc.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_landscape_to_nc.py --help` |
| `tools/parse_forefire_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_forefire_output.py --help` |
| `tools/prepare_fire_case.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/prepare_fire_case.py --help` |
| `tools/run_forefire.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_forefire.py --help` |
| `tools/validate_spread.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/validate_spread.py --help` |

*6 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# ForeFire v1.0 -- Knowledge Infrastructure Skill Document

> **Version**: v1.0.0
> **Domain**: wildfire spread / fire behavior
> **Last updated**: 2026-08-18
> **Validation status**: `build_validated`

**Package**: `wildfire-forefire` v1.0.0
**Model**: ForeFire (C++ wildfire propagation engine)
**Developed by**: CNRS / Universite de Corse Pascal Paoli
**Stats**: 6 tools | 5 stage documents | 24 diagnostic triplets

---

## 1. Model Identity

| Property | Value |
|----------|-------|
| Full name | ForeFire |
| Version | v1.0.0 |
| Package | `wildfire-forefire` v1.0.0 |
| Language | C++ engine with optional Python bindings |
| Primary domain | Wildfire spread / fire behavior |
| Spatial mode | 2D front-tracking propagation over gridded landscape data |
| Developer | CNRS / Universite de Corse Pascal Paoli |
| Primary interface | `forefire` CLI interpreter, `.ff` scripts, optional `pyforefire`, HTTP server mode, `libforefireL` |
| Validation status | `build_validated` |
| Citation | Filippi et al. (2025), Journal of Open Source Software, 10(116), 8680 |

---

## 2. What This Model Does

This knowledge infrastructure enables autonomous wildfire spread simulation using ForeFire, an open-source C++ wildfire simulation engine. The tools replace manual data preparation with a Python pipeline that handles landscape data ingestion, fuel parameter configuration, simulation execution, output parsing, and validation.

ForeFire is a 2D front-tracking wildfire propagation simulator. It simulates:
- Fire front propagation using multiple Rate of Spread (ROS) models: Rothermel, Balbi2020, RothermelAndrews2018, Farsite, Isotropic.
- Wind-driven and slope-driven fire spread.
- Fuel-dependent combustion characteristics.
- Fire-atmosphere coupling with MesoNH, when configured.
- Multi-front ignition and merging.
- Output in KML, GeoJSON, NetCDF, and custom `.ff` formats.

**Key interfaces**:
- `forefire` CLI interpreter, either interactive or driven by script files ending in `.ff`.
- Python bindings (`pyforefire`) for programmatic control.
- HTTP server mode for web-based simulation.
- C++ library (`libforefireL`) for direct integration.

### Propagation Models

#### Rothermel (1972)

Classic surface fire spread model. Uses dead fuel parameters from `fuels.csv`.

**Key equations** (simplified):
- Reaction intensity: `I_R = Gamma' * w_n * DeltaH * eta_M * eta_s`
- ROS: `R = (I_R * xi) / (rho_b * epsilon * Q_ig) * (1 + phi_w + phi_s)`

Where `phi_w` is wind factor and `phi_s` is slope factor.

**Wind limit**: When `windReductionFactor < 1.0`, applies Andrews/Cruz/Rothermel (2013) wind limit: `U_f = 96.81 * I_R^(1/3)`. Otherwise `U_f = 0.9 * I_R`.

#### Balbi2020

Physics-based model from Universite de Corse. Uses an iterative solver with max 40 iterations.

**Key features**:
- Accounts for radiative and convective heat transfer.
- Uses flame angle, flame height, and vertical velocity.
- Requires temperature and moisture layers in addition to fuel.
- Convergence tolerance: 0.01 m/s.

#### RothermelAndrews2018

Updated Rothermel formulation per Andrews (2018), RMRS-GTR-371. Uses NFFL/FBFM-style fuel parameters directly in Imperial units.

#### Farsite

FARSITE-compatible propagation model. Uses standard NFFL fuel models with moisture classes: 1-hr, 10-hr, 100-hr, live herbaceous, live woody.

#### Isotropic (Iso)

Constant speed in all directions. Useful for testing.

---

## 3. Input Requirements

**Exact shapes live in `docs/format_spec.yaml`**. That file is projected from `dag.yaml` and `diagnostics/triplets.yaml`; regenerate it after changing either source and never hand-edit it.

Before preparing data, run `python preflight_check.py` in this KI directory. Do not debug a model run that never had a healthy environment.

### 3.1 Forcing Data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for weather forcing documentation. See `data_ki/MTBS/SKILL.md` for fire perimeter observations.

| Variable | Unit model expects | Source dataset | Source unit | Conversion |
|----------|-------------------|----------------|-------------|------------|
| `windU` | m/s | CMFD/MSWX/NASA POWER or station forcing | dataset-specific | Convert to m/s before writing `data.nc` |
| `windV` | m/s | CMFD/MSWX/NASA POWER or station forcing | dataset-specific | Convert to m/s before writing `data.nc` |
| `temperature` | K | CMFD/MSWX/NASA POWER or station forcing | dataset-specific | Required by Balbi2020 when used |
| `moisture` | fraction (0-1) | fuel / weather-derived source | dataset-specific | Optional layer; must be fraction |

### 3.2 Static Inputs

| Input | Source | Tool that prepares it |
|-------|--------|----------------------|
| DEM / topography | geospatial raster source | `tools/convert_landscape_to_nc.py` |
| Fuel index map | land-cover / fuel-map source | `tools/convert_landscape_to_nc.py` |
| Fuel properties | standard fuel model table or user fuel table | `tools/convert_fuel_params.py` |
| Fire perimeter observations | MTBS or other perimeter observations | `tools/validate_spread.py` |

### 3.3 Landscape Data (`data.nc`)

The primary geospatial input contains gridded layers:

| Variable | Dimensions | Units | Description |
|----------|------------|-------|-------------|
| `altitude` | (t, z, y, x) | m | Digital elevation model |
| `fuel` | (t, z, y, x) | index (0-N) | Fuel type index, referencing `fuels.csv` |
| `windU` | (t, z, y, x) | m/s | U-component, eastward, of wind |
| `windV` | (t, z, y, x) | m/s | V-component, northward, of wind |
| `moisture` | (t, z, y, x) | fraction (0-1) | Fuel moisture content, optional |
| `temperature` | (t, z, y, x) | K | Air temperature, optional for Balbi |

**Coordinate system**: UTM projection in meters. The active ForeFire local frame is domain-local meters; use the docs and `prepare_fire_case.py` when converting projected coordinates to `startFire[loc=...]`.

### 3.4 Fuel Properties (`fuels.csv`)

Semicolon-delimited CSV. Each row is a fuel type indexed by the `Index` column.

#### Rothermel/Balbi Fuel Parameters

| Column | Symbol | Units | Description |
|--------|--------|-------|-------------|
| `Index` | - | - | Fuel type index, matching NetCDF fuel layer |
| `Rhod` | rho_d | kg/m^3 | Dead fuel particle density |
| `Rhol` | rho_l | kg/m^3 | Live fuel particle density |
| `Md` | M_d | fraction | Dead fuel moisture content |
| `Ml` | M_l | fraction | Live fuel moisture content |
| `sd` | s_d | 1/m | Dead fuel surface-area-to-volume ratio |
| `sl` | s_l | 1/m | Live fuel surface-area-to-volume ratio |
| `e` | e | m | Fuel bed depth |
| `Sigmad` | sigma_d | kg/m^2 | Dead fuel load |
| `Sigmal` | sigma_l | kg/m^2 | Live fuel load |
| `stoch` | - | - | Stochiometric coefficient |
| `RhoA` | rho_a | kg/m^3 | Air density |
| `Ta` | T_a | K | Ambient temperature |
| `Tau0` | tau_0 | s | Flame residence time |
| `Deltah` | Delta h | J/kg | Heat of vaporization of water |
| `DeltaH` | Delta H | J/kg | Heat of combustion |
| `Cp` | C_p | J/(kg*K) | Fuel specific heat |
| `Cpa` | C_pa | J/(kg*K) | Air specific heat |
| `Ti` | T_i | K | Ignition temperature |
| `X0` | chi_0 | - | Radiant fraction |
| `r00` | r_00 | m | Flame base radiation length |
| `Blai` | LAI | m^2/m^2 | Leaf area index |
| `me` | M_e | fraction | Moisture of extinction |

#### RothermelAndrews2018 Fuel Parameters

| Column | Units | Description |
|--------|-------|-------------|
| `fl1h_tac` | US tons/acre | 1-hour fuel loading |
| `fd_ft` | ft | Fuel bed depth |
| `SAVcar_ftinv` | 1/ft | Characteristic SAV ratio |
| `mdOnDry1h_r` | ratio | 1-hour dead moisture fraction |
| `fuelDens_lbft3` | lb/ft^3 | Oven-dry particle density |
| `H_BTUlb` | BTU/lb | Low heat of combustion |
| `Dme_pc` | % | Dead moisture of extinction |
| `totMineral_r` | ratio | Total mineral content |
| `effectMineral_r` | ratio | Effective mineral content |

### 3.5 ForeFire Script Files

ForeFire uses a command-based scripting language. Each command has the form `commandName[param1=val1;param2=val2]`.

| Command | Purpose | Example |
|---------|---------|---------|
| `setParameter[key=value]` | Set simulation parameter | `setParameter[propagationModel=Rothermel]` |
| `FireDomain[sw=(...);ne=(...);t=T]` | Create simulation domain | `FireDomain[sw=(0,0,0);ne=(50000,50000,0);t=0]` |
| `loadData[file;timestamp]` | Load landscape NetCDF | `loadData[data.nc;2025-02-10T17:35:54Z]` |
| `startFire[loc=(...);t=T]` | Ignite fire at domain-local coordinates | `startFire[loc=(35881,28699,0);t=0]` |
| `startFire[lonlat=(...);t=T]` | Ignite fire at lon/lat | `startFire[lonlat=(8.70,41.952,0);t=0]` |
| `trigger[wind;loc=(...);vel=(...)]` | Set wind vector | `trigger[wind;loc=(0,0,0);vel=(10,5,0)]` |
| `step[dt=T]` | Advance simulation by T seconds | `step[dt=3600]` |
| `goTo[t=T]` | Advance to absolute time T | `goTo[t=360]` |
| `include[file.ff]` | Include another script | `include[params.ff]` |
| `print[]` | Print fire front state | `print[output.geojson]` |
| `save[]` | Save state to NetCDF | `save[filename=out.nc]` |
| `listenHTTP[]` | Start HTTP server | `listenHTTP[]` |

| Parameter | Default | Description |
|-----------|---------|-------------|
| `propagationModel` | required | ROS model: `Rothermel`, `Balbi2020`, `RothermelAndrews2018`, `Farsite`, `Iso` |
| `fuelsTableFile` | `fuels.csv` | Path to fuel properties CSV |
| `ForeFireDataDirectory` | `.` | Working directory for data files |
| `spatialIncrement` | 3 | Spatial resolution for front nodes (m) |
| `perimeterResolution` | 10 | Perimeter node spacing (m) |
| `propagationSpeedAdjustmentFactor` | 1.0 | Global ROS multiplier |
| `windReductionFactor` | 1.0 | Wind speed reduction factor (0-1) |
| `dumpMode` | `ff` | Output format: `ff`, `kml`, `geojson`, `json` |
| `minSpeed` | 0.009 | Minimum propagation speed (m/s) |
| `relax` | 0.5 | Relaxation factor for front smoothing |
| `minimalPropagativeFrontDepth` | 20 | Minimum front depth for propagation (m) |
| `noInitialScan` | 0 | Skip initial domain scan (1=yes) |

---

## 4. Build Instructions

### Build from Source (Linux)

```bash
apt-get update
apt install build-essential libnetcdf-c++4-dev cmake -y

cd /path/to/forefire
mkdir -p build && cd build
cmake ../
make -j$(nproc)

# Binary at: forefire/bin/forefire
# Library at: forefire/lib/libforefireL.so
```

### Python Bindings

```bash
cd bindings/python
pip install -e .
```

### Docker

```bash
docker build . -t forefire:latest
docker run -it --rm -p 8000:8000 forefire
```

### Dependencies

| Dependency | Purpose |
|------------|---------|
| `libnetcdf-c++4` | NetCDF I/O for landscape and output data |
| `cmake >= 3.10` | Build system |
| C++11 compiler | Core engine compilation |
| MPI, optional | Parallel computing / MesoNH coupling |
| Python >= 3.8 | Bindings and KI tools |

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `FOREFIREHOME` | Root directory of ForeFire installation |
| `NETCDF_HOME` | NetCDF installation path, if not system default |
| `SRC_MESONH` | MesoNH source path for coupled simulations |
| `XYZ` | MesoNH build target identifier |

**Known build issues**: Check `diagnostics/triplets.yaml` before debugging. Common build failures include missing NetCDF C++ library (`dt_013`) and missing NetCDF development headers (`dt_014`).

---

## 5. Execution

Run the KI preflight first:

```bash
python preflight_check.py
```

Then compose or generate a case, run ForeFire, parse outputs, and validate:

```bash
python tools/prepare_fire_case.py --help
python tools/run_forefire.py --help
python tools/parse_forefire_output.py --help
python tools/validate_spread.py --help
```

### Pipeline

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | manual / `prepare_fire_case` | Define domain, period, ignition points, ROS model |
| 1 | Landscape data | `convert_landscape_to_nc` | Elevation, fuel index, wind to NetCDF |
| 2 | Fuel parameters | `convert_fuel_params` | Fuel properties CSV for Rothermel/Balbi/Andrews-style parameters |
| 3 | Simulation script | `prepare_fire_case` / manual `.ff` file | ForeFire script with parameters, data load, ignition |
| 4 | Execution | `run_forefire` | Run the ForeFire binary with preflight and postflight checks |
| 5 | Output parsing | `parse_forefire_output` | Extract fire perimeters to CSV/GeoJSON |
| 6 | Validation | `validate_spread` | Compare simulated vs observed perimeters |

### Parallelism

Stages 1 and 2 can run in parallel. Stage 3 depends on 1 and 2. Stage 4 depends on 3. Stages 5 and 6 depend on 4.

**Execution policy**: You must run the actual ForeFire binary or package. Do not substitute a simplified Python formula, regression equation, or hand-coded approximation.

---

## 6. Output Description

**Source: `dag.yaml`. The dag wins over this body if they ever disagree.**

RANK-1 OUTPUT (dag.yaml, verbatim): `var='burned_area' unit='ha' description='Total wildfire-burned vegetation area derived from the arrival-time / perimeter at a given time.'`

**Headline output**: `burned_area` is the dag's rank-1 variable, and this model is judged by it.

| Output variable (dag `var`) | Validation rank | Unit | Description |
|-----------------------------|-----------------|------|-------------|
| `burned_area` | 1 | ha | Total wildfire-burned vegetation area derived from the arrival-time / perimeter at a given time. |

Other dag outputs:
- `arrival_time_of_front`
- `fire_front_perimeter`
- `rate_of_spread`
- `fire_line_intensity`

### Output Formats

#### KML

Fire front perimeters as polygons. Generated with `dumpMode=kml` and `print[output.kml]`.

#### GeoJSON

Fire front geometries. Generated with `dumpMode=geojson` and `print[output.geojson]`.

#### NetCDF (`ForeFire.0.nc`)

State output including:
- Burning map / arrival time at each grid cell.
- Wind field snapshots.
- Fuel and altitude data.

Generated with `save[]` or `save[filename=out.nc;fields=fuel,altitude,wind]`.

#### ForeFire Format (`.ff`)

Text-based reload format. Contains the full fire front state, including node positions and velocities. Generated with `print[output.ff]`.

---

## 7. Tool Inventory

| Tool | Stage | Script Path | Purpose |
|------|-------|-------------|---------|
| `convert_landscape_to_nc` | s1 | `tools/convert_landscape_to_nc.py` | DEM + fuel map + wind layers to ForeFire NetCDF |
| `convert_fuel_params` | s2 | `tools/convert_fuel_params.py` | Standard fuel models to ForeFire `fuels.csv` |
| `prepare_fire_case` | s3 | `tools/prepare_fire_case.py` | Prepare case metadata and `.ff` run setup, including domain-local ignition coordinates |
| `run_forefire` | s4 | `tools/run_forefire.py` | Execute ForeFire with preflight/postflight checks |
| `parse_forefire_output` | s5 | `tools/parse_forefire_output.py` | Extract fire perimeters from output |
| `validate_spread` | s6 | `tools/validate_spread.py` | Compare simulated vs observed fire spread |

### Shared Utilities

Use KI shared helpers instead of writing raw extraction or conversion code:

```python
from ki_tools_common.load_forcing import load_daily_forcing
```

### Stage Documents

| Stage | Topic | Skill Document |
|-------|-------|----------------|
| s1 | Landscape data preparation | `docs/s1_landscape_data.md` |
| s2 | Fuel parameter configuration | `docs/s2_fuel_parameters.md` |
| s3 | Simulation scripting (`.ff` files) | `docs/s3_simulation_scripting.md` |
| s4 | Execution and runtime | `docs/s4_execution.md` |
| s5 | Output parsing and visualization | `docs/s5_output_parsing.md` |

---

## 8. Unit Conversion Table and Output Units

These are the highest-priority failure modes because they can produce silent errors.

| # | Trap | Internal Unit | Common Source Unit | Conversion | Effect if Wrong |
|---|------|---------------|--------------------|------------|-----------------|
| 1 | Wind speed | m/s | mph, km/h, ft/min | mph * 0.44704 = m/s | ROS off by factor of 2-3x |
| 2 | Fuel density, Rothermel | kg/m^3 to internally lb/ft^3 | kg/m^3 | * 0.06 in model code | Already handled in code |
| 3 | SAV ratio, Rothermel | 1/m to internally 1/ft | 1/m | / 3.28084 in model code | Already handled in code |
| 4 | Fuel depth, Rothermel | m to internally ft | m | * 3.28084 in model code | Already handled in code |
| 5 | Fuel load, Rothermel | kg/m^2 to internally lb/ft^2 | kg/m^2 | * 0.2048 in model code | Already handled in code |
| 6 | Heat of combustion, Rothermel | J/kg to internally BTU/lb | J/kg | / 2326 in model code | Already handled in code |
| 7 | Wind for Andrews2018 | m/s to ft/min in code | m/s input | * 196.85 in model code | Input must be m/s |
| 8 | Fuel load for Andrews2018 | US tons/acre in CSV | t/ac | * 0.224 / 4.882 in code | CSV must be tons/acre |
| 9 | Slope | tan(slope) | degrees | tan(deg) if using Balbi; tan(rise/run) for Rothermel | Wrong model gives wrong interpretation |
| 10 | ROS output | m/s | ft/min internal | * 0.00508 in Rothermel code | Output is always m/s |
| 11 | Coordinates | UTM meters / domain-local meters | lon/lat or absolute projected coordinates | Reproject to UTM, then convert ignition to local frame when using `loc` | Domain mismatch, fire outside bounds, or empty output |
| 12 | Time | seconds from domain start | ISO 8601 | `loadData` accepts ISO time | Wrong reference time gives wrong wind timing |

**Critical**: The Rothermel model internally converts SI inputs to Imperial units, computes ROS in ft/min, then converts back to m/s. The `fuels.csv` values must be in SI: kg/m^3, 1/m, m, kg/m^2, J/kg. The RothermelAndrews2018 model expects Imperial units directly in the fuel table.

### Sign Conventions and Output Units

| Variable | Convention in this model | Common alternative | Impact if wrong |
|----------|--------------------------|--------------------|-----------------|
| `burned_area` | area in ha, derived from arrival-time / perimeter at a given time | m^2 or acres | Magnitude error in headline validation |
| `fire_front_perimeter` | perimeter geometry / front trace | raster mask only | Overlap metrics fail or compare different supports |
| `arrival_time_of_front` | time the front reaches grid cells | binary burned/unburned only | Time-dependent burned area is evaluated at wrong instant |
| `rate_of_spread` | m/s output | ft/min internal | ROS magnitude error |

**Output unit verification checklist**:
- Read output metadata when using NetCDF: print variable attributes before scoring.
- Print first 10 values and check order of magnitude.
- For perimeters, confirm the simulated and observed geometries are in the same projected CRS before rasterizing.
- For area-overlap metrics, use one shared grid for both masks.
- For `burned_area`, keep the final report in ha.

---

## 9. Diagnostic Triplets (Top 5)

The full corpus stays in `diagnostics/triplets.yaml`. On any error, check that YAML first and follow the matched remedy before writing new debugging code.

| # | Error / symptom | Diagnosis | Remedy |
|---|-----------------|-----------|--------|
| 1 | `dt_019`: `loadData` silently loads nothing; "Domain variable not found" or "Skipping variable" appears. | `data.nc` lacks the scalar `domain` variable and/or required per-layer `type` attributes. | Regenerate with `convert_landscape_to_nc`, then verify `domain` plus `altitude`, `fuel`, `windU`, and `windV` type attributes. |
| 2 | `dt_020`: "NetCDF: Numeric conversion not representable"; time origin appears wrong and fire never ignites. | `domain` variable or attributes were written with wrong NetCDF types. | Write `domain` as NC_STRING with float32 attrs and use one time slab. |
| 3 | `dt_022`: ForeFire exits 0 but every `print[]` is an empty GeoJSON FeatureCollection. | `startFire[loc=...]` received projected CRS coordinates instead of domain-local meters. | Use `prepare_fire_case.py` to write `ignition_local_m`, or use `startFire[lonlat=...]`. |
| 4 | `dt_023`: `validate_spread` reports high Sorensen for non-overlapping fires or near zero for visibly overlapping fires. | Simulated and observed perimeters were rasterized on separate bounding boxes and then padded. | Rasterize both perimeters on one shared grid before computing CSI/Sorensen/POD/FAR. |
| 5 | `dt_024`: ForeFire cannot find `data.nc` even though it exists in the passed workdir. | `ForeFireDataDirectory` resolves against the `PWD` environment variable, not only subprocess `cwd`. | Use `run_forefire.py`, which sets `PWD` to the resolved workdir, or pass absolute paths. |

---

## 10. Coupling Interfaces

| Upstream model / data source | Variable exchanged | Unit | Temporal resolution |
|------------------------------|-------------------|------|---------------------|
| CMFD/MSWX/NASA POWER or station forcing | `windU`, `windV` | m/s | case-specific |
| DEM / topography source | `altitude` | m | static |
| Fuel / land-cover source | `fuel` | index | static |
| Fuel model table | `fuels.csv` parameters | model-specific | static |

| Downstream model / consumer | Variable exchanged | Unit | Temporal resolution |
|-----------------------------|-------------------|------|---------------------|
| Validation pipeline | `burned_area` | ha | analysis time |
| Validation pipeline | `fire_front_perimeter` | geometry | analysis time |
| GIS / visualization | KML, GeoJSON fire perimeter | geometry | output print times |
| Coupled atmosphere workflow | fire front / state fields | model-specific | coupled run cadence |

---

## 11. Validated Results

**Source: `docs/validation_convention.yaml`. The convention wins over this body if they ever disagree.**

This KI's validation status is `build_validated`. For scored runs, the headline variable is the dag rank-1 output `burned_area`; use the field bar below rather than intuition. The convention stores null bands for these ForeFire metrics, so each null band is written as `no cited threshold`.

### Headline Output Bar

| Dag variable | Metric | Direction | Very good | Good | Satisfactory | Citation |
|--------------|--------|-----------|-----------|------|--------------|----------|
| `burned_area` | `csi` | maximize | no cited threshold | no cited threshold | no cited threshold | `filippi2014` |
| `burned_area` | `sorensen` | maximize | no cited threshold | no cited threshold | no cited threshold | `filippi2014` |
| `burned_area` | `pbias` | zero_centered | no cited threshold | no cited threshold | no cited threshold | `filippi2014` |

### Other Convention Bars

| Dag variable | Metric | Direction | Very good | Good | Satisfactory | Citation |
|--------------|--------|-----------|-----------|------|--------------|----------|
| `fire_front_perimeter` | `csi` | maximize | no cited threshold | no cited threshold | no cited threshold | `filippi2014` |
| `fire_front_perimeter` | `sorensen` | maximize | no cited threshold | no cited threshold | no cited threshold | `filippi2014` |

### Run Result Tracking

| Component | Source | Status | Notes |
|-----------|--------|--------|-------|
| Model binary/package | Actual ForeFire binary/package | Required | Must pass `python preflight_check.py` before a scored run |
| Landscape input | `convert_landscape_to_nc` | Pipeline | Must include the `domain` variable and layer `type` attributes |
| Fuel table | `convert_fuel_params` | Pipeline | Units depend on propagation model |
| Simulation execution | `run_forefire` | Pipeline | Runs the actual model; no formula substitution |
| Output parsing | `parse_forefire_output` | Pipeline | Extracts fire perimeters / outputs for scoring |
| Validation | `validate_spread` | Pipeline | Compare simulated and observed perimeters on a shared grid |

No achieved numeric validation score is restated here because the sourced convention facts provided for this body update contain bars, directions, and citation keys, not achieved run values.

---

## 12. Parameter Selection by Region

This KI does not provide a region-calibrated parameter table in the SKILL body. Choose physically informed starting points from the model documentation, the selected propagation model, the fuel table source, and the case's observed fire behavior; then document all chosen values in the `.ff` script and case metadata.

| Region / fuel context | Key parameters | Rationale |
|-----------------------|----------------|-----------|
| Any new case | `propagationModel`, `fuelsTableFile`, `spatialIncrement`, `perimeterResolution`, `windReductionFactor`, `propagationSpeedAdjustmentFactor` | These control the ROS formulation, fuel interpretation, front resolution, wind limit behavior, and global speed adjustment |
| Rothermel/Balbi fuel setup | SI fuel parameters in `fuels.csv` | The standard Rothermel path converts SI to Imperial internally before returning ROS in m/s |
| RothermelAndrews2018 setup | Imperial NFFL/FBFM-style fuel parameters in `fuels.csv` | Andrews2018 expects the fuel table directly in Imperial units |
| Validation cases | Analysis time, shared grid resolution, perimeter CRS | `burned_area`, CSI, and Sorensen depend on consistent time and spatial support |

### References

Filippi, J.-B., Baggio, R., Paugam, R., Bosseur, F., Leblanc, A., & Alonso-Pinar, A. (2025).
ForeFire: A Modular, Scriptable C++ Simulation Engine and Library for Wildland-Fire Spread.
Journal of Open Source Software, 10(116), 8680. https://doi.org/10.21105/joss.08680
