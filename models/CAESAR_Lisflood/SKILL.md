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
