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

# DHSVM Knowledge Infrastructure

- **Package**: dhsvm-ki v1.0.0
- **Model**: DHSVM 3.2 (Distributed Hydrology-Soil-Vegetation Model)
- **Domain**: Distributed watershed hydrology
- **Language**: C (28,000+ lines)
- **Build**: CMake
- **Tools**: 5 validated Python scripts
- **Diagnostics**: 18 triplets across 6 failure domains
- **Validation**: Chiwawa watershed test case
- **Created**: 2026-03-25

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/HWSD/SKILL.md` for soil property documentation.
See `data_ki/ObservedQ/SKILL.md` for observed discharge data.


## 1. Overview

DHSVM (Distributed Hydrology-Soil-Vegetation Model) is a physically-based, spatially
distributed hydrological model developed at the University of Washington and maintained
by PNNL. It simulates the effects of topography, soil type, vegetation, and climate on
the water balance of mountainous watersheds at high spatial resolution (typically
30-150 m grid cells).

**Key capabilities:**
- Full energy and water balance at each grid cell
- Explicit snow accumulation and melt (energy balance approach)
- Multi-layer soil moisture accounting (typically 3 layers)
- Overstory/understory vegetation representation with monthly LAI
- Channel network routing (Muskingum-Cunge)
- Subsurface lateral flow driven by topography
- Overland flow routing (kinematic wave)
- Stream temperature modeling (via RBM coupling)
- Canopy gap and snow sliding algorithms (v3.2)

**Typical applications:**
- Climate change impact on mountain hydrology
- Forest management effects on streamflow
- Snow dynamics in complex terrain
- Flood prediction in steep watersheds
- Water resource assessment

---

## 2. Installation

### 2.1 Dependencies

**System packages:**
- C compiler (gcc >= 4.8)
- CMake >= 3.0
- flex, bison (for tableio lexer)
- libnetcdf-dev (optional, for NetCDF I/O)
- libx11-dev (optional, for X11 graphics)

**Python packages (for KI tools):**
- numpy, pandas, matplotlib
- pyyaml, netCDF4 (optional)

### 2.2 Build from Source

```bash
cd /path/to/DHSVM/source/repo
mkdir build && cd build
cmake -DCMAKE_BUILD_TYPE=Release \
      -DDHSVM_USE_NETCDF=OFF \
      -DDHSVM_USE_X11=OFF ..
cmake --build . -j$(nproc)
```

The binary is produced at `build/DHSVM/sourcecode/DHSVM`.

### 2.3 CMake Options

| Option | Default | Description |
|--------|---------|-------------|
| `DHSVM_USE_NETCDF` | OFF | Enable NetCDF I/O |
| `DHSVM_USE_X11` | OFF | Enable X11 real-time display |
| `DHSVM_USE_RBM` | OFF | Enable stream temperature (RBM) |
| `DHSVM_SNOW_ONLY` | OFF | Snow-only mode |
| `DHSVM_D8` | ON | 8-direction flow routing (vs D4) |

### 2.4 Quick Test

```bash
cd /path/to/TestCase/Chiwawa
../../build/DHSVM/sourcecode/DHSVM INPUT.Chiwawa.Baseline
```

---

## 3. Pipeline Stages

| # | Stage | Tool | Description |
|---|-------|------|-------------|
| 0 | Configuration | — | Define basin extent, time period, options |
| 1 | Terrain Prep | — | Generate DEM, mask, slope/aspect binary maps |
| 2 | Met Forcing | `convert_forcing.py` | Convert global met data to DHSVM ASCII format |
| 3 | Soil Params | `convert_soil_params.py` | Build soil type map and parameter table |
| 4 | Veg Params | — | Build vegetation type map and parameter table |
| 5 | Stream Network | — | Create stream map, network, and class files |
| 6 | Config Assembly | — | Write the DHSVM input configuration file |
| 7 | Execution | `run_dhsvm.py` | Run the DHSVM binary |
| 8 | Output Analysis | `parse_output.py` | Extract results to CSV, compute metrics |
| 9 | Validation | — | Compare to observations, plot hydrographs |

### Parallelism

Stages 2, 3, 4, and 5 can run in parallel once Stage 1 (terrain) is complete.
Stage 6 depends on all of 2-5. Stages 7-9 are sequential.

---

## 4. Tools Reference

| Tool | Stage | Script | Lines | Purpose |
|------|-------|--------|-------|---------|
| Forcing Converter | s2 | `tools/convert_forcing.py` | ~280 | Convert global gridded met data to DHSVM format |
| Soil Converter | s3 | `tools/convert_soil_params.py` | ~220 | Convert HWSD/STATSGO soil data to DHSVM tables |
| Execution Wrapper | s7 | `tools/run_dhsvm.py` | ~180 | Run DHSVM binary with validation |
| Output Parser | s8 | `tools/parse_output.py` | ~250 | Parse Aggregated.Values and Stream.Flow to CSV |
| Config Generator | s6 | `tools/generate_config.py` | ~300 | Generate DHSVM input configuration file |

---

## 5. Unit Trap Table

These are the most common unit conversion errors. Each links to a diagnostic triplet.

| Variable | DHSVM Expects | Common Source | Conversion | Triplet |
|----------|---------------|---------------|------------|---------|
| Precipitation | m/timestep | mm/hr (CMFD) | `mm/hr * dt_hr / 1000` | dt_001 |
| Temperature | deg C | K (ERA5) | `K - 273.15` | dt_002 |
| Relative Humidity | % (0-100) | fraction (0-1) | `frac * 100` | dt_003 |
| Wind Speed | m/s | km/hr | `km/hr / 3.6` | dt_004 |
| Shortwave Radiation | W/m2 | MJ/m2/day | `MJ * 1e6 / 86400` | dt_005 |
| Longwave Radiation | W/m2 | W/m2 | no conversion | — |
| Soil Depth | m | cm | `cm / 100` | dt_006 |
| Hydraulic Conductivity | m/s | mm/hr | `mm/hr / 3.6e6` | dt_007 |
| Porosity | fraction (0-1) | % | `% / 100` | dt_008 |
| Elevation (DEM) | m | feet | `ft * 0.3048` | dt_009 |
| Slope | radians | degrees | `deg * pi/180` | dt_010 |
| Lapse Rate | C/m | C/km | `C/km / 1000` | dt_011 |

---

## 6. Critical Domain Knowledge

### 6.1 Precipitation must be in meters per timestep (dt_001)

DHSVM reads precipitation as **meters per timestep** (e.g., meters per 3 hours).
Global datasets like CMFD provide mm/hr or mm/3hr. If you feed mm directly, rainfall
is 1000x too high. The model won't crash — it will simply produce absurd runoff.

**Conversion:** `precip_m = precip_mm / 1000.0 * (dt_hours / source_hours)`

### 6.2 Temperature must be Celsius (dt_002)

DHSVM uses Celsius for all temperature variables. ERA5 and many reanalysis products
provide Kelvin. Feeding Kelvin directly produces no error but results in no snow
(temperatures ~273 C) and extreme evapotranspiration.

**Conversion:** `T_C = T_K - 273.15`

### 6.3 Relative Humidity is percent, not fraction (dt_003)

DHSVM expects RH as 0-100%. Some datasets provide 0-1 fraction. If fraction is used,
RH appears near-zero, vapor pressure deficit explodes, and ET is unrealistically high.

**Conversion:** `RH_pct = RH_frac * 100.0`

### 6.4 Met file naming must match grid coordinates exactly (dt_012)

Met forcing files are named `data_<lat>_<lon>` with exactly `GRID_DECIMAL` decimal
places. A mismatch of even one decimal place causes DHSVM to fail to find the file.
Example: if GRID_DECIMAL=5, the file must be `data_47.21875_-120.21875`.

### 6.5 Binary maps must match grid dimensions exactly (dt_013)

DEM, mask, soil, and vegetation binary files must contain exactly `nrows * ncols`
values as 32-bit integers or floats. A single extra or missing byte causes all
subsequent pixels to be shifted, producing garbage results with no error message.

### 6.6 Soil layer depths must be monotonically increasing (dt_014)

In the configuration file, soil layer depths are specified from surface downward.
Each layer depth must be greater than the previous. Non-monotonic depths cause
incorrect soil moisture redistribution.

### 6.7 Vegetation height must exceed Reference Height for met adjustment (dt_015)

The Reference Height constant in [CONSTANTS] is used for wind profile adjustment.
If vegetation height is less than Reference Height, the logarithmic wind profile
calculation produces negative or NaN values.

### 6.8 Time format is MM/DD/YYYY-HH (dt_016)

DHSVM uses a non-standard date format: `MM/DD/YYYY-HH` (no minutes/seconds in
the config, though output includes :MM:SS). Using ISO format or DD/MM/YYYY causes
the parser to misinterpret dates silently.

### 6.9 Basin suitability gate (domain of validity)

DHSVM is a high-resolution (30-150 m grid), physically-based DISTRIBUTED model for
STEEP, MOUNTAINOUS watersheds. Its core physics — topographically-driven subsurface
lateral flow and energy-balance snow — assume real relief and an unregulated channel
network. Before building inputs for a new basin, CHECK and REJECT if any hold:

- **Low relief**: basin relief (max-min DEM elevation) < ~300 m. Without slope-driven
  gradients the subsurface routing is meaningless.
- **Too large for native resolution**: area >> ~10,000 km^2. At 30-150 m a 121,000 km^2
  basin is 10^7-10^8 cells — computationally infeasible and not what DHSVM is for.
- **Regulated lowland plain**: dams/sluices/diversions dominate the hydrograph (e.g.
  managed plains); DHSVM has no reservoir-operations module.

**Worked REJECT example — Huai basin:** ~121,000 km^2, DEM 34-238 m (relief ~200 m),
flat regulated lowland plain. This is OUTSIDE DHSVM's declared domain. Do NOT attempt a
DHSVM run here. Either (a) remap the obs to a steep headwater sub-basin (relief > 500 m,
area < a few thousand km^2) that lies within the native domain, or (b) stop and record a
wrong-domain SKIP — the verification target is incompatible with the model.

---

## 7. Input File Format

### 7.1 Configuration File

INI-style text file with sections in brackets. Key sections:

```
[OPTIONS]
Format               = BIN
Extent               = BASIN
Flow Routing         = NETWORK
Sensible Heat Flux   = FALSE
Infiltration         = STATIC
Interpolation        = NEAREST

[AREA]
Coordinate System    = UTM
Extreme North        = 5331870.0
Extreme West         = 628440.0
Center Latitude      = 47.9
Center Longitude     = -120.9
Number of Rows       = 425
Number of Columns    = 300
Grid spacing         = 90

[TIME]
Time Step            = 3
Model Start          = 10/01/1970-00
Model End            = 10/01/1971-00

[CONSTANTS]
Ground Roughness     = 0.01
Snow Roughness       = 0.03
Rain Threshold       = -0.45
Snow Threshold       = 0.46
Temperature Lapse Rate = -0.0065
Precipitation Lapse Rate = 0.0000030
```

### 7.2 Meteorological Forcing Files

One ASCII file per grid cell, named `data_<lat>_<lon>`:

```
MM/DD/YYYY-HH  Tair(C)  Wind(m/s)  RH(%)  Swin(W/m2)  Lwin(W/m2)  Precip(m/step)
01/01/1970-00   -8.93    3.60       62.56  0.00        219.53      0.000235
01/01/1970-03   -11.76   3.60       80.58  0.00        210.31      0.000235
```

### 7.3 Binary Map Files

Flat binary, row-major, 32-bit (int for type maps, float for continuous):
- DEM: float, elevation in meters
- Mask: int, 1=inside basin, 0=outside
- Soil type: int, index into soil parameter table
- Vegetation type: int, index into vegetation parameter table

### 7.4 Stream Network Files

Three ASCII files define the channel network:
- `stream.map.dat`: grid cell → segment ID mapping
- `stream.network.dat`: segment connectivity, length, slope, width
- `stream.class.dat`: channel type properties (Manning's n, geometry)

---

## 8. Output Format

### 8.1 Aggregated.Values

Basin-averaged time series, comma-separated:

```
Date,Precip(m),Snow(m),IExcess(m),HasSnow,Swq,Melt,ET,...
10/01/1970-00:00:00,0.000194,0,0,0,0,0,0.000206,...
```

### 8.2 Stream.Flow

Tab-separated stream discharge per segment:

```
TIMESTAMP  SEGMENT_ID  FLOW(m3/s)  ...  "NAME"
10.01.1970-00:00:00  0  0.00034  15  0  0  15  "Totals"
```

### 8.3 Mass.Balance

Running water balance check:

```
Date  Precip  ET  ChannelInt  SoilWater  SWQ  SatFlow
```

### 8.4 Mass.Final.Balance

End-of-simulation summary (printed to stderr):

```
Total Inflow .................. XX.XX mm
  Precip/Inflow .............. XX.XX mm
Total Outflow ................. XX.XX mm
  ET ......................... XX.XX mm
  ChannelInt ................. XX.XX mm
Storage Change ................ XX.XX mm
```

### 8.5 Pixel Time Series

Same format as Aggregated.Values but for individual output pixels.

---

## 9. Calibration Parameters

| Parameter | Section | Range | Controls | Sensitivity |
|-----------|---------|-------|----------|-------------|
| Lateral Conductivity | [SOILS] | 1e-6 – 1e-2 m/s | Baseflow magnitude | High |
| Exponential Decrease | [SOILS] | 0.5 – 5.0 | Baseflow recession | High |
| Depth Threshold | [SOILS] | 0.5 – 3.0 m | Subsurface storage | Medium |
| Maximum Infiltration | [SOILS] | 1e-6 – 1e-3 m/s | Surface runoff | Medium |
| Temperature Lapse Rate | [CONSTANTS] | -0.003 – -0.010 C/m | Snow line elevation | High |
| Precipitation Lapse Rate | [CONSTANTS] | 0 – 1e-4 m/m | Orographic precip | High |
| Rain Threshold | [CONSTANTS] | -2.0 – 1.0 C | Rain vs snow partition | Medium |
| Snow Threshold | [CONSTANTS] | -1.0 – 3.0 C | Rain vs snow partition | Medium |
| Manning's n | stream.class | 0.01 – 0.15 | Flow timing | Low |
| Soil Depth | [SOILS] | 0.5 – 5.0 m | Total storage | High |
| Porosity | [SOILS] | 0.3 – 0.6 | Soil water capacity | Medium |
| Field Capacity | [SOILS] | 0.1 – 0.4 | Drainage timing | Medium |

---

## 10. Quick Start

```bash
# 1. Convert met forcing data (e.g., from CMFD)
python tools/convert_forcing.py \
  --input-dir /path/to/cmfd/data \
  --output-dir /path/to/dhsvm/forcing \
  --source-format cmfd \
  --timestep 3 \
  --grid-decimal 5 \
  --start-date 1970-10-01 --end-date 1971-10-01

# 2. Convert soil parameters
python tools/convert_soil_params.py \
  --hwsd-file /path/to/HWSD_data.csv \
  --soil-map /path/to/soil_class.tif \
  --output soil_params.json

# 3. Generate DHSVM configuration file
python tools/generate_config.py \
  --template base_config.txt \
  --dem-file input/dem.bin \
  --forcing-dir forcing/ \
  --soil-params soil_params.json \
  --output INPUT.MyBasin

# 4. Run the model
python tools/run_dhsvm.py \
  --binary build/DHSVM/sourcecode/DHSVM \
  --config INPUT.MyBasin \
  --output-dir output/

# 5. Parse and analyze output
python tools/parse_output.py \
  --aggregated output/Aggregated.Values \
  --streamflow output/Stream.Flow \
  --output results.csv

# 6. Validate against observations
python tools/parse_output.py \
  --aggregated output/Aggregated.Values \
  --observed /path/to/obs_streamflow.csv \
  --metrics nse,kge,pbias \
  --output validation.json
```

---

## 11. Diagnostic Triplets Summary

| ID | Severity | Domain | Summary |
|----|----------|--------|---------|
| dt_001 | silent | unit_conversion | Precip in mm instead of m → 1000x flood |
| dt_002 | silent | unit_conversion | Temperature in K instead of C → no snow |
| dt_003 | silent | unit_conversion | RH fraction instead of percent → extreme ET |
| dt_004 | silent | unit_conversion | Wind in km/hr instead of m/s → wrong turbulent fluxes |
| dt_005 | silent | unit_conversion | Shortwave in MJ/day instead of W/m2 |
| dt_006 | silent | unit_conversion | Soil depth in cm instead of m |
| dt_007 | silent | unit_conversion | Hydraulic conductivity wrong units |
| dt_008 | silent | unit_conversion | Porosity as percent instead of fraction |
| dt_009 | silent | unit_conversion | Elevation in feet instead of meters |
| dt_010 | silent | unit_conversion | Slope in degrees instead of radians |
| dt_011 | silent | unit_conversion | Lapse rate in C/km instead of C/m |
| dt_012 | fatal | path_resolution | Met file name decimal mismatch |
| dt_013 | silent | parameter_format | Binary map size mismatch |
| dt_014 | degraded | parameter_format | Non-monotonic soil layer depths |
| dt_015 | fatal | runtime | Veg height < reference height → NaN wind |
| dt_016 | silent | dependency_mismatch | Wrong date format in forcing files |
| dt_017 | fatal | runtime | Mask and DEM dimension mismatch |
| dt_018 | degraded | silent_error | Timestep mismatch between config and forcing |

---

## 12. File Structure

```
ki/
  SKILL.md                          # This file
  tools/
    convert_forcing.py              # Met forcing converter
    convert_soil_params.py          # Soil parameter converter
    run_dhsvm.py                    # Execution wrapper
    parse_output.py                 # Output parser
    generate_config.py              # Config file generator
  docs/
    s1_terrain_preparation.md       # Terrain prep skill
    s2_met_forcing.md               # Met forcing skill
    s3_soil_parameters.md           # Soil params skill
    s7_execution.md                 # Model execution skill
    s8_output_analysis.md           # Output analysis skill
  diagnostics/
    triplets.yaml                   # Diagnostic triplets
```
