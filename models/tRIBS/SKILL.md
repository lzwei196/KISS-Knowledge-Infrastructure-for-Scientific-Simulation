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

# tRIBS Knowledge Infrastructure

| Field | Value |
|-------|-------|
| Model | tRIBS v5.3.1 (TIN-based Real-time Integrated Basin Simulator) |
| Domain | Distributed watershed hydrology |
| Language | C++ (C++17 standard) |
| Build | CMake ≥ 3.20 |
| Binary | `tRIBS` (serial), `tRIBSpar` (parallel, MPI) |
| Repository | https://github.com/tribshms/tRIBS |
| Licence | See LICENSE.txt in repo root |

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/HWSD/SKILL.md` for soil property documentation.
See `data_ki/ObservedQ/SKILL.md` for observed discharge data.


## 1. Overview

tRIBS is a **fully distributed, physically-based hydrological model** that simulates
watershed hydrology using **Triangulated Irregular Networks (TINs)**. It represents
terrain as a Delaunay triangulation with Voronoi tessellation, enabling variable
spatial resolution that adapts to topographic complexity.

**Key processes simulated:**
- Rainfall interception (Gray or Rutter schemes)
- Infiltration (Green-Ampt based)
- Evapotranspiration (Penman-Monteith, Deardorff, Priestley-Taylor, or Pan)
- Unsaturated zone soil moisture dynamics
- Saturated zone / groundwater flow (optional)
- Surface runoff (infiltration excess + saturation excess)
- Kinematic wave routing (hillslope + channel)
- Snow accumulation and melt (energy balance, optional)
- Reservoir operations (optional)

**Spatial representation:** Node-based variables on TIN mesh with Voronoi cells.
**Temporal integration:** Continuous or event-based; adaptive time stepping.

---

## 2. Installation

### Serial build (recommended for single-basin runs)
```bash
cd /path/to/tRIBS/repo
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --target all
# Binary at: build/tRIBS
```

### Parallel build (requires MPI)
```bash
cmake -S . -B build -Dparallel=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build --target all
# Binary at: build/tRIBSpar
```

### Dependencies
| Dependency | Required | Purpose |
|-----------|----------|---------|
| C++17 compiler (g++/clang++) | Yes | Core compilation |
| CMake ≥ 3.20 | Yes | Build system |
| MPI (OpenMPI/MPICH/Intel) | Parallel only | Domain decomposition |

---

## 3. Execution

### CLI invocation
```bash
# Serial
./tRIBS <input_file.in> [options]

# Parallel
mpirun -np <N> ./tRIBSpar <input_file.in> [options]
```

### Command-line options
| Flag | Description |
|------|-------------|
| `-A` | Automatic listing of rainfall files (zero if missing) |
| `-F` | Measured and forecasted rainfall mode |
| `-O` | Stay on after simulation (await user input) |
| `-K` | Check/validate input file |
| `-V [NodeID]` | Verbose mode (optional node ID for detailed output) |
| `-M` | Suppress headers in pixel/hydrograph/voronoi output files |

### Input file format
The `.in` control file uses keyword-value pairs:
```
KEYWORD_NAME
value
```
Lines starting with `#` are comments. All parameters, file paths, and options
are specified through this single file.

---

## 4. Pipeline Stages

| # | Stage | Input | Output | Tool |
|---|-------|-------|--------|------|
| S1 | Mesh preparation | DEM raster, points file | TIN mesh files (.nodes, .edges, .tri, .z) | External GIS / tRIBS mesh options |
| S2 | Soil & land-use tables | HWSD / SSURGO data | Soil reclassification table (.sdt), land-use table (.ldt) | `convert_soil_params.py` |
| S3 | Meteorological forcing | Global reanalysis (CMFD/ERA5/MSWX) | Station files (.sdf) + time-series (.mdf) | `convert_met_forcing.py` |
| S4 | Rainfall preparation | Gauge data or gridded radar | Rain gauge file (.gdf) + rain data (.mdf) | `convert_met_forcing.py` |
| S5 | Control file assembly | All above paths + simulation params | `.in` control file | Manual or template |
| S6 | Execution | `.in` file + binary | Runtime output + log | `run_tribs.py` |
| S7 | Output parsing | Pixel (.pixel), outlet (.qout), MRF files | CSV time series | `parse_tribs_output.py` |
| S8 | Validation | Parsed output + observed data | Metrics (NSE, KGE, PBIAS) + figures | External analysis |

### Stage dependency graph
```
S1 (mesh) ──┐
S2 (soil) ──┤
S3 (met)  ──┼──> S5 (control file) ──> S6 (run) ──> S7 (parse) ──> S8 (validate)
S4 (rain) ──┘
```

---

## 5. Unit Conventions — Critical Trap Table

> **Silent-failure risk:** tRIBS uses a mix of mm, m, m/s, and hours internally.
> Mismatched units produce plausible but wrong results with no runtime error.

| Variable | tRIBS expects | Common source unit | Conversion | Trap ID |
|----------|--------------|-------------------|------------|---------|
| Rainfall rate | mm/hr | mm/day (ERA5) | ÷ 24 | dt_001 |
| Rainfall rate | mm/hr | m/s (CMFD) | × 3.6e6 | dt_001 |
| Temperature | °C | K (reanalysis) | − 273.15 | dt_002 |
| Wind speed | m/s | m/s | None | — |
| Relative humidity | fraction (0–1) | % (0–100) | ÷ 100 | dt_003 |
| Atmospheric pressure | mb (hPa) | Pa (reanalysis) | ÷ 100 | dt_004 |
| Shortwave radiation | W/m² | W/m² | None | — |
| Soil depth to bedrock | mm | m (HWSD) | × 1000 | dt_005 |
| Surface soil depth | mm | m | × 1000 | dt_005 |
| Root zone depth | mm | m | × 1000 | dt_005 |
| Hydraulic conductivity (Ks) | mm/hr | m/s (HWSD) | × 3.6e6 | dt_006 |
| Soil porosity | dimensionless (0–1) | % | ÷ 100 | dt_007 |
| Coordinates (mesh) | meters (UTM) | degrees (lat/lon) | Reproject | dt_008 |
| Elevation | meters (MSL) | feet | × 0.3048 | dt_009 |
| Hillslope/stream velocity | m/s | — | — | — |
| Discharge (output) | m³/s | — | — | — |
| Time step (METSTEP) | hours | minutes | ÷ 60 | dt_010 |
| Latitude/longitude (basin) | decimal degrees | DMS | Convert | — |
| Vapor pressure | mb (hPa) | kPa | × 10 | dt_011 |
| Snow water equivalent | mm | m | × 1000 | dt_012 |

---

## 6. Key Input Files

### 6.1 Control file (.in)
Master configuration with all parameters and file paths. Key sections:

**Mesh parameters:**
- `OPTMESHINPUT` — Mesh source (0=scratch, 1=points, 2=grid, 8=tRIBS files, 9=meshbuilder)
- `INPUTDATAFILE` — Path to mesh data files
- `ARESSION` — Resolution for mesh construction

**Timing:**
- `STARTDATE` — Simulation start (MM/DD/YYYY/HH/MM)
- `ENDDATE` — Simulation end
- `METSTEP` — Met data time step (hours)
- `RAESSION` — Rainfall time step (hours)

**Hydrologic options:**
- `OPTEVAP` — ET method (1=Penman-Monteith, 2=Deardorff, 3=Priestley-Taylor, 4=Pan)
- `OPTINTERC` — Interception (1=Gray, 2=Rutter)
- `OPTSNOW` — Snow module (0=off, 1=on)
- `OPTGROUNDWATER` — Groundwater (0=off, 1=on)
- `GFLUXOPTION` — GW flux option

**Soil/land use:**
- `SOILTABLENAME` — Soil reclassification table (.sdt)
- `LANDTABLENAME` — Land-use table (.ldt)
- `DEPTHTOBEDROCK` — Uniform bedrock depth (mm)
- `SURFACESOILDEPTH` — Surface layer depth (mm, default 100)
- `ROOTZONEDEPTH` — Root zone depth (mm, default 1000)

**Met forcing:**
- `HYDROMETFILE` — Weather station metadata file
- `METDATAOPTION` — Met data source type
- `RAINFILE` — Rainfall data pathname
- `RAINGAUGEFILE` — Rain gauge station data

**Output:**
- `OUTFILENAME` — Base name for all outputs
- `HYDRONODELIST` — Node IDs for pixel output
- `OPTSPATIAL` — Write spatial output (0/1)
- `OPTINTERHYDRO` — Write intermediate hydrographs (0/1)

### 6.2 Soil reclassification table (.sdt)
Tab-delimited table mapping soil class IDs to hydraulic parameters:
```
ID  Ks  ThetaS  ThetaR  PsiB  PoreSize  Conductivity  Residual  ...
1   5.0 0.43    0.04    12.7  0.38      1.0           0.04      ...
```
- Ks: saturated hydraulic conductivity (mm/hr)
- ThetaS: porosity (0–1)
- ThetaR: residual moisture (0–1)
- PsiB: air entry pressure (mm)

### 6.3 Land-use table (.ldt)
Tab-delimited table mapping land-use class IDs to vegetation parameters:
```
ID  a  b1  P  S  K  bv  LAI  ...
1   0.5 0.8 2.0 0.5 0.1 0.5 3.0 ...
```
- LAI: leaf area index (m²/m²)
- Interception and vegetation resistance parameters

### 6.4 Meteorological station file
Header with station metadata followed by time series:
```
nStations
ID Lat Lon Elev Filepath
```

### 6.5 Meteorological data file (.mdf)
Columnar time series per station:
```
Year Month Day Hour PA TD XC US TA TS NR
```
- PA: atmospheric pressure (mb)
- TD: dew point temperature (°C)
- XC: sky cover (tenths, 0–10)
- US: wind speed (m/s)
- TA: air temperature (°C)
- TS: surface temperature (°C)
- NR: net radiation (W/m²) or individual SW/LW components

---

## 7. Key Output Files

### 7.1 Pixel files (.pixel)
Time series at selected nodes. Each row contains ~50+ variables:
- Rainfall, interception, net precipitation
- Soil moisture (saturated, unsaturated), water table depth (Nwt)
- Runoff components (srf, hsrf, esrf, psrf, satsrf, rsrf, sbsrf)
- ET components (EvapWetCanopy, EvapDryCanopy, EvapSoil, EvapoTranspiration)
- Met variables (AirTemp, DewTemp, RelHumid, WindSpeed, radiation)
- Snow variables (liqWEq, iceWEq, snTemperC, cumMelt, cumSnSub)
- Energy fluxes (latent, sensible, ground, precipitation heat)

### 7.2 Outlet discharge (.qout)
Time series of discharge at basin outlet(s):
```
Time(hr)  Q(m³/s)
```

### 7.3 Mean response file (.mrf)
Basin-averaged water balance variables over time.

### 7.4 Spatial snapshots
Voronoi-based spatial output at specified intervals (if OPTSPATIAL=1).

---

## 8. Tools Reference

| Tool | Lines | Purpose |
|------|-------|---------|
| `convert_met_forcing.py` | ~350 | Convert global reanalysis → tRIBS met format with unit conversions |
| `convert_soil_params.py` | ~280 | Convert HWSD/SSURGO → tRIBS soil table (.sdt) |
| `run_tribs.py` | ~200 | Execute tRIBS binary with preflight checks |
| `parse_tribs_output.py` | ~250 | Parse pixel/outlet/MRF output to CSV |

---

## 9. Critical Domain Knowledge

### 9.1 Non-obvious rules that cause silent failures

1. **Rainfall in mm/hr, not mm/day or m/s** — A 24× or 3.6e6× error in rainfall
   produces plausible-looking hydrographs that are simply scaled wrong. No error
   is raised. Always verify peak rainfall values are in mm/hr range for the region.

2. **Soil depths in mm, not m** — HWSD reports bedrock depth in meters. tRIBS
   expects mm. Forgetting the ×1000 conversion gives a 1mm deep soil column,
   causing immediate saturation and unrealistic runoff. No error is raised.

3. **Ks in mm/hr, not m/s** — HWSD hydraulic conductivity in m/s must be converted
   to mm/hr (×3.6e6). Wrong units cause either no infiltration (too low) or all
   infiltration (too high).

4. **Coordinates must be in UTM meters** — Supplying lat/lon in degrees for mesh
   coordinates produces a ~1m × 1m domain. The model runs but results are garbage.

5. **METSTEP is in hours, not minutes** — Setting METSTEP=60 (meaning minutes)
   tells tRIBS to expect data every 60 hours, causing massive gaps and interpolation
   artifacts.

6. **RH as fraction (0–1), not percent** — Providing RH=65 instead of 0.65 causes
   ET to exceed physically possible values. Model may crash or produce NaN.

7. **Atmospheric pressure in mb (hPa)** — Reanalysis data in Pa (×100 larger)
   corrupts psychrometric calculations, leading to wrong ET.

8. **Vapor pressure in mb** — kPa values (10× too small) cause dewpoint errors
   and wrong latent heat calculations.

9. **OPTMESHINPUT must match available files** — Setting option 8 (tRIBS format)
   when only a DEM raster is available causes a cryptic file-not-found crash.

---

## 10. Calibration Parameters

| Parameter | Range | Sensitivity | Affects |
|-----------|-------|-------------|---------|
| Ks (saturated hydraulic conductivity) | 0.1–100 mm/hr | High | Infiltration, runoff partitioning |
| ThetaS (porosity) | 0.3–0.6 | Medium | Storage capacity, soil moisture |
| DEPTHTOBEDROCK | 500–5000 mm | High | Subsurface storage, baseflow |
| HILLSLOPE_KSE (hillslope velocity) | 0.001–0.1 m/s | Medium | Hillslope response time |
| STREAM_KSE (stream velocity) | 0.5–5.0 m/s | High | Channel routing, peak timing |
| Manning's n (channel roughness) | 0.01–0.1 | Medium | Flow velocity, peak attenuation |
| Interception parameters (a, b) | varies | Low-Medium | Water balance partitioning |
| LAI (leaf area index) | 0.5–8.0 m²/m² | Medium | Transpiration, interception |

---

## 11. Simulation Workflow

### Quick start
```bash
# 1. Build
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build

# 2. Prepare inputs (mesh, soil table, met forcing, rain data)
python convert_met_forcing.py --source era5 --input raw/ --output met/
python convert_soil_params.py --source hwsd --input soil/ --output tables/

# 3. Create control file (edit template.in)
cp template.in my_basin.in
# Edit paths, dates, options

# 4. Run
./build/tRIBS my_basin.in

# 5. Parse output
python parse_tribs_output.py --input output/ --output results/
```

---

## 12. Restart Capability

tRIBS supports simulation restart via `RESTARTMODE`:
| Mode | Description |
|------|-------------|
| 0 | New simulation (default) |
| 1 | Continue from current state |
| 2 | Restart from file |
| 3 | Restart from file with preprocessing |

Restart files store the full model state (soil moisture, water table, snow, etc.)
at a checkpoint. Use `RESTARTFILE` to specify the path.

---

## 13. Parallel Execution

The parallel version (`tRIBSpar`) uses MPI for domain decomposition:
- Graph-based partitioning of stream reaches across processors
- Each processor handles its assigned nodes
- Communication via MPI for boundary exchanges
- `OPTMESHINPUT=9` (meshbuilder format) recommended for parallel runs

```bash
mpirun -np 8 ./tRIBSpar my_basin.in
```

---

## 14. Diagnostic Triplets Summary

See `diagnostics/triplets.yaml` for the full 20-entry diagnostic reference covering:
- **Unit conversion traps** (dt_001–dt_012): Rainfall, temperature, pressure, soil depths
- **Configuration errors** (dt_013–dt_015): Mesh options, file paths, time steps
- **Runtime failures** (dt_016–dt_018): NaN propagation, memory, convergence
- **Silent errors** (dt_019–dt_020): Wrong hydrograph shape, water balance closure

---

## 15. File Structure

```
ki/
├── SKILL.md                          # This file — entry point
├── tools/
│   ├── convert_met_forcing.py        # Global reanalysis → tRIBS met format
│   ├── convert_soil_params.py        # HWSD/SSURGO → soil table
│   ├── run_tribs.py                  # Execute binary with validation
│   └── parse_tribs_output.py         # Parse output to CSV
├── docs/
│   ├── s1_mesh_preparation.md        # Mesh/TIN preparation
│   ├── s2_soil_landuse.md            # Soil and land-use tables
│   ├── s3_met_forcing.md             # Meteorological forcing
│   ├── s4_execution.md               # Running the model
│   └── s5_output_analysis.md         # Output parsing and validation
└── diagnostics/
    └── triplets.yaml                 # 20 symptom→diagnosis→remedy entries
```
