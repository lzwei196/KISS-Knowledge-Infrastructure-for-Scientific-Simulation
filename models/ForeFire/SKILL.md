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

# ForeFire v1.0 — Knowledge Infrastructure

**Package**: `wildfire-forefire` v1.0.0
**Model**: ForeFire (C++ wildfire propagation engine)
**Developed by**: CNRS / Universite de Corse Pascal Paoli
**Last updated**: 2026-03-26
**Stats**: 5 tools | 5 skill documents | 18 diagnostic triplets
**Validation status**: `build_validated`

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for weather forcing documentation.
See `data_ki/MTBS/SKILL.md` for fire perimeter observations.


## Overview

This knowledge infrastructure enables autonomous wildfire spread simulation using ForeFire, an open-source C++ wildfire simulation engine. The tools replace manual data preparation with a Python pipeline that handles landscape data ingestion, fuel parameter configuration, simulation execution, and output parsing.

**What ForeFire does**: 2D front-tracking wildfire propagation simulator. Simulates:
- Fire front propagation using multiple Rate of Spread (ROS) models (Rothermel, Balbi2020, RothermelAndrews2018, Farsite, Isotropic)
- Wind-driven and slope-driven fire spread
- Fuel-dependent combustion characteristics
- Fire-atmosphere coupling with MesoNH (optional)
- Multi-front ignition and merging
- Output in KML, GeoJSON, NetCDF, and custom formats

**Key interfaces**:
- `forefire` CLI interpreter (interactive console or script files `.ff`)
- Python bindings (`pyforefire`) for programmatic control
- HTTP server mode for web-based simulation
- C++ library (`libforefireL`) for direct integration

---

## Installation

### Build from Source (Linux)

```bash
# Dependencies
apt-get update
apt install build-essential libnetcdf-c++4-dev cmake -y

# Build
cd /path/to/forefire
mkdir -p build && cd build
cmake ../
make -j$(nproc)

# Binary at: forefire/bin/forefire
# Library at: forefire/lib/libforefireL.so
```

### Python Bindings (optional)

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
|-----------|---------|
| libnetcdf-c++4 | NetCDF I/O for landscape/output data |
| cmake >= 3.10 | Build system |
| C++11 compiler | Core engine compilation |
| MPI (optional) | Parallel computing / MesoNH coupling |
| Python >= 3.8 | Bindings (pybind11, numpy, matplotlib) |

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `FOREFIREHOME` | Root directory of ForeFire installation |
| `NETCDF_HOME` | NetCDF installation path (if not system default) |
| `SRC_MESONH` | MesoNH source path (for coupled simulations) |
| `XYZ` | MesoNH build target identifier |

---

## Pipeline (7 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | (manual) | Define domain, period, ignition points, ROS model |
| 1 | Landscape data | `convert_landscape_to_nc` | Elevation, fuel index, wind to NetCDF |
| 2 | Fuel parameters | `convert_fuel_params` | Fuel properties CSV (Rothermel/Balbi parameters) |
| 3 | Simulation script | (manual/.ff file) | ForeFire script with parameters, data load, ignition |
| 4 | Execution | `run_forefire` | Run the ForeFire binary with preflight checks |
| 5 | Output parsing | `parse_forefire_output` | Extract fire perimeters to CSV/GeoJSON |
| 6 | Validation | `validate_spread` | Compare simulated vs observed perimeters |

### Parallelism

Stages 1 and 2 can run in parallel.
Stage 3 depends on 1 and 2.
Stage 4 depends on 3.
Stages 5 and 6 depend on 4.

---

## Tools Reference

| Tool | Stage | Script Path | Purpose |
|------|-------|-------------|---------|
| `convert_landscape_to_nc` | s1 | `tools/convert_landscape_to_nc.py` | DEM + fuel map to ForeFire NetCDF |
| `convert_fuel_params` | s2 | `tools/convert_fuel_params.py` | Standard fuel models to ForeFire fuels.csv |
| `run_forefire` | s4 | `tools/run_forefire.py` | Execute ForeFire with preflight/postflight |
| `parse_forefire_output` | s5 | `tools/parse_forefire_output.py` | Extract fire perimeters from output |
| `validate_spread` | s6 | `tools/validate_spread.py` | Compare simulated vs observed fire spread |

---

## ForeFire Script Language (.ff files)

ForeFire uses a command-based scripting language. Each command has the form `commandName[param1=val1;param2=val2]`.

### Core Commands

| Command | Purpose | Example |
|---------|---------|---------|
| `setParameter[key=value]` | Set simulation parameter | `setParameter[propagationModel=Rothermel]` |
| `FireDomain[sw=(...);ne=(...);t=T]` | Create simulation domain | `FireDomain[sw=(0,0,0);ne=(50000,50000,0);t=0]` |
| `loadData[file;timestamp]` | Load landscape NetCDF | `loadData[data.nc;2025-02-10T17:35:54Z]` |
| `startFire[loc=(...);t=T]` | Ignite fire at location | `startFire[loc=(35881,28699,0);t=0]` |
| `startFire[lonlat=(...);t=T]` | Ignite fire at lon/lat | `startFire[lonlat=(8.70,41.952,0);t=0]` |
| `trigger[wind;loc=(...);vel=(...)]` | Set wind vector | `trigger[wind;loc=(0,0,0);vel=(10,5,0)]` |
| `step[dt=T]` | Advance simulation by T seconds | `step[dt=3600]` |
| `goTo[t=T]` | Advance to absolute time T | `goTo[t=360]` |
| `include[file.ff]` | Include another script | `include[params.ff]` |
| `print[]` | Print fire front state | `print[output.geojson]` |
| `save[]` | Save state to NetCDF | `save[filename=out.nc]` |
| `listenHTTP[]` | Start HTTP server | `listenHTTP[]` |

### Key Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `propagationModel` | (required) | ROS model: `Rothermel`, `Balbi2020`, `RothermelAndrews2018`, `Farsite`, `Iso` |
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

## Input Formats

### 1. Landscape Data (NetCDF: data.nc)

The primary geospatial input. Contains gridded layers:

| Variable | Dimensions | Units | Description |
|----------|-----------|-------|-------------|
| `altitude` | (t, z, y, x) | m | Digital elevation model |
| `fuel` | (t, z, y, x) | index (0-N) | Fuel type index (references fuels.csv) |
| `windU` | (t, z, y, x) | m/s | U-component (eastward) of wind |
| `windV` | (t, z, y, x) | m/s | V-component (northward) of wind |
| `moisture` | (t, z, y, x) | fraction (0-1) | Fuel moisture content (optional) |
| `temperature` | (t, z, y, x) | K | Air temperature (optional, for Balbi) |

**Coordinate system**: UTM projection (meters). The domain SW/NE corners define the spatial extent.

### 2. Fuel Properties (CSV: fuels.csv)

Semicolon-delimited CSV. Each row is a fuel type indexed by `Index` column.

#### Rothermel/Balbi Fuel Parameters

| Column | Symbol | Units | Description |
|--------|--------|-------|-------------|
| `Index` | - | - | Fuel type index (matches NetCDF fuel layer) |
| `Rhod` | ρ_d | kg/m³ | Dead fuel particle density |
| `Rhol` | ρ_l | kg/m³ | Live fuel particle density |
| `Md` | M_d | fraction | Dead fuel moisture content |
| `Ml` | M_l | fraction | Live fuel moisture content |
| `sd` | s_d | 1/m | Dead fuel surface-area-to-volume ratio |
| `sl` | s_l | 1/m | Live fuel surface-area-to-volume ratio |
| `e` | e | m | Fuel bed depth |
| `Sigmad` | σ_d | kg/m² | Dead fuel load |
| `Sigmal` | σ_l | kg/m² | Live fuel load |
| `stoch` | - | - | Stochiometric coefficient |
| `RhoA` | ρ_a | kg/m³ | Air density |
| `Ta` | T_a | K | Ambient temperature |
| `Tau0` | τ_0 | s | Flame residence time |
| `Deltah` | Δh | J/kg | Heat of vaporization of water |
| `DeltaH` | ΔH | J/kg | Heat of combustion |
| `Cp` | C_p | J/(kg·K) | Fuel specific heat |
| `Cpa` | C_pa | J/(kg·K) | Air specific heat |
| `Ti` | T_i | K | Ignition temperature |
| `X0` | χ_0 | - | Radiant fraction |
| `r00` | r_00 | m | Flame base radiation length |
| `Blai` | LAI | m²/m² | Leaf area index |
| `me` | M_e | fraction | Moisture of extinction |

#### RothermelAndrews2018 Fuel Parameters (NFFL/FBFM style)

| Column | Units | Description |
|--------|-------|-------------|
| `fl1h_tac` | US tons/acre | 1-hour fuel loading |
| `fd_ft` | ft | Fuel bed depth |
| `SAVcar_ftinv` | 1/ft | Characteristic SAV ratio |
| `mdOnDry1h_r` | ratio | 1-hour dead moisture fraction |
| `fuelDens_lbft3` | lb/ft³ | Oven-dry particle density |
| `H_BTUlb` | BTU/lb | Low heat of combustion |
| `Dme_pc` | % | Dead moisture of extinction |
| `totMineral_r` | ratio | Total mineral content |
| `effectMineral_r` | ratio | Effective mineral content |

---

## Unit Conversion Traps

These are the **highest-priority failure modes** — all produce silent errors.

| # | Trap | Internal Unit | Common Source Unit | Conversion | Effect if Wrong |
|---|------|--------------|-------------------|------------|-----------------|
| 1 | Wind speed | m/s | mph, km/h, ft/min | mph × 0.44704 = m/s | ROS off by factor of 2-3x |
| 2 | Fuel density (Rothermel) | kg/m³ → internally lb/ft³ | kg/m³ | × 0.06 in model code | Already handled in code |
| 3 | SAV ratio (Rothermel) | 1/m → internally 1/ft | 1/m | ÷ 3.28084 in model code | Already handled in code |
| 4 | Fuel depth (Rothermel) | m → internally ft | m | × 3.28084 in model code | Already handled in code |
| 5 | Fuel load (Rothermel) | kg/m² → internally lb/ft² | kg/m² | × 0.2048 in model code | Already handled in code |
| 6 | Heat of combustion (Rothermel) | J/kg → internally BTU/lb | J/kg | ÷ 2326 in model code | Already handled in code |
| 7 | Wind for Andrews2018 | m/s → ft/min in code | m/s (input) | × 196.85 in model code | Input MUST be m/s |
| 8 | Fuel load for Andrews2018 | US tons/acre in CSV | t/ac | × 0.224 ÷ 4.882 in code | CSV must be tons/acre |
| 9 | Slope | tan(slope) | degrees | tan(deg) if using Balbi; tan(rise/run) for Rothermel | Wrong model → wrong interpretation |
| 10 | ROS output | m/s | ft/min internal | × 0.00508 in Rothermel code | Output is always m/s |
| 11 | Coordinates | UTM meters | lon/lat | Must project to UTM | Domain mismatch, fire outside bounds |
| 12 | Time | seconds from domain start | ISO 8601 | `loadData` accepts ISO time | Wrong reference time = wrong wind timing |

**Critical**: The Rothermel model internally converts SI inputs to Imperial (US customary) units, computes ROS in ft/min, then converts back to m/s. The fuels.csv values must be in SI (kg/m³, 1/m, m, kg/m², J/kg). The RothermelAndrews2018 model expects Imperial units directly in the fuel table.

---

## Output Formats

### KML (Google Earth)

Fire front perimeters as polygons. Generated with `dumpMode=kml` and `print[output.kml]`.

### GeoJSON

Fire front geometries. Generated with `dumpMode=geojson` and `print[output.geojson]`.

### NetCDF (ForeFire.0.nc)

State output including:
- Burning map (arrival time at each grid cell)
- Wind field snapshots
- Fuel and altitude data

Generated with `save[]` or `save[filename=out.nc;fields=fuel,altitude,wind]`.

### ForeFire Format (.ff)

Text-based reload format. Contains the full fire front state (node positions, velocities). Generated with `print[output.ff]`.

---

## Propagation Models

### Rothermel (1972)

Classic surface fire spread model. Uses dead fuel parameters from fuels.csv.

**Key equations** (simplified):
- Reaction intensity: I_R = Γ' × w_n × ΔH × η_M × η_s
- ROS: R = (I_R × ξ) / (ρ_b × ε × Q_ig) × (1 + φ_w + φ_s)

Where φ_w is wind factor, φ_s is slope factor.

**Wind limit**: When `windReductionFactor < 1.0`, applies Andrews/Cruz/Rothermel (2013) wind limit: U_f = 96.81 × I_R^(1/3). Otherwise U_f = 0.9 × I_R.

### Balbi2020

Physics-based model from Universite de Corse. Uses iterative solver (max 40 iterations).

**Key features**:
- Accounts for radiative and convective heat transfer
- Uses flame angle, flame height, and vertical velocity
- Requires temperature and moisture layers in addition to fuel
- Convergence tolerance: 0.01 m/s

### RothermelAndrews2018

Updated Rothermel formulation per Andrews (2018), RMRS-GTR-371.
Uses NFFL/FBFM-style fuel parameters directly in Imperial units.

### Farsite

FARSITE-compatible propagation model. Uses standard NFFL fuel models with moisture classes (1-hr, 10-hr, 100-hr, live herbaceous, live woody).

### Isotropic (Iso)

Constant speed in all directions. Useful for testing.

---

## Skill Knowledge Summary

| Stage | Topic | Skill Document |
|-------|-------|---------------|
| s1 | Landscape data preparation | `docs/s1_landscape_data.md` |
| s2 | Fuel parameter configuration | `docs/s2_fuel_parameters.md` |
| s3 | Simulation scripting (.ff files) | `docs/s3_simulation_scripting.md` |
| s4 | Execution and runtime | `docs/s4_execution.md` |
| s5 | Output parsing and visualization | `docs/s5_output_parsing.md` |

---

## Citation

Filippi, J.-B., Baggio, R., Paugam, R., Bosseur, F., Leblanc, A., & Alonso-Pinar, A. (2025).
ForeFire: A Modular, Scriptable C++ Simulation Engine and Library for Wildland-Fire Spread.
Journal of Open Source Software, 10(116), 8680. https://doi.org/10.21105/joss.08680
