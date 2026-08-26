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
| to run the pipeline stages | `tools/` (7 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (6 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (28 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (19 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/build_cwatm_ancillary.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/build_cwatm_ancillary.py --help` |
| `tools/build_cwatm_static.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/build_cwatm_static.py --help` |
| `tools/build_cwatm_waterbodies.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/build_cwatm_waterbodies.py --help` |
| `tools/convert_forcing_to_cwatm.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing_to_cwatm.py --help` |
| `tools/convert_soil_to_cwatm.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_soil_to_cwatm.py --help` |
| `tools/parse_cwatm_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_cwatm_output.py --help` |
| `tools/run_cwatm_wrapper.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_cwatm_wrapper.py --help` |

*7 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# CWatM v1.5 (Community Water Model) — Knowledge Infrastructure

**Package**: `hydrocraft-cwatm` v1.0.0
**Model**: CWatM v1.5 (IIASA Water Security Group)
**Domain**: Global/regional hydrology — daily water cycle simulation
**Last updated**: 2026-03-25
**Stats**: 4 tools | 5 skill documents | 15+ diagnostic triplets
**Validation status**: `dissection_complete`

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: KDT 5.0 removed the tools from `data_ki/`; the old
`data_ki/CMFD/SKILL.md`, `data_ki/HWSD/SKILL.md` and `data_ki/ObservedQ/SKILL.md`
references are STALE. Use instead:
- forcing units and traps → `ki_tools_common.load_forcing`, plus `tools/convert_forcing_to_cwatm.py`
- soil properties → `ki_tools_common.soil_utils`, plus `tools/convert_soil_to_cwatm.py`
- observed discharge → `KISSPATH_DATA_KI/dataset_index.yaml`
  (`observation.discharge`) and `kdt_dataset_layouts.yaml` for on-disk format quirks.


## Overview

CWatM (Community Water Model) is an open-source, spatially distributed hydrological model that simulates the terrestrial water cycle at global and regional scales on a daily time step. Developed and maintained by IIASA's Water Security Research Group, CWatM integrates surface water, groundwater, snow/ice processes, water demand, and reservoir operations into a comprehensive water resources assessment framework.

**What CWatM does**:
- Precipitation partitioning (rain/snow) with multi-layer elevation zones (up to 10 layers)
- Snow accumulation, melt (degree-day + radiation), and refreezing
- Soil water dynamics (3-layer Richards-based, Arno scheme for heterogeneous runoff)
- Potential evapotranspiration (Penman-Monteith FAO56, Hamon, or pre-computed)
- Actual evapotranspiration across 6 land cover types (forest, grassland, irrigated paddy, irrigated non-paddy, sealed, open water)
- Groundwater storage and baseflow (linear reservoir or MODFLOW coupling)
- Kinematic wave channel routing (with C++ acceleration)
- Lake and reservoir operations (storage-outflow rules, demand-driven releases)
- Water demand and allocation (domestic, industrial, livestock, irrigation)
- Environmental flow assessment
- Optional water quality module
- Optional glacier coupling (OGGM)

**Key difference from other hydrological models**: CWatM operates on structured grids (30 arcmin or 5 arcmin) with daily time step, uses NetCDF throughout, and couples water demand/supply with human water management. It is designed for integrated assessment (MESSAGE-GLOBIOM-CWatM nexus).

---

## Installation

### Source

```
Repository: https://github.com/iiasa/CWatM
Version:    1.5 (branch: develop, commit: 5e5c455)
License:    GNU GPLv3
Language:   Python 3.8+ with C++ routing acceleration
```

### Python Dependencies

```
numpy, scipy, netCDF4, gdal (osgeo), pandas
Optional: flopy 3.3.2, xmipy (for MODFLOW coupling)
Optional: openpyxl (for Excel-based reservoir data)
```

### C++ Shared Library (Routing Acceleration)

```
Source:   cwatm/hydrological_modules/routing_reservoirs/t5.cpp
Linux:    t5_linux.so  (pre-compiled)
Windows:  t5.dll       (pre-compiled)
macOS:    t5_mac.so    (pre-compiled)
```

The C++ library provides optimized kinematic wave routing, upstream area calculation, LDD repair, and runoff concentration functions. Pre-compiled binaries are included; recompilation requires a C++ compiler.

### Test Example

```
Tutorials/01_Turn-ON/      # Rhine basin at 30 arcmin
  settings_Rhine-30min_Tutorial-1.ini   # Minimal configuration
Tutorials/06_Watercycle/   # Full template with all options
  settings_CWatM_template_30min.ini     # Complete reference settings
```

### Execution

```bash
# Basic run
python run_cwatm.py settings.ini

# Quiet mode (progress dots only)
python run_cwatm.py settings.ini -q

# Very quiet (no output)
python run_cwatm.py settings.ini -v

# Verbose (timestep + discharge)
python run_cwatm.py settings.ini -l

# Input data check (no simulation)
python run_cwatm.py settings.ini -c

# Input check with output file
python run_cwatm.py settings.ini -c results.csv

# Timing profiler
python run_cwatm.py settings.ini -t
```

---

## Pipeline (9 Stages)

| # | Stage | Module(s) | Description |
|---|-------|-----------|-------------|
| 0 | Configuration | settings.ini | Define domain, period, paths, options |
| 1 | Forcing preparation | readmeteo | Prepare NetCDF meteorological inputs |
| 2 | Static data preparation | soil, miscInitial | Prepare topography, soil, land cover NetCDFs |
| 3 | Model initialization | cwatm_initial | Load mask, parameters, initial conditions |
| 4 | Snow & frost | snow_frost | Precipitation partitioning, snow dynamics |
| 5 | Soil & land cover | soil, landcoverType, evaporation | Infiltration, percolation, ET, runoff generation |
| 6 | Groundwater | groundwater (or modflow) | Recharge, storage, baseflow |
| 7 | Routing & water bodies | routing_kinematic, lakes_reservoirs | Channel routing, lake/reservoir operations |
| 8 | Water demand & output | water_demand, output | Demand allocation, results writing |

### Stage Dependencies

```
Stage 0 (config) → Stage 1, 2 (data prep, can run in parallel)
Stage 1, 2 → Stage 3 (initialization)
Stage 3 → Stage 4 → Stage 5 → Stage 6 → Stage 7 → Stage 8 (sequential per timestep)
```

---

## Input Data Requirements

### Meteorological Forcing (NetCDF, daily or sub-daily)

| Variable | Settings Key | Unit (input) | Unit (internal) | Conversion |
|----------|-------------|--------------|-----------------|------------|
| Precipitation | PrecipitationMaps | kg m⁻² s⁻¹ | m/day | × `precipitation_coversion` (default 86.4) |
| Average temperature | TavgMaps | K | K | None (internal K) |
| Min temperature | TminMaps | K | K | For Penman-Monteith only |
| Max temperature | TmaxMaps | K | K | For Penman-Monteith only |
| Surface pressure | PSurfMaps | Pa | Pa | For Penman-Monteith |
| Specific humidity | QAirMaps | kg/kg | kg/kg | Or use RhsMaps instead |
| Relative humidity | RhsMaps | % | % | Alternative to QAirMaps |
| Wind speed (10m) | WindMaps | m/s | m/s | For Penman-Monteith |
| Shortwave radiation | RSDSMaps | W/m² | W/m² → MJ (×86400×1e-6) | For Penman-Monteith |
| Longwave radiation | RSDLMaps | W/m² | W/m² | For Penman-Monteith |

**Alternative**: Pre-computed ET can be provided instead of Penman-Monteith inputs:
| E0Maps | Reference evaporation (water) | m/day | m/day |
| ETMaps | Reference evapotranspiration (crop) | m/day | m/day |

### Temperature Setting (CRITICAL)

```ini
[OPTIONS]
TemperatureInKelvin = True   # If True, input T is in Kelvin
                             # If False, input T is in Celsius
```

**TRAP**: If `TemperatureInKelvin = True` but input data is in Celsius, all snow/ET calculations will be catastrophically wrong. No error is raised.

### Topographic/Static Data (NetCDF)

| Data | Settings Key | Unit | Description |
|------|-------------|------|-------------|
| Local drain direction | Ldd | 1-9 code | PCRaster LDD convention (5=pit) |
| Elevation | dem | m | Digital elevation model |
| Elevation std dev | ElevationStD | m | For snow zone partitioning |
| Cell area | CellArea | m² | Grid cell area |
| Channel gradient | chanGrad | - | Dimensionless slope |
| Channel length | chanLength | m | Channel segment length |
| Channel width | chanWidth | m | Bankfull bottom width |
| Channel depth | chanDepth | m | Bankfull depth |
| Manning's n | chanMan | s/m^(1/3) | Channel roughness |

### Soil Parameters (NetCDF)

| Parameter | Unit | Description |
|-----------|------|-------------|
| KSat1, KSat2, KSat3 | cm/day | Saturated hydraulic conductivity per layer |
| alpha1, alpha2, alpha3 | 1/cm | van Genuchten alpha parameter |
| lambda1, lambda2, lambda3 | - | van Genuchten lambda (pore-size index) |
| thetas1, thetas2, thetas3 | - | Saturated volumetric water content |
| thetar1, thetar2, thetar3 | - | Residual volumetric water content |
| percolationImp | - | Fraction of impermeable area |
| StorDepth1, StorDepth2 | m | Soil layer depths |

**TRAP**: KSat is in **cm/day**, not m/day or m/s. Source data (e.g., HWSD) often provides Ksat in cm/day already, but if using SoilGrids (mm/hr), conversion is required: `cm/day = mm/hr × 2.4`.

### Land Cover Data (NetCDF)

Six land cover types with fractional coverage per grid cell:
1. Forest
2. Grassland
3. Irrigated paddy
4. Irrigated non-paddy
5. Sealed/impervious
6. Open water

Each land cover type has specific parameters for: root depth, interception capacity, crop coefficient, crop depletion factor, and vegetation fraction.

---

## 6. Output Description

**Source of truth**: `dag.yaml`. This section restates the DAG output block for quick reading; if this section and `dag.yaml` ever disagree, `dag.yaml` wins.

**Headline output** (`validation_rank: 1`):

> `discharge` — Channel/river flow - the primary reported and calibrated variable. (`m3/s`)

| Output variable (dag `var`) | Rank | Unit | Emitted in | DAG description |
|-----------------------------|------|------|------------|-----------------|
| `discharge` | 1 | `m3/s` | NetCDF map / TSS time series at the configured aggregation suffix | Channel/river flow - the primary reported and calibrated variable. |
| `tws` | 2 | `m` | NetCDF map | Total water storage anomaly (groundwater + soil + surface water + snow). |
| `totalET` | 3 | `m` | NetCDF map at requested aggregation | Total actual evapotranspiration — water flux from land surface and vegetation to the atmosphere. |
| `SnowCover` | 4 | `m SWE` | NetCDF map | Snow water equivalent (state, reportable). |
| `storGroundwater` | 5 | `m` | NetCDF map | Linear-reservoir groundwater storage (state). |
| `baseflow` | 6 | `m` | NetCDF map at requested aggregation | Groundwater contribution to streamflow. |
| `sum_gwRecharge` | 7 | `m` | NetCDF map at requested aggregation | Groundwater recharge flux. |
| `unmetDemand` | 8 | `m` | NetCDF map / TSS | Unsatisfied water demand (water-stress indicator). |

### Output Format

### Time Series Output (at gauge locations)

Configured in settings.ini under `[OUTPUT]`:
```ini
OUT_Dir = $(FILE_PATHS:PathOut)
OUT_TSS_Daily = discharge        # Daily discharge at gauges [m³/s]
OUT_TSS_MonthAvg = discharge     # Monthly average discharge
```

Output format: NetCDF with gauge-indexed time series, or CSV.

### Spatial Map Output (gridded NetCDF)

```ini
OUT_MAP_Daily = discharge, precipitation, Tavg
OUT_MAP_MonthAvg = discharge, totalET, baseflow
OUT_MAP_AnnualAvg = discharge, runoff
OUT_MAP_TotalEnd = storGroundwater   # End-of-simulation state
```

### Key Output Variables

| Variable | Unit | Description |
|----------|------|-------------|
| discharge | m³/s | River discharge at each cell |
| totalET | m | Total evapotranspiration |
| baseflow | m | Groundwater contribution to streamflow |
| runoff | m | Total runoff (surface + subsurface) |
| precipitation | m | Precipitation input |
| storGroundwater | m | Groundwater storage |
| channelStorage | m³ | Water stored in channels |
| lakeResStorage | m³ | Lake and reservoir storage |
| tws | m | Total water storage (all compartments) |
| SnowCover | m | Snow water equivalent |
| unmetDemand | m | Unmet water demand |

### NetCDF Output Metadata

Variable metadata is defined in `cwatm/metaNetcdf.xml` with CF-compliant attributes (long_name, standard_name, unit). Temporal aggregation suffixes: `_daily`, `_monthavg`, `_monthtot`, `_annualavg`, `_annualtot`, `_totalend`.

---

## 8. Unit Conversion Table

Exact input/output shapes live in `docs/format_spec.yaml`; this table captures the conversions the CWatM KI repeatedly guards because mismatches are silent.

| Quantity | Source unit / case | Model unit | Factor or transform | Type |
|----------|--------------------|------------|---------------------|------|
| Precipitation forcing | `kg m⁻² s⁻¹` | `m/day` | `precipitation_coversion = 86.4` | multiplicative |
| Precipitation forcing | `m/day` | `m/day` | `precipitation_coversion = 1.0` | identity |
| Precipitation forcing | `mm/day` | `m/day` | `precipitation_coversion = 0.001` | multiplicative |
| Precipitation forcing | `mm/hr` | `m/day` | `precipitation_coversion = 0.024` | multiplicative |
| Average temperature, Tmin, Tmax | `K` with `TemperatureInKelvin = True` | `K` | none | identity |
| Average temperature, Tmin, Tmax | `°C` with `TemperatureInKelvin = False` | `K` internally | `+273.15` | additive |
| Shortwave radiation | `W/m²` | `MJ/m²/day` path for ET | `×86400×1e-6` | multiplicative |
| Longwave radiation | `W/m²` | `W/m²` | none | identity |
| Surface pressure | `hPa` | `Pa` | `×100` | multiplicative |
| Surface pressure | `kPa` | `Pa` | `×1000` | multiplicative |
| Wind speed | `km/hr` | `m/s` | `÷3.6` | multiplicative |
| KSat from HWSD | `cm/day` | `cm/day` | none | identity |
| KSat from SoilGrids | `mm/hr` | `cm/day` | `×2.4` | multiplicative |
| KSat from source in `m/s` | `m/s` | `cm/day` | `×8640000` | multiplicative |
| van Genuchten alpha | `1/m` | `1/cm` | `÷100` | multiplicative |
| Elevation | `km` | `m` | `×1000` | multiplicative |
| Elevation | `ft` | `m` | `×0.3048` | multiplicative |
| Channel gradient | `%` | dimensionless | `÷100` | multiplicative |
| Channel gradient | `‰` | dimensionless | `÷1000` | multiplicative |
| Cell area | `km²` | `m²` | `×1e6` | multiplicative |

### Unit Trap Table

| Quantity | Expected Unit | Common Wrong Unit | Factor | Symptom |
|----------|--------------|-------------------|--------|---------|
| Precipitation (input) | kg m⁻² s⁻¹ | mm/day | ÷86400÷1000 | Flooding or drought |
| precipitation_coversion | 86.4 | 1.0 or 86400 | - | 86.4 converts kg/m²/s → m/day |
| Temperature | K (if flag=True) | °C | +273.15 | Wrong snow, wrong ET |
| KSat (soil) | cm/day | m/s or mm/hr | ×2.4 from mm/hr | Infiltration wrong |
| van Genuchten alpha | 1/cm | 1/m | ÷100 | Soil water retention wrong |
| Shortwave radiation | W/m² | MJ/m²/day | ÷0.0864 | ET totally wrong |
| Surface pressure | Pa | hPa/kPa | ×100 or ×1000 | Penman-Monteith fails |
| Wind speed | m/s | km/hr | ÷3.6 | ET biased |
| Elevation | m | km or ft | ×1000 or ×0.3048 | Lapse rate, snow wrong |
| Channel gradient | dimensionless | % or ‰ | ÷100 or ÷1000 | Routing velocity wrong |
| Cell area | m² | km² | ×1e6 | Water balance wrong |

---

## 9. Diagnostic Triplets (Top 5)

Check `diagnostics/triplets.yaml` before debugging any failure. These are the highest-priority silent unit-conversion triplets in that file; do not duplicate the full YAML here.

| # | Triplet id | Error / symptom | Diagnosis | Remedy |
|---|------------|-----------------|-----------|--------|
| 1 | `dt_001` | Extreme flooding or discharge 100-1000× too high | `precipitation_coversion` factor does not match precipitation input units | Match `precipitation_coversion` to the actual forcing NetCDF units |
| 2 | `dt_002` | Zero or near-zero discharge despite precipitation | Precipitation is too low because the scale or conversion factor is wrong | Check internal precipitation output; daily precipitation should be 0-0.1 m/day |
| 3 | `dt_003` | Snow never melts, or all precipitation is snow/rain regardless of season | `TemperatureInKelvin` flag does not match input data units | Check temperature values and set `TemperatureInKelvin` correctly |
| 4 | `dt_004` | Water drains instantly or soil stays waterlogged | KSat units are wrong; CWatM expects `cm/day` | Convert KSat before use: HWSD is already `cm/day`; SoilGrids needs `×2.4`; `m/s` needs `×8640000` |
| 5 | `dt_005` | Soil retention curve, field capacity, or wilting point is unrealistic | van Genuchten alpha is in `1/m` instead of `1/cm` | Divide source alpha by `100` when converting from `1/m` to `1/cm` |

---

## Tools Reference

| Tool | Stage | Script Path | Purpose |
|------|-------|-------------|---------|
| `build_cwatm_static` | s2 | `tools/build_cwatm_static.py` | **Bootstrap a NEW basin**: MaskMap, Ldd, dem, ElevationStD, CellArea, chan* and land-cover fractions from MERIT-Hydro + ESA-CCI-LC + HydroBASINS |
| `build_cwatm_ancillary` | s2 | `tools/build_cwatm_ancillary.py` | Crop coefficients, interception capacities (10-day), relativeElevation |
| `convert_forcing_to_cwatm` | s1 | `tools/convert_forcing_to_cwatm.py` | Convert CMFD/ERA5/MSWX to CWatM NetCDF format; `--target_res` resamples onto the static grid; `--tminmax_3hr_dir` derives real tmin/tmax |
| `convert_soil_to_cwatm` | s2 | `tools/convert_soil_to_cwatm.py` | Convert HWSD/SoilGrids to CWatM soil parameters |
| `run_cwatm` | s3 | `tools/run_cwatm_wrapper.py` | Execute CWatM with preflight validation (`--flags=-q`, `--timeout`) |
| `parse_cwatm_output` | s4 | `tools/parse_cwatm_output.py` | Extract discharge/state variables to CSV |

### Bootstrapping a new basin (the order matters)

```bash
# 1. static stack — defines THE grid every other input must match
python tools/build_cwatm_static.py --gauge_lon 115.98 --gauge_lat 29.73 \
    --bbox 24.0 36.0 90.0 117.0 --res 0.5 \
    --hydrobasins .../hybas_as_lev06_v1c.shp \
    --expected_area_km2 1488210 --out_dir case/static

# 2. forcing, resampled ONTO that grid (--target_res == --res above)
python tools/convert_forcing_to_cwatm.py --forcing_type cmfd \
    --forcing_dir .../Data_forcing_01dy_010deg --bbox 24.0 36.0 90.0 117.0 \
    --start_date 2007-01-01 --end_date 2023-12-31 --target_res 0.5 --resume \
    --tminmax_3hr_dir .../Data_forcing_03hr_010deg/Temp --output_dir case/forcing

# 3. soil (--resolution == --res) and ancillary
python tools/convert_soil_to_cwatm.py --source hwsd --input_dir .../HWSD_RASTER \
    --bbox 24.0 36.0 90.0 117.0 --resolution 0.5 --output_dir case/soil
python tools/build_cwatm_ancillary.py --static_dir case/static --output_dir case/ancillary

# 4. run
python tools/run_cwatm_wrapper.py --settings case/settings.ini \
    --cwatm_dir <KI>/source/repo --flags=-q
```

`build_cwatm_static.py` verifies itself: it prints the MERIT upstream area at the
snapped gauge pixel and the summed basin area, against `--expected_area_km2`.
Agreement within a few percent means the LDD upscaling found the right river.

**Spin-up.** A large basin starts with empty channels and an empty groundwater
store. At Jiujiang (1.5 M km²) a 10-day spin-up produced 60 m³/s against an
observed 10,000 m³/s. Allow 2–3 years between `StepStart` and `SpinUp`.

---

## Calibration Parameters (Priority Order)

| Parameter | Settings Key | Range | Controls | Sensitivity |
|-----------|-------------|-------|----------|-------------|
| Snow melt coefficient | SnowMeltCoef | 0.001-0.01 | Snow dynamics | HIGH |
| Crop correction factor | crop_correct | 0.8-1.5 | ET magnitude | HIGH |
| Soil depth factor | soildepth_factor | 0.5-2.0 | Soil storage capacity | HIGH |
| Arno beta (runoff shape) | arnoBeta_add | 0.01-1.0 | Direct runoff fraction | HIGH |
| Interflow factor | factor_interflow | 0.5-10.0 | Lateral subsurface flow | MEDIUM |
| Recession coefficient | recessionCoeff_factor | see below | Baseflow timing | **HIGH** |
| Manning's n | manningsN | 0.5-5.0 | Routing velocity (multiplier) | MEDIUM |
| Preferential flow | preferentialFlowConstant | 1.0-10.0 | Bypass flow to GW | LOW (inert unless `preferentialFlow = True`) |
| Normal storage limit | normalStorageLimit | 0.1-0.9 | Reservoir operations | LOW (inert unless `includeWaterBodies = True`) |
| Lake A factor | lakeAFactor | 0.1-1.0 | Lake outflow | LOW (inert unless `includeWaterBodies = True`) |
| Lake evaporation factor | lakeEvaFactor | 0.8-2.0 | Lake evaporation | LOW (inert unless `includeWaterBodies = True`) |

### `recessionCoeff_factor` is a DIVISOR, and it is the single most important parameter

`cwatm/hydrological_modules/groundwater.py:72-73` does

```python
self.var.recessionCoeff = 1 / self.var.recessionCoeff * loadmap('recessionCoeff_factor')
self.var.recessionCoeff = 1 / self.var.recessionCoeff
```

i.e. **effective recessionCoeff = `recessionCoeff` ÷ `recessionCoeff_factor`**, and baseflow
is `recessionCoeff × storGroundwater`. So *raising* `recessionCoeff_factor` makes baseflow
**slower**, not faster. The "1.0–10.0" range quoted above can only ever slow the store down;
if the basin needs a faster store, that range contains no solution.

**Recipe**: pin `recessionCoeff = 1.0` in `[GROUNDWATER]`. Then `recessionCoeff_factor`
*is* the groundwater linear-reservoir residence time τ in **days**, and a sane search range
is τ ∈ [2, 40].

**Symptom of getting this wrong** (measured at Jiujiang, Yangtze, 1.5 M km², 2010–2023):
with the KI's old default (`recessionCoeff = 0.02`, factor `1.0` → τ = 50 d) baseflow was
**414 of 553 mm/yr (BFI 0.75)** and its climatology **peaked in October** while CMFD
precipitation peaks in June. That quarter-cycle phase lag capped the correlation at
r = 0.729, hence `NSE ≤ r² = 0.531` — unreachable no matter how bias and variance are
corrected. Dropping to τ = 4 d lifted r to 0.852 and NSE from 0.44 → 0.65 on 2010–2013.

**Always check the baseflow fraction and its phase before calibrating anything else.** Write
`OUT_Map_MonthAvg = runoff, baseflow`, take the basin-area-weighted mean of each, and compare
the month of peak baseflow with the month of peak precipitation. If BFI > 0.6 or the peaks are
more than ~1 month apart, τ is wrong and no amount of `crop_correct` / `arnoBeta_add` will fix it.

---

## Settings File Structure

The settings file (`.ini` format) is organized into sections:

```
[OPTIONS]         - Boolean/integer model switches
[FILE_PATHS]      - Root paths with variable substitution: $(SECTION:KEY)
[NETCDF_ATTRIBUTES] - Output metadata
[MASK_OUTLET]     - Domain definition (MaskMap, Gauges)
[TIME-RELATED_CONSTANTS] - StepStart, StepEnd, SpinUp (DD/MM/YYYY)
[INITITIAL CONDITIONS]   - Warm start / save state
[CALIBRATION]     - Calibration parameter values
[TOPOP]           - Topographic data paths
[METEO]           - Meteorological forcing paths + conversion factors
[EVAPORATION]     - Penman-Monteith parameters / albedo
[SNOW]            - Snow layers, lapse rate, melt parameters
[FROST]           - Frost index parameters
[VEGETATION]      - Crop group numbers
[SOIL]            - Soil hydraulic properties
[LANDCOVER]       - Land cover fractions and types
[__forest], [__grassland], [__irrPaddy], [__irrNonPaddy], [__sealed], [__open_water]
                  - Per-land-cover parameters
[GROUNDWATER]     - Aquifer properties
[WATERDEMAND]     - Demand data and allocation
[RUNOFF_CONCENTRATION] - Runoff lag parameters
[ROUTING]         - Channel routing parameters
[LAKES_RESERVOIRS] - Water body configuration
[INFLOW]          - External inflow data
[ENVIRONMENTALFLOW] - Environmental flow settings
[OUTPUT]          - Output variable selection and aggregation
```

**Key syntax features**:
- Cross-section variable substitution: `$(FILE_PATHS:PathMaps)`
- Same-section substitution: `$(PathRoot)`
- Boolean options: `True` / `False`
- Date format: `DD/MM/YYYY`
- Comments: Lines starting with `#`

---

## Critical Domain Knowledge

### 1. Precipitation conversion factor (precipitation_coversion = 86.4)

CWatM reads precipitation in kg m⁻² s⁻¹ (same as mm/s) and multiplies by `precipitation_coversion` to get m/day. The default 86.4 = 86400 s/day ÷ 1000 mm/m. If your input is already in m/day, set `precipitation_coversion = 1.0`. If in mm/day, set `precipitation_coversion = 0.001`. Getting this wrong produces either extreme flooding or zero runoff.

### 2. Temperature in Kelvin vs Celsius

The `TemperatureInKelvin` option controls whether CWatM adds 273.15 to input temperatures. If the flag is wrong, snow partitioning (TempSnow threshold in °C), melt calculations, and ET calculations all fail silently. Check: if your forcing NetCDF has temperature values > 200, it's Kelvin.

### 3. Soil KSat units are cm/day

CWatM expects saturated hydraulic conductivity in cm/day. HWSD provides this natively. SoilGrids provides mm/hr (multiply by 2.4). Using wrong units causes either instant drainage (too high) or waterlogging (too low).

### 4. LDD coding follows PCRaster convention

Local drain direction uses values 1-9 where 5 = pit/outlet:
```
7 8 9
4 5 6
1 2 3
```
If using ArcGIS D8 convention (1=E, 2=SE, ..., 128=NE), conversion is required.

### 5. Three-layer soil scheme

CWatM uses a 3-layer soil column:
- Layer 1: Top soil (depth from settings, typically 0.05 m)
- Layer 2: Subsoil (StorDepth1, typically 0.25 m)
- Layer 3: Deep soil (StorDepth2, typically 1.0-1.5 m)

Each layer has independent van Genuchten parameters.

### 6. Channel routing C++ acceleration

The kinematic wave solver uses Newton-Raphson iteration (max 10 iterations, epsilon=0.0001). The C++ shared library (`t5_linux.so`) is ~100x faster than pure Python. If the library fails to load, CWatM falls back to Python but runtime increases dramatically.

---

## 10. Coupling Interfaces

| Direction | Partner Model | Interface |
|-----------|--------------|-----------|
| Forcing input | ERA5, CMFD, MSWX, ISIMIP | NetCDF meteorological variables |
| GW coupling | MODFLOW 6 | Via flopy/xmipy (bi-directional) |
| Glacier coupling | OGGM | Glacier melt as additional input |
| Downstream | MESSAGE-GLOBIOM | Water availability constraints |
| Water quality | Internal module | Integrated water quality tracking |

---

## 11. Validated Results

**Source of truth**: `docs/validation_convention.yaml`. This section states the field bars used to judge model skill; do not infer achieved scores from these thresholds. Run metrics must come from actual CWatM outputs after `python preflight_check.py` and a real model execution.

### Headline Output

| Property | Value |
|----------|-------|
| DAG rank-1 variable | `discharge` |
| Unit | `m3/s` |
| Description | Channel/river flow - the primary reported and calibrated variable. |
| Other DAG outputs | `tws`, `totalET`, `SnowCover`, `storGroundwater`, `baseflow`, `sum_gwRecharge`, `unmetDemand` |

### Performance Metrics — judged against the field's bar, not intuition

| DAG variable | Metric | Direction | Band | Convention threshold | Citation keys |
|--------------|--------|-----------|------|----------------------|---------------|
| `discharge` | `nse` | maximize | `satisfactory` | `>= 0.5` | `arnold2012`, `panarctic2020`, `bouregreg2011` |
| `discharge` | `nse` | maximize | `good` | `>= 0.7` | `arnold2012`, `panarctic2020`, `bouregreg2011` |
| `discharge` | `nse` | maximize | `very_good` | `>= 0.75` | `arnold2012`, `panarctic2020`, `bouregreg2011` |
| `discharge` | `pbias` | zero_centered | `satisfactory` | `<= 25` toward zero | `panarctic2020`, `bouregreg2011` |
| `discharge` | `pbias` | zero_centered | `good` | `<= 15` toward zero | `panarctic2020`, `bouregreg2011` |
| `discharge` | `pbias` | zero_centered | `very_good` | `<= 10` toward zero | `panarctic2020`, `bouregreg2011` |
| `tws` | `r` | maximize | `satisfactory` | no cited threshold | none in convention |

The convention contains `discharge` PBIAS bars for both point time-series and regional aggregate time-series validation; both use `very_good: 10`, `good: 15`, and `satisfactory: 25` with citation keys `panarctic2020` and `bouregreg2011`.

| Metric | Calibration | Validation | Full Period | Bar (convention, cited) |
|--------|-------------|------------|-------------|-------------------------|
| `nse` for `discharge` | not stated in this KI body | not stated in this KI body | not stated in this KI body | `satisfactory >= 0.5`, `good >= 0.7`, `very_good >= 0.75` (`arnold2012`, `panarctic2020`, `bouregreg2011`) |
| `pbias` for `discharge` | not stated in this KI body | not stated in this KI body | not stated in this KI body | zero-centered: `satisfactory <= 25`, `good <= 15`, `very_good <= 10` (`panarctic2020`, `bouregreg2011`) |
| `r` for `tws` | not stated in this KI body | not stated in this KI body | not stated in this KI body | `satisfactory`: no cited threshold; citation keys: none in convention |

### Data Replacement Tracking

No per-case replacement-status table is stated in `docs/validation_convention.yaml` or in the extracted validated-results facts. For a run, record replacement status in the run artifact after preparing forcing, soil, static domain, observed discharge, and model outputs from the KI tools named above.

---

## File Structure

```
cwatm/
├── run_cwatm.py          # Main entry point (CLI parser, execution control)
├── cwatm_model.py        # CWATModel class (combines ini + dyn)
├── cwatm_initial.py      # Initialization (all modules setup)
├── cwatm_dynamic.py      # Timestep execution loop
├── metaNetcdf.xml        # Output variable metadata (CF conventions)
├── version.py            # Git version tracking
├── hydrological_modules/
│   ├── readmeteo.py      # Meteorological data reader + downscaling
│   ├── snow_frost.py     # Snow/ice/frost processes
│   ├── soil.py           # 3-layer soil water dynamics
│   ├── evaporationPot.py # Potential ET (Penman-Monteith)
│   ├── evaporation.py    # Actual ET partitioning
│   ├── groundwater.py    # Linear reservoir groundwater
│   ├── interception.py   # Canopy interception
│   ├── capillarRise.py   # Capillary rise from GW
│   ├── landcoverType.py  # Land cover fractions and dynamics
│   ├── inflow.py         # External inflow hydrographs
│   ├── runoff_concentration.py  # Runoff lag/concentration
│   ├── lakes_res_small.py       # Small lakes/wetlands
│   ├── lakes_reservoirs.py      # Large lakes and reservoirs
│   ├── sealed_water.py   # Impervious surface runoff
│   ├── environflow.py    # Environmental flow calculation
│   ├── waterquality1.py  # Water quality module
│   ├── routing_reservoirs/
│   │   ├── routing_kinematic.py  # Kinematic wave routing
│   │   ├── routing_sub.py        # Routing helper functions
│   │   ├── t5.cpp                # C++ routing acceleration
│   │   ├── t5_linux.so           # Pre-compiled Linux binary
│   │   └── t5.dll                # Pre-compiled Windows binary
│   ├── groundwater_modflow/
│   │   └── transient.py  # MODFLOW 6 coupling
│   └── water_demand/
│       ├── water_demand.py    # Water demand calculation
│       └── wastewater.py      # Wastewater treatment
└── management_modules/
    ├── configuration.py   # Settings file parser (ExtParser)
    ├── data_handling.py   # NetCDF/GeoTIFF I/O, spatial operations
    ├── dynamicModel.py    # Model framework (timestep control)
    ├── globals.py         # Global variables and dictionaries
    ├── output.py          # Output generation (TSS + maps)
    ├── timestep.py        # Date handling and timestep management
    ├── checks.py          # Input validation
    ├── messages.py        # Error and warning messages
    └── replace_pcr.py     # PCRaster compatibility functions
```
