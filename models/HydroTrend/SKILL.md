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
| on ANY error, before debugging | `diagnostics/triplets.yaml` (29 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (18 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 8 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/build_hypsometry.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/build_hypsometry.py --help` |
| `tools/convert_climate_to_hydrotrend.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_climate_to_hydrotrend.py --help` |
| `tools/parse_hydrotrend_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_hydrotrend_output.py --help` |
| `tools/run_hydrotrend.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_hydrotrend.py --help` |

*4 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# HydroTrend Knowledge Infrastructure

## Overview

HydroTrend is a climate-driven hydrological transport model that simulates daily
water discharge (Q), suspended sediment load (Qs), bedload (Qb), and sediment
concentration (Cs) at a river mouth. Developed by Albert Kettner and James
Syvitski at INSTAAR/University of Colorado, it operates at the basin scale using
statistical climate inputs, hypsometry, and empirical sediment transport formulas.

**Domain**: Geomorphology / Fluvial Sediment Transport
**Language**: C (with BMI interface)
**Time step**: Daily (can output monthly/seasonal/yearly averages)
**Spatial scale**: Lumped basin (single outlet or multi-outlet delta)

### Key Capabilities
- Stochastic daily weather generation from monthly climate statistics
- Snow/ice/glacier melt with lapse-rate elevation dependence
- Groundwater storage and baseflow routing
- Three sediment transport formulas: QRT, ART, BQART
- Reservoir trapping efficiency (Brune/Vorosmarty)
- Multi-outlet delta sediment distribution
- Earthquake-driven sediment pulse decay
- Multi-epoch climate change scenarios

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for meteorological forcing documentation.
See `data_ki/USGS_Sediment/SKILL.md` for suspended sediment observations.


## Pipeline Stages

| # | Stage | Tool | Description |
|---|-------|------|-------------|
| 1 | Climate Preparation | `convert_climate_to_hydrotrend.py` | Convert global reanalysis to monthly T/P statistics |
| 2 | Hypsometry Building | `build_hypsometry.py` | Generate elevation-area curve from DEM |
| 3 | Parameter Assembly | `generate_hydro_in.py` | Build HYDRO.IN input file with all 47 lines |
| 4 | Model Execution | `run_hydrotrend.py` | Compile (if needed) and run the binary |
| 5 | Output Parsing | `parse_hydrotrend_output.py` | Extract Q, Qs, Qb, Cs to CSV |
| 6 | Validation | (manual/script) | Compare to observed discharge/sediment data |

---

## Installation and Build

### Prerequisites
- C compiler (gcc or clang)
- CMake >= 3.0
- bmi-c library (BMI C interface)
- pkg-config

### Build Commands
```bash
cd /path/to/hydrotrend/source/repo
mkdir _build && cd _build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
```

The build produces:
- `hydrotrend` — standalone CLI executable
- `libhydrotrend.a` / `libhydrotrend.so` — library for BMI coupling

### Running
```bash
hydrotrend --in-dir=./input --out-dir=./output --prefix=HYDRO
```

CLI options:
| Flag | Description |
|------|-------------|
| `-p, --prefix=PREFIX` | Input file prefix (default: HYDRO) |
| `-S, --in-dir=DIR` | Input directory (default: ./HYDRO_IN) |
| `-D, --out-dir=DIR` | Output directory |
| `-V, --verbose` | Verbose output |
| `-v, --version` | Print version (3.0.5) |

---

## Input Files

### 1. Main Input File: `{PREFIX}.IN`

A 47-line ASCII file with one parameter per line. Comments after the value are
ignored (typically tab-separated descriptions).

| Line | Parameter | Units (user provides) | Internal conversion | Internal units |
|------|-----------|----------------------|---------------------|----------------|
| 1 | Title | text | — | — |
| 2 | ASCII output flag | ON/OFF | — | — |
| 3 | Output directory | path | — | — |
| 4 | Number of epochs | integer | — | — |
| 5 | Start year, # years, timestep | yr, yr, D/M/S/Y | — | — |
| 6 | Number of grain sizes | 1–10 | — | — |
| 7 | Grain size proportions | fractions (sum=1) | — | — |
| 8 | Temperature trend | °C, °C/yr, °C | — | °C |
| 9 | Precipitation trend | m/yr, m/yr², m | — | m/yr |
| 10 | Rainfall mass balance | coeff, exp, range | — | — |
| 11 | Base flow | m³/s | — | m³/s |
| 12–23 | Monthly climate (×12) | name, °C, °C, **mm**, mm | **÷1000** | m |
| 24 | Lapse rate | **°C/km** | **÷1000** | °C/m |
| 25 | Glacier ELA start, change | m, m/yr | — | m |
| 26 | Dry evaporation fraction | 0–1 | — | — |
| 27 | Canopy interception α, β | **mm/d**, — | **÷1000** | m/d |
| 28 | Evapotranspiration α, β | **mm/d**, — | **÷1000** | m/d |
| 29 | Delta plain gradient | m/m | — | m/m |
| 30 | Bedload rating term | — | — (−9999→1.0) | — |
| 31 | Basin length | **km** | **×1000** | m |
| 32 | Reservoir volume, param | km³, flag (a/d) | — | km³ |
| 33 | Velocity coeff, exponent | k, m | — | v=kQ^m |
| 34 | Width coeff, exponent | a, b | — | w=aQ^b |
| 35 | Average river velocity | m/s | — | m/s |
| 36 | GW storage max, min | m³, m³ | — | m³ |
| 37 | Initial GW storage | m³ | — | m³ |
| 38 | Subsurface storm flow coeff, exp | m³/s, — | — | — |
| 39 | Saturated hydraulic conductivity | **mm/day** | **÷1000** | m/day |
| 40 | River mouth lon, lat | decimal degrees | — | degrees |
| 41 | Number of outlets | int or u/r | — | — |
| 42 | Outlet fractions | fractions | — | — |
| 43 | Event specification | n# or q# | — | — |
| 44 | Sediment filter | 0–0.9 | — | — |
| 45 | Sediment formula | 0=QRT, 1=ART, 2=BQART | — | — |
| 46 | Lithology factor | 0.3–3.0 | — | — |
| 47 | Anthropogenic factor | 0.5–8.0 | — | — |

### 2. Hypsometry File: `{PREFIX}0.HYPS`

```
[5 header lines]
46                    # number of bins
1       0             # elevation(m)  cumulative_area(km²)
51      43.73
101     143.35
...
2251    9440.46
```

- Elevation in meters above sea level
- Area in km² (cumulative area below each elevation)
- Must be monotonically increasing in both columns

### 3. Optional Climate File: `{PREFIX}.CLIMATE`

Daily temperature and precipitation time series. Overrides stochastic generation.

### 4. Optional Earthquake File: `{PREFIX}.QUAKE`

Earthquake events with year, energy, distance, duration for sediment pulse modeling.

---

## Output Files

| File | Variable | Units | Format |
|------|----------|-------|--------|
| `{PREFIX}ASCII.Q` | Water discharge | m³/s | Daily, one value/line |
| `{PREFIX}ASCII.QS` | Suspended sediment | kg/s | Daily, one value/line |
| `{PREFIX}ASCII.QB` | Bedload | kg/s | Daily, one value/line |
| `{PREFIX}ASCII.CS` | Sediment concentration | kg/m³ | Daily, one value/line |
| `{PREFIX}ASCII.VWD` | Velocity, width, depth | m/s, m, m | Three columns/line |
| `{PREFIX}.TRN1` | Annual discharge summary | — | Annual statistics |
| `{PREFIX}.TRN2` | Annual peak Q per outlet | — | Annual |
| `{PREFIX}.TRN3` | Comprehensive annual data | — | Multi-column |
| `{PREFIX}.DIS` | Binary discharge+sediment | — | Binary |
| `{PREFIX}.LOG` | Execution log | — | Text |

## Output Description

This section restates `dag.yaml`, which is the source of truth for what the
model predicts. If this section and `dag.yaml` ever disagree, `dag.yaml` wins.

**Rank-1 output**: `Q` — Daily water discharge at the river mouth (BMI:
channel_exit_water__volume_flow_rate) (`m3/s`).

Other dag outputs: `Qs`, `Qb`, `Cs`, `velocity_width_depth`.

| Output variable (dag `var`) | Rank | Unit | Description / role |
|-----------------------------|------|------|--------------------|
| `Q` | 1 | `m3/s` | Daily water discharge at the river mouth (BMI: channel_exit_water__volume_flow_rate) |
| `Qs` | not stated here | see `dag.yaml` | Other dag output |
| `Qb` | not stated here | see `dag.yaml` | Other dag output |
| `Cs` | not stated here | see `dag.yaml` | Other dag output |
| `velocity_width_depth` | not stated here | see `dag.yaml` | Other dag output |

### BMI Output Variables (standardized names)

| BMI Name | Units |
|----------|-------|
| `channel_exit_water__volume_flow_rate` | m³/s |
| `channel_exit_water_sediment~suspended__mass_flow_rate` | kg/s |
| `channel_exit_water_sediment~suspended__mass_concentration` | kg/m³ |
| `channel_entrance_water_sediment~bedload__mass_flow_rate` | kg/s |
| `channel_exit_water_sediment~bedload__mass_flow_rate` | kg/s |
| `channel_exit_water_flow__speed` | m/s |
| `channel_exit_water_x-section__width` | m |
| `channel_exit_water_x-section__depth` | m |
| `atmosphere_bottom_air__domain_mean_of_temperature` | °C |
| `atmosphere_water__domain_mean_of_precipitation_leq-volume_flux` | m/d |

---

## Unit Conversion Trap Table

These are the **silent killers** — the model reads values in user-friendly units
and converts them internally. If you pre-convert, you get double-conversion.
If you forget the expected units, the model runs but produces garbage.

| Parameter | User Provides | Model Reads As | Internal Conversion | Common Trap |
|-----------|--------------|----------------|---------------------|-------------|
| Monthly precip (lines 12–23) | mm | mm | ÷1000 → m | Providing m instead of mm → 1000× too small |
| Lapse rate (line 24) | °C/km | °C/km | ÷1000 → °C/m | Providing °C/m → 1000× too small |
| Canopy interception α (line 27) | mm/d | mm/d | ÷1000 → m/d | Providing m/d → 1000× too small |
| Evapotranspiration α (line 28) | mm/d | mm/d | ÷1000 → m/d | Providing m/d → 1000× too small |
| Basin length (line 31) | km | km | ×1000 → m | Providing m → 1000× too large |
| Hydraulic conductivity (line 39) | mm/day | mm/day | ÷1000 → m/day | Providing m/day → 1000× too small |
| Annual precip (line 9) | m/yr | m/yr | No conversion | Providing mm/yr → 1000× too large |
| Hypsometry area | km² | km² | Used as km² internally | Providing m² → 1e6× too large |

---

## Sediment Transport Formulas

### QRT (flag=0): Discharge-Relief-Temperature
```
Qsbar = α₆ × (1-TE) × Q^α₇ × H^α₈ × exp(k₂ × T)
```

### ART (flag=1): Area-Relief-Temperature
```
Qsbar = α₃ × (1-TE) × A^α₄ × H^α₅ × exp(k₁ × T)
```

### BQART (flag=2): Basin-Discharge-Area-Relief-Temperature
```
If T ≥ 2°C: Qsbar = α₉ × B × L × (1-TE) × Eh × A^α₁₁ × (Q×yTOs/1e9)^α₁₀ × (H/1000) × T
If T < 2°C: Qsbar = 2 × α₉ × B × L × (1-TE) × Eh × A^α₁₁ × (Q×yTOs/1e9)^α₁₀ × (H/1000)
```
Where B = lithology factor (0.3–3), Eh = anthropogenic factor (0.5–8).

---

## Critical Domain Knowledge

1. **Precipitation units are mixed**: Annual P is in m/yr (line 9), but monthly P
   is in mm (lines 12–23). The model divides monthly by 1000 internally.

2. **Lapse rate sign convention**: Positive lapse rate means temperature DECREASES
   with altitude (standard atmosphere ~6.5 °C/km). The model uses
   `T_elev = T_base - lapserate × (elevation - base_elevation)`.

3. **-9999 sentinel**: Lapse rate of -9999 triggers global default calculation.
   Bedload rating of -9999 resets to 1.0.

4. **Grain size proportions must sum to 1.0**: The model does not normalize.
   If sum ≠ 1, sediment mass is not conserved.

5. **Hypsometry bin 0 must have area 0**: First elevation bin represents the
   lowest point; its cumulative area should be 0.

6. **Reservoir trapping uses different formulas by volume**: < 0.5 km³ uses
   Brown's method; ≥ 0.5 km³ uses Vorosmarty's method. The cutoff is hard-coded.

7. **Depth coefficient is derived**: `depcof = 1/(velcof × widcof)` and
   `deppow = 1 - velpow - widpow`. Do not specify depth parameters directly.

8. **BQART temperature threshold at 2°C**: Below 2°C, the formula doubles the
   coefficient and drops the temperature term entirely.

9. **Output ASCII files require flag ON**: Line 2 must be "ON" (case-insensitive)
   or no ASCII output files are produced. Only binary .DIS is written.

---

## Tool Reference

| Tool | Lines | Purpose |
|------|-------|---------|
| `convert_climate_to_hydrotrend.py` | ~220 | Global reanalysis → monthly T/P statistics |
| `build_hypsometry.py` | ~180 | DEM → HYPS elevation-area file |
| `run_hydrotrend.py` | ~200 | Build and execute HydroTrend binary |
| `parse_hydrotrend_output.py` | ~190 | ASCII output → structured CSV + JSON |

---

## Diagnostic Triplets Summary

See `diagnostics/triplets.yaml` for 20 symptom→diagnosis→remedy entries covering:
- Unit conversion errors (6 entries)
- Input format errors (4 entries)
- Runtime/NaN crashes (3 entries)
- Silent output errors (4 entries)
- Build/dependency issues (3 entries)

---

## Validation Approach

For hydrological validation:
- **NSE** (Nash-Sutcliffe Efficiency): Target > 0.5
- **KGE** (Kling-Gupta Efficiency): Target > 0.5
- **PBIAS** (Percent Bias): Target |PBIAS| < 25%
- **Sediment yield**: Compare annual Qs to published values for similar basins

The default test case simulates a Greenland fjord (1000 years, starting 1908) with:
- Basin area ~9440 km², relief 2250 m
- Mean annual T ~24.9°C, annual P ~1.24 m/yr
- BQART sediment formula with lithology=0.3, anthropogenic=1.0

## Validated Results

Performance is judged against `docs/validation_convention.yaml`; do not replace
these cited bars with intuition or remembered thresholds. The headline dag
variable is `Q`.

### Convention Bars

| Dag variable | Metric | Direction | Satisfactory | Good | Very good | Citation key |
|--------------|--------|-----------|--------------|------|-----------|--------------|
| `Q` | `nse` | maximize | `0.5` (`moriasi2007`, `moriasi2015`) | `0.7` (`moriasi2007`, `moriasi2015`) | `0.8` (`moriasi2007`, `moriasi2015`) | `moriasi2007`, `moriasi2015` |
| `Q` | `pbias` | zero_centered | `15` (`moriasi2015`) | `10` (`moriasi2015`) | `5` (`moriasi2015`) | `moriasi2015` |
| `Q` | `pbias` | zero_centered | `15` (`moriasi2015`) | `10` (`moriasi2015`) | `5` (`moriasi2015`) | `moriasi2015` |
| `Qs` | `nse` | maximize | `0.45` (`moriasi2015`) | `0.7` (`moriasi2015`) | `0.8` (`moriasi2015`) | `moriasi2015` |
| `Qs` | `pbias` | zero_centered | `20` (`moriasi2015`) | `15` (`moriasi2015`) | `10` (`moriasi2015`) | `moriasi2015` |

For zero-centered `pbias`, apply the bands to absolute percent bias around zero.
The convention currently lists the `Q` `pbias` bar twice with identical bands;
keep both entries in sync with `docs/validation_convention.yaml`.

### Reported Run Results Already Documented In This Skill

| Case | Variable | Reported result | Convention context |
|------|----------|-----------------|--------------------|
| Low-relief snowmelt-prairie / seasonal gauges, e.g. HYDAT 05EC005 Redwater R, AB | Daily `Q` | zero-lag `r=0.287`, `r=0.53` at +6-day lag, `PBIAS +8%`, `simmax~obsmax`, and structural daily `NSE <= r^2 ~ 0.08` | Use `Q` `pbias` bars from `moriasi2015`; no cited `r` threshold is stated here. |
| Huai @ Wangjiaba, GloFAS dis24, 30,630 km2, 2003/2007/2018/2020 | Daily `Q` | pooled daily `NSE -0.96 -> 0.73`, `r 0.56 -> 0.86`, `KGE -> 0.86`, `PBIAS 0.8%` after routing attenuation (`L=600 km`, `v=0.6 m/s`) | Use `Q` `nse` bars from `moriasi2007`, `moriasi2015` and `Q` `pbias` bars from `moriasi2015`; no cited `KGE` or `r` threshold is stated here. |

Do not invent validation verdicts for metrics without convention bars. Where the
convention holds a null band, write `no cited threshold`.

---

## File Structure

```
ki/
├── SKILL.md                              # This file
├── knowledge_infrastructure.yaml         # Schema metadata
├── tools/
│   ├── convert_climate_to_hydrotrend.py  # Stage 1: Climate forcing
│   ├── build_hypsometry.py               # Stage 2: Hypsometry from DEM
│   ├── run_hydrotrend.py                 # Stage 3: Model execution
│   └── parse_hydrotrend_output.py        # Stage 4: Output parsing
├── docs/
│   ├── 01_climate_preparation.md         # Climate data preparation
│   ├── 02_hypsometry_construction.md     # Building elevation-area curves
│   ├── 03_input_file_assembly.md         # HYDRO.IN parameter guide
│   ├── 04_model_execution.md             # Running HydroTrend
│   └── 05_output_analysis.md             # Interpreting results
└── diagnostics/
    └── triplets.yaml                     # Failure diagnosis entries
```

## Daily-Q gauge validation — domain limits (added 2026-06-21)

HydroTrend's snow routine is a **lumped degree-day** model: basin-wide melt is
released the instant air temperature crosses the melt point, with **no snowpack
cold-content/ripening delay** and **no distributed-melt spreading**. It also has
no frozen-soil infiltration or depression-storage / fill-and-spill routing.

Consequence at **low-relief snowmelt-prairie / seasonal gauges** (e.g. HYDAT
05EC005 Redwater R, AB, relief 135 m): the simulated freshet **leads observed by
a constant ~6 days and is too broad**. Daily Pearson r is therefore capped near
0.3 (verified: zero-lag r=0.287, but r=0.53 at +6-day lag), so NSE <= r^2 ~ 0.08
regardless of magnitude calibration — even though mean/variance/peak match
(PBIAS +8%, simmax~obsmax).

**Validation guidance:** daily-Q-vs-gauge comparison is reliable only for
nival or rainfall-dominated basins whose freshet timing is **channel-routing-
controlled**. For low-relief prairie / cold-regions fill-and-spill basins,
validate against **monthly or seasonal Q**, or against **annual suspended-
sediment yield** (the model's design output) — not the daily gauge. Do not
retry-tune a daily gauge here; the ceiling is structural to the C source.

## Daily-Q on LARGE rainfall-dominated basins — route to attenuate (2026-06-23)

For a large **rainfall-dominated lowland** basin the limiting factor is NOT
melt timing but **peak attenuation**: the lumped model has only one smoothing
mechanism — the channel travel-time lag in `hydrorain.c` (`distbins`), set by
**basin length (line 28, km) ÷ mean river velocity (line 32, m/s)**. With the
defaults (short length / fast velocity, ~3-day spread) storm peaks run 2–5×
above a network-routed reference (GloFAS/LISFLOOD), giving negative NSE even
after the mean is calibrated. **Increase L and/or lower v so the spread
(~L/v ÷ 86400 days) matches the basin concentration time.** Verified on
**Huai @ Wangjiaba (GloFAS dis24, 30,630 km²)**: `L=600 km, v=0.6 m/s`
(~12-day spread) lifted pooled daily **NSE −0.96 → 0.73, r 0.56 → 0.86,
KGE → 0.86, PBIAS 0.8%** across 2003/2007/2018/2020. Set the mean independently
via evaporation (lines 26 dry-evap + 26b groundwater-ET α, mm/d) and add
baseflow damping with a large groundwater store (line 33). See triplet ht_022.

## Authoring HYDRO.IN (no generate_hydro_in.py tool exists)

The Pipeline Stages table lists `generate_hydro_in.py` (Stage 3) but **no such
tool ships** — assemble `{PREFIX}.IN` by adapting the shipped example
(`source/repo/data/input/HYDRO.IN`) or a prior working run
(`outputs/hydrotrend_*/HYDRO.IN`). Drive date-aligned daily validation by
emitting a `{PREFIX}.CLIMATE` daily override with
`convert_climate_to_hydrotrend.py --climate-out` (this replaces the stochastic
weather generator — the only way to match an observed daily series by date).
