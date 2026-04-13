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

# PRMS v5.1.0 (Precipitation-Runoff Modeling System) — Knowledge Infrastructure

**Package**: `hydrocraft-prms` v1.0.0
**Model**: PRMS v5.1.0 (USGS Precipitation-Runoff Modeling System)
**Created by**: Jianyun Zhang Research Group, Hohai University
**Last updated**: 2026-03-25
**Stats**: 5 tools | 7 skill documents | 18 diagnostic triplets | ~2,000 lines of validated Python
**Validation status**: `dissected`

---

## Overview

This knowledge infrastructure enables autonomous simulation of watershed hydrology using the USGS Precipitation-Runoff Modeling System (PRMS) v5.1.0 on any basin, **without manual data preparation**. The 5 validated tools replace the standard manual PRMS workflow with a Python pipeline that integrates directly with HydroCraft's forcing, soil, and routing infrastructure.

**What PRMS does**: Deterministic, distributed-parameter, physically-based watershed model. Simulates:
- Precipitation distribution (rain/snow partitioning by HRU, lapse rate methods)
- Temperature distribution (station-based or gridded climate-by-HRU)
- Solar radiation estimation (degree-day or cloud-cover methods)
- Potential evapotranspiration (Jensen-Haise, Hamon, Hargreaves-Samani, Penman-Monteith, Priestley-Taylor)
- Canopy interception (rain and snow on vegetated surfaces)
- Snow dynamics (energy-balance snowpack accumulation and melt)
- Surface runoff (variable-source-area: SMIDX or CAREA methods)
- Soil zone moisture accounting (infiltration, ET, recharge, interflow)
- Groundwater flow (linear reservoir conceptualization)
- Streamflow routing (Muskingum or simple addition)
- Depression storage (optional closed/open surface depressions)
- Cascading flow between HRUs (topographic routing of overland + subsurface flow)

**Key architectural feature**: PRMS uses the Modular Modeling System (MMS) framework. The C-language MMF core handles parameter I/O, module dispatch, and time stepping. All physical process modules are in Fortran 90. The model is configured via three file types: control file, parameter file(s), and data file.

**Unit system**: PRMS internally works in **US customary units**: temperatures in degrees Fahrenheit, precipitation in inches/day, areas in acres, elevations in feet (configurable), streamflow in cubic feet per second (cfs). This is a critical difference from most global datasets (metric). The tools handle all conversions.

---

## Installation

### Binary

```
PRMS v5.1.0:  source/repo/prms/prms_hpc
Version:      5.1.0 (05/01/2020)
Platform:     Linux x86-64, gfortran + gcc
Source:       github.com/nhm-usgs/prms
```

### Build from Source

```bash
cd source/repo
make          # Builds mmf library + prms executable
ls prms/prms_hpc   # Output binary
```

### Dependencies

```
gcc (C compiler for MMF framework)
gfortran (Fortran 90 for process modules)
libnetcdf + libnetcdff (NetCDF output support)
libhdf5 (HDF5 backend for NetCDF4)
```

### Python dependencies (all in HydroCraft venv)

```
numpy, pandas, xarray, matplotlib, pyyaml
```

---

## Execution

### Command Line Interface

```bash
# Basic run (control file specifies everything)
./prms_hpc -C/path/to/control_file

# Flags
-C<path>        # Path to control file (REQUIRED, no space after -C)
-batch          # Batch mode (default, suppress GUI)
-print          # Print parameters and variables, then exit
-por            # Run for period of record in data file
-set <var> <val> # Override control variable
-MAXDATALNLEN N # Max data line length (default 256)
-debug N        # Debug level
```

### Three Required Input Files

1. **Control file** — Master configuration: module selection, file paths, time period
2. **Parameter file(s)** — Physical parameters for each HRU (area, elevation, soil, etc.)
3. **Data file** — Time series of observed forcing (precip, temperature, streamflow)

---

## Pipeline (7 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | (manual) | Basin selection, period, module choices |
| 1 | Forcing preparation | `convert_forcing_to_prms` | Global gridded data to PRMS data file (unit conversions) |
| 2 | Parameter preparation | `convert_params_to_prms` | Soil/land use data to PRMS parameter file |
| 3 | Control file generation | `generate_control_file` | Assemble control file with paths and settings |
| 4 | Model execution | `run_prms` | Execute PRMS binary with preflight validation |
| 5 | Output analysis | `parse_prms_output` | Parse output files to CSV, compute metrics |

### Parallelism

Stages 1, 2 can run in parallel after stage 0.
Stage 3 depends on stages 1 and 2 (needs file paths).
Stage 4 depends on stage 3.
Stage 5 depends on stage 4.

---

## Tools Reference

| Tool | Stage | Script Path | Lines | Purpose |
|------|-------|-------------|------:|---------|
| `convert_forcing_to_prms` | s1 | `tools/convert_forcing_to_prms.py` | 420 | CMFD/ERA5/MSWX to PRMS data file (C->F, mm->in, m/s->cfs) |
| `convert_params_to_prms` | s2 | `tools/convert_params_to_prms.py` | 380 | HWSD/SOILGRIDS + DEM to PRMS parameter file |
| `generate_control_file` | s3 | `tools/generate_control_file.py` | 300 | Build PRMS control file |
| `run_prms` | s4 | `tools/run_prms.py` | 250 | Run PRMS with validation |
| `parse_prms_output` | s5 | `tools/parse_prms_output.py` | 350 | Parse stat/CSV output, compute NSE/KGE/PBIAS |

**Total**: 5 tools, ~1,700 lines of validated Python code.

---

## Input File Formats

### Control File Format

The control file is a plain-text file with `####` delimiters. Each variable has a key, size, type code, and value(s).

```
PRMS control file
####
start_time
6
1
1980
10
1
0
0
0
####
end_time
6
1
2010
9
30
0
0
0
####
param_file
1
4
./input/hru.param
####
data_file
1
4
./input/basin.data
####
model_mode
1
4
PRMS
####
precip_module
1
4
climate_hru
####
temp_module
1
4
climate_hru
####
et_module
1
4
potet_jh
####
solrad_module
1
4
ddsolrad
####
srunoff_module
1
4
srunoff_smidx
####
strmflow_module
1
4
strmflow
####
transp_module
1
4
transp_tindex
```

**Type codes**: 1=long integer, 2=float, 3=double, 4=string

### Parameter File Format

```
Written by PRMS parameter tool
Version: PRMS parameter tool v1.0
** Dimensions **
####
nhru
10
####
nsegment
3
####
nobs
1
** Parameters **
####
hru_area
1
nhru
10
2
100.5
200.3
...
####
hru_elev
1
nhru
10
2
1500.0
1600.5
...
```

**Dimension format**: `####`, dimension name, dimension value (NO count line between name and value).

**File header**: Two lines before `** Dimensions **` (info string + version string). The reader consumes both before searching for `** Dimensions **`.

**Parameter format**: `####`, parameter name, number of dimension names, dimension name(s), total number of values, type code (1=int, 2=float, 3=double, 4=string), then values one per line.

**Dimension assignments**: gwflow_coef/gwstor_init/gwstor_min/gwsink_coef use `ngw`. ssr2gw_rate/ssr2gw_exp/ssstor_init use `nssr`. Most other per-HRU params use `nhru`.

### Data File Format

```
PRMS data file for Test Basin
tmax 1
tmin 1
precip 1
runoff 1
####
1980 10 1 0 0 0 55.4 32.1 0.00 10.5
1980 10 2 0 0 0 58.2 34.5 0.12 12.3
1980 10 3 0 0 0 52.1 30.8 0.45 15.7
```

Header: info string, variable declarations (name + count), `####` delimiter, then daily values: year month day hour min sec val1 val2 ...

### CBH (Climate-By-HRU) Files

When using `climate_hru` module, forcing is provided per-HRU in separate files:

```
tmax 10           # variable_name nhru
########################################
1980 10 1 0 0 0 55.4 56.2 54.8 57.1 55.9 56.5 54.2 55.8 56.9 57.3
1980 10 2 0 0 0 58.2 59.1 57.5 60.0 58.7 59.4 57.1 58.5 59.8 60.2
```

---

## Unit Trap Table

This is the most critical section. PRMS uses US customary units internally. All global datasets use metric.

| Variable | PRMS Internal Unit | Common Source Unit | Conversion | Trap |
|----------|-------------------|-------------------|------------|------|
| Temperature (tmax, tmin) | degrees Fahrenheit | degrees Celsius | F = C * 9/5 + 32 | Off by ~50 if unconverted |
| Precipitation | inches/day | mm/day | in = mm / 25.4 | 25.4x too much precip |
| Elevation | feet (default, elev_units=0) | meters | ft = m / 0.3048 | Lapse rate errors |
| Area (hru_area) | acres | km2 or m2 | acres = km2 * 247.105 | Water balance wrong |
| Streamflow (runoff) | cfs (default, runoff_units=0) | m3/s (cms) | cfs = cms / 0.028317 | Calibration mismatch |
| Solar radiation | Langleys/day | W/m2 | Ly = W/m2 * 0.0864 | Affects ET and snow |
| Wind speed | m/s | m/s | No conversion needed | — |
| Humidity | percentage (0-100) | fraction (0-1) | % = fraction * 100 | Extreme ET if wrong |
| Latitude | decimal degrees | decimal degrees | No conversion needed | — |
| Longitude | degrees East | degrees East | No conversion needed | — |
| Snow depth | inches | mm or cm | in = mm / 25.4 | — |
| Pan evaporation | inches/day | mm/day | in = mm / 25.4 | — |
| Soil moisture max | inches | mm | in = mm / 25.4 | Soil dries instantly |
| Slope | decimal fraction | degrees or % | — | Use tan(degrees) |

### Internal Conversion Constants (from basin.f90)

```fortran
INCH2CM = 2.54
INCH2MM = 25.4
INCH2M = 0.0254
MM2INCH = 1.0 / 25.4    ! = 0.03937
FEET2METERS = 0.3048
METERS2FEET = 1.0 / 0.3048  ! = 3.28084
CFS2CMS_CONV = 0.028316847
FT2_PER_ACRE = 43560.0
```

---

## Module Selection Guide

### Temperature Distribution

| Module | When to Use | Input |
|--------|-------------|-------|
| `temp_1sta` | Single station, lapse rate adjustment | Station tmax/tmin in data file |
| `temp_laps` | Multiple stations, lapse rate | Station data + elevations |
| `temp_dist2` | Multiple stations, inverse distance | Station data + locations |
| `climate_hru` | Pre-gridded data per HRU (CBH files) | Separate tmax/tmin files |
| `ide_dist` | Inverse-distance-elevation | Station data |
| `xyz_dist` | XYZ distance weighting | Station data |

### Precipitation Distribution

| Module | When to Use | Input |
|--------|-------------|-------|
| `precip_1sta` | Single station | Station precip in data file |
| `precip_laps` | Lapse rate adjustment | Station data + elevations |
| `precip_dist2` | Multiple stations | Station data + locations |
| `climate_hru` | Pre-gridded data per HRU (CBH files) | Separate precip file |

### Potential Evapotranspiration

| Module | Data Required | Best For |
|--------|--------------|----------|
| `potet_jh` | Tmax, Tmin | General use, data-sparse areas |
| `potet_hamon` | Tmax, Tmin | Simple, temperature-only |
| `potet_hs` | Tmax, Tmin | Hargreaves-Samani, arid regions |
| `potet_pt` | Tmax, Tmin, humidity, wind | Priestley-Taylor, humid regions |
| `potet_pm` | Tmax, Tmin, humidity, wind | Penman-Monteith, best physics |
| `potet_pan` | Pan evaporation data | When pan data available |

### Streamflow Routing

| Module | When to Use |
|--------|-------------|
| `strmflow` | Simple summation, no channel routing |
| `strmflow_in_out` | Pass-through routing |
| `muskingum` | Muskingum channel routing |
| `muskingum_lake` | Muskingum with lake routing |

### Surface Runoff

| Module | Method |
|--------|--------|
| `srunoff_smidx` | Non-linear soil moisture index |
| `srunoff_carea` | Linear contributing area |

---

## Critical Domain Knowledge

These non-obvious facts cause **silent failures** if violated.

### 1. Temperature MUST be in Fahrenheit (dt_001)

PRMS expects all temperatures in degrees Fahrenheit. Global datasets (ERA5, CMFD, MSWX) provide Celsius. If you feed Celsius directly, snow never accumulates (20C interpreted as 20F = -6.7C... but actually 20C = 68F), and the rain/snow partitioning fails completely. The `tmax_allsnow` parameter defaults to 32F.

### 2. Precipitation MUST be in inches/day (dt_002)

PRMS expects daily precipitation in inches. CMFD gives mm/3hr, ERA5 gives m/timestep. If you feed mm/day directly, the basin receives 25.4x too much precipitation, causing extreme flooding.

### 3. Elevation units matter for lapse rates (dt_003)

The `elev_units` parameter (0=feet, 1=meters) controls how lapse rate corrections are applied. If your elevations are in meters but `elev_units=0`, lapse rates are applied as if the elevation difference is in feet (3.28x too small), producing nearly flat temperature fields.

### 4. HRU area MUST be in acres (dt_004)

The `hru_area` parameter is in acres. If you use km2 without converting (1 km2 = 247.105 acres), the water balance is wrong by orders of magnitude.

### 5. Control file `-C` flag has NO space (dt_005)

The command line requires `-C/path/to/control` with NO space between `-C` and the path. Using `-C /path/to/control` (with space) treats `/path/to/control` as a separate argument and fails silently.

### 6. Data file column order must match header (dt_006)

The data file header declares variables and their sizes. The data columns MUST appear in the exact same order. PRMS does not match by name — it reads positionally after the `####` delimiter.

### 7. Parameter file dimensions must be declared first (dt_007)

In the parameter file, all dimensions (nhru, nsegment, etc.) must appear in the `** Dimensions **` section before any parameters in `** Parameters **`. Dimensions referenced by parameters must exist.

### 8. CBH files require specific header format (dt_008)

Climate-by-HRU files must have exactly one header line (`variable_name nhru_count`) followed by a `########` delimiter line, then data. Extra blank lines or comments break the reader.

---

## Key Dimensions

| Dimension | Description | Typical Range |
|-----------|-------------|---------------|
| `nhru` | Number of Hydrologic Response Units | 1 - 100,000+ |
| `nsegment` | Number of stream segments | 1 - nhru |
| `ngw` | Number of groundwater reservoirs (= nhru) | = nhru |
| `nssr` | Number of subsurface reservoirs (= nhru) | = nhru |
| `nobs` | Number of streamflow observation stations | 0 - 10 |
| `ntemp` | Number of temperature stations | 0 - 50 |
| `nrain` | Number of precipitation stations | 0 - 50 |
| `nsol` | Number of solar radiation stations | 0 - 10 |
| `nsub` | Number of subbasins | 0 - nhru |
| `nmonths` | Months in year (always 12) | 12 |
| `ndepl` | Number of snow depletion curves | 1 - 10 |

---

## Key Parameters (per HRU)

| Parameter | Unit | Description | Typical Range |
|-----------|------|-------------|---------------|
| `hru_area` | acres | Area of each HRU | 1 - 50,000 |
| `hru_elev` | elev_units (ft or m) | Mean elevation | 0 - 15,000 |
| `hru_lat` | degrees | Latitude | -90 to 90 |
| `hru_type` | none | Type (0=inactive, 1=land, 2=lake, 3=swale) | 0-3 |
| `cov_type` | none | Cover type (0=bare, 1=grass, 2=shrub, 3=tree, 4=conifer) | 0-4 |
| `covden_sum` | fraction | Summer vegetation cover density | 0-1 |
| `covden_win` | fraction | Winter vegetation cover density | 0-1 |
| `hru_percent_imperv` | fraction | Fraction impervious area | 0-0.99 |
| `soil_moist_max` | inches | Maximum soil moisture capacity | 1-20 |
| `soil_rechr_max` | inches | Maximum recharge zone capacity | 0.5-10 |
| `soil_type` | none | Soil type (1=sand, 2=loam, 3=clay) | 1-3 |
| `gwflow_coef` | fraction/day | GW linear flow coefficient | 0.001-0.5 |
| `slowcoef_lin` | fraction/day | Linear interflow coefficient | 0.001-0.5 |
| `fastcoef_lin` | fraction/day | Linear preferential flow coefficient | 0.001-1.0 |
| `ssr2gw_rate` | fraction/day | Subsurface to GW transfer rate | 0.001-0.5 |
| `smidx_coef` | fraction | Surface runoff SMIDX coefficient | 0.001-0.06 |
| `smidx_exp` | 1/inch | Surface runoff SMIDX exponent | 0.1-0.5 |
| `tmax_allsnow` | temp_units | Tmax below which all precip is snow | 32 F |
| `tmax_allrain` | temp_units | Tmax above which all precip is rain | 38 F |

---

## Output Files

### Model Output File (model_output_file)

Basin-level daily summary written to the file specified by `model_output_file` control variable. Contains water balance components.

### CSV Output (csv_output_file)

Daily comma-separated output when `csvON_OFF = 1`:

```csv
Year,Month,Day,basin_potet,basin_actet,basin_ppt,basin_rain,basin_snow,...
1980,10,1,0.045,0.032,0.12,0.12,0.00,...
```

### Basin Summary

When `basinOutON_OFF = 1`, writes daily/monthly/yearly basin averages.

### NHru Summary

When `nhruOutON_OFF = 1`, writes per-HRU values for selected variables.

### Statvar File

When `statsON_OFF = 1`, writes selected variables at each timestep.

---

## Skill Documents

| Stage | Document | Path |
|-------|----------|------|
| s0 | Basin Configuration | `docs/s0_basin_configuration.md` |
| s1 | Forcing Preparation | `docs/s1_forcing_preparation.md` |
| s2 | Parameter Preparation | `docs/s2_parameter_preparation.md` |
| s3 | Control File Generation | `docs/s3_control_file_generation.md` |
| s4 | Model Execution | `docs/s4_model_execution.md` |
| s5 | Output Analysis | `docs/s5_output_analysis.md` |
| s6 | Calibration | `docs/s6_calibration.md` |

---

## Diagnostic Triplets

18 diagnostic triplets covering unit conversion, file format, parameterization, and runtime failures.
See `diagnostics/triplets.yaml` for the complete set.

---

## Version History

- PRMS v5.1.0 (2020-05-01): Current version with NHM support, NetCDF output, CBH input
- PRMS v5.0.0 (2018): Added PRMS4 backward compatibility, dynamic parameters
- PRMS v4.0.3 (2015): Stable release widely used in USGS modeling
- PRMS v3.0 (2004): Modular rewrite with MMS framework
