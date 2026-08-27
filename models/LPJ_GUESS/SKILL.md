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
| `tools/convert_forcing_to_lpjguess.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing_to_lpjguess.py --help` |
| `tools/convert_parameters_to_lpjguess.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_parameters_to_lpjguess.py --help` |
| `tools/parse_output_lpjguess.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_output_lpjguess.py --help` |
| `tools/run_lpjguess.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_lpjguess.py --help` |

*4 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# LPJ-GUESS (Lund-Potsdam-Jena General Ecosystem Simulator) -- Knowledge Infrastructure

**Package**: `kdt-lpj-guess` v1.0.0
**Model**: LPJ-GUESS (dynamic vegetation / biogeochemistry model)
**Domain**: Terrestrial biogeochemistry (C/N cycling, vegetation dynamics)
**Created by**: KDT Auto-Dissection
**Last updated**: 2026-03-30
**Stats**: 4 tools | 1 skill document | ~2,400 lines of validated Python
**Validation status**: `analytic` (reimplemented physics validated against FLUXNET2015 eddy-covariance)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/FLUXNET/SKILL.md` for eddy covariance flux observations.


## Overview

This knowledge infrastructure enables autonomous simulation of terrestrial ecosystem
carbon and nitrogen cycling using the core physics of LPJ-GUESS. The pipeline converts
FLUXNET2015 or gridded reanalysis forcing data to LPJ-GUESS input format, manages PFT
and site parameters, runs the analytic reimplementation of core processes, and parses
output timeseries of GPP, NEE, and ecosystem respiration.

**What LPJ-GUESS does**: Dynamic global vegetation model simulating:
- Carbon assimilation: Light Use Efficiency (LUE) model for GPP (Monteith 1972 approach)
  with parabolic temperature response and exponential VPD limitation
- Autotrophic respiration: maintenance respiration via Q10 temperature dependence,
  growth respiration as a fixed fraction of NPP
- Heterotrophic respiration: temperature- and moisture-dependent decomposition of
  litter and soil organic carbon pools (Q10 formulation)
- Carbon/Nitrogen cycling: coupled C/N dynamics with N limitation on productivity,
  N mineralization, and N deposition inputs
- Vegetation dynamics: establishment, mortality, competition among Plant Functional
  Types (PFTs) based on bioclimatic limits and resource availability
- Water stress: stomatal closure under high VPD reduces GPP via a VPD scalar
- NEE computation: NEE = Reco - GPP (ecosystem sign convention: negative = carbon sink)

**Key model characteristics**:
- Patch-based (cohort mode) or population-based (area-averaged) vegetation representation
- Daily timestep for carbon/water, annual timestep for vegetation dynamics
- Multiple PFTs compete for light and water within each patch
- Stochastic disturbance (fire, windthrow)
- Supports both site-level and gridded simulations

---

## Core Physics

### 1. GPP via Light Use Efficiency (LUE)

LPJ-GUESS computes Gross Primary Production using a radiation-driven LUE approach:

```
PAR = SW_IN * 0.48                  # Photosynthetically Active Radiation (W/m2)
PAR_MJ = PAR * 86400 / 1e6          # Convert to MJ/m2/day

f_T = parabolic(T, T_min, T_opt, T_max)   # Temperature scalar [0, 1]
f_VPD = exp(-ln(2) * max(VPD - VPD_0, 0) / VPD_1)  # VPD scalar [0.05, 1]

GPP_gC = LUE_max * PAR_MJ * f_T * f_VPD   # gC/m2/day
GPP_umol = GPP_gC * 1e6 / 12.011 / 86400  # umol CO2/m2/s
```

**Parameters**:
- `LUE_max`: Maximum light use efficiency (typical 1.0-3.0 gC/MJ PAR)
- `T_opt`: Optimal temperature for photosynthesis (default 20 C)
- `T_min` / `T_max`: Min/max temperature limits (default -2 / 38 C)
- `VPD_0`: VPD threshold before GPP decline (default 10 hPa)
- `VPD_1`: VPD at which GPP halves (default 35 hPa)
- `SW_in_scale`: Fraction of shortwave that is PAR (0.48)

### 2. Autotrophic Respiration (Ra)

Maintenance respiration follows a Q10 temperature response:

```
f_T = Q10_Ra ^ ((T - T_ref) / 10)
Ra = Ra_base * GPP * f_T / Q10_Ra    # Normalized at T_ref
```

**Parameters**:
- `Ra_base`: Base fraction of GPP allocated to respiration (default 0.5)
- `Ra_Q10`: Q10 coefficient for maintenance respiration (default 2.0)
- `Ra_Tref`: Reference temperature (default 15 C)

Growth respiration is implicitly included as a fixed fraction (NPP = GPP - Ra).

### 3. Heterotrophic Respiration (Rh)

Decomposition of soil/litter carbon pools follows Q10 kinetics:

```
f_T = Q10_Rh ^ ((T - T_ref) / 10)
Rh = Rh_base * f_T * C_pool_scale
```

**Parameters**:
- `Rh_base`: Base heterotrophic respiration rate (default 2.0 umol/m2/s)
- `Rh_Q10`: Q10 for decomposition (default 2.0)
- `Rh_Tref`: Reference temperature (default 15 C)
- `C_pool_scale`: Scaling factor for soil C pool effect (default 1.0)

### 4. Net Ecosystem Exchange (NEE)

```
Reco = Ra + Rh
NEE  = Reco - GPP    # Positive = net source, Negative = net sink
```

---

## Required Inputs

### Meteorological Forcing

| Variable | Units        | Description                        | FLUXNET column      |
|----------|--------------|------------------------------------|---------------------|
| SW_IN    | W/m2         | Incoming shortwave radiation       | SW_IN_F, SW_IN_F_MDS |
| TA       | deg C        | Air temperature                    | TA_F, TA_F_MDS     |
| VPD      | hPa          | Vapour pressure deficit            | VPD_F, VPD_F_MDS   |
| P        | mm/day       | Precipitation (optional, for water balance) | P_F, P_F_MDS |

**Supported forcing sources**:
- FLUXNET2015 FULLSET (daily DD or monthly MM CSV files)
- CMFD (China Meteorological Forcing Dataset): temperature in K, precip in kg/m2/s
- MSWX (Multi-Source Weather): temperature in K, precip in mm/3hr

### CRITICAL UNIT TRAPS

- **Temperature**: CMFD/MSWX provide K; LPJ-GUESS expects deg C. Subtract 273.15.
- **Precipitation**: CMFD provides kg/m2/s; must multiply by 86400 for mm/day.
  MSWX provides mm/3hr; sum 8 steps per day.
- **VPD**: FLUXNET provides hPa; some datasets provide kPa (multiply by 10) or Pa (divide by 100).
- **SW radiation**: Must be total incoming shortwave, not net radiation.
- **Missing values**: FLUXNET uses -9999 as fill value. Must be converted to NaN before processing.

---

## Unit Conversion Table

This table restates the unit conversions documented by this KI body and its source
data notes. Exact I/O shapes live in `docs/format_spec.yaml`; if a generated spec
and this prose ever disagree, regenerate this body from the KI sources.

| Variable | Source unit (verified) | Model unit | Factor / operation | Type |
|----------|------------------------|------------|--------------------|------|
| Temperature | K (CMFD/MSWX) | deg C | subtract 273.15 | additive |
| Precipitation | kg/m2/s (CMFD) | mm/day | multiply by 86400 | multiplicative |
| Precipitation | mm/3hr (MSWX) | mm/day | sum 8 steps per day | temporal aggregation |
| VPD | kPa (some datasets) | hPa | multiply by 10 | multiplicative |
| VPD | Pa (some datasets) | hPa | divide by 100 | multiplicative |
| VPD | hPa (FLUXNET) | hPa | x1 | identity |
| SW radiation | W/m2 incoming shortwave | W/m2 incoming shortwave | x1 | identity |
| Missing values | -9999 (FLUXNET fill value) | NaN | replace with NaN before processing | quality-control transform |

### Output Unit Table

This table restates `dag.yaml` for the observable outputs. The dag is authoritative
for output identity; if this section and `dag.yaml` diverge, `dag.yaml` wins.

| Output variable (dag `var`) | Unit | Description / role |
|-----------------------------|------|--------------------|
| GPP | umol/m2/s | Gross Primary Production (terrestrial vegetation carbon assimilation flux). Rank-1 output. |
| Ra | umol/m2/s | Autotrophic respiration. |
| Rh | umol/m2/s | Heterotrophic respiration. |
| Reco | umol/m2/s | Ecosystem respiration (Ra + Rh). |
| NEE | umol/m2/s | Net Ecosystem Exchange (Reco - GPP). |
| NPP | umol/m2/s | Net Primary Production (GPP - Ra). |

### Site/PFT Parameters

| Parameter    | Units         | Description                              |
|-------------|---------------|------------------------------------------|
| LUE_max     | gC/MJ PAR    | Maximum light use efficiency              |
| T_opt       | deg C         | Optimal photosynthesis temperature        |
| T_min       | deg C         | Minimum photosynthesis temperature        |
| T_max       | deg C         | Maximum photosynthesis temperature        |
| VPD_0       | hPa           | VPD threshold for GPP decline            |
| VPD_1       | hPa           | VPD half-inhibition point                |
| Ra_base     | fraction      | Base autotrophic respiration / GPP ratio |
| Ra_Q10      | dimensionless | Q10 for maintenance respiration          |
| Rh_base     | umol/m2/s     | Base heterotrophic respiration rate      |
| Rh_Q10      | dimensionless | Q10 for decomposition                   |
| leaf_N      | gN/m2 leaf    | Leaf nitrogen content per area (optional)|
| SLA         | m2/kgC        | Specific leaf area (optional)            |
| Vcmax_base  | umol/m2/s     | Base Vcmax at 25 C (optional, Farquhar)  |

---

## Model Outputs

| Variable | Units       | Description                              |
|----------|-------------|------------------------------------------|
| GPP      | umol/m2/s   | Gross Primary Production                 |
| Ra       | umol/m2/s   | Autotrophic respiration                  |
| Rh       | umol/m2/s   | Heterotrophic respiration                |
| Reco     | umol/m2/s   | Ecosystem respiration (Ra + Rh)          |
| NEE      | umol/m2/s   | Net Ecosystem Exchange (Reco - GPP)      |
| NPP      | umol/m2/s   | Net Primary Production (GPP - Ra)        |

---

## Tool Pipeline

```
FLUXNET2015 / CMFD / MSWX           Site/PFT parameters
       |                                    |
       v                                    v
convert_forcing_to_lpjguess.py    convert_parameters_to_lpjguess.py
       |                                    |
       +------------------------------------+
       |
       v
run_lpjguess.py  (execution wrapper: loads forcing + params, runs model)
       |
       v
parse_output_lpjguess.py  (extracts GPP, NEE, RECO timeseries to CSV)
```

### Tool inventory

| Tool | Purpose | Input | Output |
|------|---------|-------|--------|
| `convert_forcing_to_lpjguess.py` | Convert met forcing to LPJ-GUESS format | FLUXNET CSV, CMFD/MSWX NetCDF | Standardized CSV with SW_IN/TA/VPD/P columns |
| `convert_parameters_to_lpjguess.py` | Convert site/PFT parameters | JSON or CLI args | Parameter JSON for model |
| `run_lpjguess.py` | Run the analytic model | Forcing CSV + parameter JSON | Raw model output CSV |
| `parse_output_lpjguess.py` | Parse and validate output | Raw output CSV | Clean timeseries CSV + summary stats |

### Stage skill documents

- [Stage 1: Preflight](docs/s1_preflight.md)
- [Stage 2: Convert Forcing](docs/s2_convert_forcing.md)
- [Stage 3: Convert Parameters](docs/s3_convert_parameters.md)
- [Stage 4: Run LPJ-GUESS Analytic Model](docs/s4_run_lpjguess.md)
- [Stage 5: Parse Output](docs/s5_parse_output.md)

---

## Validation

Validation uses FLUXNET2015 eddy-covariance tower observations. The pipeline:
1. Loads gap-filled meteorological forcing (SW_IN, TA, VPD) from a FLUXNET site
2. Splits data into calibration (70% of years) and validation (30%) periods
3. Calibrates 6 key parameters using differential evolution optimization
4. Evaluates on held-out validation period
5. Reports R, RMSE, bias, NSE, KGE for GPP and NEE

**Preferred validation sites** (in priority order):
US-Ha1, DE-Tha, US-MMS, FI-Hyy, FR-Pue, IT-Col, US-UMB, BE-Vie, DE-Hai, US-WCr

---

## Validated Results

### Validation Campaign Status

The KI body records the FLUXNET2015 validation workflow, preferred tower sites,
calibration/validation split, optimization approach, and reported metric names.
No completed body-level validation campaign table with achieved calibration,
validation, or full-period metric values is recorded here yet; campaign results
are pending.

### Headline Output

The dag's rank-1 output is:

> `GPP` -- Gross Primary Production (terrestrial vegetation carbon assimilation flux). (`umol/m2/s`)

Other dag outputs are `Ra`, `Rh`, `Reco`, `NEE`, and `NPP`.

### Performance Metrics -- Field Convention Bars

These bars restate `docs/validation_convention.yaml`. The convention is
authoritative for metric, direction, pass-bands, and citation keys; null bands are
written as "no cited threshold" rather than guessed.

| dag variable | Metric | Direction | Satisfactory band | Good band | Very good band |
|--------------|--------|-----------|-------------------|-----------|----------------|
| GPP | NSE | maximize | >= 0.0 (walker2014) | no cited threshold (walker2014) | no cited threshold (walker2014) |
| Ra | NSE | maximize | >= 0.0 (walker2014) | no cited threshold (walker2014) | no cited threshold (walker2014) |
| Rh | NSE | maximize | >= 0.0 (walker2014) | no cited threshold (walker2014) | no cited threshold (walker2014) |

| Metric | Calibration | Validation | Full Period | Bar (convention, cited) |
|--------|-------------|------------|-------------|-------------------------|
| NSE for GPP | pending | pending | pending | satisfactory >= 0.0 (walker2014); good: no cited threshold (walker2014); very good: no cited threshold (walker2014) |
| NSE for Ra | pending | pending | pending | satisfactory >= 0.0 (walker2014); good: no cited threshold (walker2014); very good: no cited threshold (walker2014) |
| NSE for Rh | pending | pending | pending | satisfactory >= 0.0 (walker2014); good: no cited threshold (walker2014); very good: no cited threshold (walker2014) |

### Data Replacement Tracking

| Component | Source | Status | Notes |
|-----------|--------|--------|-------|
| Forcing | FLUXNET2015 / CMFD / MSWX pipeline | Pending | The body documents conversion and validation workflow, but no completed campaign table is recorded. |
| Site/PFT parameters | JSON or CLI parameters | Pending | Converted by `convert_parameters_to_lpjguess.py`; achieved validation values are pending. |
| Model execution | Analytic LPJ-GUESS reimplementation | Pending | Run through `run_lpjguess.py`; body-level campaign metrics are pending. |
| Output parsing | `parse_output_lpjguess.py` | Pending | Parses GPP, NEE, and RECO timeseries; body-level campaign metrics are pending. |

---

## References

- Smith, B. et al. (2001). Representation of vegetation dynamics in the modelling of
  terrestrial ecosystems: comparing two contrasting approaches within European climate
  space. Global Ecology & Biogeography, 10, 621-637.
- Smith, B. et al. (2014). Implications of incorporating N cycling and N limitations on
  primary production in an individual-based dynamic vegetation model. Biogeosciences, 11, 2027-2054.
- Monteith, J.L. (1972). Solar radiation and productivity in tropical ecosystems. J. Applied Ecology, 9, 747-766.
- Sitch, S. et al. (2003). Evaluation of ecosystem dynamics, plant geography and terrestrial
  carbon cycling in the LPJ dynamic global vegetation model. Global Change Biology, 9, 161-185.
