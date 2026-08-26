---
name: hype-hydrocraft
version: "1.0.0"
model: HYPE v5.35.0
domain: semi-distributed hydrology with integrated nutrient transport
validation_status: production_validated
---

> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model. Doing so produces
> scientifically invalid results and defeats the purpose of the KI.
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
| to run the pipeline stages | `tools/` (23 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (10 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (25 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
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
| `tools/calib_run.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/calib_run.py --help` |
| `tools/s10_calibration/parse_calibration_results.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s10_calibration/parse_calibration_results.py --help` |
| `tools/s10_calibration/setup_calibration.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s10_calibration/setup_calibration.py --help` |
| `tools/s1_subbasin_delineation/delineate_subbasins.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s1_subbasin_delineation/delineate_subbasins.py --help` |
| `tools/s1_subbasin_delineation/validate_topology.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s1_subbasin_delineation/validate_topology.py --help` |
| `tools/s2_slc_classification/compute_slc_fractions.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s2_slc_classification/compute_slc_fractions.py --help` |
| `tools/s2_slc_classification/generate_geoclass.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s2_slc_classification/generate_geoclass.py --help` |
| `tools/s3_forcing_preparation/convert_forcing_to_hype.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s3_forcing_preparation/convert_forcing_to_hype.py --help` |
| `tools/s4_geodata_generation/generate_geodata.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s4_geodata_generation/generate_geodata.py --help` |
| `tools/s4_geodata_generation/validate_geodata.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s4_geodata_generation/validate_geodata.py --help` |
| `tools/s5_parameter_setup/extract_wwh_params.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s5_parameter_setup/extract_wwh_params.py --help` |
| `tools/s5_parameter_setup/setup_parameters.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s5_parameter_setup/setup_parameters.py --help` |
| `tools/s6_lake_reservoir_config/generate_damdata.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s6_lake_reservoir_config/generate_damdata.py --help` |
| `tools/s6_lake_reservoir_config/generate_lakedata.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s6_lake_reservoir_config/generate_lakedata.py --help` |
| `tools/s6_lake_reservoir_config/setup_lake_data.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s6_lake_reservoir_config/setup_lake_data.py --help` |
| `tools/s7_execution/configure_info.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s7_execution/configure_info.py --help` |
| `tools/s7_execution/run_hype.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s7_execution/run_hype.py --help` |
| `tools/s8_output_analysis/compare_vic_hype.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s8_output_analysis/compare_vic_hype.py --help` |
| `tools/s8_output_analysis/parse_hype_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s8_output_analysis/parse_hype_output.py --help` |
| `tools/s8_output_analysis/plot_hype_results.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s8_output_analysis/plot_hype_results.py --help` |
| `tools/s9_water_quality/configure_npc.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s9_water_quality/configure_npc.py --help` |
| `tools/s9_water_quality/generate_cropdata.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s9_water_quality/generate_cropdata.py --help` |
| `tools/s9_water_quality/parse_npc_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s9_water_quality/parse_npc_output.py --help` |

*23 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

---

# HYPE -- Knowledge Infrastructure Skill Document

> **Version**: 1.0.0
> **Domain**: semi-distributed hydrology with integrated nutrient transport
> **Last updated**: 2026-08-18
> **Validation status**: production_validated

---

## 1. Model Identity

| Property | Value |
|----------|-------|
| Full name | HYPE (HYdrological Predictions for the Environment) |
| Version | 5.35.0 |
| Language | Fortran 90 |
| License | LGPL-3.0-only |
| Repository | https://sourceforge.net/projects/hype/files/release_hype_5_35_0/ |
| Citation | SMHI HYPE 5.35.0 source and this KI's gathered papers |
| Primary domain | Semi-distributed hydrology with integrated nutrient transport |
| Spatial mode | Semi-distributed subbasin/SLC |

## 2. What This Model Does

HYPE simulates subbasin water balance, routing, snow, evapotranspiration, soil water,
groundwater, lake/reservoir effects, and coupled nitrogen/phosphorus transport. It uses
subbasins connected by MAINDOWN topology, with each subbasin divided into SLC
(soil-land use class) fractions.

## 3. Input Requirements

**Exact shapes live in `docs/format_spec.yaml`** (projected from dag + triplets; regenerate it,
never hand-edit). This section explains intent and gotchas; the spec file is the contract.

### 3.1 Meteorological Forcing

| Variable | Unit model expects | Source dataset | Source unit | Conversion |
|----------|-------------------|----------------|-------------|------------|
| Precipitation | mm/day | CMFD/MSWX/NASA POWER through `ki_tools_common.load_forcing` | CMFD kg/m^2/s or 3-hourly depth; MSWX 3-hourly depth | convert to daily total; CMFD kg/m^2/s uses timestep conversion before daily sum |
| Temperature | deg C | CMFD/MSWX/NASA POWER through `ki_tools_common.load_forcing` | CMFD K; MSWX deg C | CMFD subtract 273.15, then daily mean |
| Shortwave radiation | MJ/m^2/day | CMFD/MSWX when PET model requires it | W/m^2 | daily mean then convert to MJ/m^2/day |
| Wind speed | m/s | CMFD/MSWX when PET model 5 requires it | m/s | daily mean |
| Humidity | fraction | CMFD/MSWX when PET model 5 requires it | kg/kg or RH source field | convert to relative humidity fraction |

### 3.2 Static Inputs

| Input | Source | Tool that prepares it |
|-------|--------|----------------------|
| Subbasins and MAINDOWN routing | DEM-derived watershed topology | `tools/s1_subbasin_delineation/` |
| Soil-land use class fractions | Land cover + soil data | `tools/s2_slc_classification/` |
| GeoData/GeoClass | Delineation + SLC products | `tools/s4_geodata_generation/` |
| Parameters | WWH defaults, literature, or calibration setup | `tools/s5_parameter_setup/` and `tools/s10_calibration/` |
| Lake/reservoir configuration | HydroLAKES + GRanD | `tools/s6_lake_reservoir_config/` |

### 3.3 Configuration Files

| File | Format | Notes |
|------|--------|-------|
| `info.txt` | whitespace/tab-delimited HYPE control file | directory paths must end with `/`; sets dates, paths, outputs, PET/snow options, calibration |
| `GeoData.txt` | tab-separated subbasin table | includes SUBID, MAINDOWN, AREA, SLC fractions, RIVLEN, coordinates, elevation, slope, lake fields |
| `GeoClass.txt` | tab-separated SLC class table | land use, soil, crop, vegtype, special code, stream depth, soil layers |
| `par.txt` | HYPE parameter file | value counts must match max land-use and soil IDs |
| `Pobs.txt`, `Tobs.txt`, optional forcing files | tab-separated daily time series | header row is line 1; no `!!` comments |
| `Qobs.txt` | tab-separated observed discharge | optional for scoring/calibration; units are m^3/s |

## 4. Build Instructions

The production binary is `KISSPATH_BINARIES/hype/hype`. If rebuilding from
source, use the HYPE 5.35.0 source directory and compile without NetCDF unless NetCDF output is
explicitly required:

```bash
cd KISSPATH_BINARIES/hype/hype_5_35_0_src/
make comp=gfortran
```

Known build issues are captured in `diagnostics/triplets.yaml`, including `dt_b01`
(unnecessary NetCDF linker flags) and `dt_b02` (unsupported or overly strict gfortran setup).

## 5. Execution

Before any run, execute the KI preflight from this directory:

```bash
python preflight_check.py
```

Run the actual HYPE binary or the KI's stage-7 wrapper; do not replace it with a simplified
formula or surrogate:

```bash
KISSPATH_BINARIES/hype/hype ./
python tools/s7_execution/run_hype.py --project_dir <path>
```

The direct binary argument must end with `/`, because HYPE concatenates the directory string
with `info.txt`.

## 6. Output Description

**Source: `dag.yaml`.** The dag is the model's identity. If this section ever disagrees with
`dag.yaml`, the dag wins and this section is the bug.

**Headline output** (the dag's `validation_rank: 1` variable):

> `cout` -- Simulated outflow (discharge) from the outlet lake / subbasin, positive flow only. (`m^3/s`)

Extracted dag facts:
- RANK-1 OUTPUT: var=`cout`, unit=`m^3/s`, description=`Simulated outflow (discharge) from the outlet lake / subbasin, positive flow only.`
- Other dag outputs: `snow`, `evap`, `soim`, `gwat`, `wcom`, `c1TN`, `c1TP`

| Output variable (dag `var`) | Rank | File | Unit | Description |
|-----------------------------|------|------|------|-------------|
| `cout` | 1 | `timeCOUT.txt` / subbasin output files | m^3/s | Simulated outflow (discharge) from the outlet lake / subbasin, positive flow only. |
| `evap` | 2 | `timeEVAP.txt` | mm/day | Actual evapotranspiration from subbasin soil water and land surface. |
| `snow` | 3 | `timeSNOW.txt` | mm | Snow water equivalent, subbasin land-area average. |
| `soim` | 4 | `timeSOIM.txt` | mm | Computed soil moisture (root zone and full profile). |
| `gwat` | 5 | `timeGWAT.txt` | m | Groundwater table level (negative downward from surface). |
| `wcom` | 6 | `timeWCOM.txt` | m | Water level of the outlet lake at end of timestep, in the user reference system (via w0ref). |
| `c1TN` | 7 | `timeC1TN.txt` | ug/L | Modelled total nitrogen concentration in surface-water main outflow. |
| `c1TP` | 8 | `timeC1TP.txt` | ug/L | Modelled total phosphorus concentration in surface-water main outflow. |

The dag output set is `cout`, `snow`, `evap`, `soim`, `gwat`, `wcom`, `c1TN`, and `c1TP`.

## 7. Tool Inventory

| Tool area | Purpose | Inputs | Outputs |
|-----------|---------|--------|---------|
| `tools/s1_subbasin_delineation/` | Delineate subbasins and routing topology | DEM/domain inputs | Subbasin polygons and MAINDOWN |
| `tools/s2_slc_classification/` | Compute SLC fractions | land cover and soil data | SLC tables/fractions |
| `tools/s3_forcing_preparation/convert_forcing_to_hype.py` | Convert forcing to HYPE format | daily forcing dict or source grids | `Pobs.txt`, `Tobs.txt`, optional forcing files |
| `tools/s4_geodata_generation/` | Generate HYPE static files | subbasins and SLC products | `GeoData.txt`, `GeoClass.txt` |
| `tools/s5_parameter_setup/` | Prepare parameters | defaults, literature, basin setup | `par.txt` |
| `tools/s6_lake_reservoir_config/` | Configure lakes and dams | HydroLAKES, GRanD, GeoData | `LakeData.txt`, `DamData.txt` |
| `tools/s7_execution/run_hype.py` | Execute HYPE and parse logs | complete run directory | HYPE result directory |
| `tools/s8_output_analysis/` | Parse and score outputs | result files and observations | metrics, plots, comparison tables |
| `tools/s9_water_quality/` | Enable and parse N/P simulation | crop, region, nutrient settings | NPC-ready config and nutrient outputs |
| `tools/s10_calibration/` | Configure and parse built-in calibration | HYPE setup, observations, parameter choices | `optpar.txt`, calibration results |

Shared utilities should be used instead of raw extraction code where available:

```python
from ki_tools_common.load_forcing import load_daily_forcing
from ki_tools_common.metrics import all_metrics
from ki_tools_common.validation import validate_forcing_ranges
from ki_tools_common.units import convert
```

## 8. Unit Conversion Table

| Variable | Source unit (verified) | Model unit | Factor | Type |
|----------|------------------------|------------|--------|------|
| Precipitation | CMFD kg/m^2/s for a 3-hour timestep | mm/3hr before daily aggregation | x10800 | multiplicative |
| Precipitation | 3-hourly depth | mm/day | sum 8 timesteps | aggregation |
| Temperature | K | deg C | -273.15 | additive |
| Temperature | 3-hourly deg C | deg C daily | mean 8 timesteps | aggregation |
| Shortwave radiation | W/m^2 | MJ/m^2/day | daily mean x 0.0864 | multiplicative |
| Pressure | Pa | hPa | /100.0 | multiplicative |

### 8c. Sign Conventions and Output Units

| Variable | Convention in this model | Common alternative | Impact if wrong |
|----------|--------------------------|--------------------|-----------------|
| `cout` | positive simulated outflow discharge, m^3/s | signed inflow/outflow or depth-normalized runoff | wrong sign or magnitude in discharge scoring and coupling |
| `snow` | snow water equivalent, mm | binary snow cover or snow depth | wrong observation pairing and metric interpretation |
| `evap` | actual evapotranspiration, mm/day | PET demand or energy flux | water-balance and ET comparison errors |
| `gwat` | groundwater table level, negative downward from surface, m | positive depth below ground | inverted groundwater dynamics |
| `c1TN`, `c1TP` | concentration in ug/L | areal nutrient load | invalid water-quality comparison unless converted |

Output unit verification checklist:
- Read the output entry in `dag.yaml` before post-processing.
- Print the first values from the parsed HYPE output and check order of magnitude.
- For discharge, confirm `cout` is absolute flow in m^3/s, not basin-depth runoff.
- For nutrient outputs, compare concentrations as concentrations unless explicitly converted.

## 9. Diagnostic Triplets (Top 5)

The full diagnostic corpus stays in `diagnostics/triplets.yaml`; check it before debugging.

| # | Error | Diagnosis | Remedy |
|---|-------|-----------|--------|
| 1 (`dt_r01`) | HYPE fails to open `info.txt` / `Cannot open file` | directory argument lacks the trailing slash used by HYPE string concatenation | pass the run directory with a trailing `/`, or use `run_hype.py` |
| 2 (`dt_u03`) | all precipitation in `Pobs.txt` is zero despite CMFD data | CMFD precipitation is kg/m^2/s and needs timestep conversion | multiply by 10800 for mm/3hr, then sum 8 steps for daily |
| 3 (`dt_s01`) | water balance is wrong but HYPE exits successfully | SLC fractions in `GeoData.txt` do not sum to 1.0 | validate each subbasin row so SLC fractions sum to 1.0 within 0.001 |
| 4 (`dt_s08`) | zero discharge despite valid precipitation | `GeoClass.txt` streamdepth column is 0 | set streamdepth greater than 0 for non-water SLC classes |
| 5 (`dt_r04`) | fatal forcing date mismatch | forcing dates do not cover the full `bdate` to `edate` range | regenerate forcing files so `Pobs.txt` and `Tobs.txt` cover the full period with no gaps |

## 10. Coupling Interfaces

| Upstream model/data | Variable exchanged | Unit | Temporal resolution |
|---------------------|-------------------|------|---------------------|
| CMFD/MSWX/NASA POWER forcing loaders | precipitation, temperature, optional radiation/wind/humidity/pressure | mixed source units converted to HYPE daily units | daily after aggregation |
| HydroLAKES/GRanD data KIs | lake and dam geometry/regulation fields | mixed | static |
| VIC comparison workflow | discharge at matching outlet | m^3/s | daily or evaluation period |

| Downstream model/workflow | Variable exchanged | Unit | Temporal resolution |
|---------------------------|-------------------|------|---------------------|
| HydroCraft discharge comparison | `cout` | m^3/s | daily |
| Water-quality analysis | `c1TN`, `c1TP` | ug/L | daily or configured output period |
| Calibration/scoring tools | `cout` against `rout`/`Qobs.txt` | m^3/s | daily or configured criterion period |

## 11. Validated Results

### Test Basin: Bengbu -- Huai River

| Property | Value |
|----------|-------|
| Location | Huai River at Bengbu |
| Area | ~121,330 km^2 |
| Period | 1980-1990, with 1980 warmup and 1981-1990 evaluated |
| Resolution | lumped 1-subbasin setup with daily forcing |

### Performance Metrics -- judged against the field's bar, not intuition

**Source: `docs/validation_convention.yaml`.** Bands below are copied from the convention. Null
bands are written as `no cited threshold`.

Extracted convention facts:
- CONVENTION BAR for `cout`: metric=`nse`, direction=`maximize`, bands={very_good: 0.8, good: 0.7, satisfactory: 0.5}, cites=`pandit2025`, `shrestha2020`
- CONVENTION BAR for `cout`: metric=`pbias`, direction=`zero_centered`, bands={very_good: 5, good: 10, satisfactory: 15}, cites=`pandit2025`
- CONVENTION BAR for `snow`: metric=`nse`, direction=`maximize`, satisfactory=`no cited threshold`, cites=none
- CONVENTION BAR for `snow`: metric=`csi`, direction=`maximize`, satisfactory=`no cited threshold`, cites=none

> Bar for `cout` (nse, per `pandit2025`, `shrestha2020`): satisfactory >= 0.5,
> good >= 0.7, very_good >= 0.8. Bengbu achieved 0.678, which is satisfactory.

> Bar for `cout` (pbias, per `pandit2025`): very_good within 5, good within 10,
> satisfactory within 15, direction zero_centered. Bengbu achieved +19.8%, outside
> the satisfactory band.

| Dag variable | Metric | Direction | Achieved value in this SKILL | Bar (convention, cited) | Verdict |
|--------------|--------|-----------|------------------------------|--------------------------|---------|
| `cout` | nse | maximize | 0.678 | satisfactory >= 0.5, good >= 0.7, very_good >= 0.8 (`pandit2025`, `shrestha2020`) | satisfactory |
| `cout` | pbias | zero_centered | +19.8% | very_good within 5, good within 10, satisfactory within 15 (`pandit2025`) | outside satisfactory |
| `snow` | nse | maximize | not evaluated here | no cited threshold | no verdict |
| `snow` | csi | maximize | not evaluated here | no cited threshold | no verdict |

### Data Replacement Tracking

| Component | Source | Status | Notes |
|-----------|--------|--------|-------|
| Forcing | CMFD 0.1 degree 3-hourly converted to daily in the validated Bengbu run | production_validated for Bengbu | keep unit checks from `dt_u03` active |
| Soil/SLC | KI stage outputs | production_validated for the documented Bengbu setup | SLC fractions must sum to 1.0 |
| Land cover | KI stage outputs | production_validated for the documented Bengbu setup | represented through SLC fractions |
| DEM/routing | KI stage outputs | production_validated for the documented Bengbu setup | use semi-distributed setup for large basins when routing attenuation matters |
| Initial conditions | warmup period | production_validated for Bengbu discharge | 1980 warmup, 1981-1990 evaluated |

## 12. Parameter Selection by Region

Use these as physically informed starting points when no site-specific calibration exists; they
do not replace calibration against observations.

| Climate / Region | Key parameters | Rationale |
|------------------|----------------|-----------|
| Large monsoon basins | `lp`, `cevpam`, `wcfc`, `wcwp`, `wcep`, `rrcs1`, `rivvel`, `damp` | water balance, seasonal PET, soil storage, recession, and routing attenuation dominate discharge behavior |
| Snow-affected basins | `ttmp`, `cmlt`, snowmelt model option, radiation forcing where available | snow accumulation and melt timing control seasonal runoff |
| Lake/reservoir basins | `gratk`, `gratefk`, `gldepi`, `gldepol`, per-lake `rate`, `exp`, `w0ref`, `regvol`, `qprod1`, `qprod2` | outlet storage and regulation modify flow timing and peak attenuation |
| Nutrient simulations | `fastn0`, `fastp0`, `humusn0`, `humusp0`, `denitrlu`, `denitwr`, `denitwl`, `minerfn`, `sedon`, `sedpp`, `soilcoh`, `soilerod` | N/P pools and transformations need multi-year warmup and regional management inputs |

---

## Data Preparation (use these commands — do NOT write custom data extraction code)

### Lake/reservoir data
```bash
# Generate LakeData.txt from HydroLAKES + GRanD:
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s6_lake_reservoir_config/generate_lakedata.py \
    --geodata [GEODATA] --geoclass [GEOCLASS] --output [OUTPUT] \
    --lat [LAT] --lon [LON] --search_radius_km 100 --update_geodata

# Generate DamData.txt from GRanD:
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s6_lake_reservoir_config/generate_damdata.py \
    --geodata [GEODATA] --output [OUTPUT] \
    --lat [LAT] --lon [LON] --search_radius_km 200
```

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.
Then convert to HYPE forcing format using this KI's tool: `tools/s3_forcing_preparation/convert_forcing_to_hype.py`

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.

---

# HYPE Knowledge Infrastructure for HydroCraft

## Model Overview

**HYPE (HYdrological Predictions for the Environment)** is a semi-distributed, process-based hydrological and nutrient transport model developed at SMHI (Swedish Meteorological and Hydrological Institute). It operates on a subbasin-SLC (Soil-Land use Class) structure where the landscape is divided into subbasins, each containing fractional areas of soil-landcover combinations.

**Binary**: `KISSPATH_BINARIES/hype/hype` (v5.35.0, compiled from source)
**Source**: `KISSPATH_BINARIES/hype/hype_5_35_0_src/` (38 Fortran 90 files, 93,622 lines)
**Demo**: `KISSPATH_BINARIES/hype/demo/` (3-subbasin test case, validated)

### What Makes HYPE Unique in HydroCraft

| Capability | VIC | mHM | **HYPE** |
|-----------|-----|-----|----------|
| Spatial structure | Grid cells | Grid (L0/L1/L11) | **Subbasins + SLC fractions** |
| Nutrient simulation | No | No | **Yes (N + P cycles)** |
| Lake/reservoir modeling | No | No | **Yes (native, LakeData/DamData)** |
| Parameter type | Per-cell | MPR global | **Per land-use/soil type** |
| Routing topology | External (Lohmann/CaMa) | Internal (MRM) | **Internal (MAINDOWN)** |
| World-Wide setup | No | No | **Yes (WWH)** |
| Data assimilation | No | No | **Yes (built-in ensemble)** |
| Calibration | External | Built-in DDS/SCE | **Built-in DDS/DEMC** |
| Dependencies | NetCDF | NetCDF, LAPACK | **None (pure Fortran 90)** |

### Strategic Value

1. **Integrated water quality**: HYPE simulates nitrogen and phosphorus transport simultaneously with hydrology -- no coupling needed.
2. **World-Wide HYPE (WWH)**: A global setup exists with pre-calibrated parameters, enabling prediction anywhere.
3. **Lake/reservoir support**: Native handling of regulated lakes and dams via LakeData.txt and DamData.txt.
4. **Parameter regionalization**: Parameters are defined per soil type and land use, enabling transfer between basins with similar landscapes.
5. **No dependencies**: Pure Fortran 90, compiles with gfortran in under 60 seconds.

---

## Architecture: Subbasins + SLC

HYPE divides the landscape into **subbasins** connected by a routing network (MAINDOWN topology). Each subbasin contains fractional areas of **SLC (Soil-Land use Class)** combinations:

```
Basin
  |-- Subbasin 1 (area=150 km2)
  |     |-- SLC_1 (forest/till)     60%
  |     |-- SLC_2 (cropland/clay)   30%
  |     |-- SLC_3 (water)           10%
  |-- Subbasin 2 (area=200 km2)
  |     |-- SLC_1                   40%
  |     |-- SLC_2                   50%
  |     |-- SLC_3                   10%
  |-- Subbasin 3 (outlet, area=500 km2)
        |-- SLC_1                   35%
        |-- SLC_2                   45%
        |-- SLC_3                   20%
```

**CRITICAL**: SLC fractions per subbasin MUST sum to 1.0. If they don't, the water balance is wrong but HYPE produces NO warning.

---

## Input File Format Reference

All HYPE input files are **tab-separated text** with `!!` comment lines at the top.

### info.txt (Main configuration)
```
bdate     2005-01-01
cdate     2005-01-01          !! criteria/output start (skip warmup)
edate     2010-12-31
resultdir ./resultdir/        !! trailing slash required
modeldir  ./modelfiles/       !! trailing slash required
forcingdir ./forcingdir/       !! trailing slash required
logdir    ./logdir/            !! trailing slash required
timeoutput variable cout rout snow evap cprc
timeoutput meanperiod 1
modeloption petmodel 1         !! 0=default, 1=Jensen-Haise, 2=Hargreaves, 5=Penman-Monteith
modeloption snowmeltmodel 2    !! 0=degree-day, 2=degree-day with radiation
```

**CRITICAL**: All directory paths in info.txt MUST end with `/`. Missing slash causes silent file-not-found.

### GeoClass.txt (SLC definitions)
```
!! SLC_ID  landuse  soil  crop  crop2  rotation  vegtype  special  tiledepth  streamdepth  numlayers  soildepth1  [soildepth2]  [soildepth3]
1   1   1   0   0   0   1   0   0   0   3   0.3   0.6   1.5
2   2   2   1   0   0   2   0   0.8   0   3   0.3   0.9   1.8
3   3   3   0   0   0   0   2   0   0   1   5.0
```
- `numlayers` determines how many soildepth columns follow (1-3)
- `special=2` marks water class (lake/river)
- `vegtype`: 1=conifer, 2=deciduous, 3=grass, 0=bare/water

### GeoData.txt (Subbasin properties)
```
SUBID  MAINDOWN  AREA  SLC_1  SLC_2  SLC_3  RIVLEN  LATITUDE  LONGITUDE  ELEV_MEAN  SLOPE_MEAN  LAKE_DEPTH
1      3         1.5E8 0.60   0.30   0.10   15000   31.50     117.00     120        0.05        2.0
2      3         2.0E8 0.40   0.50   0.10   20000   31.30     117.20     85         0.03        1.5
3      0         5.0E8 0.35   0.45   0.20   25000   31.10     117.10     45         0.02        3.0
```
- `MAINDOWN=0` marks the outlet subbasin
- `AREA` is in m^2
- `RIVLEN` is main river length in meters within the subbasin
- SLC fractions MUST sum to 1.0 per subbasin

### par.txt (Parameters)
```
!! Land use dependent (nlanduse values per line)
ttmp   0.0   0.0   0.0
cmlt   3.5   4.0   0.0
cevp   0.15  0.20  0.0
srrcs  0.1   0.05  0.0
!! Soil type dependent (nsoil values per line)
wcfc   0.15  0.25  0.05
wcwp   0.05  0.10  0.01
wcep   0.35  0.40  0.50
rrcs1  0.1   0.05  0.0
rrcs2  0.01  0.005 0.0
!! General (1 value per line)
rrcs3  0.001
lp     0.8
rivvel 1.0
damp   0.5
```

**CRITICAL**: Number of values per parameter MUST match:
- Land-use params: exactly `max(landuse IDs in GeoClass)` values
- Soil params: exactly `max(soil IDs in GeoClass)` values
- General params: exactly 1 value
Too few values causes fatal error. Too many causes warning but is ignored.

### Pobs.txt / Tobs.txt (Forcing data)
```
DATE       1      2      3
2005-01-01 2.5    3.1    1.8
2005-01-02 0.0    0.5    0.0
...
```
- Daily values, tab-separated
- Column headers are SUBID numbers matching GeoData.txt
- Pobs.txt: precipitation in mm/day
- Tobs.txt: temperature in degrees Celsius
- Missing values: -9999

### ForcKey.txt (Forcing-subbasin mapping)
```
SUBID   FROSESSION
1       1
2       2
3       3
```
Maps each subbasin to a forcing observation station. Usually 1:1 for gridded forcing.

### Qobs.txt (Observed discharge, optional)
```
DATE       3
2005-01-01 15.2
2005-01-02 14.8
...
```
- Only subbasins with gauges need columns
- Units: m^3/s

---

## Unit Conversion Table (CRITICAL)

| Variable | HYPE expects | CMFD native | MSWX native | Conversion |
|----------|-------------|-------------|-------------|------------|
| Precipitation | mm/day | mm/3hr | mm/3hr | SUM 8 timesteps per day |
| Temperature | deg C | K (3-hourly) | deg C (3-hourly) | MEAN + subtract 273.15 for CMFD |
| PET forcing | Not needed for petmodel 1-2 | - | - | Jensen-Haise/Hargreaves compute from T |
| SW radiation | MJ/m^2/day | W/m^2 (3-hourly) | W/m^2 (3-hourly) | MEAN x 0.0864 |
| Wind speed | m/s | m/s | m/s | MEAN (only for petmodel 5) |
| Humidity | fraction | kg/kg | kg/kg | Convert to RH (only for petmodel 5) |
| Pressure | hPa | Pa | Pa | /100.0 (only for petmodel 5) |

**CRITICAL**: HYPE uses **daily** forcing. CMFD/MSWX are 3-hourly. You MUST aggregate to daily:
- Precipitation: SUM over 8 timesteps (not average!)
- Temperature: MEAN over 8 timesteps
- Radiation: MEAN over 8 timesteps, then convert to MJ/m^2/day

For `petmodel 1` (Jensen-Haise, default) or `petmodel 2` (Hargreaves), only P and T are needed.
For `petmodel 5` (Penman-Monteith), additional forcing files are required: SWobs.txt, Uobs.txt, RHobs.txt, SFobs.txt.

---

## Pipeline Stages

```
s1_subbasin_delineation   Delineate subbasins + MAINDOWN topology from DEM
        |
s2_slc_classification     Compute SLC fractions from landcover + soil data
        |
s3_forcing_preparation    Convert CMFD/MSWX 3-hourly to daily Pobs.txt + Tobs.txt
        |
s4_geodata_generation     Generate GeoData.txt + GeoClass.txt
        |
s5_parameter_setup        Set up par.txt from WWH defaults or literature
        |
s6_lake_reservoir_config  Configure LakeData.txt and DamData.txt (optional)
        |
s7_execution              Run HYPE, parse log, verify completion
        |
s8_output_analysis        Parse timeCOUT.txt/mapCOUT.txt, compute metrics, compare with VIC
        |
s9_water_quality          Enable N/P simulation, configure NPC parameters, parse nutrient output
        |
s10_calibration           Built-in calibration (DDS/DEMC/MC) with optpar.txt + criteria
```

### Stage Skill Documents

- [s1_subbasin_delineation](docs/s1_subbasin_delineation.md)
- [s2_slc_classification](docs/s2_slc_classification.md)
- [s3_forcing_preparation](docs/s3_forcing_preparation.md)
- [s4_geodata_generation](docs/s4_geodata_generation.md)
- [s5_parameter_setup](docs/s5_parameter_setup.md)
- [s6_lake_reservoir_config](docs/s6_lake_reservoir_config.md)
- [s7_execution](docs/s7_execution.md)
- [s8_output_analysis](docs/s8_output_analysis.md)
- [s9_water_quality](docs/s9_water_quality.md)
- [s10_calibration](docs/s10_calibration.md)

---

## Key Parameters

### General Parameters
| Parameter | Description | Default | Range | Sensitivity |
|-----------|------------|---------|-------|------------|
| lp | Limit for PET reduction | 0.8 | 0.1-1.0 | High |
| rivvel | River velocity (m/s) | 1.0 | 0.1-5.0 | Moderate |
| damp | Damping coefficient | 0.5 | 0.0-1.0 | Moderate |
| cevpam | Amplitude of PET seasonal cycle | 0.3 | 0.0-1.0 | High |
| cevpph | Phase shift of PET (days) | 30 | 0-365 | Low |
| rrcs3 | Deep groundwater recession | 0.001 | 0.0-0.1 | Moderate |

### Land-Use Dependent Parameters
| Parameter | Description | Range | Calibrate? |
|-----------|------------|-------|-----------|
| ttmp | Threshold temperature for snow (C) | -3 to 3 | Yes |
| cmlt | Degree-day snowmelt factor (mm/C/day) | 1-10 | Yes |
| cevp | PET coefficient | 0.05-0.5 | Yes |
| srrcs | Surface runoff recession coefficient | 0.0-1.0 | Yes |

### Soil-Type Dependent Parameters
| Parameter | Description | Range | Calibrate? |
|-----------|------------|-------|-----------|
| wcfc | Field capacity (fraction) | 0.05-0.5 | Yes |
| wcwp | Wilting point (fraction) | 0.01-0.3 | Yes |
| wcep | Effective porosity (fraction) | 0.1-0.7 | Yes |
| rrcs1 | Upper soil recession coefficient | 0.0-1.0 | Yes |
| rrcs2 | Lower soil recession coefficient | 0.0-0.5 | Yes |

---

## Lake and Reservoir Configuration (Stage s6)

HYPE has native support for outlet lakes (olake) and regulated dams. Lakes modify
the flow hydrograph by adding storage and attenuation; dams add active regulation
rules (production flow, flood control, seasonal operation).

### When to Enable Lakes/Reservoirs

- Basin contains significant lakes (>1 km^2) or reservoirs
- Flow hydrograph shows reservoir regulation effects (sustained low flows, abrupt releases)
- GRanD shows dams within or upstream of the basin

### Prerequisites

1. **GeoClass.txt** must have an SLC with `special=2` (outlet lake class)
2. **GeoData.txt** must have:
   - `SLC_N` fraction > 0 for the olake SLC in subbasins with lakes
   - `lake_depth` column with depth in meters
   - `lakedataid` column linking subbasins to LakeData rows
3. LakeData.txt goes in `modeldir/` (same as GeoData.txt)
4. DamData.txt goes in `modeldir/` (same as GeoData.txt)

**CRITICAL**: Do NOT set `special=2` on any SLC class unless LakeData.txt is
provided. Without it, HYPE creates a zero-volume lake that traps all water.

### Generating LakeData.txt

```bash
# Search HydroLAKES + GRanD for lakes/dams within the basin area:
python tools/s6_lake_reservoir_config/generate_lakedata.py \
    --geodata modelfiles/GeoData.txt \
    --geoclass modelfiles/GeoClass.txt \
    --output modelfiles/LakeData.txt \
    --lat [LAT] --lon [LON] \
    --search_radius_km 100 \
    --min_lake_area_km2 1.0 \
    --update_geodata
```

The `--update_geodata` flag automatically adds `lakedataid` and updates
`lake_depth` in GeoData.txt from HydroLAKES data.

### Generating DamData.txt

```bash
# Search GRanD for regulated dams near the basin:
python tools/s6_lake_reservoir_config/generate_damdata.py \
    --geodata modelfiles/GeoData.txt \
    --output modelfiles/DamData.txt \
    --lat [LAT] --lon [LON] \
    --search_radius_km 200

# Or by specific dam names:
python tools/s6_lake_reservoir_config/generate_damdata.py \
    --geodata modelfiles/GeoData.txt \
    --output modelfiles/DamData.txt \
    --dam_names "Meishan,Xianghongdian,Foziling"

# Filter by purpose (3=flood control):
python tools/s6_lake_reservoir_config/generate_damdata.py \
    --geodata modelfiles/GeoData.txt \
    --output modelfiles/DamData.txt \
    --lat 32.4 --lon 115.7 --purpose 3
```

### LakeData.txt Column Reference

| Column | Type | Unit | Description |
|--------|------|------|-------------|
| lakedataid | int | - | Links to GeoData lakedataid column (REQUIRED) |
| ldtype | int | - | 1=simple olake, 5=outlet1, 6=outlet2, 7=equal-level basin (REQUIRED) |
| area | real | m^2 | Lake surface area |
| lake_depth | real | m | Mean lake depth (overrides GeoData value) |
| lake_shape | real | - | Depth exponent (1.0=flat, 2.0=conical) |
| rate | real | - | Rating curve coefficient |
| exp | real | - | Rating curve exponent (typically 1.5) |
| w0ref | real | m | Reference water level threshold |
| regvol | real | Mm^3 | Regulation volume (for regulated lakes) |
| wamp | real | m | Regulation amplitude |
| qprod1 | real | m^3/s | Production flow, period 1 |
| qprod2 | real | m^3/s | Production flow, period 2 |
| datum1 | int | MMDD | Start date for production period 1 |
| datum2 | int | MMDD | Start date for production period 2 |
| minflow | real | m^3/s | Minimum environmental flow |

### DamData.txt Column Reference

| Column | Type | Unit | Description |
|--------|------|------|-------------|
| subid | int | - | Subbasin ID matching GeoData (REQUIRED) |
| purpose | int | - | 1=Irrigation, 2=WaterSupply, 3=FloodControl, 4=Hydropower |
| lake_depth | real | m | Reservoir mean depth |
| regvol | real | Mm^3 | Regulation volume (dam capacity) |
| rate | real | - | Spillway rating curve coefficient |
| exp | real | - | Spillway rating curve exponent |
| w0ref | real | m | Reference spill level |
| wamp | real | m | Regulation amplitude |
| qprod1/qprod2 | real | m^3/s | Seasonal production flows |
| datum1/datum2 | int | MMDD | Season boundary dates |
| qinfjan-qinfdec | real | m^3/s | Monthly natural inflows (12 columns) |
| minflow | real | m^3/s | Minimum environmental flow |

### Data Sources

| Input | Data KI | Tool | Coverage |
|-------|---------|------|----------|
| Lake area, depth, volume | HydroLAKES v10 | `search_lakes.py` | Global, lakes >= 10 ha |
| Dam capacity, height, year | GRanD | `search_dams.py` | Global, 7,320 large dams |

### Key Lake Parameters (par.txt)

| Parameter | Type | Description | Default | Range |
|-----------|------|-------------|---------|-------|
| gratk | genpar | General lake rating curve coefficient | 1.0 | 0.01-10 |
| gratefk | genpar | General rating curve exponent factor | 1.5 | 1.0-3.0 |
| gldepi | genpar | Internal lake depth (m) | 1.0 | 0.5-10 |
| gldepol | genpar | General olake depth (m) | 5.0 | 1-50 |

### HYPE Lake Outflow Logic (from sw_proc.f90)

For **unregulated lakes** (regvol not set):
```
if water_level > w0ref:
    outflow = rate * (water_level - w0ref)^exp
else:
    outflow = 0
```

For **regulated lakes** (regvol > 0, wmin calculated):
```
if water_level > w0ref:
    outflow = max(rating_curve_flow, production_flow)
elif water_level > wmin:
    outflow = production_flow
else:
    outflow = 0
```
where `wmin = -regvol * 1e6 / lake_area_m2` (negative = below threshold).

### Known Issues

1. **Lumped setup limitation**: With 1 subbasin, the lake IS the entire basin outlet.
   All water passes through the lake, which may over-attenuate the hydrograph.
   Use multi-subbasin setups for realistic lake routing.

2. **Rating curve calibration**: Generated rating curves are estimates.
   Calibrate `rate` and `exp` against observed discharge downstream of the lake.

3. **Monthly inflows in DamData**: The `qinfjan-qinfdec` values are estimated
   from area-runoff relationships. For accurate dam regulation, run a natural
   (no-dam) simulation first and use those monthly flows.

4. **LakeData vs DamData**: Both files can exist simultaneously. DamData
   provides additional regulation on top of LakeData configuration.

---

## Running HYPE

```bash
# From the directory containing info.txt:
KISSPATH_BINARIES/hype/hype ./

# Or specify a different info directory:
KISSPATH_BINARIES/hype/hype /path/to/run/directory/

# CRITICAL: The argument MUST end with a slash (/)
# Without slash: looks for info.txt at wrong path
```

**Exit codes**:
- 0: Success
- 1: Fatal error (check hyss_*.log in logdir or infodir)
- Other: Fortran runtime error

**Output files**:
- `timeCOUT.txt` -- Simulated discharge at each subbasin (m^3/s)
- `timeROUT.txt` -- Observed discharge (-9999 = missing) (m^3/s)
- `timeSNOW.txt` -- Snow water equivalent (mm)
- `timeEVAP.txt` -- Evapotranspiration (mm/day)
- `timeCPRC.txt` -- Corrected precipitation (mm/day)
- `mapCOUT.txt` -- Spatial map output (periodic averages)

---

## Water Quality: Nitrogen & Phosphorus (NPC) Simulation

HYPE's unique selling point — integrated N/P transport with hydrology. No external
coupling needed. Simulates 4 substance pools: IN (inorganic N), ON (organic N),
SP (soluble P), PP (particulate P).

### Enabling NPC Simulation

```bash
# Step 1: Generate CropData.txt from NPKGRIDS (auto-detects region + reads real fertilizer rates)
python tools/s9_water_quality/generate_cropdata.py \
    --lat 32.4 --lon 115.6 \
    --crops wheat,maize \
    --output modelfiles/CropData.txt

# Step 2: Add REGION column to GeoData.txt (required for NPC)
# Ensure GeoData.txt header includes REGION and each subbasin has REGION=1

# Step 3: Enable N/P in info.txt and add NPC parameters to par.txt
python tools/s9_water_quality/configure_npc.py \
    --info_txt info.txt \
    --par_txt modelfiles/par.txt \
    --substances "N P" \
    --region huai_river \
    --geoclass modelfiles/GeoClass.txt

# Step 4: Run HYPE (same binary, NPC is activated by 'substance N P' in info.txt)
python tools/s7_execution/run_hype.py --project_dir <path>

# Step 5: Parse nutrient output
python tools/s9_water_quality/parse_npc_output.py \
    --result_dir resultdir/ \
    --subbasin_id 1 \
    --basin_area_km2 11573 \
    --output_csv nutrient_loads.csv
```

### Data Sources for NPC

| Input File | Data KI | Tool | Auto? |
|-----------|---------|------|-------|
| CropData.txt | NPKGRIDS + crop calendar | `generate_cropdata.py` | YES |
| GeoData REGION | Manual | Add column | Simple |
| Soil N/P pools (par.txt) | Literature defaults | `configure_npc.py` | YES |
| Freundlich P params | Literature | `configure_npc.py` | YES |

### info.txt NPC Configuration

Add to info.txt to enable nutrient simulation:
```
substance   N P                    !! Enable nitrogen + phosphorus
timeoutput variable cout rout reTN reTP ccIN ccON ccSP ccPP
```

### Key NPC Parameters (par.txt)

| Parameter | Type | Description | Range | Sensitivity |
|-----------|------|-------------|-------|-------------|
| fastn0 | genpar | Initial fast N pool (kg/km²) | 1-100 | Medium |
| fastp0 | genpar | Initial fast P pool (kg/km²) | 0.1-50 | Medium |
| humusn0 | landpar | Humus N pool (kg/km²/m) | 50-500 | High |
| humusp0 | landpar | Humus P pool (kg/km²/m) | 5-50 | High |
| denitrlu | landpar | Land denitrification (kg/m²/day) | 0.0001-0.001 | High |
| denitwr | genpar | River denitrification (kg/m²/day) | 0.001-0.01 | Medium |
| denitwl | genpar | Lake denitrification (kg/m²/day) | 0.0005-0.005 | Medium |
| minerfn | landpar | Fast N mineralization (1/day) | 0.001-0.005 | Medium |
| sedon | genpar | ON sedimentation (kg/m²/day) | 0.0001-0.01 | Medium |
| sedpp | genpar | PP sedimentation (kg/m²/day) | 0.0001-0.01 | Medium |
| soilcoh | soilpar | Soil cohesion for erosion (kPa) | 5-15 | P only |
| soilerod | soilpar | Soil erodibility factor | 0.5-2.0 | P only |

### NPC Output Variables

Use `c1*` (computed main flow) variables for modelled concentrations. The `re*`
variables require observed nutrient data (xobs) and will show -9999 without it.

| Variable | File | Unit | Description |
|----------|------|------|-------------|
| c1TN | timeC1TN.txt | ug/L | Modelled TN in main outflow |
| c1TP | timeC1TP.txt | ug/L | Modelled TP in main outflow |
| c1IN | timeC1IN.txt | ug/L | Inorganic N concentration |
| c1ON | timeC1ON.txt | ug/L | Organic N concentration |
| c1SP | timeC1SP.txt | ug/L | Soluble P concentration |
| c1PP | timeC1PP.txt | ug/L | Particulate P concentration |

**IMPORTANT**: Do NOT use `reTN`, `reIN`, `reSP` — these require observed nutrient
data and output -9999 without it. Always use `c1TN`, `c1IN`, `c1SP` for modelled output.

### Expected Nutrient Yields

| Land use | TN (kgN/ha/yr) | TP (kgP/ha/yr) | Source |
|----------|----------------|----------------|--------|
| Agricultural (China) | 5-20 | 0.5-3 | Chinese watershed studies |
| Agricultural (US Midwest) | 10-40 | 1-5 | SPARROW/USGS |
| Forest | 1-5 | 0.05-0.5 | Background levels |
| Urban | 5-15 | 1-3 | USEPA |

### NPC Warmup Requirements

N/P pools need 3-5 years of warmup to stabilize. Set `nyskip >= 3` in time.sim
or a sufficiently early `bdate` in info.txt. Check that `c1TN` reaches a stable
seasonal pattern before the evaluation period.

### NPC Known Issues

1. **Lumped (1-subbasin) setups produce unrealistic IN/SP concentrations.** Dissolved
   inorganic forms (IN, SP) accumulate without downstream export. Use multi-subbasin
   setups (3+ subbasins) for NPC simulation. Organic/particulate forms (ON, PP) are
   unaffected and work correctly in lumped setups.

2. **GeoClass `special=2` requires LakeData.txt.** Do NOT set special=2 (internal lake)
   on any SLC class unless LakeData.txt is provided. Without it, HYPE creates a zero-
   volume lake that traps all water. Use special=0 for regular water classes.

3. **ForcKey.txt location**: Must be in `forcingdir/`, not `modeldir/`. HYPE looks for
   it in the forcing directory path specified in info.txt.

4. **Pobs/Tobs must NOT have `!!` comment lines.** HYPE expects the header row (DATE
   followed by subbasin IDs) as line 1. Comment lines cause silent data misparse.

---

## VIC-HYPE Coupling Points

HYPE and VIC serve complementary roles in HydroCraft:

| Aspect | VIC | HYPE | Coupling |
|--------|-----|------|---------|
| Forcing | 3-hourly gridded | Daily per-subbasin | CMFD/MSWX -> aggregate to daily for HYPE |
| Soil | Grid-cell parameters | Per soil-type parameters | HWSD shared source |
| Routing | External (Lohmann/CaMa) | Internal (MAINDOWN) | Compare discharge at outlet |
| Water quality | Not supported | N/P transport | HYPE adds nutrient dimension to VIC basins |
| Scale | Any | Subbasin (>10 km^2 typical) | VIC grid -> HYPE subbasins via area-weighted mapping |

**Cross-model comparison**: Use `compare_vic_hype.py` to compare discharge time series at the outlet, computing NSE, KGE, and PBIAS for both models against observations.

---

## Common Errors and Diagnostics

See `diagnostics/triplets.yaml` for the full triplet catalog (24 triplets). Key failure modes:

1. **SLC fractions don't sum to 1.0** -- SILENT ERROR, no warning, wrong water balance
2. **Missing trailing slash in info.txt paths** -- Fatal, but cryptic "file not found" message
3. **par.txt value count mismatch** -- Fatal, must match exact number of land-use/soil types
4. **MAINDOWN topology has cycles** -- Fatal at startup, check ordering
5. **Forcing dates don't match bdate/edate** -- Fatal, forcing must cover entire period
6. **Tab vs space in input files** -- HYPE expects TAB separators, spaces may cause silent misparse

---

## Validated Results

### Bengbu (蚌埠) — Huai River, 1981-1990 (production_validated)

| Metric | Value |
|--------|-------|
| Basin | Huai River @ Bengbu, ~121,330 km² |
| Period | 1980-1990 (1980 warmup, 1981-1990 evaluated) |
| Forcing | CMFD 0.1° 3-hourly → daily |
| Setup | Lumped (1 subbasin), 3 SLC classes |
| NSE | **0.678** |
| KGE | **0.740** |
| R² | 0.712 |
| PBIAS | +19.8% (slight overprediction) |
| Mean obs Q | ~900 m³/s |
| Mean sim Q | ~1,080 m³/s |
| Seasonal cycle | Captured correctly (monsoon peak Jun-Aug) |
| Output | `outputs/bengbu_hype_1980_1990/` |
| Plots | `hype_discharge_comparison.png`, `hype_scatter.png`, `hype_annual_cycle.png` |

**Errors found during validation** (9 run attempts):
1. CMFD precip in kg/m²/s — must ×10800 (dt_u03)
2. GeoClass streamdepth=0 → zero discharge (dt_s08)
3. SLC fractions validation needed (dt_s01)

### Chaohe (潮河) — North China, 2001-2010

| Metric | Value |
|--------|-------|
| Basin | Chaohe @ Zhangjiaofen, ~8,783 km² |
| Period | 2000-2010 (2000 warmup, 2001-2010 evaluated) |
| Setup | Lumped (1 subbasin) |
| Mean sim Q | 21.7 m³/s |
| Literature Q | 31-47 m³/s |
| Assessment | 46% low — needs calibration or semi-distributed setup |

---

## Calibration: Built-in Optimization (Stage s10)

HYPE has a powerful built-in optimization engine in `optim.f90` (3,422 lines) supporting
Monte Carlo, DEMC, staged MC, Brent line search, and quasi-Newton methods. The HYPE binary
handles calibration internally -- no external optimizer is needed.

### Calibration Methods

| Method | Code | Best For | Speed |
|--------|------|----------|-------|
| Monte Carlo | MC | First exploration, identify parameter sensitivity | Fast |
| DEMC (Differential Evolution Markov Chain) | DEMC | Posterior sampling, uncertainty | Medium |
| Staged Monte Carlo | SM | Progressive zoom on parameter space | Medium |
| Brent line search | BN | Local refinement around a good solution | Fast |
| Quasi-Newton BFGS | Q2 | Gradient-based local optimization | Fast |

### Calibration Criteria

| Code | Name | Direction | Recommended For |
|------|------|-----------|-----------------|
| MKG | Mean Kling-Gupta Efficiency | max -> 1 | RECOMMENDED (balanced bias/variability/correlation) |
| MNS | Mean Nash-Sutcliffe Efficiency | max -> 1 | Classic, penalizes bias less |
| TAU | Kendall tau | max -> 1 | Robust to outliers |
| MRE | Mean Relative Error | min -> 0 | Volume bias calibration |
| MAR | Mean Absolute Relative Error | min -> 0 | Absolute volume bias |
| MCC | Mean Correlation Coefficient | max -> 1 | Timing only |
| MDA | Median NSE | max -> 1 | Multi-station calibration |

### Setting Up Calibration

```bash
# Step 1: Set up optpar.txt and add criteria to info.txt
python tools/s10_calibration/setup_calibration.py \
    --method MC \
    --geoclass modelfiles/GeoClass.txt \
    --info_txt info.txt \
    --output modelfiles/optpar.txt \
    --num_runs 500 \
    --criterion MKG \
    --crit_variable cout \
    --obs_variable rout \
    --outlet_subid 3

# Step 2: Run HYPE (calibration is automatic when calibration=Y in info.txt)
KISSPATH_BINARIES/hype/hype ./

# Step 3: Parse calibration results
python tools/s10_calibration/parse_calibration_results.py \
    --result_dir resultdir/ \
    --output_par best_par.txt \
    --geoclass modelfiles/GeoClass.txt \
    --output_csv calibration_results.csv \
    --plot_convergence convergence.png
```

### DEMC Calibration (Bayesian Posterior Sampling)

```bash
# DEMC requires >= 3 populations. More populations = better exploration but slower.
python tools/s10_calibration/setup_calibration.py \
    --method DEMC \
    --geoclass modelfiles/GeoClass.txt \
    --info_txt info.txt \
    --output modelfiles/optpar.txt \
    --demc_ngen 100 --demc_npop 5 \
    --criterion MKG \
    --crit_variable cout \
    --obs_variable rout

KISSPATH_BINARIES/hype/hype ./
```

### Calibrating with NPC Parameters

```bash
# Include N/P parameters in calibration
python tools/s10_calibration/setup_calibration.py \
    --method MC \
    --geoclass modelfiles/GeoClass.txt \
    --info_txt info.txt \
    --output modelfiles/optpar.txt \
    --num_runs 1000 \
    --criterion MKG \
    --crit_variable cout \
    --obs_variable rout \
    --substances "N P"
```

### Calibrating a Subset of Parameters

```bash
# Calibrate only the most sensitive parameters (faster convergence)
python tools/s10_calibration/setup_calibration.py \
    --method MC \
    --geoclass modelfiles/GeoClass.txt \
    --info_txt info.txt \
    --output modelfiles/optpar.txt \
    --num_runs 500 \
    --criterion MKG \
    --crit_variable cout \
    --obs_variable rout \
    --params_subset "lp,cevpam,wcfc,wcwp,wcep,rrcs1,cmlt"
```

### Calibration Output Files

| File | Location | Description |
|------|----------|-------------|
| allsim.txt | resultdir/ | All simulations: criterion + performance + parameters (CSV) |
| bestsims.txt | resultdir/ | Best N parameter sets (same format as allsim.txt) |
| calibration.log | resultdir/ | Detailed calibration progress |

### optpar.txt Format Reference

The file has two sections:
1. **Header** (1 line skipped + 20 info lines): optimization task and method settings
2. **Parameter block**: triplets of (min, max, precision) for each parameter

```
!! Heading (skipped)
task MC                    !! Method code: MC, DE, SM, BN, Q2
task WA                    !! Write all results to allsim.txt
num_mc 500                 !! Number of Monte Carlo runs
num_ens 10                 !! Number of best to keep
cal_log Y                  !! Write calibration.log
!! (reserved)              !! Pad to 20 info lines
...
!! Parameter ranges (min / max / precision triplets)
lp      0.1                !! min value (1 value for general params)
lp      1.0                !! max value
lp      3                  !! decimal precision
wcfc    0.05  0.05         !! min values (nsoil values for soil params)
wcfc    0.50  0.50         !! max values
wcfc    3     3            !! precision
```

When min == max for a parameter, it is NOT calibrated (fixed value).

### info.txt Calibration Settings

Added automatically by setup_calibration.py:
```
calibration Y
crit 1 criterion MKG       !! Criterion code
crit 1 cvariable cout       !! Computed (simulated) variable
crit 1 rvariable rout       !! Recorded (observed) variable
crit 1 weight 1.0           !! Weight for multi-criteria
crit meanperiod 1           !! 1=daily, 2=weekly, 3=monthly
crit subbasin 3             !! Subbasin for single-station calibration
```

### Calibration Tips

1. **Start with MC**: Run 200-500 MC simulations first to identify sensitive parameters
2. **Use KGE (MKG)**: More balanced than NSE -- penalizes bias equally with variability
3. **Warmup matters**: Ensure 1-2 years warmup (bdate before cdate) for stable states
4. **Qobs.txt required**: Calibration needs observed discharge in Qobs.txt (same format as Pobs.txt)
5. **Subset calibration**: For many parameters, calibrate only the most sensitive ones first
6. **Check convergence**: Use parse_calibration_results.py to verify the optimizer has converged
7. **DEMC for uncertainty**: DEMC produces posterior parameter distributions, not just a best fit

---

## Recommendations for Future Runs

1. **Semi-distributed**: For basins >10,000 km², use 5-10 subbasins for routing attenuation
2. **Calibration**: Use `setup_calibration.py` with MC (exploration) or DEMC (posterior), key params: lp, cevpam, cmlt, wcfc, wcwp, wcep, rrcs1. See Stage s10 above.
3. **Nutrient calibration**: Include `--substances "N P"` in setup_calibration.py to calibrate NPC parameters jointly with hydrology
4. **Lake regulation**: Tools available — use `generate_lakedata.py` + `generate_damdata.py` to configure LakeData.txt/DamData.txt from HydroLAKES/GRanD


## Stage documentation (one doc per pipeline stage)

- docs/s1_subbasin_delineation.md
- docs/s2_slc_classification.md
- docs/s3_forcing_preparation.md
- docs/s4_geodata_generation.md
- docs/s5_parameter_setup.md
- docs/s6_lake_reservoir_config.md
- docs/s7_execution.md
- docs/s8_output_analysis.md
- docs/s9_water_quality.md
- docs/s10_calibration.md
