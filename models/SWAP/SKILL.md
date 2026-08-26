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
| on ANY error, before debugging | `diagnostics/triplets.yaml` (23 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (21 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |
| what past runs learned | `.kdt_evolution.jsonl` | append-only memory of previous runs and fixes on this KI. |

*Projected 2026-08-17 from the KI's actual contents — 10 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/assemble_swap_config.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/assemble_swap_config.py --help` |
| `tools/convert_forcing_to_swap.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing_to_swap.py --help` |
| `tools/convert_soil_to_swap.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_soil_to_swap.py --help` |
| `tools/parse_swap_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_swap_output.py --help` |
| `tools/plot_swap_results.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/plot_swap_results.py --help` |
| `tools/run_swap.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_swap.py --help` |
| `tools/score_swap_point_obs.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/score_swap_point_obs.py --help` |

*7 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# SWAP v4.2.0 (Soil-Water-Atmosphere-Plant) — Knowledge Infrastructure

**Package**: `hydrocraft-swap-soil` v1.0.0
**Model**: SWAP v4.2.0
**Developer**: Wageningen University and Research (WUR), The Netherlands
**Last updated**: 2026-03-28
**Stats**: 6 tools | 6 skill documents | 23 diagnostic triplets | ~1,600 lines of validated Python
**Validation status**: `analytic` (Hupselbrook, NL, 2002-2004) + `real-case` (FLUXNET US-Ne1, 2001-2013)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for meteorological forcing documentation.
See `data_ki/HWSD/SKILL.md` for soil property documentation.
See `data_ki/RISMA/SKILL.md` for soil moisture observations.


## Overview

This knowledge infrastructure enables autonomous simulation of vadose zone water, solute, and heat transport using SWAP (Soil-Water-Atmosphere-Plant) on any field site worldwide, **without manual data preparation**. The 5 validated tools replace the standard manual SWAP workflow with a Python pipeline that integrates with HydroCraft's forcing, soil, and observation infrastructure.

**What SWAP does**: 1D vertical transport model for variably saturated soils. Simulates:
- Soil water flow (Richards' equation with Mualem-van Genuchten hydraulics)
- Evapotranspiration (Penman-Monteith, crop factors, or reference ET)
- Crop growth (simple, WOFOST general, WOFOST grass)
- Solute transport (convection-dispersion, adsorption, decay)
- Heat transport (analytical or numerical)
- Snow accumulation and melt
- Macropore flow (bypass flow, dual-permeability)
- Drainage (Hooghoudt, Ernst, multi-level systems)
- Irrigation scheduling (deficit-based, fixed, or managed)

**Key difference from other HydroCraft models**: SWAP operates at field scale (1D vertical column, single point), not gridded. It couples with WOFOST for detailed crop growth and can interface with regional groundwater models.

---

## Installation

### Binary (built from source)

```
SWAP v4.2.0:  Built via Meson + Fortran compiler (gfortran or Intel ifx)
Source:       github.com/SWAP-model/swap
Platform:     Linux x86-64, Windows x86-64
Dependencies: ttutil library v4.2.7 (auto-downloaded by Meson build)
```

### Build from source

```bash
cd source/repo
meson setup builddir
meson compile -C builddir
# Binary: builddir/swap
```

### Test case

```
tests/cases/1.hupselbrook/     # Hupselbrook, Netherlands
  swap.swp                     # Main configuration file
  283.met                      # Daily meteorological data (KNMI station 283)
  grassd.crp, maizes.crp, potatod.crp  # Crop parameter files
  swap.dra                     # Drainage configuration
  run_swap.sh                  # Execution script
```

**Validated**: SWAP runs successfully on Hupselbrook. Water balance for 2002:
- Rain+snow: 84.18 cm, Transpiration: 38.17 cm, Soil evaporation: 16.69 cm, Drainage: 22.11 cm

Reproduced bit-for-bit 2026-08-11 through `tools/run_swap.py` + `tools/parse_swap_output.py`
(0.8 s, balance deviation 0.00 cm). NOTE: the binary exits with code **100** on success — see
Critical Domain Knowledge #9.

**Second validated site (2026-08-11)**: FLUXNET2015 **US-Ne1** (irrigated maize, Mead NE,
41.1651 N / -96.4766 E), 2001-2013, NASA POWER daily forcing + HWSD soil, full pipeline
s1-s7 through the KI tools. Uncalibrated daily ET vs eddy-covariance:
r 0.76 / KGE -0.12 / NSE -1.14 / PBIAS +48% against `LE_F_MDS`, and
r 0.75 / KGE 0.36 / NSE -0.13 / PBIAS +17.6% against energy-balance-corrected `LE_CORR`.
Water balance closes to 0.0 mm over 4383 d. The residual bias is over-irrigation from the
shipped `maizes.crp` scheduling defaults (dt_023), not a forcing/unit error.

---

## Pipeline (8 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | (manual) | Site selection, period, forcing source |
| 1 | Met forcing | `convert_forcing_to_swap` | CMFD/MSWX/NASA POWER/GSWP3 → SWAP .met (via `ki_tools_common.load_forcing`) |
| 2 | Soil parameters | `convert_soil_to_swap` | HWSD → van Genuchten parameters for .swp file |
| 3 | Config assembly | `assemble_swap_config` | Build .swp from a validated base + site params, MvG table, crop rotation, irrigation |
| 4 | Execution | `run_swap` | Run SWAP binary with preflight checks |
| 5 | Output parsing | `parse_swap_output` | Extract .blc/.inc/.csv results to structured CSV |
| 6 | Visualization | `plot_swap_results` | Water balance, soil moisture profiles, ET timeseries |
| 7 | Validation | (manual) | Compare against observations |

---

## Unit Trap Table (CRITICAL — read before preparing ANY input)

These are the most common silent-failure unit conversions. Getting any one wrong produces
plausible but incorrect results with no error message.

| Variable | External Source | SWAP Expects | Conversion | Trap |
|----------|---------------|--------------|------------|------|
| Radiation (Rad) | W/m² (CMFD), W/m² (MSWX) | kJ/m²/d | × 86.4 (daily) or × period_seconds/1000 | ×1000 internal to J/m²/d |
| Temperature | K (CMFD/MSWX) | °C | − 273.15 | Must subtract, not divide |
| Humidity (Hum) | kg/kg specific (CMFD), kg/kg (MSWX) | kPa (vapor pressure) | Convert via Clausius-Clapeyron | NOT relative humidity 0-1 |
| Rainfall (Rain) | mm/day (CMFD), mm/3hr (MSWX) | mm/d | CMFD: direct; MSWX: ×8 | Internal: ×0.1 to cm |
| Wind speed | m/s | m/s at measurement height | Direct, but specify ALTW correctly | Default ALTW=10m |
| ETref | mm/d | mm/d | Direct (only if SWETR=1) | Not needed if SWETR=0 |
| Pressure head | Positive depth (some DBs) | Negative cm (unsaturated) | Negate and convert to cm | Sign convention critical |
| Ksat | m/d, m/s | cm/d | × 100 (m/d), × 8.64e6 (m/s) | Orders of magnitude error |
| Bulk density | kg/m³, g/cm³ | mg/cm³ (= kg/m³) | g/cm³ × 1000 | Range: 100-10000 |
| Drain spacing | m | m (some params in cm) | Check parameter docs carefully | Mix of m and cm units |
| Irrigation depth | mm | mm in .swp file | Direct | But internal conversion to cm |
| Solute concentration | mg/L | mg/cm³ (= mg/mL = g/L) | mg/L ÷ 1000 | 3 orders of magnitude |
| Soil depth | m (HWSD) | cm (SWAP) | × 100 | All depths in cm |

### Internal conversion chain (executed by SWAP automatically):

```
Input .met file:
  Rad (kJ/m²/d)  →  × 1000  →  J/m²/d  (readmeteo.f90)
  Rain (mm/d)     →  × 0.1   →  cm/d    (readmeteo.f90)
  Hum (kPa)       →  direct  →  kPa     (used in Penman-Monteith)
  Tmin, Tmax (°C) →  direct  →  °C      (+ 273.15 for some calcs)
  Wind (m/s)      →  direct  →  m/s     (height-adjusted in penmon.f90)
```

---

## Unit Conversion Table

Exact I/O shapes live in `docs/format_spec.yaml`; this table summarizes the unit conversions
that the SWAP KI tools apply or must preserve when preparing and parsing model files.

| Variable | Source unit | SWAP / KI unit | Conversion | Notes |
|----------|-------------|----------------|------------|-------|
| Radiation (`Rad`) | W/m² | kJ/m²/d in `.met` | `W/m² * 86.4` for daily means, or `W/m² * period_seconds / 1000` | SWAP then converts kJ/m²/d to J/m²/d internally |
| Temperature (`Tmin`, `Tmax`) | K | °C | `K - 273.15` | CMFD/MSWX-derived Kelvin inputs must be converted before writing `.met` |
| Humidity (`Hum`) | kg/kg specific humidity | kPa vapor pressure | Clausius-Clapeyron / Magnus conversion | This is actual vapor pressure, not relative humidity |
| Rainfall (`Rain`) | mm/day or mm/3hr | mm/d in `.met`; cm/d internally | CMFD daily direct; MSWX 3-hour values summed to daily; SWAP internal `* 0.1` | Do not mix daily totals and sub-daily rates |
| Wind speed | m/s | m/s | direct | Measurement height must match `ALTW` |
| Reference ET (`ETref`) | mm/d | mm/d | direct | Used only when `SWETR=1` |
| Pressure head | positive depth in some databases | negative cm above water table | negate and convert to cm | Unsaturated-zone heads are negative |
| Ksat | m/d or m/s | cm/d | `m/d * 100`; `m/s * 8.64e6` | Silent orders-of-magnitude failure if wrong |
| Bulk density | g/cm³ or kg/m³ | mg/cm³ | `g/cm³ * 1000`; `kg/m³` direct | SWAP range check expects mg/cm³ |
| Irrigation depth | mm | mm in `.swp` | direct | SWAP handles its internal water-depth conversion |
| Solute concentration | mg/L | mg/cm³ | `mg/L / 1000` | Soil pore-water solute, not ocean salinity |
| Soil depth | m | cm | `m * 100` | SWAP depths are in cm and downward from the surface |
| `actual_soil_evaporation` | SWAP parsed output | cm | direct | Dag rank-1 output unit is `cm` |

---

## Input File Reference

### .met file (Meteorological forcing)

```
* Comment lines start with * or !
Station,DD,MM,YYYY,Rad,Tmin,Tmax,Hum,Wind,Rain,ETref,Wet
'STA',01,01,2002,3810.0,-3.2,-0.1,0.523764,4.9,0.000,0.4,0.000
```

| Column | Units | Range | Description |
|--------|-------|-------|-------------|
| Station | string | — | Station identifier in quotes |
| DD | integer | 1-31 | Day of month |
| MM | integer | 1-12 | Month |
| YYYY | integer | — | Year |
| Rad | kJ/m²/d | 0-50000 | Global solar radiation |
| Tmin | °C | -50..50 | Minimum air temperature |
| Tmax | °C | -50..60 | Maximum air temperature |
| Hum | kPa | 0-10 | Actual vapor pressure |
| Wind | m/s | 0-150 | Wind speed at ALTW height |
| Rain | mm/d | 0-1000 | Daily precipitation |
| ETref | mm/d | 0-100 | Reference ET (only if SWETR=1) |
| Wet | fraction | 0-1 | Wet duration fraction of day |

### .swp file (Main configuration)

Key-value format with `*` comment lines. Sections:
1. General (paths, period, output switches)
2. Meteorology (met file, Penman-Monteith params)
3. Crop (rotation schedule, crop file references)
4. Soil water (initial conditions, discretization, MvG params, numerics)
5. Lateral drainage (Hooghoudt/Ernst or flux tables)
6. Bottom boundary (GWL, flux, free drainage, etc.)
7. Heat flow (analytical or numerical)
8. Solute transport (CDE parameters)

### .crp file (Crop parameters)

Three types: simple (CROPTYPE=1), WOFOST general (CROPTYPE=2), WOFOST grass (CROPTYPE=3).
Contains: development stages, LAI tables, root growth, water stress functions (Feddes/de Jong van Lier), oxygen stress, salt stress, interception.

### .dra file (Drainage)

Three methods: DRAMET=1 (flux-GWL table), DRAMET=2 (Hooghoudt/Ernst equations), DRAMET=3 (multi-level resistance).

### .bbc file (Bottom boundary)

Eight options: SWBOTB=1 (prescribed GWL), 2 (prescribed flux), 3 (aquifer head), 4 (GWL-flux relation), 5 (prescribed pressure head), 6 (zero flux), 7 (free drainage), 8 (free outflow).

---

## Output File Reference

| Extension | Content | Key Variables |
|-----------|---------|---------------|
| .blc | Detailed yearly water balance | Rain, interception, runoff, transpiration, evaporation, drainage, bottom flux (all in cm) |
| .bal | Summary yearly water balance | Same as .blc, condensed |
| .inc | Water balance increments (daily) | Cumulative fluxes per output interval (cm) |
| .vap | Soil profiles at output dates | z(cm), theta(-), h(cm), K(cm/d) |
| .ate | Soil temperature profiles | z(cm), T(°C) |
| .wba | Cumulative daily water balance | Running totals of all flux components (cm) |
| .sba | Cumulative daily solute balance | Solute mass components (mg/cm²) |
| .end | End conditions (restart file) | Final h, theta, T per compartment |
| .csv | Custom CSV output | User-selected variables via INLIST_CSV |
| .crp | Crop growth output | DVS, LAI, biomass, rooting depth |

---

## Output Description

This section restates the dag identity for the reader. If anything here disagrees with
`dag.yaml`, the dag wins.

**Headline output** (`validation_rank: 1`):

> `actual_soil_evaporation` — Actual bare-soil evaporation from the surface compartment. (`cm`)

| Dag output variable | Rank | Unit | Description |
|---------------------|------|------|-------------|
| `actual_soil_evaporation` | 1 | cm | Actual bare-soil evaporation from the surface compartment. |

Other dag outputs are:
`actual_transpiration`, `evapotranspiration`, `soil_water_content_profile`,
`pressure_head_profile`, `groundwater_level`, `drainage_flux`, `bottom_flux`,
`solute_concentration_output`, `soil_temperature_profile`, `crop_yield`, and
`leaf_area_index`.

---

## Output Unit Table

The dag-sourced unit that governs the headline judged output is:

| Dag variable | Unit | Source |
|--------------|------|--------|
| `actual_soil_evaporation` | cm | `dag.yaml` |

For the remaining dag outputs, read `dag.yaml` directly before binding observations or
computing metrics; do not infer their units from variable names.

---

## Critical Domain Knowledge

### 1. Humidity is vapor pressure, NOT relative humidity
SWAP .met files expect actual vapor pressure in kPa. This is NOT relative humidity (0-1 or 0-100%). To convert from specific humidity (kg/kg) as in CMFD/MSWX:
```python
e_sat = 0.6108 * exp(17.27 * T_C / (T_C + 237.3))  # kPa, Magnus formula
e_actual = q * P / (0.622 + 0.378 * q)                # kPa, from specific humidity
```
Where T_C is temperature in °C, q is specific humidity (kg/kg), P is pressure in kPa.

### 2. Radiation must be in kJ/m²/d
CMFD and MSWX provide radiation in W/m² (instantaneous). For daily SWAP input:
```python
Rad_kJ = Rad_Wm2 * 86400 / 1000  # W/m² → kJ/m²/d
```
SWAP internally converts kJ/m²/d → J/m²/d (×1000) for Penman-Monteith.

### 3. Pressure heads are NEGATIVE in unsaturated zone
All h values above the water table are negative. h = 0 at saturation, h < 0 above.
Common mistake: entering positive values from databases that store |h|.

### 4. Depth convention: surface = 0, downward = negative
Soil depths in SWAP are measured from the surface (z = 0) downward (z < 0).
Compartment boundaries: -1, -2, ..., -200 cm (typical profile).

### 5. All path and file names MUST be lowercase on Linux
SWAP on Linux requires all file references in .swp to be lowercase. Windows is case-insensitive but Linux is not. This causes silent "file not found" errors.

### 6. Time step control is critical for convergence
DTMIN (1e-7 to 0.1 d) and DTMAX (dtmin to 1 d) control Richards' equation solver.
Too large DTMAX → oscillations/non-convergence. Too small DTMIN → excessive runtime.
Recommended: DTMIN=1e-6, DTMAX=0.04 for standard cases.

### 7. Mualem-van Genuchten parameter ranges
Typical sandy soil:  ORES=0.01-0.05, OSAT=0.35-0.45, ALFA=0.02-0.05, NPAR=1.5-3.0
Typical clay soil:   ORES=0.05-0.10, OSAT=0.40-0.55, ALFA=0.005-0.02, NPAR=1.1-1.5
Ksat: sand 10-100 cm/d, clay 0.1-10 cm/d

### 8. Water balance closure check
The .blc file provides In/Out totals. Sum(In) - Sum(Out) should equal storage change.
Deviation > 0.01 cm indicates numerical issues. Check CRITDEVH1CP and MAXIT.

### 9. SWAP's NORMAL exit code is 100, not 0
`src/swap_main.f90` ends with `Call Exit(100)` after printing `Swap normal completion!`.
A wrapper that tests `returncode != 0` marks EVERY successful run as failed. Assert success
from the model's own evidence: rc 0, **or** rc 100 with "normal completion" on stdout / a
`*.ok` file in the work dir (`run_swap.swap_run_succeeded()`). See dt_018.

### 10. SWAP output files are COMMA-separated and latin-1 encoded
`.inc`, `.vap` and the native `.csv` are blank-padded **comma**-separated (splitting on
whitespace shifts every field by one). The `.vap` units header contains `ºC` (byte 0xBA),
so opening SWAP output as UTF-8 raises `UnicodeDecodeError` — use `encoding="latin-1"`.
`.blc` is a two-column `INPUT | OUTPUT` table with labels like `Gross Rainfall` /
`Plant Transpiration` / `- system 1` (drainage), NOT `key : value` lines. See dt_019.

### 11. Tables in .swp are read by their COLUMN-NAME header
ttutil's `rddata` locates a table by its header row (`CROPSTART CROPEND CROPFIL CROPTYPE`,
`ORES OSAT ALFA ...`). Dropping or reordering that line gives
`Inconsistent variable type` inside `rdinit_`, pointing at the first data row. See dt_022.

### 12. Crop rotation dates must not overlap
Each crop period (CROPSTART to CROPEND) must not overlap with adjacent crops.
Between crops, the soil is treated as bare.

---

## Observation compatibility (what SWAP can and cannot be scored against)

SWAP is a **1-D vadose-zone column**: one field, depths 0 to ~-200 cm, no horizontal
dimension and no ocean. Before accepting a validation target, check the support:

| Obs kind | Scoreable? | Notes |
|---|---|---|
| Flux tower ET/LE at the column's field (FLUXNET2015) | yes | `point_time_series`; compare Tact+Eact |
| In-situ soil moisture / soil temperature profile (ISMN, RISMA) | yes | match the sensor depth to a compartment in `.vap` |
| Piezometer / water-table depth | yes, with care | only meaningful with SWBOTB 1/3/4 and a shallow GWL |
| Tile-drain discharge at the field | yes | `.blc` "- system 1" (needs SWDRA>0) |
| Soil pore-water solute / soil salinity (EC, mg/cm³) at that field | yes | `.sba` / `.vap` solute1; watch mg/L vs mg/cm³ (dt_017) |
| **Gridded / regional field (any variable)** | **no** | there is no gridded or batch-of-columns runner in this KI |
| **Ocean salinity (EN4, WOA23, `sea_water_salinity` in psu)** | **NO — structural** | EN4.2.2 is a 1°×1° monthly ocean analysis on 42 sub-sea depth levels (5 m … 5350 m) with land masked. SWAP has no ocean compartment and its solute state is soil pore-water concentration in mg/cm³ on a land column. There is no unit, no support and no domain in common — do NOT construct a metric from it. |

Verified 2026-08-11: `KISSPATH_DATA/obs/en4-2-2/EN.4.2.2.analyses.g10.*.zip`,
variable `salinity`, `standard_name = sea_water_salinity`, dims (time, depth, lat, lon),
72.6% of surface cells wet, land = NaN.

---

## Validated Results

### Hupselbrook, Netherlands

| Property | Value |
|----------|-------|
| Period | 2002-2004 |
| Representative reported year | 2002 |
| Run evidence | Reproduced bit-for-bit 2026-08-11 through `tools/run_swap.py` and `tools/parse_swap_output.py` |
| Runtime | 0.8 s |
| Balance deviation | 0.00 cm |

Water balance for 2002:

| Quantity | Value |
|----------|-------|
| Rain+snow | 84.18 cm |
| Transpiration | 38.17 cm |
| Soil evaporation | 16.69 cm |
| Drainage | 22.11 cm |

### FLUXNET2015 US-Ne1

| Property | Value |
|----------|-------|
| Site | US-Ne1, irrigated maize, Mead NE |
| Location | 41.1651 N / -96.4766 E |
| Period | 2001-2013 |
| Inputs | NASA POWER daily forcing + HWSD soil |
| Pipeline | Full s1-s7 through the KI tools |
| Water balance closure | 0.0 mm over 4383 d |

Uncalibrated daily ET against eddy-covariance observations:

| Observation target | r | KGE | NSE | PBIAS |
|--------------------|---|-----|-----|-------|
| `LE_F_MDS` | 0.76 | -0.12 | -1.14 | +48% |
| `LE_CORR` | 0.75 | 0.36 | -0.13 | +17.6% |

The residual bias is over-irrigation from the shipped `maizes.crp` scheduling defaults
(`dt_023`), not a forcing/unit error.

### Performance Metrics — judged against `docs/validation_convention.yaml`

The convention wins over remembered thresholds. Bands listed as null in the convention are
reported here as `no cited threshold`.

| Dag variable | Metric | Direction | Very good band | Good band | Satisfactory band | Citation key(s) |
|--------------|--------|-----------|----------------|-----------|-------------------|-----------------|
| `actual_soil_evaporation` | nse | maximize | no cited threshold | no cited threshold | no cited threshold | none |
| `actual_transpiration` | nse | maximize | no cited threshold | no cited threshold | no cited threshold | none |
| `evapotranspiration` | mre | minimize | 10 (`wang2020`) | 20 (`wang2020`) | 30 (`wang2020`) | `wang2020` |

For the dag's rank-1 variable, `actual_soil_evaporation`, the convention bar is NSE with
direction `maximize`; the convention provides no cited threshold for satisfactory, good, or
very good performance.

---

## Tool Reference

| Tool | Script | Purpose | Key Inputs | Key Outputs |
|------|--------|---------|------------|-------------|
| convert_forcing_to_swap | `tools/convert_forcing_to_swap.py` | CMFD/MSWX/NASA POWER/GSWP3 → .met | `--source`, lat/lon, dates | .met file |
| convert_soil_to_swap | `tools/convert_soil_to_swap.py` | HWSD → MvG params | HWSD raster, lat/lon | Soil parameter table |
| assemble_swap_config | `tools/assemble_swap_config.py` | Base .swp → site .swp | base .swp, MvG table, crop/irrigation rows, `--set KEY=VALUE` | swap.swp (+ trap checks) |
| run_swap | `tools/run_swap.py` | Execute SWAP binary | .swp file, binary path | Exit code, output files |
| parse_swap_output | `tools/parse_swap_output.py` | Extract results to CSV | SWAP output dir | Structured CSV files |
| plot_swap_results | `tools/plot_swap_results.py` | Visualization | Parsed CSV files | PNG figures |

---

## Diagnostic Quick Reference

| ID | Symptom | Root Cause | Fix |
|----|---------|-----------|-----|
| dt_001 | Extreme ET, soil dries instantly | Radiation in W/m² instead of kJ/m²/d | ÷ (86400/1000) |
| dt_002 | Extreme evaporation, no transpiration | Humidity as RH fraction instead of kPa | Convert via Magnus |
| dt_003 | Waterlogged soil, unrealistic runoff | Rainfall in mm/3hr not aggregated to mm/d | Sum 3hr → daily |
| dt_004 | Temperature sum never reached | Temperature in K instead of °C | − 273.15 |
| dt_005 | No drainage, GWL at surface | Ksat in m/s instead of cm/d | × 8.64e6 |
| dt_006 | "File not found" on Linux | Uppercase characters in file paths | Lowercase all paths |
| dt_007 | Convergence failure, tiny timesteps | DTMAX too large for clay soils | Reduce DTMAX to 0.01 |
| dt_008 | Zero crop growth | CROPSTART after actual emergence | Check dates match reality |
| dt_009 | Oscillating water table | GWLCONV too loose | Tighten to 1-10 cm |
| dt_010 | All water drains immediately | ORES/OSAT swapped or unrealistic | Check MvG parameter order |
