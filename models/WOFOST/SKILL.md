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

> **CMFD direct reader available:** Use `from ki_tools_common.netcdf_utils import load_cmfd_daily_all` to read CMFD 3-hourly data directly. Returns daily precip (mm), temp (°C with Tmin/Tmax), radiation (W/m²), wind, humidity. Handles subdirectory search (Prec/, Temp/, etc.) and unit conversions automatically.
> to verify that the model binary/package and required data are available.
>
> **DEBUGGING PROTOCOL** — When something goes wrong, follow this order:
> 1. **Check triplets** — `diagnostics/triplets.yaml` may already cover this error
> 2. **Read official docs** — The model's own documentation for expected formats/units
> 3. **Find working examples** — Check `outputs/` or the model's shipped test data
> 4. **Fix the tool** — With knowledge of what "correct" looks like
>
> Do NOT write custom debug scripts. The answers are in the docs and examples.

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.
WOFOST forcing tools in this KI:
- `extract_cmfd_weather.py` — Extracts CMFD data for PCSE weather input
- `convert_vic_to_pcse_weather.py` — Converts VIC forcing to PCSE weather format
- `create_csv_weather_file.py` — Creates CSV weather files for PCSE
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
| 3 | Weather Data Preparation | [s3_weather_prep_skill.md](docs/s3_weather_prep_skill.md) | `convert_vic_to_pcse_weather`, `create_csv_weather_file`, `validate_weather_data` |
| 4 | Agromanagement Definition | [s4_agromanagement_skill.md](docs/s4_agromanagement_skill.md) | `generate_agromanagement_yaml`, `validate_agromanagement` |
| 5 | Engine Configuration | [s5_engine_config_skill.md](docs/s5_engine_config_skill.md) | `configure_pcse_engine`, `validate_engine_config` |
| 6 | Simulation Execution | [s6_execution_skill.md](docs/s6_execution_skill.md) | `run_wofost_simulation`, `check_simulation_status` |
| 7 | Output Parsing | [s7_output_parsing_skill.md](docs/s7_output_parsing_skill.md) | `parse_wofost_output`, `export_output_csv` |
| 8 | Yield Analysis & Ensemble | [s8_yield_analysis_skill.md](docs/s8_yield_analysis_skill.md) | `compute_gridded_yield`, `compare_wofost_dssat`, `generate_yield_map` |

**Stages 1-4 can run in parallel.** Stage 5 depends on all of 1-4. Stage 6 depends on 5. Stages 7-8 are sequential after 6.

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
# ki_tools_common.load_forcing with source='nasa_power' and build a custom
# WeatherDataProvider (see tools/extract_cmfd_weather.py for the pattern).
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

- **⚠️ IRRAD is J/m2/day (JOULES), NOT kJ or MJ!** — The PCSE documentation says "kJ" but the internal DB stores JOULES. Spain example: IRRAD=15,657,000 J/m²/d = 15.7 MJ. **Convert from VIC: IRRAD = SW_W_m2 × 86400** (not × 86.4). If IRRAD < 100,000, it's 1000x too low and yield will be ZERO. This is the #1 cause of WOFOST zero-yield bugs. **(dt_v005)**
- **E0/ES0/ET0 are cm/day, NOT mm/day** — Spain DB values: ET0=0.08-0.88 cm/d. If Hargreaves gives mm/day, **divide by 10**. Values >1.5 cm/d cause extreme water stress. **(dt_v006)**
- **RAIN unit is context-dependent** -- In a **CSVWeatherDataProvider CSV the RAIN column is mm/day** (PCSE divides it by 10 -> cm internally); only the *internal model variable* / a hand-built WeatherDataContainer use cm/day. Writing the CSV in cm makes rainfall 10-100x too low -> drought-stressed crop, low yield. Ground truth: create_csv_weather_file.py docstring + dt_004.
- **VAP is kPa, NOT hPa or mbar** — Vapor pressure must be in kPa. 1 kPa = 10 hPa = 10 mbar.

### Validated Results — Bengbu (VIC forcing, DB crop params)
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

---

## Error Handling

When errors occur during WOFOST/PCSE simulation, consult the diagnostic triplets at [`diagnostics/triplets.yaml`](diagnostics/triplets.yaml). The triplets cover 15 failure patterns across 12 domains including YAML parse errors, unit conversion traps, vernalization misconfiguration, zero yield silent death, and PCSE API version changes.

---

## Model Couplings

See [`docs/model_couplings.yaml`](docs/model_couplings.yaml) for formal coupling definitions:
- **VIC weather → PCSE weather provider**: VIC forcing output → unit conversion → PCSE CSV weather
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
│   │   ├── convert_vic_to_pcse_weather.py
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
