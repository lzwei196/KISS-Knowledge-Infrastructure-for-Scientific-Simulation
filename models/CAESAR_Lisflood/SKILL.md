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
| on ANY error, before debugging | `diagnostics/triplets.yaml` (20 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (21 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 8 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/convert_dem_to_caesar.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_dem_to_caesar.py --help` |
| `tools/convert_rainfall_to_caesar.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_rainfall_to_caesar.py --help` |
| `tools/convert_soil_to_caesar.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_soil_to_caesar.py --help` |
| `tools/parse_caesar_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_caesar_output.py --help` |
| `tools/run_caesar.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_caesar.py --help` |

*5 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# HAIL-CAESAR (CAESAR-Lisflood) -- Knowledge Infrastructure

**Package**: `hydrocraft-caesar-lisflood` v1.0.0
**Model**: HAIL-CAESAR v1.0 (High-performance Architecture Independent LISFLOOD-CAESAR)
**Domain**: Geomorphology / Flood inundation / Landscape evolution
**Language**: C++ (compiled with g++, OpenMP parallelisation)
**Source**: https://github.com/dvalters/HAIL-CAESAR
**Created by**: Hydrocraft dissection pipeline
**Last updated**: 2026-03-26
**Stats**: 4 tools | 5 skill documents | 15+ diagnostic triplets
**Validation status**: `test_validated` (Boscastle 50m, 72hr flood simulation)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for meteorological forcing documentation.
See `data_ki/USGS_Sediment/SKILL.md` for suspended sediment observations.


## Overview

This knowledge infrastructure enables simulation of catchment-scale hydrodynamics,
flood inundation, sediment transport, and landscape evolution using the HAIL-CAESAR model.
HAIL-CAESAR is a C++ port of the CAESAR-Lisflood model (Coulthard et al., 2013), a
cellular automaton model that uses the LISFLOOD-FP flow routing algorithm (Bates et al., 2010).

**What HAIL-CAESAR does**: 2.5D cellular automaton landscape evolution model. Simulates:
- Hydrodynamic flow routing (LISFLOOD-FP shallow water equations, non-steady state)
- TOPMODEL-based rainfall-runoff (semi-distributed or fully-distributed)
- Sediment transport (Wilcock-Crowe or Einstein-Brown transport laws)
- Multi-fraction grain size tracking (9 fractions, 0.065mm to 128mm)
- Hillslope processes (creep, landsliding, slope failure)
- Lateral channel erosion (experimental)
- Vegetation growth effects on erosion
- Groundwater flow (basic or SLiM model)
- OpenMP shared-memory parallelisation

**Key difference from other HydroCraft models**: HAIL-CAESAR uses explicit non-steady-state
flow routing rather than drainage-area-based steady-state approximations. This makes it
suitable for both flood inundation modelling and long-term landscape evolution (hours to
thousands of years).

---

## Installation

### Compilation

```bash
cd /path/to/HAIL-CAESAR
make                      # Produces bin/HAIL-CAESAR.exe
```

**Compiler**: g++ with C++11 and OpenMP support
**Flags**: `-std=c++11 -fopenmp -DOMP_COMPILE_FOR_PARALLEL`
**Dependencies**: None beyond standard C++ library and OpenMP runtime

### Binary Location

```
bin/HAIL-CAESAR.exe       # Main executable
```

### Test Example

```
test/input_data/boscastle/boscastle_input_data/
  boscastle_square_50m.asc                    # 50m DEM (120x60 cells)
  boscastle_72hr_rain_u.txt                   # 72hr rainfall timeseries
  boscastle_test_72hr_50m_u.params            # Parameter file (hydro-only)
  boscastle_test_72hr_50m_u_erosion.params    # Parameter file (with erosion)
```

**Run** — from `<repo>/test`, exactly as the shipped `test/run_tests.sh` does.
The paths inside the shipped `.params` are relative to `<repo>/test`, NOT to the
repo root and NOT to the data dir; running it from the repo root fails with
"No terrain DEM found" (triplet T003 / T022):

```bash
cd <repo>/test
mkdir -p ./results/boscastle50m_72_u/
../bin/HAIL-CAESAR.exe ./input_data/boscastle/boscastle_input_data/ boscastle_test_72hr_50m_u.params
```

Equivalently through the KI tool:

```bash
python tools/run_caesar.py --source_dir <repo> --cwd <repo>/test \
    --data_dir <repo>/test/input_data/boscastle/boscastle_input_data/ \
    --param_file boscastle_test_72hr_50m_u.params --skip_compile --num_threads 8
```

**Binary argument 1 locates only the PARAMETER file.** Every *data* file is built
as `read_path + "/" + fname` and resolved against the process working directory
(`src/main.cpp`), so a relative `read_path` depends on where you `cd`. In your own
runs use ABSOLUTE `read_path` / `write_path` and the ambiguity disappears.

---

## Pipeline (7 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 1 | DEM preparation | `convert_dem_to_caesar` | Prepare ASCII grid DEM with outlet at edge |
| 2 | Rainfall forcing | `convert_rainfall_to_caesar` | Convert precipitation data to mm/hr text timeseries |
| 3 | Parameter setup | (manual / template) | Create .params file with all model parameters |
| 4 | Grain size data | `convert_soil_to_caesar` | Optional: prepare grain size distribution file |
| 5 | Execution | `run_caesar` | Compile and run HAIL-CAESAR binary |
| 6 | Output parsing | `parse_caesar_output` | Extract timeseries (hydrograph, sedigraph) and rasters |
| 7 | Validation | (analysis scripts) | Compare against observations, compute metrics |

---

## Input Files

### 1. DEM (required)
- **Format**: ESRI ASCII Grid (.asc)
- **Header**: ncols, nrows, xllcorner, yllcorner, cellsize, NODATA_value
- **Units**: Elevation in **metres** above datum
- **Critical requirement**: Outlet must touch DEM edge (no NODATA between outlet and edge)
- **Example**: `boscastle_square_50m.asc` (120 cols x 60 rows, 50m resolution)

### 2. Rainfall timeseries (required)
- **Format**: Plain text, headerless, space-delimited
- **Units**: mm/hr (instantaneous rate, regardless of timestep)
- **Layout**: One row per timestep. If spatially variable: N columns matching N hydroindex zones
- **Timestep**: Set by `rain_data_time_step` parameter (in minutes)
- **Example**: `boscastle_72hr_rain_u.txt` (864 rows at 5-min intervals for 72 hours)

### 3. Parameter file (required)
- **Format**: Plain text, key-value pairs separated by `:`
- **Comments**: Lines starting with `#`
- **Extension**: Conventionally `.params` (any name accepted)
- **Example**: `boscastle_test_72hr_50m_u.params`

### 4. Hydroindex (optional, for spatially variable rainfall)
- **Format**: ESRI ASCII Grid (.asc), same extent as DEM
- **Values**: Integer zone IDs (1, 2, 3, ...) matching rainfall columns

### 5. Grain data file (optional, for pre-set grain distributions)
- **Format**: Special text format with index, x, y, and grain fractions

### 6. Bedrock DEM (optional)
- **Format**: ESRI ASCII Grid (.asc), same extent as DEM
- **Requirement**: Elevations must be lower than surface DEM

---

## Output Files

### 1. Timeseries file (e.g., `catchment.dat`)
A space-delimited text file with 14 columns:

| Col | Variable | Units | Description |
|-----|----------|-------|-------------|
| 1 | Time index | - | Row number at each save interval (multiply by `timeseries_save_interval` for minutes) |
| 2 | Actual discharge | m3/s (cumecs) | Instantaneous water discharge at outlet(s) |
| 3 | Expected discharge | m3/s (cumecs) | TOPMODEL-estimated discharge |
| 4 | Sand output | m3 | (Legacy column, usually zero) |
| 5 | Total sediment Q | m3 | Total sediment discharge for interval |
| 6-14 | Grain fractions 1-9 | m3 | Sediment discharge per grain size fraction |

**Save interval**: Set by `timeseries_save_interval` (model minutes)

### 2. Raster outputs (optional, set in params)
Written at intervals set by `raster_output_interval` (model minutes):
- **Water depths**: `WaterDepths_NNNN.asc` (metres)
- **Elevations**: `Elevations_NNNN.asc` (metres)
- **Grain sizes**: `Grainz_NNNN.asc`
- **Elevation difference**: `ElevationDiff_NNNN.asc` (metres)

---

## 6. Output Description (from `dag.yaml`)

The dag is the output contract. If this section disagrees with `dag.yaml`, the dag wins.

**Headline output** (the dag's `validation_rank: 1` variable):

> `Actual discharge (Qw)` -- Instantaneous mean water discharge summed over the grid-edge outlet cell(s) (`m3/s`)

| Output variable (dag `var`) | Rank | Emitted in | Unit | Description |
|-----------------------------|------|------------|------|-------------|
| `Actual discharge (Qw)` | 1 | `catchment.dat` column 2 | `m3/s` | Instantaneous mean water discharge summed over the grid-edge outlet cell(s) |
| `Total sediment discharge (Qs) and per-fraction sediment (Qg 1-9)` | 2 | `catchment.dat` columns 5-14 | `m3 per save interval (interval total, NOT a rate)` | Sediment volume leaving the outlet per save interval, total and per grain fraction |
| `Water depth raster` | 3 | `WaterDepths_NNNN.asc` | `m` | Per-cell flow depth from the shallow-water routing |
| `Flow velocity raster` | 4 | `flowvel_NNNN.asc` | `m/s` | Per-cell depth-averaged flow speed from the shallow-water routing |
| `Surface elevation raster` | 5 | `Elevations_NNNN.asc` | `m` | Current evolving surface DEM |
| `Elevation difference raster` | 6 | `ElevationDiff_NNNN.asc` | `m` | Net sediment erosion/deposition thickness (elev - initial elev) |
| `Surface grain size (D50) raster` | 7 | `Grainz_NNNN.asc` | `m` | Median surface-layer grain size per cell |

**Validation implication**: an agent reading only this file should judge the model first by
`Actual discharge (Qw)`, not by rasters or sediment outputs unless the task explicitly asks
for those variables.

---

## Key Parameters and Units

### Numerical Control
| Parameter | Units | Default | Description |
|-----------|-------|---------|-------------|
| `min_time_step` | seconds | 0 | Minimum internal timestep |
| `max_time_step` | seconds | 3600 | Maximum internal timestep |
| `max_run_duration` | hours | - | Simulation duration (set to T-1, e.g., 71 for 72hr) |
| `run_time_start` | hours | 0 | Simulation start time |

### Hydrology
| Parameter | Units | Default | Description |
|-----------|-------|---------|-------------|
| `topmodel_m_value` | m | 0.005 | TOPMODEL m parameter (0.005=flashy, 0.02=slow) |
| `mannings_n` | s/m^(1/3) | 0.04 | Manning's roughness coefficient |
| `courant_number` | - | 0.7 | CFL stability (0.3-0.7; lower for finer DEMs) |
| `froude_num_limit` | - | 0.8 | Froude number limit (subcritical flow) |
| `hflow_threshold` | m | 0.00001 | Min gradient for flow routing |
| `slope_on_edge_cell` | - | 0.001 | Slope at DEM edge (approx channel slope near outlet) |
| `rain_data_time_step` | minutes | 60 | Timestep of rainfall input file |
| `min_q_for_depth_calc` | m3/s | 0.01 | Min Q for depth calculation (~10% of cellsize) |
| `max_q_for_depth_calc` | m3/s | 1000 | Max Q threshold |

### Sediment
| Parameter | Units | Default | Description |
|-----------|-------|---------|-------------|
| `transport_law` | - | wilcock | `wilcock` or `einstein` |
| `max_tau_velocity` | m/s | 5 | Max velocity for sediment transport |
| `active_layer_thickness` | m | 0.2 | Surface layer thickness (>= 4x erode_limit) |
| `erode_limit` | m | 0.05 | Max erosion/deposition per cell per step |
| `chann_lateral_erosion` | - | 20 | Prevents overdeepening feedback |
| `water_depth_erosion_threshold` | m | 0.01 | Min water depth for erosion |

### Hillslope
| Parameter | Units | Default | Description |
|-----------|-------|---------|-------------|
| `creep_rate` | m/yr | 0.0025 | Soil creep rate |
| `slope_failure_thresh` | degrees | 45 | Critical angle for landslide |

---

## 8. Unit Conversion Table

Use this table before preparing model inputs or comparing parsed outputs. Exact I/O shapes
remain in `docs/format_spec.yaml`; this table records the unit conversions that repeatedly
cause silent errors in this KI.

| Variable | Source unit / representation | Model or comparison unit | Conversion | Type |
|----------|------------------------------|--------------------------|------------|------|
| Rainfall rate | `mm/day` | `mm/hr` | divide by `24` | multiplicative |
| Rainfall rate | `m/s` | `mm/hr` | multiply by `3.6e6` | multiplicative |
| Rainfall rate | `kg/m2/s` | `mm/hr` | multiply by `3600` | multiplicative |
| Rainfall timestep | seconds | minutes | divide by `60` | multiplicative |
| Rainfall timestep | hours | minutes | multiply by `60` | multiplicative |
| DEM elevation | feet | metres | multiply by `0.3048` | multiplicative |
| DEM elevation | centimetres | metres | divide by `100` | multiplicative |
| DEM cellsize | degrees (WGS84) | metres | reproject to UTM/local CRS first | spatial transform |
| TOPMODEL m | millimetres | metres | divide by `1000` | multiplicative |
| Active layer thickness | centimetres | metres | divide by `100` | multiplicative |
| Erosion limit | centimetres | metres | divide by `100` | multiplicative |
| Time index in `catchment.dat` | interval count | minutes | multiply by `timeseries_save_interval` | multiplicative |
| Sediment output | `m3 per save interval` | `m3/s` for flux comparison | divide by interval seconds (`timeseries_save_interval * 60`) | multiplicative |
| Water discharge output | `m3/s` | `m3/s` | no conversion | none |

---

## Unit Trap Table

These are the most common unit conversion errors when preparing inputs:

| Variable | Model expects | Common source | Trap |
|----------|--------------|---------------|------|
| Rainfall rate | mm/hr | mm/day, m/s, kg/m2/s | Divide daily by 24; multiply m/s by 3.6e6; multiply kg/m2/s by 3600 |
| DEM elevation | metres | feet, cm | Multiply feet by 0.3048; divide cm by 100 |
| DEM cellsize | metres | degrees (WGS84) | Must reproject to UTM/local CRS first |
| Manning's n | s/m^(1/3) | - | Typical: 0.03-0.06 for channels, 0.1+ for floodplains |
| Run duration | hours (T-1) | hours (T) | Set to desired_hours - 1 (model quirk) |
| Rain timestep | minutes | seconds, hours | Convert: seconds/60 or hours*60 |
| TOPMODEL m | metres | mm | Divide mm by 1000 |
| Active layer | metres | cm | Divide cm by 100; must be >= 4x erode_limit |
| Courant number | dimensionless | - | 0.3 for <2m DEMs, 0.7 for 20-50m DEMs |
| Sediment output | m3 (total in interval) | - | NOT a rate; divide by interval for m3/s |
| Water discharge | m3/s (instantaneous) | - | Already a rate, no conversion needed |
| Time index in output | interval count | minutes | Multiply by `timeseries_save_interval` for minutes |
| NODATA | -9999 | -9999.9, NaN | Must match DEM header exactly |
| Erosion limit | metres | cm | Divide cm by 100; ~0.01 for <=10m DEMs |

---

## Execution

### Command Line

```bash
./bin/HAIL-CAESAR.exe /path/to/input_files/ parameter_file.params
```

- **Argument 1**: Path to directory containing DEM, rainfall file, and other inputs
- **Argument 2**: Name of the parameter file (must be in the path above)
- **Note**: The path in the parameter file (`read_path`) should match or be relative to where the binary is run

### Parallel Execution

```bash
export OMP_NUM_THREADS=4    # Set to number of available cores
./bin/HAIL-CAESAR.exe /path/to/data/ params.params
```

### Typical Runtimes
- Boscastle 50m, 72hr, hydro-only: ~5 min (single core), ~2 min (4 cores)
- Boscastle 5m, 48hr, with erosion: ~2-3 hours (single core)
- Runtime scales primarily with number of grid cells

---

## Tool Reference

| Tool | Purpose | Input | Output |
|------|---------|-------|--------|
| `convert_rainfall_to_caesar.py` | Convert global forcing (CMFD/ERA5/CSV) to HAIL-CAESAR rainfall format | NetCDF/CSV with precip data | Headerless text file (mm/hr) |
| `convert_soil_to_caesar.py` | Convert HWSD/soil data to grain size fractions | HWSD soil type raster | Grain data text file |
| `run_caesar.py` | Build and execute HAIL-CAESAR | Source dir, params file | Binary + model outputs |
| `parse_caesar_output.py` | Extract timeseries and rasters to CSV/analysis format | Model output files | CSV with discharge/sediment, raster summaries |

---

## 11. Validated Results

### Test Basin: Boscastle shipped example

| Property | Value |
|----------|-------|
| Scenario | Boscastle 50m, 72hr flood simulation |
| Status in this SKILL body | body campaign pending |
| Headline judged variable | `Actual discharge (Qw)` |
| Headline output description | Instantaneous mean water discharge summed over the grid-edge outlet cell(s) |
| Headline output unit | `m3/s` |

### Performance Metrics -- convention bars from `docs/validation_convention.yaml`

A metric value without the field's pass-band is not a verdict. Use these bars exactly;
do not replace them with remembered thresholds.

| Dag variable | Metric | Direction | Bar (convention, cited) |
|--------------|--------|-----------|--------------------------|
| `Actual discharge (Qw)` | `nse` | maximize | satisfactory >= `0.5` (`hess2015`); good >= `0.65` (`hess2015`); very_good >= `0.75` (`hess2015`) |
| `Actual discharge (Qw)` | `pbias` | zero_centered | very_good <= `10` (`hess2015`); good <= `15` (`hess2015`); satisfactory <= `25` (`hess2015`) |
| `Total sediment discharge (Qs) and per-fraction sediment (Qg 1-9)` | `pbias` | zero_centered | very_good <= `15` (`hess2015`); good <= `30` (`hess2015`); satisfactory <= `55` (`hess2015`) |

**Pending result note**: this SKILL body does not record achieved calibration,
validation, or full-period metric values for the body campaign. Until those values
exist, report the campaign as pending rather than inferring a pass/fail verdict.

### Data Replacement Tracking

| Component | Source | Status | Notes |
|-----------|--------|--------|-------|
| Forcing | Pipeline / shipped Boscastle rainfall example | Pending | Run `python preflight_check.py` before any model execution. |
| Soil / grain size | Pipeline or default model grain fractions | Pending | Full morphodynamic runs require grain-size checks. |
| DEM | Pipeline / shipped Boscastle DEM example | Pending | Outlet must touch the DEM edge. |
| Initial conditions | Model defaults plus provided inputs | Pending | Do not substitute simplified formulas for model state. |
| Observations for `Actual discharge (Qw)` | Gauge-compatible point time series or peak snapshot | Pending | Compare against the dag's rank-1 output first. |

---

## Key References

1. Coulthard, T.J., Neal, J.C., Bates, P.D., Ramirez, J., de Almeida, G.A.M., Hancock, G.R. (2013). Integrating the LISFLOOD-FP 2D hydrodynamic model with the CAESAR model: implications for modelling landscape evolution. Earth Surface Processes and Landforms, 38(15), 1897-1906.

2. Bates, P.D., Horritt, M.S., Fewtrell, T.J. (2010). A simple inertial formulation of the shallow water equations for efficient two-dimensional flood inundation modelling. Journal of Hydrology, 387(1-2), 33-45.

3. Wilcock, P.R. and Crowe, J.C. (2003). Surface-based transport model for mixed-size sediment. Journal of Hydraulic Engineering, 129(2), 120-128.

4. Beven, K.J. and Kirkby, M.J. (1979). A physically based, variable contributing area model of basin hydrology. Hydrological Sciences Bulletin, 24(1), 43-69.

---

## Troubleshooting Quick Reference

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Water pools, no outlet | DEM outlet doesn't touch edge | Rotate DEM or extend channel to edge |
| Extremely slow run | Courant number too low, or fine DEM | Increase courant_number (max 0.7) |
| Checkerboard water pattern | Froude limit too high | Reduce `froude_num_limit` to 0.7 |
| Immediate crash, "No terrain DEM found" | Wrong `read_path` or `read_fname` | Check paths in param file (no extension in read_fname) |
| All zeros in output | `max_run_duration` too short | Set to desired_hours - 1 |
| Numerical instability / NaN | Timestep too large or courant too high | Reduce `max_time_step` and `courant_number` |
| No erosion output | `hydro_model_only: yes` | Set to `no` for erosion simulations |
| OpenMP reports 1 thread | `OMP_NUM_THREADS` not set | `export OMP_NUM_THREADS=N` |
