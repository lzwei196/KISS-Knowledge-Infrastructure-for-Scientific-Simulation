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
| before running a stage | `docs/s*_*.md` (6 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (26 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (16 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/convert_forcing_to_wasp.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing_to_wasp.py --help` |
| `tools/convert_parameters_to_wasp.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_parameters_to_wasp.py --help` |
| `tools/parse_output_wasp.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_output_wasp.py --help` |
| `tools/run_wasp.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_wasp.py --help` |

*4 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# WASP Knowledge Infrastructure

**Package**: hydrocraft-wasp v1.0.0
**Model**: WASP (Water Analysis Simulation Program) -- Analytic Reimplementation
**Domain**: Lake and reservoir water quality modeling
**Language**: Python (analytic reimplementation of WASP core physics)
**License**: Public domain (EPA)
**Created**: 2026-03-30
**Validation**: Lake Erie Central Basin, WQP observations (Temp R=0.885, DO Cal R=0.816)

| Metric | Value |
|--------|-------|
| Tools | 4 |
| Pipeline stages | 6 |
| Diagnostic triplets | 26 |
| Validation lake | Lake Erie Central Basin |

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for meteorological forcing documentation.
See `data_ki/WQP/SKILL.md` for water quality observations.
See `data_ki/HydroLAKES/SKILL.md` for lake morphometry.


## 1. Overview

WASP (Water Analysis Simulation Program) is a generalized water quality model
developed by US EPA for simulating contaminant fate and transport in surface
waters. This analytic reimplementation captures WASP's core water quality
processes for lakes and reservoirs.

Core physics:

- **Streeter-Phelps BOD-DO dynamics**: Classic oxygen sag model coupling
  biochemical oxygen demand (BOD) decay with atmospheric reaeration.
  BOD decays first-order: `BOD(t) = BOD0 * exp(-kd * t)`. The oxygen
  deficit evolves as:
  ```
  D(t) = [kd*BOD0/(ka-kd)] * [exp(-kd*t) - exp(-ka*t)] + D0*exp(-ka*t)
  ```
  where `kd` is the BOD deoxygenation rate (1/d), `ka` is the reaeration
  rate (1/d), and `D0` is the initial oxygen deficit (mg/L).

- **Benson-Krause DO saturation**: Temperature-dependent dissolved oxygen
  saturation concentration (mg/L) following Benson & Krause (1984):
  ```
  ln(DO_sat) = -139.34411 + 1.575701e5/TK - 6.642308e7/TK^2
               + 1.2438e10/TK^3 - 8.621949e11/TK^4
  ```
  where TK is absolute temperature in Kelvin. This is the standard WASP
  formulation. At 20 C, DO_sat ~ 9.09 mg/L; at 0 C, ~14.6 mg/L.

- **Logistic thermocline model**: 1-D vertical temperature profile using
  a logistic (sigmoid) function (CE-QUAL-W2 style):
  ```
  T(z) = T_bottom + (T_surface - T_bottom) / (1 + exp((z - z_thermo) / w))
  ```
  where `z` is depth (m), `z_thermo` is thermocline depth (m), and `w` is
  thermocline width (m). This captures the three-layer lake structure:
  epilimnion (warm mixed surface), metalimnion (thermocline), and
  hypolimnion (cold bottom).

- **Carlson Trophic State Index (TSI)**: Lake trophic classification
  (Carlson 1977):
  ```
  TSI(Chl-a)  = 9.81 * ln(Chl-a) + 30.6       [ug/L]
  TSI(Secchi) = 60 - 14.41 * ln(SD)            [m]
  TSI(TP)     = 14.42 * ln(TP) + 4.15          [ug/L]
  ```
  TSI < 30: oligotrophic, 30-50: mesotrophic, 50-70: eutrophic, >70: hypereutrophic.

- **Sinusoidal seasonal temperature model**: Surface water temperature
  varies seasonally following:
  ```
  T(doy) = T_mean + amplitude * sin(2*pi*(doy - phase) / 365)
  ```
  where `T_mean` is annual average temperature (deg C), `amplitude` is
  the seasonal swing (deg C), and `phase` is the day of peak temperature
  offset (typically ~130 for Northern Hemisphere lakes).

- **Seasonal DO model**: Dissolved oxygen coupled to temperature via
  steady-state Streeter-Phelps:
  ```
  DO(doy) = clip(DO_sat(T(doy)) - kd*BOD0/(ka - kd) + DO_offset, 0, 20)
  ```
  This captures the inverse relationship between temperature and DO
  saturation, modulated by BOD loading.

- **1-D DO profile**: Depth-dependent dissolved oxygen with epilimnion near
  saturation and hypolimnion depleted by sediment oxygen demand:
  ```
  DO(z) = DO_sat(T(z)) * depletion_factor(z, thermocline_depth, SOD_rate)
  ```

Key characteristics:
- Designed for lake and reservoir water quality analysis
- Processes: temperature, dissolved oxygen, BOD, nutrients (Chl-a, TP)
- Calibration against WQP (Water Quality Portal) lake observations
- Supports multiple lakes (Erie, DeGray, Jordan, Mead) via WQP data
- Vertical profiles via discrete profile data and NLA surveys
- 3 + 4 calibration parameters (temperature model + DO model)
- Output: seasonal T/DO time series, vertical T/DO profiles, TSI values

---

## 2. Installation

### Analytic reimplementation (Python)

```bash
# No compilation needed -- pure Python
pip install numpy pandas scipy matplotlib
```

### Dependencies

| Component    | Required | Purpose                                         |
|--------------|----------|-------------------------------------------------|
| numpy        | Yes      | Numerical computation                           |
| pandas       | Yes      | Time series handling, WQP CSV parsing           |
| scipy        | Yes      | Calibration (Nelder-Mead optimization)          |
| matplotlib   | Optional | Validation plots                                |

---

## 3. Pipeline

| # | Stage                  | Tool                          | Description                                              |
|---|------------------------|-------------------------------|----------------------------------------------------------|
| 1 | Forcing preparation    | `convert_forcing_to_wasp.py`  | WQP/NLA CSV to cleaned T/DO/Chl-a time series            |
| 2 | Parameter setup        | `convert_parameters_to_wasp.py`| Lake morphometry + BOD-DO kinetics + thermal params      |
| 3 | Model execution        | `run_wasp.py`                 | Run seasonal T/DO model + profiles + TSI                 |
| 4 | Output parsing         | `parse_output_wasp.py`        | Extract T/DO profiles, compute validation metrics        |
| 5 | Calibration            | `run_wasp.py --mode calibrate`| Nelder-Mead against observed T and DO                    |
| 6 | TSI analysis           | `parse_output_wasp.py`        | Carlson TSI computation and NLA percentile ranking        |

**Parallelism**: Stages 1--2 can run in parallel. Stage 3 depends on 1--2.
Stage 4 depends on 3.

### Stage skill documents

- [Stage 1: Forcing preparation](docs/s1_forcing_preparation.md)
- [Stage 2: Parameter setup](docs/s2_parameter_setup.md)
- [Stage 3: Model execution](docs/s3_model_execution.md)
- [Stage 4: Output parsing](docs/s4_output_parsing.md)
- [Stage 5: Calibration](docs/s5_calibration.md)
- [Stage 6: TSI analysis](docs/s6_tsi_analysis.md)

---

## 4. Output Description

Source: `dag.yaml`. The dag is the authority for output identity; if this
section ever disagrees with `dag.yaml`, the dag wins and this section should be
fixed.

**Headline output** (`validation_rank: 1`, the variable this model is judged by):

> `do_timeseries` -- Seasonal dissolved-oxygen time series (steady-state Streeter-Phelps). (mg/L)

Dag outputs restated from the KI:

| Output variable (dag `var`) | Rank | Unit | Description |
|-----------------------------|------|------|-------------|
| `do_timeseries` | 1 | mg/L | Seasonal dissolved-oxygen time series (steady-state Streeter-Phelps). |
| `temperature_timeseries` | See `dag.yaml` | See `dag.yaml` | See `dag.yaml` |
| `temperature_profile` | See `dag.yaml` | See `dag.yaml` | See `dag.yaml` |
| `do_profile` | See `dag.yaml` | See `dag.yaml` | See `dag.yaml` |
| `do_saturation` | See `dag.yaml` | See `dag.yaml` | See `dag.yaml` |
| `TSI` | See `dag.yaml` | See `dag.yaml` | See `dag.yaml` |

The rank-1 output is the seasonal dissolved-oxygen time series,
`do_timeseries`, in mg/L.

---

## 4a. Unit Table

This unit table summarizes the model-facing units used by the pipeline. Exact
I/O shapes live in `docs/format_spec.yaml`; `dag.yaml` is authoritative for
output variables.

| Variable | Model unit | Source or context | Notes |
|----------|------------|-------------------|-------|
| `do_timeseries` | mg/L | `dag.yaml` rank-1 output | Seasonal dissolved-oxygen time series. |
| Temperature | deg C | WQP / forcing / seasonal model | Convert Fahrenheit or Kelvin before use. |
| Dissolved oxygen | mg/L | WQP observations and DO outputs | Values > 20 mg/L are suspect. |
| Depth | m | WQP profile depth and lake morphometry | Convert ft or cm before use. |
| Chlorophyll-a | ug/L | TSI input | Used for Carlson TSI. |
| Total phosphorus | ug/L | TSI input | Used for Carlson TSI. |
| Secchi depth | m | TSI input | Used for Carlson TSI. |
| BOD decay rate `kd` | 1/d | DO seasonal model parameter | Convert hourly rates to daily rates. |
| Reaeration rate `ka` | 1/d | DO seasonal model parameter | Convert hourly rates to daily rates. |
| Lake area | km2 | Lake morphometry | Convert ha or m2 before use. |
| Lake volume | m3 | Lake morphometry | Convert acre-ft before use. |

---

## 4b. Unit Trap Table

These unit conversions cause **silent failures** if wrong. The model performs
no internal unit conversion; all inputs must be in the expected units.

| Variable              | Model expects  | Common source unit  | Conversion                     | Trap ID |
|-----------------------|----------------|---------------------|--------------------------------|---------|
| Temperature           | **deg C**      | deg F (some WQP)    | (F - 32) x 5/9                | dt_001  |
| Temperature           | **deg C**      | K                   | - 273.15                       | dt_002  |
| Dissolved oxygen      | **mg/L**       | ug/L (some labs)    | / 1000                         | dt_003  |
| Dissolved oxygen      | **mg/L**       | % saturation        | x DO_sat(T) / 100             | dt_004  |
| Depth                 | **m**          | ft (some WQP)       | x 0.3048                       | dt_005  |
| Depth                 | **m**          | cm                  | / 100                          | dt_006  |
| Chlorophyll-a         | **ug/L**       | mg/L                | x 1000                         | dt_007  |
| Total phosphorus      | **ug/L**       | mg/L                | x 1000                         | dt_008  |
| Secchi depth          | **m**          | ft                  | x 0.3048                       | dt_009  |
| BOD decay rate kd     | **1/d**        | 1/h                 | x 24                           | dt_010  |
| Reaeration rate ka    | **1/d**        | 1/h                 | x 24                           | dt_011  |
| Lake area             | **km2**        | ha                  | / 100                          | dt_012  |
| Lake area             | **km2**        | m2                  | / 1e6                          | dt_013  |
| Lake volume           | **m3**         | acre-ft             | x 1233.48                      | dt_014  |

**Rule**: If DO values are > 20 mg/L, units are almost certainly ug/L not mg/L.
If temperature values are > 50, units are likely Fahrenheit or Kelvin.
If depth values are > 100 in a lake context, units may be feet or cm.

---

## 5. Tools Reference

| Tool                       | Stage      | Script                          | Purpose                                               |
|----------------------------|------------|----------------------------------|-------------------------------------------------------|
| `convert_forcing_to_wasp`  | s1_forcing | `tools/convert_forcing_to_wasp.py` | WQP/NLA CSV to cleaned observation time series      |
| `convert_parameters_to_wasp`| s2_params | `tools/convert_parameters_to_wasp.py`| Lake morphometry + kinetic + thermal parameters    |
| `run_wasp`                 | s3_execute | `tools/run_wasp.py`                | Execute seasonal T/DO model + profiles + TSI        |
| `parse_output_wasp`        | s4_output  | `tools/parse_output_wasp.py`       | Parse T/DO profiles, compute R/RMSE/bias, TSI       |

All tools follow the **validate -> process -> validate** pattern:
1. Parse CLI arguments with `argparse`
2. Validate all inputs (file existence, unit plausibility, range checks)
3. Process (convert, run, parse)
4. Validate outputs (physical plausibility, diagnostic warnings)
5. Return JSON: `{"status": "success/error", "output": {...}, "log": [...]}`

---

## 6. Critical Domain Knowledge

These non-obvious facts cause silent failures. Each links to a diagnostic triplet.

1. **dt_001 / dt_002**: WQP temperature data may be in Fahrenheit or Kelvin
   depending on the monitoring organization. Always check
   `ResultMeasure/MeasureUnitCode`. Values > 50 in a temperate lake are
   almost certainly Fahrenheit. Values > 200 are Kelvin.

2. **dt_003 / dt_004**: WQP dissolved oxygen is typically mg/L but some
   entries report percent saturation. At 20 C, 100% saturation = 9.09 mg/L.
   Using percent values directly gives DO of 80-110 "mg/L" which is absurd.

3. **dt_005 / dt_006**: WQP depth fields
   (`ActivityDepthHeightMeasure/MeasureValue`) vary in units. The most
   common unit is meters, but some stations report in feet. Check
   `ActivityDepthHeightMeasure/MeasureUnitCode`.

4. **Benson-Krause temperature sensitivity**: DO saturation drops from
   14.6 mg/L at 0 C to 7.6 mg/L at 30 C. A 1 C error in temperature
   produces ~0.2 mg/L error in DO saturation. This is the dominant source
   of DO model error in thermally stratified lakes.

5. **Thermocline depth varies seasonally**: The logistic thermocline model
   uses a fixed thermocline depth, valid only during summer stratification
   (June-August in Northern Hemisphere). Applying summer profiles to spring
   or fall data produces large errors because the thermocline is developing
   or breaking down.

6. **Hypolimnetic oxygen depletion**: In productive lakes, the hypolimnion
   becomes hypoxic during summer stratification due to sediment oxygen
   demand (SOD) and decomposition. The DO profile model captures this via
   a depletion rate parameter, but the rate varies by lake productivity
   (oligotrophic: 0.01-0.03, eutrophic: 0.05-0.15 per meter below
   thermocline).

7. **Carlson TSI independence assumption**: The three TSI indices (Chl-a,
   Secchi, TP) are designed to agree for algae-dominated systems. Deviations
   indicate non-algal turbidity (TSI_Secchi >> TSI_Chl-a) or nutrient
   limitation (TSI_TP >> TSI_Chl-a).

8. **WQP data quality flags**: WQP data includes a
   `ResultStatusIdentifier` field. Records marked "Rejected" or
   "Preliminary" should be excluded. Also filter
   `ResultValueTypeName != "Estimated"` for calibration data.

---

## 7. WASP Parameters

### Temperature Seasonal Model (3 parameters)

| Parameter   | Symbol    | Unit    | Typical Range   | Description                          |
|-------------|-----------|---------|-----------------|--------------------------------------|
| Mean temp   | T_mean    | deg C   | [2, 30]         | Annual average surface temperature   |
| Amplitude   | amplitude | deg C   | [3, 18]         | Seasonal temperature swing           |
| Phase       | phase     | day     | [90, 170]       | Day-of-year of temperature peak      |

### DO Seasonal Model (4 parameters, coupled to temperature)

| Parameter   | Symbol    | Unit    | Typical Range   | Description                          |
|-------------|-----------|---------|-----------------|--------------------------------------|
| BOD decay   | kd        | 1/d     | [0.01, 0.5]     | Deoxygenation rate coefficient       |
| Reaeration  | ka        | 1/d     | [0.1, 2.0]      | Atmospheric reaeration rate          |
| Initial BOD | BOD0      | mg/L    | [0.5, 20]       | Background BOD loading               |
| DO offset   | DO_offset | mg/L    | [-3, 3]         | Systematic DO correction             |

### Thermal Profile (4 parameters)

| Parameter      | Symbol      | Unit  | Typical Range | Description                        |
|----------------|-------------|-------|---------------|------------------------------------|
| Surface temp   | T_surface   | deg C | [15, 30]      | Epilimnion temperature (summer)    |
| Bottom temp    | T_bottom    | deg C | [4, 15]       | Hypolimnion temperature            |
| Thermocline    | thermo_depth| m     | [3, 30]       | Depth of maximum dT/dz             |
| Thermo width   | thermo_width| m     | [0.5, 10]     | Thermocline transition thickness   |

### Lake Morphometry

| Parameter   | Symbol     | Unit   | Description                             |
|-------------|------------|--------|-----------------------------------------|
| Max depth   | z_max      | m      | Maximum lake depth                      |
| Mean depth  | z_mean     | m      | Volume / surface area                   |
| Surface area| area       | km2    | Lake surface area                       |
| Volume      | volume     | m3     | Total lake volume                       |

---

## 8. Streeter-Phelps BOD-DO Physics

The Streeter-Phelps model describes the DO sag curve downstream of a
pollution source (or temporally in a lake with BOD loading):

```
dBOD/dt = -kd * BOD          (first-order BOD decay)
dDO/dt  = ka * (DO_sat - DO) - kd * BOD    (reaeration - deoxygenation)
```

Analytical solution for oxygen deficit D = DO_sat - DO:

```
D(t) = [kd * BOD0 / (ka - kd)] * [exp(-kd*t) - exp(-ka*t)] + D0 * exp(-ka*t)
```

Critical behavior:
- If ka > kd: deficit peaks at t_c = ln(ka/kd) / (ka - kd), then recovers
- If ka = kd: degenerate case, use L'Hopital limit
- If ka < kd: reaeration dominates, rapid recovery from initial deficit
- DO is clipped to [0, DO_sat] to prevent supersaturation or negative values

Typical parameter values for lakes:
- kd: 0.05-0.3 /d (lower for lakes than rivers due to settling)
- ka: 0.1-1.0 /d (lower for deep lakes, higher for shallow/windy)
- BOD0: 1-10 mg/L (varies with pollution loading)

---

## 9. Validated Results (Lake Erie Central Basin)

| Metric                  | Calibration | Validation |
|-------------------------|-------------|------------|
| Temperature R           | 0.878       | 0.885      |
| Temperature RMSE (C)    | 4.31        | 4.10       |
| Temperature n           | 28,988      | 19,326     |
| DO R                    | 0.816       | 0.413      |
| DO RMSE (mg/L)          | 2.14        | 3.77       |
| DO n                    | 19,795      | 13,198     |
| Thermal profile R       | 0.996       | --         |
| Thermal profile RMSE (C)| 0.62        | --         |
| TSI (Chl-a)             | 40.7        | --         |
| NLA percentile          | 22.3%       | --         |

Temperature model shows strong generalization (R improves from cal to val).
DO model shows reduced generalization, typical for simple seasonal models
that cannot capture interannual variability in loading and stratification.
Thermal profile model achieves near-perfect fit (R=0.996) for summer conditions.

### Performance Metrics -- Convention Bars

Source: `docs/validation_convention.yaml`. These bars are the KI's cited
field convention for judging model skill. A null band in the convention is
reported here as "no cited threshold".

| Dag variable | Metric | Direction | Satisfactory band | Good band | Very good band |
|--------------|--------|-----------|-------------------|-----------|----------------|
| `temperature_timeseries` | nse | maximize | 0.5 (`arnold2012`, `efdc2021`, `piccolroaz2013`) | no cited threshold (`arnold2012`, `efdc2021`, `piccolroaz2013`) | 0.75 (`arnold2012`, `efdc2021`, `piccolroaz2013`) |
| `do_timeseries` | nse | maximize | 0.5 (`arnold2012`, `efdc2021`, `deepavarsa2023`) | no cited threshold (`arnold2012`, `efdc2021`, `deepavarsa2023`) | 0.75 (`arnold2012`, `efdc2021`, `deepavarsa2023`) |
| `do_timeseries` | r2 | maximize | 0.5 (`deepavarsa2023`, `lushui2021`) | 0.6 (`deepavarsa2023`, `lushui2021`) | 0.75 (`deepavarsa2023`, `lushui2021`) |
| `temperature_profile` | pbias | zero_centered | 15 (`lushui2021`) | no cited threshold (`lushui2021`) | no cited threshold (`lushui2021`) |

For the headline dag variable `do_timeseries`, the convention bars are:

- `nse`, maximize: satisfactory 0.5 (`arnold2012`, `efdc2021`, `deepavarsa2023`), good no cited threshold (`arnold2012`, `efdc2021`, `deepavarsa2023`), very good 0.75 (`arnold2012`, `efdc2021`, `deepavarsa2023`).
- `r2`, maximize: satisfactory 0.5 (`deepavarsa2023`, `lushui2021`), good 0.6 (`deepavarsa2023`, `lushui2021`), very good 0.75 (`deepavarsa2023`, `lushui2021`).

---

## 10. Supported Lakes

| Lake              | WQP Directory     | Key Variables        | Profile Data |
|-------------------|--------------------|----------------------|--------------|
| Lake Erie Central | Lake_Erie_Central  | Temp, DO, Chl-a     | Yes          |
| DeGray Lake       | DeGray_Lake        | Temp, DO             | Yes          |
| Jordan Lake       | Jordan_Lake        | Temp, DO, Chl-a     | Yes          |
| Lake Mead         | Lake_Mead          | Temp, DO             | Yes          |

NLA 2017 survey data provides additional profile validation for deep lakes
across the continental US.
