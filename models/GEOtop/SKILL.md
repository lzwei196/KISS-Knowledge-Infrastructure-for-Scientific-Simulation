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
| on ANY error, before debugging | `diagnostics/triplets.yaml` (25 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (24 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/build_domain.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/build_domain.py --help` |
| `tools/convert_forcing.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing.py --help` |
| `tools/convert_soil.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_soil.py --help` |
| `tools/parse_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_output.py --help` |
| `tools/read_modis_lst.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/read_modis_lst.py --help` |
| `tools/run_geotop.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_geotop.py --help` |

*6 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# GEOtop Knowledge Infrastructure

| Field            | Value                                                    |
|------------------|----------------------------------------------------------|
| Package          | GEOtop v3.0                                              |
| Domain           | Hydrology / Land-surface energy-water balance             |
| Language          | C++11                                                    |
| Build System      | CMake 3.0+ (also Meson)                                 |
| Last Updated      | 2026-07-21                                               |
| Tools             | 6                                                        |
| Skill Documents   | 5                                                        |
| Diagnostic Triplets| 25                                                      |

---

## Data Preparation

All forcing / soil / observation access goes through **`ki_tools_common`** plus this
KI's own `tools/`. The old `data_ki/<X>/tools/...` and `data_ki/<X>/SKILL.md`
references were removed in KDT 5.0 — do NOT look for them.

### Forcing data

| Region | Dataset | Path | Native step |
|--------|---------|------|-------------|
| **China** | CMFD V2.0 0.1° | `KISSPATH_FORCING/Data_forcing_03hr_010deg/` | 3-hourly |
| China (daily models) | CMFD V2.0 0.1° | `KISSPATH_FORCING/Data_forcing_01dy_010deg/` | daily |
| Global | MSWX 0.1° | `KISSPATH_FORCING/` | 3-hourly |
| Point fallback | NASA POWER | online API | hourly |

**A China basin must use local CMFD.** NASA POWER is daily-only, routes through the
local proxy and stalls at 0/N. Working invocation (verified 2026-07-21, NCP pixel):

```bash
python tools/convert_forcing.py --source cmfd \
    --input KISSPATH_FORCING/Data_forcing_03hr_010deg \
    --lat 36.0 --lon 116.0 --start "01/11/2017 00:00" --end "01/02/2018 00:00" \
    --dt 10800 --output <sim>/meteo/meteo0001.txt
```

`--source cmfd` routes through `ki_tools_common.load_forcing.load_hourly_forcing`,
which knows the per-variable subdirectory layout (`Temp/ Prec/ SRad/ LRad/ Wind/
SHum/ Pres/`, one file per month) and the unit conversions (K→°C,
precip kg/m²/s → mm per 3-h step).

**Set `--dt` to the forcing's NATIVE step** (CMFD/MSWX 3-hourly → `10800`, daily →
`86400`). Any change of record spacing has to redistribute Iprec as a *depth*, not
interpolate it — see dt_022. GEOtop interpolates between meteo records internally,
so a coarser meteo file does not force a coarser `TimeStepEnergyAndWater`.

**CMFD timestamps are UTC.** Verified at 36 N/116 E: the SRad diurnal peak falls at
03–06 UTC, bracketing solar noon 12:00 − 116/15 = 04:27 UTC. So set both
`StandardTimeSimulation = 0` and `MeteoStationStandardTime = 0` (Greenwich).
Getting this wrong shifts the whole solar cycle — see dt_021.

### Soil data

`python tools/convert_soil.py --source hwsd --lat <lat> --lon <lon> --layers <mm,...>`
resolves HWSD through `ki_tools_common.soil_utils.lookup_hwsd` (hwsd.bil raster →
MU_GLOBAL → attribute table). `--input` is optional and only overrides the raster
path. Use `--source manual` only when the site is genuinely outside HWSD.

### Observations

`tools/read_modis_lst.py` extracts MOD11A2 land surface temperature at a point from
`KISSPATH_DATA/obs/nasa/modis_lst/` (sinusoidal reprojection, scale factors, QC
bits, local-solar view times, clear-sky counts). See §13.


## 1. Overview

GEOtop is a physically-based, distributed model of the mass and energy balance of the
hydrological cycle. It couples the energy budget at the land surface with the water budget
in the soil, accounting for snow/glacier dynamics, vegetation, radiation, and turbulent
heat fluxes. The model is designed for complex terrain (mountain catchments) where
topographic effects on radiation, wind, and snow redistribution are important.

**Key capabilities:**
- Coupled energy-water balance solved at sub-hourly time steps (default 900 s)
- 3D Richards equation for unsaturated/saturated zone flow
- Multi-layer snow model with compaction, melt, albedo aging
- Glacier module with accumulation/ablation
- Vegetation energy partitioning (two-layer canopy + ground)
- Radiation model with sky view factor, cast shadows, horizon obstruction
- Blowing snow redistribution (PBSM parameterization)
- Point (1D column) and distributed (3D catchment) simulation modes

**Primary use cases:**
- Alpine/mountain hydrology with snow and permafrost
- Soil temperature and moisture profile simulation
- Surface energy balance studies (radiation, sensible/latent heat)
- Evapotranspiration and soil-vegetation-atmosphere transfer

---

## 2. Installation

### Binary Build (CMake)
```bash
cd /path/to/geotop/source/repo
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=RELEASE
make -j$(nproc)
# Binary: build/geotop
```

### Optional Flags
| Flag               | Purpose                                      |
|--------------------|----------------------------------------------|
| `-DWITH_METEOIO=ON`| Enable MeteoIO library for met interpolation |
| `-DMETEOIO_DIR=...`| Path to MeteoIO installation prefix          |
| `-DWITH_OMP=ON`    | Enable OpenMP parallelization (Meson only)   |
| `-DMUTE_GEOLOG=ON` | Suppress log output                          |

### Dependencies
- C++11 compiler (GCC >= 4.8, Clang >= 3.3)
- CMake >= 3.0
- No external library dependencies (all included in source tree)
- Optional: MeteoIO, OpenMP, numdiff (for tests)

### Test
```bash
cd build && ctest -R Matsch_B2_Ref_007 --output-on-failure
```

---

## 3. Pipeline Stages

| Stage | Name                    | Depends On       | Parallel | Description                                     |
|-------|-------------------------|------------------|----------|-------------------------------------------------|
| s0    | Configuration           | --               | --       | Set basin location, period, resolution, paths   |
| s1    | Domain / Grid Setup     | --               | yes      | Define DEM, slope, aspect, sky view factor maps |
| s2    | Soil Parameters         | s1               | yes      | Derive Van Genuchten params from HWSD/SoilGrids |
| s3    | Vegetation / Land Cover | s1               | yes      | Classify land cover, set LSAI, root depth       |
| s4    | Meteorological Forcing  | s1               | yes      | Convert CMFD/MSWX/ERA5 to meteoXXXX.txt format |
| s5    | Model Parameters        | s2, s3           | no       | Write geotop.inpts with all 455+ keywords       |
| s6    | Model Execution         | s4, s5           | no       | Run `./geotop <sim_folder>`                     |
| s7    | Output Parsing          | s6               | no       | Extract time series from output-tabs/            |
| s8    | Validation              | s7               | no       | Compare with observations, compute metrics      |

**Stages s1-s4 can run in parallel** since they prepare independent input files.

---

## 4. Tool Reference

| Stage | Tool Script                     | Purpose                                       |
|-------|---------------------------------|-----------------------------------------------|
| s1    | `tools/build_domain.py`         | DEM → basin delineation → ESRI-ASCII input maps (distributed mode only) |
| s2    | `tools/convert_soil.py`         | HWSD/SoilGrids → GEOtop soil CSV (Van Genuchten) |
| s4    | `tools/convert_forcing.py`      | CMFD/MSWX/NASA POWER → GEOtop meteo CSV       |
| s6    | `tools/run_geotop.py`           | Execute GEOtop binary with timeout/logging    |
| s7    | `tools/parse_output.py`         | Extract basin/point/soil/snow outputs to tidy CSV |
| s8    | `tools/read_modis_lst.py`       | MOD11A2 LST at a point (obs side of an LST validation) |

---

## 5. Critical Domain Knowledge

### 5.1 Unit Trap: Soil Layer Thickness in MILLIMETERS (dt_001)
GEOtop expects soil layer thickness `Dz` in **millimeters**, not meters.
A 10 cm layer = 100 mm. If you write 0.1 (meters), the model creates a 0.1 mm layer
and the Richards solver diverges within seconds.

### 5.2 Unit Trap: Hydraulic Conductivity in m/s (dt_002)
Van Genuchten `Kh` and `Kv` are in **m/s** (not mm/hr or cm/day).
HWSD often reports Ksat in cm/day: divide by 86400 and then by 100.
Typical range: 1E-7 to 1E-3 m/s.

### 5.3 Unit Trap: Alpha in 1/mm (dt_003)
Van Genuchten `alpha` in the soil file is in **1/mm** (not 1/cm or 1/m).
Literature values are usually in 1/cm: divide by 10 to convert to 1/mm.
The test case uses alpha=0.00131 (1/mm) which is 0.0131 (1/cm).

### 5.4 Unit Trap: Precipitation in mm (dt_004)
Meteorological forcing `Iprec` is **precipitation intensity in mm** over the time step.
If your forcing is in mm/hr and time step is 900 s, multiply by 0.25.
If forcing is in m/s (like some reanalyses), multiply by 1000*dt.

### 5.5 Unit Trap: Relative Humidity in PERCENT (dt_005)
`RelHum` in meteo files must be **0-100 (percent)**, not 0-1 fraction.
ERA5 provides specific humidity (kg/kg) which needs conversion.
CMFD provides as percent already.

### 5.6 Date Format is DD/MM/YYYY hh:mm (dt_006)
GEOtop uses European date format: day first, then month.
Using MM/DD/YYYY silently misparses dates.
The InitDate/EndDate in geotop.inpts and the Date column in meteo files must match.

### 5.7 Nodata Value is -9999 (dt_007)
Missing values in meteo files must be exactly `-9999` (not NaN, -999, or blank).
GEOtop silently uses 0 for unrecognized nodata, causing flat temperature/radiation.

### 5.8 Vegetation Height in mm (dt_008)
`VegHeight` is in **millimeters**. A 4 m tree = 4000 mm.
The test case uses VegHeight=400 mm for meadow grass (0.4 m).

### 5.9 geotop.inpts Uses TAB Separators (dt_009)
The configuration file uses `key<TAB>=<TAB>value` format.
Some editors convert tabs to spaces, which may cause parse failures.
Comments start with `!`.

### 5.10 JDfrom0 Carries the Solar Clock (dt_021)
GEOtop takes the sun's position from the **fractional part of `JDfrom0`**, not from
the `Date` column: `h = (JDfrom0 - floor(JDfrom0))*24 + lon/15 - StandardTime + Et`
(`radiation.cc::SolarHeight`). So `frac(JDfrom0)*24` **must equal the hour of day**
— midnight is `.0000`, 01:00 is `.0417`. A fractional day offset (e.g. `365.25+1`)
silently shifts the sun by 6 h: the shortwave pulse lands hours after true solar
noon, daytime skin temperature comes out ~10 K too cold, and air temperature —
which GEOtop reads directly — still looks fine. Anchor against the shipped test
`tests/1D/Matsch_B2_Ref_007`: `02/10/2009 00:00 = 734047.0000`.

### 5.11 Iprec Is an Accumulated Depth, Not a Rate (dt_004, dt_022)
The value on the record at time *t* is the depth accumulated over *(t−dt, t]*.
GEOtop derives the intensity itself (`meteodata.cc::fill_Pint` divides by the
record spacing). Two consequences: (a) never rescale Iprec "to an intensity";
(b) if you change the record spacing you must redistribute the depth (split on
upsample, sum on downsample) — interpolating it multiplies total precipitation by
`native_step / target_step`.

### 5.12 Horizon Files Are Required for Radiation (dt_010)
If `FlagSkyViewFactor=1` and `HorizonMeteoStationFile` is set, the horizon file
must exist. Missing it silently sets all horizon angles to 0, overpredicting solar input.

---

## 6. Output Description

**Source of truth: `dag.yaml`.** The dag is the contract for what GEOtop predicts
and how outputs are named. If this section ever disagrees with `dag.yaml`, the dag
wins and this body text must be corrected.

**Headline output** (`validation_rank: 1` in `dag.yaml`):

> `discharge` -- Catchment discharge at the basin outlet from the channel network. (`m3/s`)

| Output variable (dag `var`) | rank | Unit | Description |
|-----------------------------|------|------|-------------|
| `discharge` | 1 | `m3/s` | Catchment discharge at the basin outlet from the channel network. |

Other dag outputs named by this KI are: `SWE`, `snowDepth`, `soilTz`,
`thetaliq`, `thetaice`, `LE`, `H`, and `Tsurface`.

---

## 6a. Input File Specifications

### 6.1 geotop.inpts (Main Configuration)
- **Format**: Key-value pairs, TAB-separated, `!` comments
- **455+ keywords** defined in `src/geotop/keywords.h`
- Controls simulation period, physics toggles, file paths, all parameters

### 6.2 meteoXXXX.txt (Meteorological Forcing)
- **Format**: CSV with header row
- **Columns**: Date, JDfrom0, Iprec(mm), WindSp(m/s), WindDir(deg), RelHum(%), AirT(C), Swglobal(W/m2), CloudTrans(0-1), [LWin(W/m2), DewT(C), AirPress(mbar)]
- **Nodata**: -9999
- **One file per station**: meteo0001.txt, meteo0002.txt, ...

### 6.3 soilXXXX.txt (Soil Properties)
- **Format**: CSV with header row
- **Columns**: Dz(mm), Kh(m/s), Kv(m/s), vwc_r(-), vwc_w(-), vwc_fc(-), vwc_s(-), alpha(1/mm), n(-), stor(1/m)
- **One row per layer**, top to bottom
- **One file per point**: soil0001.txt, soil0002.txt, ...

### 6.4 DEM and Maps (ESRI ASCII Grid)
- dem.txt, slope.txt, aspect.txt, sky.txt, curvature.txt
- Standard ESRI ASCII format: ncols, nrows, xllcorner, yllcorner, cellsize, NODATA_value

### 6.5 horizonXXXX.txt
- **Columns**: AngleFromNorthClockwise(deg), HorizonHeight(deg)
- Azimuth angles (0-360) and corresponding horizon elevation angles

---

## 7. Output File Specifications

### 7.1 Basin-Averaged (output-tabs/basin.txt)
- CSV with columns: Date, JDfrom0, TimeFromStart, Prain, Psnow, Pnet, Tair, Tsurface,
  Evap, Transpiration, LE, H, SW, LW, SWin, LWin, MassBalError, MeanTimeStep
- Units: mm for water fluxes, W/m2 for energy, C for temperature, s for time step

### 7.2 Point Output (output-tabs/pointXXXX.txt)
- Same structure as basin but for single observation points
- Higher resolution temporal output available

### 7.3 Soil Profiles (output-tabs/soilTzXXXX.txt, thetaliqXXXX.txt, etc.)
- Matrix format: rows=time steps, columns=soil layers
- soilTz: temperature (C), thetaliq: volumetric water content (-), thetaice: ice content (-), psiz: matric potential (mm)

### 7.4 Snow Profiles (output-tabs/snowTXXXX.txt, snowDepthXXXX.txt, etc.)
- Matrix format: rows=time steps, columns=snow layers
- Temperature (C), depth (mm), ice content (kg/m2), liquid content (kg/m2)

### 7.5 Discharge (output-tabs/discharge.txt)
- Time series of catchment discharge
- Units: m3/s

---

## 8. Unit Conversion Table

Exact I/O shapes live in `docs/format_spec.yaml`; regenerate that file from the KI
instead of hand-editing it. This table restates unit conversions already documented
in this body and the output unit from `dag.yaml`.

| Variable | Source unit / representation | Model or KI unit | Conversion | Type |
|----------|------------------------------|------------------|------------|------|
| CMFD precipitation | `kg/m2/s` | `mm` per 3-hour step | multiply by `10800` | accumulated depth |
| CMFD temperature | `K` | `C` | subtract `273.15` | additive |
| CMFD shortwave radiation | `W/m2` | `W/m2` | none | identity |
| CMFD longwave radiation | `W/m2` | `W/m2` | none | identity |
| CMFD relative humidity | percent | percent | none | identity |
| MSWX precipitation | `mm/3hr` | `mm` per 3-hour step | no multiplication; sum 8 steps for daily totals | accumulated depth |
| MSWX temperature | `C` | `C` | none | identity |
| Soil layer thickness `Dz` | meters or centimeters in outside sources | `mm` | convert to millimeters before writing `soilXXXX.txt` | length |
| Hydraulic conductivity `Kh`, `Kv` | `cm/day` in HWSD-style sources | `m/s` | divide by `86400` and then by `100` | rate |
| Van Genuchten `alpha` | `1/cm` in many literature tables | `1/mm` | divide by `10` | inverse length |
| Vegetation height `VegHeight` | meters in land-cover sources | `mm` | multiply by `1000` | length |
| Rank-1 output `discharge` | `output-tabs/discharge.txt` | `m3/s` | read as written | dag output unit |

---

## 8a. Calibration Parameters (Priority Order)

| Priority | Parameter                    | Typical Range    | Units    | Sensitivity          |
|----------|------------------------------|------------------|----------|----------------------|
| 1        | NormalHydrConductivity (Kv)  | 1E-7 to 1E-3    | m/s      | Controls infiltration|
| 2        | AlphaVanGenuchten            | 0.0001-0.01      | 1/mm     | Retention curve shape|
| 3        | NVanGenuchten                | 1.1-3.0          | -        | Retention curve shape|
| 4        | SnowCorrFactor               | 0.5-2.0          | -        | Precipitation bias   |
| 5        | ThresTempRain/Snow           | -5 to 5          | C        | Rain-snow partition  |
| 6        | SoilRoughness                | 10-1000          | mm       | Surface runoff       |
| 7        | MinStomatalRes               | 10-200           | s/m      | Transpiration rate   |
| 8        | LSAI                         | 0.5-8.0          | m2/m2    | Canopy interception  |
| 9        | FreshSnowReflVis             | 0.7-0.95         | -        | Snow melt timing     |
| 10       | InitWaterTableDepth          | 100-5000         | mm       | Initial soil moisture|

---

## 9. Diagnostic Triplets Summary

| Failure Domain   | Count | Silent | Fatal | Degraded |
|------------------|-------|--------|-------|----------|
| unit_conversion  | 9     | 8      | 1     | 0        |
| parameter_format | 5     | 2      | 2     | 1        |
| file_structure   | 4     | 2      | 2     | 0        |
| runtime          | 3     | 0      | 2     | 1        |
| initialization   | 3     | 2      | 0     | 1        |
| **Total**        | **25**| **14** | **7** | **3**    |

56% of failures are **silent** -- the model runs without error but produces wrong results.
See `diagnostics/triplets.yaml` for full symptom-diagnosis-remedy entries.

---

## 10. Coupling Points

### Upstream Data Sources
| Source            | Variables                          | Tool                    |
|-------------------|------------------------------------|-------------------------|
| CMFD/MSWX/ERA5   | AirT, Precip, Wind, RH, SW, LW    | `convert_forcing.py`    |
| HWSD/SoilGrids   | Sand/Silt/Clay, Ksat, BD, OC      | `convert_soil.py`       |
| SRTM/MERIT DEM   | Elevation grid                     | External GIS processing |
| MODIS/AVHRR      | Land cover, LSAI                   | External classification |

### Downstream Models
| Model             | Variable Provided                   | Format                  |
|-------------------|------------------------------------|-------------------------|
| River routing     | Surface runoff, baseflow            | CSV time series         |
| Crop models       | Soil moisture, soil temperature     | CSV profiles            |
| Glacier models    | Snow/glacier mass balance           | CSV time series         |
| Atmospheric models| Surface fluxes (H, LE, LW)         | CSV time series         |

---

## 11. Validated Results

**Source of truth for judgment bars: `docs/validation_convention.yaml`.** These
thresholds are the field convention used by this KI; do not replace them with
remembered hydrology thresholds. A run is not graded by intuition.

### Headline Output Bar

The dag's rank-1 output is `discharge`, with unit `m3/s` and description:
"Catchment discharge at the basin outlet from the channel network."

| Dag variable | Metric | Direction | Bands from convention |
|--------------|--------|-----------|-----------------------|
| `discharge` | `nse` | maximize | satisfactory `0.5` (`moriasi2015`, `schuol2012`); good `0.7` (`moriasi2015`, `schuol2012`); very_good `0.8` (`moriasi2015`, `schuol2012`) |
| `discharge` | `pbias` | zero_centered | satisfactory `15` (`moriasi2015`); good `10` (`moriasi2015`); very_good `5` (`moriasi2015`) |

### Other Convention Bars Carried by This KI

| Dag variable | Metric | Direction | Bands from convention |
|--------------|--------|-----------|-----------------------|
| `SWE` | `rmse` | minimize | satisfactory `95` (`endrizzi2014`, `terzago2020`, `avanzi2023`); good `40` (`endrizzi2014`, `terzago2020`, `avanzi2023`); very_good `37.1` (`endrizzi2014`, `terzago2020`, `avanzi2023`) |
| `SWE` | `pbias` | zero_centered | satisfactory `17.3` (`endrizzi2014`, `avanzi2023`); good `8.5` (`endrizzi2014`, `avanzi2023`); very_good `3.2` (`endrizzi2014`, `avanzi2023`) |
| `SWE` | `rmse` | minimize | satisfactory `300` (`avanzi2023`); good `200` (`avanzi2023`); very_good `95` (`avanzi2023`) |

### Achieved Results Recorded in This Body

The body currently records two validation anchors below: the repository reference
case `tests/1D/Matsch_B2_Ref_007`, and an end-to-end North China Plain point
recipe comparing `Tsurface` against MODIS MOD11A2. The field bars above are the
cited convention bars extracted for `discharge` and `SWE`; no discharge achieved
metric is stated in this body section.

---

## 11a. File Structure

```
ki/
|-- SKILL.md                          # This file
|-- tools/
|   |-- convert_forcing.py            # s4: Met data -> GEOtop meteo CSV
|   |-- convert_soil.py               # s2: HWSD/SoilGrids -> GEOtop soil CSV
|   |-- run_geotop.py                 # s6: Execute model binary
|   |-- parse_output.py               # s7: Extract outputs to tidy CSV
|-- docs/
|   |-- s1_domain_setup.md            # Domain/DEM preparation
|   |-- s2_soil_parameters.md         # Soil parameter derivation
|   |-- s4_forcing_preparation.md     # Met forcing conversion
|   |-- s6_model_execution.md         # Running the model
|   |-- s7_output_parsing.md          # Interpreting and extracting outputs
|-- diagnostics/
|   |-- triplets.yaml                 # 20 symptom-diagnosis-remedy entries
```

---

## 12. Validation Results

### Test Site: Matsch Valley Station B2 (South Tyrol, Italy)
- **Location**: 46.668N, 10.579E, elevation 1480 m
- **Period**: October 2009 (1 month)
- **Forcing**: In-situ meteorological observations (hourly)
- **Land cover**: Alpine meadow (VegHeight=400 mm, LSAI=4)
- **Soil**: 16 layers, 10-150 mm thickness, total depth 1000 mm
- **Time step**: 900 s

Reference test case from GEOtop repository (`tests/1D/Matsch_B2_Ref_007`).
This is a point simulation (1D column) exercising energy balance, water balance,
and snow processes over a representative Alpine grassland site.

---

## 13. Validated Recipe: Point LST vs MODIS MOD11A2

Reproduced end-to-end 2026-07-21 at the **North China Plain cropland pixel**
(36.0 N, 116.0 E, 44 m, MODIS tile h27v05), Nov 2017 spin-up → Jan 2018:

| Metric | Value |
|--------|-------|
| NSE  | **0.601** |
| r    | **0.968** |
| KGE  | 0.447 |
| PBIAS| +0.62 % |
| RMSE | 4.18 K |
| n    | 8 (4 windows × day+night) |

Uncalibrated. Water balance closes: P 23.3 − ET 35.4 − ΔS (−12.3) = 0.1 mm
residual (0.6 %), GEOtop's own cumulative `Mass_balance_error` = 0.0004 mm.
Runner: `models/GEOtop/run_and_score.py` (resumable at every stage).

### The chain

1. **s0** `ki_tools_common.terrain.get_terrain` → elevation. Force slope/aspect = 0
   on a flat plain; a 90 m DEM produces noisy sub-degree slopes that only perturb
   the radiation geometry.
2. **s2** `convert_soil.py --source hwsd` → 17 layers to 3160 mm. Keep the **top
   layer ≤ 20 mm** — the dag records that a coarser upper discretization injects
   >1 °C of ground-temperature error.
3. **s4** `convert_forcing.py --source cmfd --dt 10800` (see Data Preparation).
4. **s5** `geotop.inpts` from `tests/1D/Matsch_B2_Ref_007`, changing:
   `PointSim=1`, `StandardTimeSimulation=0`, `MeteoStationStandardTime=0`,
   `FlagSkyViewFactor=0` + `CalculateCastShadow=0` (flat plain — sky view factor
   is 1 by construction, and this sidesteps dt_010), `HeaderAirPress="AirPress"`
   (the Matsch template says `"AirP"`, which does **not** match what
   `convert_forcing.py` writes — a silently dropped pressure column),
   `FreeDrainageAtBottom=0` (closed column ⇒ the water balance is checkable),
   `InitSoilTemp` = the November mean air temperature.
5. **s6** `run_geotop.py` — 92 days at a 900 s step runs in seconds.
6. **s7** `parse_output.py --output-type point` → `Tsurface[C]`.
7. **s8** `read_modis_lst.py` → pair → `ki_tools_common.metrics.all_metrics`.

### Comparing a model instant to an 8-day composite

MOD11A2 is **not** an 8-day mean of daily means. It is the average, at a fixed
overpass instant, over only the **clear-sky** days of the window. So:

* sample the model at `view_time_local_solar − lon/15` **UTC** on each day
  (never at a fixed UTC hour, never at local noon);
* average over `Clear_sky_days` / `Clear_sky_nights` days, choosing the clearest
  (day: largest daily ΣSwglobal; night: lowest LWin/σT⁴) — dt_025;
* score in **Kelvin**. In Celsius the winter series straddles 0 and the
  ratio-based metrics detonate: PBIAS −96.7 % / KGE −0.12 in °C versus
  +0.62 % / +0.45 in K for the identical series — dt_024.

### Known residual: diurnal amplitude deficit

Simulated day−night contrast is 4–6 K against 11–15 K observed (day too cold,
night too warm) even after clear-sky matching, while r stays 0.97. This is *not*
a clock error — dt_021 would depress r as well. The leading explanation is that
`Tsurface` is the **ground** skin temperature beneath the canopy, whereas MODIS
sees the effective radiometric temperature of the canopy+soil mixture; with
`CanopyFraction > 0` the ground term is damped relative to the satellite view.
A pixel-effective comparison would mix `Tsurface` and `Tvegetation` by the
fourth power weighted on cover fraction and emissivity. Not yet implemented —
it changes the scored quantity away from the dag variable `Tsurface`, so it
belongs in a dedicated `Trad` output rather than in the pairing code.
