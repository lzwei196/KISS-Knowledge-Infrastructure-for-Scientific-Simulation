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
> Before starting, run: `python3 preflight_check.py` (in this KI directory). **Use `python3` (3.12, pcse 6.0.12) for ALL tools -- the default `python` (3.11) cannot import pcse (numpy ABI mismatch) and preflight FAILS.**

> **Weather from a data product (CMFD / MSWX / NASA POWER):** run `tools/s3_weather_prep/build_pcse_weather_from_source.py --source cmfd|mswx|nasa_power ...`. It reads the product through the shared loader `ki_tools_common.load_forcing.load_daily_forcing` and writes the PCSE CSV weather file. Do not read the product files yourself and do not build WOFOST weather from another model's input files.
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
| to run the pipeline stages | `tools/` (20 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (8 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (34 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (22 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-10-03 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/calib_run.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/calib_run.py --help` |
| `tools/s1_crop_params/load_crop_parameters.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s1_crop_params/load_crop_parameters.py --help` |
| `tools/s1_crop_params/validate_crop_params.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s1_crop_params/validate_crop_params.py --help` |
| `tools/s2_soil_params/convert_hwsd_to_pcse_soil.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s2_soil_params/convert_hwsd_to_pcse_soil.py --help` |
| `tools/s2_soil_params/validate_soil_params.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s2_soil_params/validate_soil_params.py --help` |
| `tools/s3_weather_prep/build_pcse_weather_from_source.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s3_weather_prep/build_pcse_weather_from_source.py --help` |
| `tools/s3_weather_prep/create_csv_weather_file.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s3_weather_prep/create_csv_weather_file.py --help` |
| `tools/s3_weather_prep/validate_weather_data.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s3_weather_prep/validate_weather_data.py --help` |
| `tools/s4_agromanagement/generate_agromanagement_yaml.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s4_agromanagement/generate_agromanagement_yaml.py --help` |
| `tools/s4_agromanagement/validate_agromanagement.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s4_agromanagement/validate_agromanagement.py --help` |
| `tools/s5_engine_config/configure_pcse_engine.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s5_engine_config/configure_pcse_engine.py --help` |
| `tools/s5_engine_config/validate_engine_config.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s5_engine_config/validate_engine_config.py --help` |
| `tools/s6_execution/check_simulation_status.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s6_execution/check_simulation_status.py --help` |
| `tools/s6_execution/run_wofost_simulation.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s6_execution/run_wofost_simulation.py --help` |
| `tools/s7_output_parsing/export_output_csv.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s7_output_parsing/export_output_csv.py --help` |
| `tools/s7_output_parsing/parse_wofost_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s7_output_parsing/parse_wofost_output.py --help` |
| `tools/s8_yield_analysis/compare_wofost_dssat.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s8_yield_analysis/compare_wofost_dssat.py --help` |
| `tools/s8_yield_analysis/compute_gridded_yield.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s8_yield_analysis/compute_gridded_yield.py --help` |
| `tools/s8_yield_analysis/generate_yield_map.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s8_yield_analysis/generate_yield_map.py --help` |
| `tools/s8_yield_analysis/validate_against_faostat.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s8_yield_analysis/validate_against_faostat.py --help` |

*20 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.
WOFOST forcing tools in this KI:
- `build_pcse_weather_from_source.py` — one point, straight from the product: `--source cmfd|mswx|nasa_power --lat --lon --elev --start_year --end_year [--forcing_dir] --output`. Calls the shared loader, writes the PCSE CSV (IRRAD kJ/m2/day = W/m2 × 86.4, TMIN/TMAX °C, VAP kPa from specific humidity + the source's pressure, WIND m/s, RAIN mm/day, SNOWDEPTH NaN) and `<output>.summary.json`. Stops and writes nothing on a missing value, a gap or a period the source does not cover. Give each point its own file name (dt_022). `mswx`: one build at a time (exfat disk).
- `create_csv_weather_file.py` — for weather you already hold as a daily table (station file): generic CSV → PCSE CSV. Same writer as the tool above.
- `validate_weather_data.py` — Validates weather data ranges and completeness

### Soil properties

- `convert_hwsd_to_pcse_soil.py` — Converts HWSD to PCSE soil parameters

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/HWSD/SKILL.md` for soil property documentation.

---

# WOFOST/PCSE Knowledge Infrastructure

**Model**: WOFOST 7.2 (WOrld FOod STudies) via PCSE 6.0 (Python Crop Simulation Environment)
**Domain**: Crop growth simulation / food production modelling
**Created by**: Zhang Jianyun Research Group, Hohai University

---

## Overview

WOFOST is the EU standard crop growth model developed at Wageningen University & Research. PCSE is its pure-Python implementation (`pip install pcse`), providing a clean programmatic API without compiled executables or batch files. This makes it an ideal complement to DSSAT for multi-model crop yield ensemble estimation within HydroCraft.

**Key advantage over DSSAT**: No compilation, no Fortran, no fixed-width column formatting. Everything is Python objects and YAML configuration. The entire simulation can be run in 15 lines of Python code.

**Key differences from DSSAT**:

| Aspect | WOFOST/PCSE | DSSAT |
|--------|-------------|-------|
| Language | Pure Python | Fortran + batch scripts |
| Phenology | DVS (0→1→2) continuous | V-stage/R-stage discrete |
| Soil model | Single-layer bucket (SMW/SMFCF/SM0) | Multi-layer (SLLL/SDUL/SSAT per layer) |
| Radiation units | **J/m2/day** (IRRAD) -- see WARNING below | MJ/m2/day (SRAD) |
| Precipitation units | **CSV column: mm/day** (CSVWeatherDataProvider divides /10 -> cm); internal var: cm/day (RAIN) | mm/day (RAIN) |
| Configuration | YAML files + Python dicts | Fixed-width text files (FileX) |
| Weather providers | NASAPower, CSV, Excel, custom | .WTH fixed-format files |
| Execution | `engine.run_till_terminate()` | `dscsm048` executable |

---

## Installation

```bash
pip install pcse
# PCSE 6.0 requires Python 3.8+
# Dependencies: numpy, PyYAML, SQLAlchemy, xlrd, openpyxl, requests
```

Verify installation:
```python
import pcse
print(pcse.__version__)  # Should print 6.0.x
```

---

## Pipeline Stages

| Order | Stage | Skill Document | Key Tools |
|-------|-------|---------------|-----------|
| 1 | Crop Parameter Configuration | [s1_crop_params_skill.md](docs/s1_crop_params_skill.md) | `load_crop_parameters`, `validate_crop_params` |
| 2 | Soil Parameter Setup | [s2_soil_params_skill.md](docs/s2_soil_params_skill.md) | `convert_hwsd_to_pcse_soil`, `validate_soil_params` |
| 3 | Weather Data Preparation | [s3_weather_prep_skill.md](docs/s3_weather_prep_skill.md) | `build_pcse_weather_from_source`, `create_csv_weather_file`, `validate_weather_data` |
| 4 | Agromanagement Definition | [s4_agromanagement_skill.md](docs/s4_agromanagement_skill.md) | `generate_agromanagement_yaml`, `validate_agromanagement` |
| 5 | Engine Configuration | [s5_engine_config_skill.md](docs/s5_engine_config_skill.md) | `configure_pcse_engine`, `validate_engine_config` |
| 6 | Simulation Execution | [s6_execution_skill.md](docs/s6_execution_skill.md) | `run_wofost_simulation`, `check_simulation_status` |
| 7 | Output Parsing | [s7_output_parsing_skill.md](docs/s7_output_parsing_skill.md) | `parse_wofost_output`, `export_output_csv` |
| 8 | Yield Analysis & Ensemble | [s8_yield_analysis_skill.md](docs/s8_yield_analysis_skill.md) | `compute_gridded_yield`, `compare_wofost_dssat`, `generate_yield_map` |

**Stages 1-4 can run in parallel.** Stage 5 depends on all of 1-4. Stage 6 depends on 5. Stages 7-8 are sequential after 6.

---

## Output Description

**Source of truth**: `dag.yaml`. The dag is the model identity for outputs; if this section and the dag disagree, the dag wins.

**Headline output** (dag `validation_rank: 1`):

> `TWSO` — Total crop storage-organ biomass (harvestable yield) (`kg ha-1`)

| Output variable (dag `var`) | Rank | Unit | Description |
|-----------------------------|------|------|-------------|
| `TWSO` | 1 | `kg ha-1` | Total crop storage-organ biomass (harvestable yield) |

Other dag outputs currently exposed by this KI: `DVS`, `DOA`, `DOM`, `LAI`, `LAIMAX`, `TAGP`, `TWLV`, `TWST`, `TWRT`, `TRA`, `CTRAT`, `SM`, `RD`, `WWLOW`.

---

## Unit Conversion Table

**Exact I/O shapes live in `docs/format_spec.yaml`; output identity and output units live in `dag.yaml`.** This table captures the known unit conversions and output-unit facts that are surfaced in this skill document.

| Variable | Source or context | Source unit | Model or output unit | Conversion / handling |
|----------|-------------------|-------------|----------------------|-----------------------|
| `TWSO` | dag output | model output | `kg ha-1` | No conversion stated here; use dag output unit. |
| `IRRAD` | shared loader `srad_wm2` (24-h mean) | `W/m2` | CSV column `kJ/m2/day`; internal `J/m2/day` | CSV: `× 86.4` (done by `build_pcse_weather_from_source`); PCSE then `× 1000`. A hand-built WeatherDataContainer takes `J/m2/day` = `W/m2 × 86400`. |
| `E0` / `ES0` / `ET0` | Hargreaves evapotranspiration output | `mm/day` | `cm/day` | Divide by 10. |
| `RAIN` | `CSVWeatherDataProvider` CSV column | `mm/day` | internal model variable `cm/day` | PCSE divides the CSV value by 10 internally. |
| `VAP` | weather input vapor pressure | `hPa` or `mbar` when supplied that way | `kPa` | `1 kPa = 10 hPa = 10 mbar`; convert to kPa before model use. |

---

## Quick Start — Minimal WOFOST Simulation

```python
import pcse
from pcse.models import Wofost72_WLP_FD
from pcse.input import NASAPowerWeatherDataProvider, YAMLCropDataProvider
from pcse.input import WOFOST72SiteDataProvider  # NOTE: moved from pcse.util in PCSE 6.0
from pcse.base import ParameterProvider
import yaml, datetime

# 1. Weather — automatic from NASA POWER
# NOTE: NASAPowerWeatherDataProvider may fail behind a proxy. If so, use
# the shared loader (source='nasa_power', no proxy) and build a
# CSV weather file with tools/s3_weather_prep/build_pcse_weather_from_source.py
# (--source nasa_power), then load it with CSVWeatherDataProvider.
weather = NASAPowerWeatherDataProvider(latitude=52.0, longitude=5.5)

# 2. Crop parameters — built-in PCSE database
crop = YAMLCropDataProvider()  # loads all built-in crop YAMLs
crop.set_active_crop('wheat', 'Winter_wheat_101')
cropdata = crop

# 3. Soil parameters — example for medium-textured soil
soildata = {
    'SMW': 0.10,     # wilting point (cm3/cm3)
    'SMFCF': 0.30,   # field capacity (cm3/cm3)
    'SM0': 0.45,      # saturation (cm3/cm3)
    'CRAIRC': 0.04,   # critical air content
    'K0': 10.0,       # saturated hydraulic conductivity (cm/day)
    'SOPE': 1.0,      # max percolation root zone (cm/day)
    'KSUB': 1.0,      # max percolation subsoil (cm/day)
    'RDMSOL': 120.0,  # max rootable depth (cm)
    'IFUNRN': 0,      # infiltration flag (0=no runoff)
    'SSMAX': 0.0,     # max surface storage (cm)
    'SSI': 0.0,       # initial surface storage (cm)
    'WAV': 20.0,      # initial available water (cm)
    'NOTINF': 0.0,    # fraction not infiltrating
    'SMLIM': 0.30,    # soil moisture limit for reduction
}

# 4. Site parameters — NOTE: CO2 is NOT accepted in PCSE 6.0 SiteDataProvider
sitedata = WOFOST72SiteDataProvider(WAV=20)

# 5. Assemble ParameterProvider
params = ParameterProvider(cropdata=cropdata, soildata=soildata, sitedata=sitedata)

# 6. Agromanagement — YAML string
agro_yaml = """
- 2000-10-01:
    CropCalendar:
        crop_name: wheat
        variety_name: Winter_wheat_101
        crop_start_date: 2000-10-15
        crop_start_type: sowing
        crop_end_date:
        crop_end_type: maturity
        max_duration: 365
    TimedEvents: null
    StateEvents: null
"""
agro = yaml.safe_load(agro_yaml)

# 7. Run simulation
engine = Wofost72_WLP_FD(params, weather, agro)
engine.run_till_terminate()

# 8. Get results
output = engine.get_output()
summary = engine.get_summary_output()

import pandas as pd
df = pd.DataFrame(output).set_index('day')
print(f"Yield (TWSO): {df['TWSO'].iloc[-1]:.0f} kg/ha")
print(f"Max LAI: {df['LAI'].max():.2f}")
print(f"Final DVS: {df['DVS'].iloc[-1]:.2f}")
```

---

## Critical Domain Knowledge (Non-Obvious Facts)

### 1. Unit Traps (SILENT ERRORS) — VERIFIED 2026-03-19

- **⚠️ IRRAD is J/m2/day (JOULES), NOT kJ or MJ!** — The PCSE documentation says "kJ" but the internal DB stores JOULES. Spain example: IRRAD=15,657,000 J/m²/d = 15.7 MJ. **From a W/m2 daily mean: internal IRRAD = W/m2 × 86400** (the CSV column is kJ/m2/day = W/m2 × 86.4; the provider multiplies by 1000). If IRRAD < 100,000, it's 1000x too low and yield will be ZERO. This is the #1 cause of WOFOST zero-yield bugs. **(dt_v005)**
- **E0/ES0/ET0 are cm/day, NOT mm/day** — Spain DB values: ET0=0.08-0.88 cm/d. If Hargreaves gives mm/day, **divide by 10**. Values >1.5 cm/d cause extreme water stress. **(dt_v006)**
- **RAIN unit is context-dependent** -- In a **CSVWeatherDataProvider CSV the RAIN column is mm/day** (PCSE divides it by 10 -> cm internally); only the *internal model variable* / a hand-built WeatherDataContainer use cm/day. Writing the CSV in cm makes rainfall 10-100x too low -> drought-stressed crop, low yield. Ground truth: create_csv_weather_file.py docstring + dt_004.
- **VAP is kPa, NOT hPa or mbar** — Vapor pressure must be in kPa. 1 kPa = 10 hPa = 10 mbar.

### Validated Results — Bengbu (March 2026 run, DB crop params)
| Crop | WOFOST | DSSAT | AquaCrop |
|------|:---:|:---:|:---:|
| Winter wheat | **3,543 kg/ha** | 3,217 | 6,307 |
| Grain maize | **6,102 kg/ha** | 5,780 | 14,281 |

WOFOST matches DSSAT within 10% for both crops with default parameters.

### ⚠️ Validating against FAOSTAT NATIONAL yields — scale/trend mismatch (added 2026-06-08)
Point or few-point WOFOST runs compared to a FAOSTAT NATIONAL yield series are a **domain/scale mismatch**, not a fair skill test. The national aggregate is spatially smoothed across many agro-climates, partly irrigated, and rises on a multi-decade technology trend (improved hybrids, fertiliser, management). A fixed-parameter, weather-driven point sim has far higher interannual variance (drought-year crop failures -> TWSO≈0; wet years -> high yield) than the buffered national mean, so **raw NSE/KGE are intrinsically very negative and raw r is low regardless of model quality.**

**Correct framing when only national obs exists:**
- Prefer sub-national / admin-unit yield obs at the simulated scale if available.
- Otherwise **detrend BOTH series and report detrended r** as the skill metric (removes the technology trend the model cannot reproduce).
- Pick a **rainfed semi-arid country+crop in WLP_FD** to maximise the weather-driven signal.

**Empirical anchor (Morocco wheat, 3 points, 1985-2024, WLP_FD, fixed Nov sowing, default Winter_wheat_107):** raw r=0.278, **detrended r=0.287** — i.e. detrending does NOT lift this case above the 0.5 skill threshold. The residual gap is structural (point-vs-national aggregate) + uncalibrated fixed-calendar agromanagement (Mediterranean wheat sowing follows the autumn rains, not a fixed date), which is **calibration / human-engineering territory, not a KI artifact bug.** Do not treat a low r on a point-vs-national comparison as a forcing/physics failure.

> **CANONICAL TOOL (added 2026-06-08):** Use `tools/s8_yield_analysis/validate_against_faostat.py SIM_CSV CROP COUNTRY OUT_JSON [UNITS]` for FAOSTAT-national validation. It is **obs_shape-aware**: it classifies the comparison as `regional_aggregate_time_series` and reports ONLY the dag-valid metric families — `magnitude_accuracy` (pbias, decadal_mean_pbias, mean_abs_pct_err) and `trend_match` (detrended r, first-difference r, trend-slope ratio). Raw NSE/r/KGE are relegated to an `invalid_for_obs_shape` block (the pre-retry gate REJECTs them as `REJECT_WRONG_METRIC` if reported as the verdict — see triplet dt_faostat_obs_shape). SIM_CSV needs columns `year,sim_tha`. The other s8 tools (compute_gridded_yield / compare_wofost_dssat / generate_yield_map) remain for gridded/cross-model work.
>
> **Validated reference (USA Corn Belt maize, 3-pt avg, PP mode, 1991-2023, default Grain_maize_205):** magnitude_accuracy pbias +6.6% (decadal +3.4%); trend_match detrended r=0.506, first-diff r=0.611. This PASSES under the correct framing — raw NSE=-1.4/r=0.09 are structurally meaningless for this obs_shape and must NOT be the verdict.

### Performance Metrics — Convention Bars

**Source of truth**: `docs/validation_convention.yaml`. A null band in the convention is written here as `no cited threshold`; do not substitute remembered thresholds.

| Dag variable | Metric | Direction | Satisfactory band | Citation key |
|--------------|--------|-----------|-------------------|--------------|
| `DVS` | `nse` | maximize | no cited threshold | none |
| `DOA` | `pbias` | zero_centered | no cited threshold | none |
| `DOM` | `pbias` | zero_centered | no cited threshold | none |


### PCSE 6.0 API Changes (validated 2026-04-10)

| Change | Old (PCSE 5.x) | New (PCSE 6.0) |
|--------|----------------|----------------|
| SiteDataProvider import | `from pcse.util import WOFOST72SiteDataProvider` | `from pcse.input import WOFOST72SiteDataProvider` |
| CO2 parameter | `WOFOST72SiteDataProvider(WAV=20, CO2=400)` | CO2 **removed** — handled internally via crop CO2 tables |
| SNOWDEPTH | Optional | Must not be NaN — set to 0.0 in custom weather |

### Maize Variety Selection Guide

| Variety | TSUM1 | TSUM2 | Best for | Yield range |
|---------|-------|-------|----------|-------------|
| Grain_maize_201 | 750 | 859 | Short season, N Europe | Low at 32°N |
| Grain_maize_204 | 855 | 900 | Medium season, C Europe / China | Good for Bengbu |
| Grain_maize_205 | 900 | 1000 | Long season, NE China / US Corn Belt | Best for Harbin |

### Spring Wheat Note
PCSE has no dedicated spring wheat variety. Use `Winter_wheat_107` (VERNSAT=5 days, effectively spring type) for spring-sown sites like Harbin.

### 2. Vernalization for Winter Crops
- Winter wheat/barley REQUIRE vernalization parameters: VERNSAT (days), VERNBASE (base temp), VERNDVS (DVS to force-stop vernalization).
- If VERNSAT is too high and winter is mild, DVS gets permanently stuck before anthesis — **the crop never matures, yield is zero, NO error message**.
- VERNDVS is a safety cutoff: forces vernalization to complete at this DVS, even if VERNSAT days not reached. Default ~0.30.
- If simulating winter crops sown in autumn, the campaign start date must precede the sowing date (e.g., campaign starts Oct 1, sowing Oct 15).

### 3. Simulation Mode Confusion
- **Wofost72_PP** — Potential Production: no water stress, no soil. Use for theoretical maximum yield.
- **Wofost72_WLP_FD** — Water-Limited Production, Free Drainage: includes water balance, water stress affects growth. Most common for real-world simulations.
- **Wofost72_WLP_CWB** — Water-Limited, Classic Water Balance: includes groundwater influence.
- Using PP mode when you want water-limited results gives unrealistically high yields — **silent error**.

### 4. crop_name and variety_name Are Case Sensitive
- `"Wheat"` fails. `"wheat"` works.
- `"winter_wheat_101"` fails. `"Winter_wheat_101"` works.
- Mismatch produces a `KeyError` that does not clearly explain the case-sensitivity issue.

### 5. AFGEN Tables Must Be Monotonic in X
- PCSE uses AFGEN (table interpolation) for many parameters (AMAXTB, SLATB, FOTB, etc.).
- Tables are defined as `[x1, y1, x2, y2, ...]` pairs. The x values MUST be monotonically increasing.
- Non-monotonic x values cause silent interpolation errors or runtime exceptions.

### 6. DVS Development Stage Interpretation
- DVS = 0: emergence
- DVS = 1: anthesis (flowering)
- DVS = 2: maturity (harvest)
- If DVS never reaches 2.0, the crop did not mature. Check TSUM1/TSUM2 (too high for the climate?) or vernalization (stuck?).

### 7. `convert_hwsd_to_pcse_soil.py` produced soils that were far too dry (dt_v007) — FIXED 2026-09-12

**Status: OPEN as of 2026-09-09. Every WOFOST site built with this tool has too little
plant-available water.** Not a site-specific problem — the bias runs across the whole texture
triangle. Water-limited (WLP) runs are affected; potential-production (PP) runs are not.

`tools/s2_soil_params/convert_hwsd_to_pcse_soil.py` → `pedotransfer_wosten()` is documented as
"Wosten et al. (1999)". It is not: Wösten's HYPRES functions are van Genuchten parameter
regressions, while the code is three ad-hoc linear forms

```python
SMW   = 0.001 + 0.26*(clay/100) + 0.05*(om/100)
SMFCF = 0.02  + 0.37*(clay/100) + 0.15*(om/100) + 0.10*(silt/100)
```

whose output is biased low everywhere. Corrected magnitudes (swept over the 12 USDA class
centroids by two reviewers): **WP and FC are ~0.4-0.6x published values**; **PAW is 0.53-0.97x** —
worst for sandy loam, nearly correct for clay and silty clay. Class centroids:

| texture | this tool SMW | this tool SMFCF | PAW |
|---|---|---|---|
| sand | 0.009 | 0.038 | 0.028 |
| loam | 0.054 | 0.136 | 0.082 |
| silt loam | 0.054 | 0.156 | 0.102 |
| clay | 0.158 | 0.264 | 0.106 |

A loam at field capacity 0.136 and a sand at wilting point 0.009 are not physical. Measured
against the canonical shared bridge at one Henan cell (HWSD MU 11509, sand 36 / clay 21):

| source | WP | FC | PAW |
|---|---|---|---|
| `ki_tools_common.soil_utils.saxton_rawls` | 0.116 | 0.233 | **0.117** |
| DSSAT KI `convert_hwsd_to_sol.py` | 0.134 | 0.287 | **0.153** |
| **this tool** | 0.056 | 0.142 | **0.086** |

**The bypass**: `get_texture_from_hwsd()` calls `ki_tools_common.soil_utils.lookup_hwsd`, and
`lookup_hwsd` already returns `result['hydraulics'] = saxton_rawls(sand, clay, oc)`. The tool takes
the raw texture out of that return value, discards those hydraulics, and recomputes them worse.

**But do not simply switch to `ki_tools_common.soil_utils.saxton_rawls` — it has its own two
defects** (found 2026-09-09 while chasing this one):

- it is **not** Saxton-Rawls. Its own inline comment says it is a 12-entry Rawls, Brakensiek &
  Saxton (1982) texture-class lookup — a step function. Clay 18/20/22/26% all return exactly
  WP 0.116 / FC 0.233; 28% jumps to 0.188 / 0.312.
- its `om` argument is a **silent no-op**: om = 0, 1.12, 5 and 20% return identical values.

The genuine continuous Saxton & Rawls (2006), correctly cited and actually using organic matter,
already exists in the library as a private fork:
`DSSAT/knowledge_infrastructure/tools/s3_soil_setup/convert_hwsd_to_sol.py::saxton_rawls`.

**Correct fix, in this order** (the ordering matters — an earlier version of this ticket had it
backwards and held the large fix hostage to the small one):

1. **Now: point this tool at `ki_tools_common.soil_utils.saxton_rawls` as it stands.** Map
   `wilting_point`→`SMW`, `field_capacity`→`SMFCF`, `saturation`→`SM0`, and correct the
   `pedotransfer_wosten` citation. Measured effect: re-running C01 rainfed through PCSE with each
   soil moved yield by **+10.5% / +42.1% / 0%** across three seasons. That is the bulk of the error.
2. **Separately, not blocking (1): upgrade the canonical function itself.** It is worth a further
   3–5% at that cell — real, but do not delay (1) for it. The genuine continuous Saxton & Rawls
   (2006) already exists in the library in at least six copies, e.g.
   `DSSAT/.../convert_hwsd_to_sol.py::saxton_rawls` and
   `SWAT_Plus/.../s4/hwsd_to_swatplus_soil.py::saxton_rawls_awc` (the same correct equations).
   Promote one, **re-homed rather than copied** — explicit units, documented OC→OM, optional
   measured bulk density, unrounded internals — and **ship a numeric accuracy test against the
   paper's published class values**. No accuracy test exists anywhere in the library today; the only
   one asserts ordering and a Ksat range, which is how a function named after a paper and never
   checked against it survived this long.

⚠️ **Do not "just fix the `om` no-op".** `soil_utils.py:269` passes `oc` into a parameter named and
documented as `om` — a 1.724× unit error that is currently harmless *only because the argument is
dead*. Making `om` live without fixing that line would silently split EPIC (which correctly passes
OM) from `lookup_hwsd` (which passes OC). Fix both together or neither.

⚠️ The canonical function has two further dead inputs: it **discards the measured bulk density** and
back-derives it from the class saturation (which is why its SAT 0.463 is the outlier while WOFOST
and DSSAT independently agree at ~0.475 from the measured BD 1.39), and it is a **step function** —
clay 15–26% all return the same values, stepping at clay 27%.

**Why the validator did not catch it**: `validate_soil_params.py` only checks ordering
(`SMW < SMFCF < SM0`) and a porosity ceiling. All three hold at half-scale. Ordering checks cannot
detect a uniform bias — a range check against texture class is needed.

**Impact on the record**: this voided the C01 stage-1 WOFOST-vs-DSSAT comparison; see
`KISSPATH_DATA/System1/offline/huai_scaleup/C01_STAGE1_FINDINGS.md`. Any past WLP result built with
this tool should be treated as run on a too-dry soil until re-run.

---

## Error Handling

When errors occur during WOFOST/PCSE simulation, consult the diagnostic triplets at [`diagnostics/triplets.yaml`](diagnostics/triplets.yaml). The triplets cover 15 failure patterns across 12 domains including YAML parse errors, unit conversion traps, vernalization misconfiguration, zero yield silent death, and PCSE API version changes.

---

## Model Couplings

See [`docs/model_couplings.yaml`](docs/model_couplings.yaml) for formal coupling definitions:
- **HWSD → PCSE soil**: HWSD raster/MDB → pedotransfer → WOFOST soil parameters
- **WOFOST ↔ DSSAT ensemble**: Run both models per grid cell → average yields → uncertainty bounds
- **WOFOST LAI → VIC feedback**: WOFOST daily LAI → VIC vegetation parameter update (experimental)

---

## File Structure

```
knowledge_infrastructure/
├── SKILL.md                          # this file — agent entry point
├── knowledge_infrastructure.yaml     # schema with all stages, tools, docs, triplets
├── workflow/
│   └── workflow.md                   # agent-readable workflow document
├── tools/                            # Layer 1: validated tools
│   ├── s1_crop_params/
│   │   ├── load_crop_parameters.py
│   │   └── validate_crop_params.py
│   ├── s2_soil_params/
│   │   ├── convert_hwsd_to_pcse_soil.py
│   │   └── validate_soil_params.py
│   ├── s3_weather_prep/
│   │   ├── build_pcse_weather_from_source.py
│   │   ├── create_csv_weather_file.py
│   │   └── validate_weather_data.py
│   ├── s4_agromanagement/
│   │   ├── generate_agromanagement_yaml.py
│   │   └── validate_agromanagement.py
│   ├── s5_engine_config/
│   │   ├── configure_pcse_engine.py
│   │   └── validate_engine_config.py
│   ├── s6_execution/
│   │   ├── run_wofost_simulation.py
│   │   └── check_simulation_status.py
│   ├── s7_output_parsing/
│   │   ├── parse_wofost_output.py
│   │   └── export_output_csv.py
│   └── s8_yield_analysis/
│       ├── compute_gridded_yield.py
│       ├── compare_wofost_dssat.py
│       └── generate_yield_map.py
├── docs/                             # Layer 2: skill documents
│   ├── s1_crop_params_skill.md
│   ├── s2_soil_params_skill.md
│   ├── s3_weather_prep_skill.md
│   ├── s4_agromanagement_skill.md
│   ├── s5_engine_config_skill.md
│   ├── s6_execution_skill.md
│   ├── s7_output_parsing_skill.md
│   ├── s8_yield_analysis_skill.md
│   └── model_couplings.yaml
└── diagnostics/                      # Layer 3: diagnostic triplets
    └── triplets.yaml
```

---

*This knowledge infrastructure package was created using the Knowledge Dissection Toolkit developed by the Zhang Jianyun Research Group, Hohai University.*

---

## Crop Calendar Reference (China)

| Region | Latitude | Winter Wheat | Summer Maize | Rice |
|--------|----------|-------------|-------------|------|
| Northeast | >40°N | — | May-Sep | — |
| North China | 35-40°N | Oct-Jun | Jun-Sep | — |
| Huang-Huai | 32-35°N | Oct-Jun | Jun-Oct | — |
| Yangtze | 28-32°N | Nov-May | — | Apr-Oct |
| South | <28°N | — | — | Mar-Jul, Jul-Nov |

**Data sources on server:**
- GGCMI Crop Calendar: `KISSPATH_HOME/Crop_model_dataset/GGCMI_phase3_crop_calendar/`
- China Phenology GeoTIFF: `KISSPATH_HOME/Crop_model_dataset/8313530/`
- SPAM crop distribution: `KISSPATH_HOME/Crop_model_dataset/dataverse_files/`
