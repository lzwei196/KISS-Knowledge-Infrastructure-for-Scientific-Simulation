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
| to run the pipeline stages | `tools/` (4 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (5 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (18 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (20 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/convert_meteo_forcing.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_meteo_forcing.py --help` |
| `tools/convert_soil_params.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_soil_params.py --help` |
| `tools/parse_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_output.py --help` |
| `tools/run_openamundsen.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_openamundsen.py --help` |

*4 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# openAMUNDSEN Knowledge Infrastructure

**Package**: hydrocraft-openamundsen-snow
**Version**: 1.0.0
**Created**: 2026-03-26
**Model**: openAMUNDSEN (fully distributed snow/hydroclimatological model)
**Domain**: Cryosphere — snow accumulation, ablation, energy balance in mountain regions
**Language**: Python (with Numba JIT acceleration)
**License**: MIT

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for atmospheric forcing documentation.
See `data_ki/SNOTEL/SKILL.md` for snow observations.
See `data_ki/BedMachine/SKILL.md` for ice topography.
See `data_ki/MEaSUREs/SKILL.md` for ice velocity.


## Overview

openAMUNDSEN is a fully distributed snow and hydroclimatological modeling framework designed
for mountain regions. It operates at spatial resolutions of 10–100 m and temporal resolutions
of 1–3 hours. The model simulates the complete snow mass and energy balance including:

- Spatial interpolation of meteorological station data (IDW, lapse rates)
- Solar radiation with terrain slope/orientation, hill shading, atmospheric transmission
- Precipitation phase partitioning (air temperature or wet-bulb temperature methods)
- Precipitation correction for wind-induced undercatch (WMO, Kochendorfer)
- Snow redistribution based on terrain factors (SRF method)
- Multilayer or cryolayer snow models with full energy balance
- Forest canopy snow interception, sublimation, and melt unloading
- Evapotranspiration via FAO Penman-Monteith
- Soil heat conduction through multiple layers
- Glacier mass balance (experimental, delta-h method)

**Key output variables**: SWE, snow depth, snow melt, runoff, sublimation, surface temperature,
albedo, radiation fluxes, evapotranspiration.

---

## Output Description

**Source of truth**: `dag.yaml`. This section restates the KI's dag facts for readers; if
this section and `dag.yaml` ever disagree, `dag.yaml` wins.

**Headline output** (`validation_rank: 1`):

`dag.yaml` rank-1 fact: `var='swe' unit='kg m-2' description='Snow water equivalent — mass of snow per unit area (CF surface_snow_amount).'`

> `swe` — Snow water equivalent — mass of snow per unit area (CF surface_snow_amount). (`kg m-2`)

| Output variable (dag `var`) | Unit | Description / role |
|-----------------------------|------|--------------------|
| `swe` | `kg m-2` | Snow water equivalent — mass of snow per unit area (CF surface_snow_amount). |
| `snow_depth` | see `dag.yaml` | Other dag output |
| `snow_cover` | area fraction / extent | Other dag output |
| `snow_melt` | see `dag.yaml` | Other dag output |
| `snow_runoff` | see `dag.yaml` | Other dag output |
| `snow_density` | see `dag.yaml` | Other dag output |
| `evapotranspiration` | see `dag.yaml` | Other dag output |

The dag's rank-1 output is `swe`. Other dag outputs are `snow_depth`,
`snow_cover` (area fraction / extent), `snow_melt`, `snow_runoff`,
`snow_density`, and `evapotranspiration`.

---

## Installation

```bash
# Recommended: conda
conda install --channel=conda-forge openamundsen

# Alternative: pip
python -m venv venv && source venv/bin/activate
pip install openamundsen

# From source
git clone https://github.com/openamundsen/openamundsen
cd openamundsen
pip install -e .
```

**Core dependencies**: numpy, pandas>=1.1, xarray>=0.14, netCDF4, rasterio>=1.1,
scipy, numba>=0.50.1, pyproj, ruamel.yaml>=0.15, cerberus, munch, pwlf

**Python version**: >= 3.10

**Binary location**: `openamundsen` CLI command (entry point from pip install)

**Test**: `openamundsen config.yml` — should run with example config

---

## Pipeline Stages

The openAMUNDSEN workflow proceeds through the following stages:

```
s1_grid_setup ──────────┐
                        ├──→ s3_configuration ──→ s4_model_init ──→ s5_execution
s2_meteo_preparation ───┘         │                     │               │
                                  │                     │               ▼
                           s6_output_config         canopy/ET      s7_output_parse
                                                    (optional)          │
                                                                        ▼
                                                                 s8_validation
```

### Stage Descriptions

| Stage | Name | Description | Tool |
|-------|------|-------------|------|
| s1 | Grid Setup | Prepare DEM and ROI as Arc/Info ASCII grids | `convert_grid_data.py` |
| s2 | Meteo Preparation | Convert meteorological data to model format (CSV or NetCDF) | `convert_meteo_forcing.py` |
| s3 | Configuration | Generate YAML configuration file | Manual / template |
| s4 | Model Init | Initialize model (reads grids, meteo, creates state vars) | `run_openamundsen.py` |
| s5 | Execution | Run simulation timesteps | `run_openamundsen.py` |
| s6 | Output Config | Define point/gridded output variables and frequencies | YAML config |
| s7 | Output Parse | Extract and convert results to CSV/plots | `parse_output.py` |
| s8 | Validation | Compare simulated vs observed SWE/snow depth | External |

---

## Unit Trap Table

**CRITICAL**: openAMUNDSEN expects specific units. Getting these wrong produces silent errors.

| Variable | Expected Unit | Common Mistake | Effect | Diagnostic |
|----------|--------------|----------------|--------|------------|
| `temp` | **K** (Kelvin) | Celsius (°C) | Snow forms at wrong temps, energy balance collapses | dt_001 |
| `precip` | **kg m⁻²** (mm per timestep) | mm/day, kg m⁻² s⁻¹ | Accumulation 24x too high or 3600x too low | dt_002 |
| `rel_hum` | **%** (0–100) | Fraction (0–1) | Near-zero humidity, sublimation/condensation wrong | dt_003 |
| `sw_in` | **W m⁻²** | kJ m⁻² h⁻¹, MJ m⁻² day⁻¹ | Radiation budget wrong, melt timing shifted | dt_004 |
| `wind_speed` | **m s⁻¹** | km h⁻¹ | Precipitation correction 3.6x too strong | dt_005 |
| `cloud_fraction` | **%** (0–100) | Fraction (0–1) | Auto-converted if max ≤ 1, but risky | dt_006 |
| `precip` (NetCDF) | **kg m⁻² s⁻¹** | kg m⁻² | Auto-converted via timestep, but only if units attr set | dt_007 |
| `altitude` | **m** (meters) | feet, km | Lapse rate corrections completely wrong | dt_008 |
| DEM elevation | **m** (meters) | cm, feet | Temperature interpolation breaks | dt_009 |
| `resolution` | **m** (integer) | km | Grid cell area 1e6x wrong | dt_010 |
| Soil thickness | **m** (meters) | cm | Soil heat flux 100x wrong | dt_011 |
| Snow density | **kg m⁻³** | g cm⁻³ | Density 1000x too low | dt_012 |
| Lapse rate | **K m⁻¹** (or per unit) | °C/100m, K/km | Interpolation gradients wrong | dt_013 |
| Coordinates (CSV) | **degrees** (WGS84) | Projected meters | Station location completely wrong | dt_014 |
| Timestep | **pandas freq** ("h","3h") | Seconds, minutes | Parsing error or wrong accumulation | dt_015 |

---

## Unit Table / Unit Conversion Table

**Source of truth**: `docs/format_spec.yaml`, `dag.yaml`, and the unit traps above. This table
summarizes the units this KI already documents; verify source-data attributes before converting
new forcing files.

| Variable | Model / dag unit | Common source or mistake | Conversion / handling documented by KI | Diagnostic |
|----------|------------------|--------------------------|----------------------------------------|------------|
| `swe` | `kg m-2` | none stated in extracted dag facts | rank-1 output unit from `dag.yaml` | n/a |
| `temp` | `K` | Celsius (`degC`) | add `273.15` when converting Celsius to Kelvin | dt_001 |
| `precip` (CSV forcing) | `kg m-2` per timestep | `mm/day`, `kg m-2 s-1` | provide per-timestep accumulation, not a daily total or rate | dt_002 |
| `precip` (NetCDF forcing) | `kg m-2 s-1` | `kg m-2` with missing or wrong `units` attribute | model auto-converts by timestep only when the units attribute is set | dt_007 |
| `rel_hum` | `%` (0-100) | fraction (0-1) | convert fraction to percent before forcing preparation | dt_003 |
| `sw_in` | `W m-2` | `kJ m-2 h-1`, `MJ m-2 day-1` | convert to instantaneous flux before model input | dt_004 |
| `wind_speed` | `m s-1` | `km h-1` | divide `km h-1` by `3.6` | dt_005 |
| `cloud_fraction` | `%` (0-100) | fraction (0-1) | convert to percent explicitly; auto-conversion is fragile | dt_006 |
| `altitude` | `m` | feet, km | convert to meters before station/grid ingestion | dt_008 |
| DEM elevation | `m` | cm, feet | convert to meters and preserve DEM filename convention | dt_009 |
| `resolution` | `m` | km | convert kilometers to meters before configuration | dt_010 |
| Soil thickness | `m` | cm | divide centimeters by `100` | dt_011 |
| Snow density | `kg m-3` | `g cm-3` | multiply `g cm-3` by `1000` | dt_012 |
| Lapse rate | `K m-1` | `degC/100m`, `K/km` | convert gradients to per-meter units | dt_013 |
| Coordinates (CSV) | degrees (WGS84) | projected meters | set `meteo.crs` to match station coordinates or transform coordinates | dt_014 |
| Timestep | pandas frequency string (`h`, `3h`) | seconds, minutes | use pandas-compatible frequency strings in config | dt_015 |

Output units to verify after every run:

- `swe`: `kg m-2`, from `dag.yaml`.
- `snow_depth`, `snow_cover`, `snow_melt`, `snow_runoff`, `snow_density`,
  and `evapotranspiration`: listed as dag outputs; read their exact units from
  `dag.yaml` and output NetCDF attributes before post-processing.

---

## Tools Reference

| Tool | Stage | Path | Lines | Purpose |
|------|-------|------|-------|---------|
| `convert_meteo_forcing.py` | s2 | `tools/convert_meteo_forcing.py` | ~280 | Convert global reanalysis data to openAMUNDSEN CSV/NetCDF format |
| `convert_soil_params.py` | s1 | `tools/convert_soil_params.py` | ~200 | Convert HWSD soil data to model soil parameters |
| `run_openamundsen.py` | s4-s5 | `tools/run_openamundsen.py` | ~220 | Execute model with preflight checks and error capture |
| `parse_output.py` | s7 | `tools/parse_output.py` | ~250 | Extract NetCDF/CSV results to analysis-ready format |

---

## Skill Knowledge Cross-Reference

| Knowledge Area | Skill Document | Key Traps |
|----------------|---------------|-----------|
| Grid setup | `docs/s1_grid_setup.md` | DEM must be Arc/Info ASCII, projected CRS |
| Meteorological forcing | `docs/s2_meteo_forcing.md` | dt_001–dt_007 (unit conversions) |
| Configuration | `docs/s3_configuration.md` | dt_010, dt_013, dt_015 |
| Model execution | `docs/s4_model_execution.md` | Runtime errors, memory issues |
| Output analysis | `docs/s5_output_analysis.md` | Variable naming, aggregation traps |

---

## Critical Domain Knowledge

These are non-obvious facts that cause silent failures if ignored:

1. **Temperature MUST be in Kelvin** (dt_001): The model uses T0=273.15 K internally.
   Input filters reject temp < 200 K, so Celsius values (e.g., -10°C) are silently clipped
   to NaN, causing interpolation failure.

2. **Precipitation is per-timestep accumulation, not rate** (dt_002): For CSV input,
   precip is kg m⁻² per timestep (e.g., mm per hour). For NetCDF with units="kg m-2 s-1",
   the model auto-converts by multiplying by timestep seconds. Mixing these up causes
   massive over/under-accumulation.

3. **Station coordinates in CSV mode must be WGS84 lon/lat** (dt_014): The `meteo.crs`
   config must match the station coordinate system. If stations.csv has projected coords
   but crs is set to epsg:4326, stations map to wrong locations.

4. **DEM filename convention is strict** (dt_009): Must be `dem_{domain}_{resolution}.asc`
   where domain and resolution match the config exactly.

5. **Lapse rates are in K/m, not K/100m or K/km** (dt_013): Monthly lapse rate arrays
   in config are per meter. A typical value is 0.0065 K/m (6.5 K/km). Using 6.5 directly
   means 6500 K/km — temperatures crash.

6. **Input filter silently replaces out-of-range values with NaN** (dt_003): If humidity
   is 0–1 fraction instead of 0–100%, values are clipped to NaN by the default filter
   (min=1, max=100). No error is raised.

7. **Cloud fraction auto-conversion is fragile** (dt_006): The model converts fraction
   (0–1) to percent only if max(cloud_fraction) ≤ 1 AND len(data) > 10. Short time
   series or already-percent data bypass conversion.

8. **Wind speed minimum is 0.1 m/s** (dt_005): Values below 0.1 are clipped. This
   prevents division-by-zero in turbulent exchange but affects calm-wind statistics.

9. **Snow model choice affects layer structure** (dt_016): "multilayer" uses explicit
   thickness layers; "cryolayers" uses categorical transitions (new→old→firn→ice).
   Switching models mid-calibration invalidates all tuned parameters.

---

## Configuration Reference

Minimal YAML configuration:

```yaml
domain: my_catchment
start_date: 2020-10-01
end_date: 2021-09-30
resolution: 50
timestep: 3h
crs: "epsg:32632"
timezone: 1

input_data:
  grids:
    dir: ./input/grid
  meteo:
    dir: ./input/meteo
    format: csv
    crs: "epsg:4326"

output_data:
  timeseries:
    format: netcdf
    add_default_variables: true
    points:
      - x: 642579
        y: 5193069
        name: station_A

snow:
  model: multilayer
  melt:
    method: energy_balance

results_dir: ./output
```

---

## Calibration Parameters (Priority Order)

| Parameter | Config Path | Range | Default | Effect |
|-----------|------------|-------|---------|--------|
| Albedo max | `snow.albedo.max` | 0.75–0.95 | 0.85 | Fresh snow reflectance |
| Albedo min | `snow.albedo.min` | 0.40–0.65 | 0.55 | Old snow reflectance |
| Cold decay timescale | `snow.albedo.cold_snow_decay_timescale` | 100–1000 h | 480 | Albedo aging rate (cold) |
| Melt decay timescale | `snow.albedo.melting_snow_decay_timescale` | 50–500 h | 200 | Albedo aging rate (melt) |
| Refresh snowfall | `snow.albedo.refresh_snowfall` | 0.1–2.0 kg m⁻² h⁻¹ | 0.5 | Snowfall to reset albedo |
| Thermal conductivity | `snow.thermal_conductivity` | 0.1–0.5 W m⁻¹ K⁻¹ | 0.24 | Snow heat conduction |
| Precipitation lapse | `meteo.interpolation.precipitation.lapse_rate` | varies | monthly | Precip elevation gradient |
| Temperature lapse | `meteo.interpolation.temperature.lapse_rate` | varies | monthly | Temp elevation gradient |
| Degree-day factor | `snow.melt.degree_day_factor` | 0.5–6.0 mm °C⁻¹ d⁻¹ | varies | Melt rate (temp-index only) |
| Precipitation threshold | `meteo.precipitation_phase.threshold_temp` | 272–275 K | 273.65 | Rain/snow partition |

---

## Data Requirements

| Data Type | Source | Format | Required |
|-----------|--------|--------|----------|
| DEM | SRTM, ASTER, LiDAR | Arc/Info ASCII (.asc) | Yes |
| ROI mask | User-defined | Arc/Info ASCII (.asc) | No |
| Station meteorology | Weather stations | CSV or NetCDF | Yes |
| Station metadata | stations.csv | CSV (id, name, x, y, alt) | Yes (CSV mode) |
| Land cover | CORINE, ESA CCI | Arc/Info ASCII (.asc) | No |
| Soil parameters | HWSD | YAML config or grid | No |

---

## Quick Start

```bash
# 1. Prepare grid data
cp dem_mydomain_50.asc input/grid/
cp roi_mydomain_50.asc input/grid/   # optional

# 2. Prepare meteorological data (CSV format)
# Place station CSV files in input/meteo/ with stations.csv

# 3. Create configuration
# Edit config.yml (see Configuration Reference above)

# 4. Run model
openamundsen config.yml

# 5. Analyze output
python parse_output.py --results-dir ./output --format csv
```

---

## Diagnostic Triplets Summary

| ID | Stage | Severity | Issue |
|----|-------|----------|-------|
| dt_001 | s2 | silent | Temperature in °C instead of K |
| dt_002 | s2 | silent | Precipitation unit mismatch (rate vs accumulation) |
| dt_003 | s2 | silent | Relative humidity as fraction (0–1) not percent |
| dt_004 | s2 | silent | Shortwave radiation unit mismatch |
| dt_005 | s2 | degraded | Wind speed in km/h instead of m/s |
| dt_006 | s2 | silent | Cloud fraction auto-conversion failure |
| dt_007 | s2 | silent | NetCDF precip units attribute missing |
| dt_008 | s1 | silent | Station altitude in wrong unit |
| dt_009 | s1 | fatal | DEM filename does not match config domain/resolution |
| dt_010 | s3 | fatal | Resolution in km instead of m |
| dt_011 | s3 | silent | Soil thickness in cm instead of m |
| dt_012 | s3 | silent | Snow density initialization in g/cm³ |
| dt_013 | s3 | silent | Lapse rate in K/km instead of K/m |
| dt_014 | s2 | fatal | Station coordinates in projected CRS but config says WGS84 |
| dt_015 | s3 | fatal | Invalid timestep string |
| dt_016 | s5 | degraded | Snow model switch invalidates calibration |
| dt_017 | s4 | fatal | No stations within grid extent |
| dt_018 | s5 | degraded | Canopy enabled but no land cover grid |

---

## Validated Results

**Source of truth**: `docs/validation_convention.yaml`. This section restates the
convention bars supplied by the KI. Do not judge a model run by intuition; compare run
metrics against these cited bands. If a convention band is null, write `no cited threshold`.

### Headline Output: `swe`

`swe` is the dag rank-1 output: Snow water equivalent — mass of snow per unit area
(CF surface_snow_amount). Unit: `kg m-2`.

| Dag variable | Metric | Direction | Satisfactory band | Good band | Very good band | Citation keys |
|--------------|--------|-----------|-------------------|-----------|----------------|---------------|
| `swe` | `nse` | maximize | `>= 0.76` (`strasser2024`) | `>= 0.93` (`strasser2024`) | `>= 0.95` (`strasser2024`) | `strasser2024` |
| `swe` | `rmse` | minimize | `<= 76.0` (`strasser2024`, `wever2015`) | `<= 55.0` (`strasser2024`, `wever2015`) | `<= 46.0` (`strasser2024`, `wever2015`) | `strasser2024`, `wever2015` |
| `swe` | `csi` | maximize | no cited threshold | no cited threshold | no cited threshold | none |

### Additional Convention Bars

| Dag variable | Metric | Direction | Satisfactory band | Good band | Very good band | Citation keys |
|--------------|--------|-----------|-------------------|-----------|----------------|---------------|
| `snow_depth` | `nse` | maximize | `>= 0.7` (`strasser2024`) | `>= 0.79` (`strasser2024`) | `>= 0.92` (`strasser2024`) | `strasser2024` |
| `snow_depth` | `rmse` | minimize | `<= 0.283` (`strasser2024`, `wever2015`) | `<= 0.269` (`strasser2024`, `wever2015`) | `<= 0.186` (`strasser2024`, `wever2015`) | `strasser2024`, `wever2015` |

Achieved calibration, validation, and full-period metric values are run outputs, not
convention bars. Record them only when produced by this KI's execution and validation tools,
then compare them against the cited bands above.

---

## File Structure

```
ki/
├── SKILL.md                          # This file
├── tools/
│   ├── convert_meteo_forcing.py      # Reanalysis → openAMUNDSEN meteo format
│   ├── convert_soil_params.py        # HWSD → model soil parameters
│   ├── run_openamundsen.py           # Execution wrapper with preflight checks
│   └── parse_output.py               # NetCDF/CSV result extraction
├── docs/
│   ├── s1_grid_setup.md              # DEM and ROI preparation
│   ├── s2_meteo_forcing.md           # Meteorological data conversion
│   ├── s3_configuration.md           # YAML configuration guide
│   ├── s4_model_execution.md         # Running the model
│   └── s5_output_analysis.md         # Output parsing and validation
└── diagnostics/
    └── triplets.yaml                 # 18 symptom→diagnosis→remedy entries
```
