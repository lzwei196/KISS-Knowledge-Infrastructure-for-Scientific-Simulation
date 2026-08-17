---
name: hydrocnhs
description: >-
  HydroCNHS (Lin, Yang & Wi 2022) — semi-distributed daily CNHS hydrology: GWLF/ABCD
  rainfall-runoff + Lohmann routing + four ABM coupling APIs. Covers Semi-distributed
  daily rainfall-runoff at the subbasin level (GWLF, ABCD, or user-supplied 'Other');
  Routing of subbasin runoff to routing outlets (within-subbasin gamma unit hydrograph +….
  Use when the task involves running, configuring, calibrating or interpreting HydroCNHS.
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

# HydroCNHS Knowledge Infrastructure

**Package**: HydroCNHS KI v1.0
**Model**: HydroCNHS v1.2.1
**Domain**: Hydrology — Coupled Natural-Human Systems
**Created**: 2026-03-25
**Validation**: Tualatin River Basin (TRB), Oregon, USA (1981–2013)

| Metric | Value |
|--------|-------|
| Tools | 5 |
| Pipeline stages | 8 |
| Diagnostic triplets | 18 |
| Skill documents | 6 |
| Validation basin | TRB, Oregon |

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/HWSD/SKILL.md` for soil property documentation.
See `data_ki/ObservedQ/SKILL.md` for observed discharge data.


## 1. Overview

HydroCNHS is a Python package for simulating **Coupled Natural-Human Systems** in water
resource management. It integrates semi-distributed hydrological modeling (rainfall-runoff
+ Lohmann routing) with agent-based modeling (ABM) for human decision-making. The model
operates on a **daily time step** and supports two rainfall-runoff schemes (GWLF and ABCD),
Lohmann routing, and four ABM APIs (Dam, RiverDiv, Conveying, InSitu).

Key capabilities:
- Semi-distributed hydrological simulation at daily resolution
- Pluggable rainfall-runoff models (GWLF: 9 params, ABCD: 5 params)
- Lohmann routing with 4 parameters per link
- Agent-based modeling for dams, diversions, aqueducts, and in-situ modifications
- Built-in genetic algorithm (DEAP) calibration with parallel computing
- Evaluation indicators: NSE, KGE, iKGE, iNSE, r, r², RMSE, RSR, Cp

The model is entirely Python-based (no compiled binaries). Execution is via the
Python API: `model = hydrocnhs.Model("model.yaml"); model.run(temp, prec, pet)`.

---

## 2. Installation

```bash
# Create virtual environment
python3 -m venv venv && source venv/bin/activate

# Install from source
cd source/repo && pip install -e .

# Or from PyPI
pip install hydrocnhs
```

**Dependencies**: joblib, matplotlib, numpy, pandas, ruamel.yaml, scipy,
scikit-learn, tqdm, pyyaml, deap

**Python versions**: 3.10, 3.11, 3.12

**Quick test**:
```python
import hydrocnhs
print(hydrocnhs.__version__)  # 1.2.1
```

---

## 3. Pipeline

The HydroCNHS pipeline has 8 stages from data preparation through validation.

| # | Stage | Tool | Input | Output |
|---|-------|------|-------|--------|
| S0 | Basin setup | — | GIS/literature | Subbasin areas, latitudes, flow lengths |
| S1 | Climate data prep | `convert_climate_inputs.py` | Global gridded data (ERA5, CMIP) | `temp_dict`, `prec_dict` [°C, cm/day] |
| S2 | Parameter estimation | `convert_parameters.py` | Soil/land-use data | Initial GWLF/ABCD params in YAML |
| S3 | Model config build | `build_model_config.py` | Basin geometry + params | `model.yaml` |
| S4 | ABM setup | — | Operational rules, literature | ABM module `.py` file |
| S5 | Model execution | `run_hydrocnhs.py` | `model.yaml` + climate dicts | `Q_routed` [cms] |
| S6 | Calibration | `run_hydrocnhs.py` | Observed streamflow + bounds | Calibrated `model.yaml` |
| S7 | Output analysis | `parse_output.py` | `Q_routed`, observed data | CSV + metrics + plots |

---

## 4. Unit Trap Table

These are the **critical unit conversions** that cause silent failures if violated.
Every value must match the model's internal expectations exactly.

| Variable | Model expects | Common source unit | Conversion | Trap ID |
|----------|--------------|-------------------|------------|---------|
| Precipitation | **cm/day** | mm/day (ERA5, CMIP) | ÷ 10 | dt_001 |
| Precipitation | **cm/day** | kg/m²/s (CMIP) | × 86400 ÷ 10 | dt_002 |
| Temperature | **°C** | K (CMIP, ERA5) | − 273.15 | dt_003 |
| PET | **cm/day** | mm/day | ÷ 10 | dt_004 |
| Subbasin area | **ha** | km² | × 100 | dt_005 |
| Subbasin area | **ha** | m² | ÷ 10000 | dt_006 |
| Flow length | **m** | km | × 1000 | dt_007 |
| Latitude | **decimal degrees** | DMS | convert properly | dt_008 |
| Discharge (output) | **cms** (m³/s) | — | native output unit | — |
| Soil water capacity (Ur) | **cm** | mm | ÷ 10 | dt_009 |
| Snowmelt coeff (Df) | **cm/°C** | mm/°C | ÷ 10 | dt_010 |
| Wave velocity | **m/s** | km/h | × 1000/3600 | dt_011 |
| Diffusivity | **m²/s** | — | native | — |

**Rule**: If your simulated discharge is 10× too high or too low, check precipitation
units first. This is the #1 cause of failed HydroCNHS runs.

---

## 5. Tools Reference

| Tool | Stage | Script | Purpose |
|------|-------|--------|---------|
| Climate converter | S1 | `tools/convert_climate_inputs.py` | ERA5/CMIP → temp[°C], prec[cm/day] dicts |
| Parameter converter | S2 | `tools/convert_parameters.py` | Soil/land-use → GWLF/ABCD initial params |
| Model config builder | S3 | `tools/build_model_config.py` | Generate model.yaml from basin geometry |
| Execution wrapper | S5–S6 | `tools/run_hydrocnhs.py` | Run model or calibration |
| Output parser | S7 | `tools/parse_output.py` | Extract Q_routed to CSV + compute metrics |

All tools follow the **validate → process → validate** pattern:
1. Parse CLI arguments with `argparse`
2. Validate all inputs (check files exist, units plausible, ranges correct)
3. Process (convert, build, run, parse)
4. Validate outputs (check results exist, values in expected range)
5. Return JSON: `{"status": "success/error", "output": {...}, "log": [...]}`

---

## 6. Critical Domain Knowledge

These facts are non-obvious and cause **silent failures** if violated:

1. **Precipitation must be in cm/day** (dt_001, dt_002). Most global datasets
   provide mm/day or kg/m²/s. Forgetting the ÷10 conversion is the single most
   common error. The model will run without error but discharge will be 10× wrong.

2. **PET is auto-calculated if not provided** (Hamon method). The Hamon PET
   uses latitude and temperature. If you provide PET, it must be in cm/day.
   If PET values seem too high, check if you passed mm/day by mistake.

3. **Area must be in hectares** (dt_005, dt_006). The GWLF runoff-to-discharge
   conversion uses area in ha. If you pass km², discharge will be 100× too low.

4. **CN2 sensitivity** — The SCS Curve Number (CN2, range 25–100) is the most
   sensitive GWLF parameter. A change of ±5 can shift peak discharge by 30–50%.
   Always calibrate CN2 first.

5. **Routing parameters interact** — GShape/GScale control within-subbasin UH
   shape, while Velo/Diff control between-subbasin wave propagation. Calibrating
   them separately can lead to equifinality. Calibrate jointly.

6. **ABM agent execution order matters** — Agents are executed in priority order
   (low number = first). Dam releases affect downstream diversions. If priorities
   are wrong, water balance violations occur silently.

7. **Calibration uses -99 sentinel** — Parameters set to -99 in the YAML are
   marked for calibration. If you forget to set bounds for a -99 parameter,
   the GA will use default bounds which may not suit your basin.

8. **Date format must be YYYY/M/D** — The model expects "1981/1/1" not
   "1981-01-01". Using the wrong format causes a silent parse failure.

9. **Data length must match date range** — The `DataLength` field in YAML must
   equal the number of days between StartDate and EndDate (inclusive). A mismatch
   causes index errors or silent truncation.

---

## 7. GWLF Parameters (per subbasin)

| Parameter | Symbol | Unit | Range | Sensitivity | Description |
|-----------|--------|------|-------|-------------|-------------|
| Curve Number | CN2 | — | [25, 100] | Very High | SCS runoff curve number |
| Interception | IS | — | [0, 0.5] | Medium | Fraction of precip intercepted |
| Recession | Res | — | [0.001, 0.5] | High | Baseflow recession coefficient |
| Deep seepage | Sep | — | [0, 0.5] | Low | Fraction to deep aquifer |
| Baseflow | Alpha | — | [0, 1] | High | Groundwater discharge rate |
| Percolation | Beta | — | [0, 1] | Medium | Unsaturated zone percolation |
| Soil water | Ur | cm | [1, 15] | High | Available water capacity |
| Snowmelt | Df | cm/°C | [0, 1] | Medium | Degree-day coefficient |
| Land cover | Kc | — | [0.5, 1.5] | Medium | Crop/vegetation coefficient |

---

## 8. ABCD Parameters (per subbasin)

| Parameter | Symbol | Unit | Range | Sensitivity | Description |
|-----------|--------|------|-------|-------------|-------------|
| Runoff ctl | a | — | [0, 1] | High | Controls runoff during unsaturation |
| Saturation | b | cm | [0, 400] | High | Maximum soil water storage |
| Recharge | c | — | [0, 1] | Medium | Groundwater recharge fraction |
| Discharge | d | — | [0, 1] | Medium | Groundwater discharge rate |
| Snowmelt | Df | cm/°C | [0, 1] | Medium | Degree-day coefficient |

---

## 9. Lohmann Routing Parameters (per link)

| Parameter | Symbol | Unit | Range | Description |
|-----------|--------|------|-------|-------------|
| UH shape | GShape | — | [1, 100] | Gamma distribution shape |
| UH scale | GScale | — | [0.01, 150] | Gamma distribution scale |
| Wave velocity | Velo | m/s | [0.5, 55] | Saint-Venant celerity |
| Diffusivity | Diff | m²/s | [200, 4000] | Saint-Venant diffusion |

---

## 10. Validation Results

**Basin**: Tualatin River Basin (TRB), Oregon, USA
**Period**: 1981/1/1 – 2013/12/31 (33 years, 12,053 days)
**Subbasins**: 7 (HaggIn, TRTR, DLLO, TRGC, DAIRY, RCTV, WSLO)
**Model**: GWLF + Lohmann routing + ABM (reservoir + diversion + pipe)

Calibrated performance at WSLO outlet (monthly):
- KGE ≈ 0.80–0.90
- NSE ≈ 0.75–0.85
- r ≈ 0.90–0.95

Key findings:
1. CN2 ranges 46–99 across subbasins, reflecting diverse land use
2. Routing velocity 8.6–48 m/s, diffusivity 295–3847 m²/s
3. ABM agents critical for reproducing regulated flow at WSLO
4. Warm-up period of 1–2 years recommended before evaluation

---

## 11. Coupling Points

HydroCNHS couples with external systems through its ABM APIs:

| API | Direction | What it controls |
|-----|-----------|-----------------|
| Dam API | Instream | Reservoir releases, storage |
| RiverDiv API | Off-stream | Irrigation diversions, return flows |
| Conveying API | Inter-basin | Aqueducts, pipelines, pumps |
| InSitu API | Within-basin | Groundwater extraction, urbanization |

---

## 12. Data Requirements

| Data | Source | Unit | Required |
|------|--------|------|----------|
| Daily temperature | ERA5, station | °C | Yes |
| Daily precipitation | ERA5, station | cm/day | Yes |
| Daily PET | Calculated or station | cm/day | Optional |
| Subbasin areas | GIS | ha | Yes |
| Subbasin latitudes | GIS | decimal degrees | Yes |
| Flow lengths | GIS | m | Yes |
| Observed streamflow | USGS, gauge | cms | For calibration |
| Soil/land-use | SSURGO, NLCD | varies | For initial params |

---

## 13. Quick Start

```python
import hydrocnhs
import pickle

# Load climate data
with open("TRB_inputs.pickle", "rb") as f:
    inputs = pickle.load(f)

# Run model
model = hydrocnhs.Model("Calibrated_TRB_GWLF.yaml")
Q = model.run(temp=inputs["temp"], prec=inputs["prec"])
sim = model.dc.Q_routed["WSLO"]

# Evaluate
indicator = hydrocnhs.Indicator()
print("NSE:", indicator.get_nse(observed, sim))
print("KGE:", indicator.get_kge(observed, sim))

# Visualize
hydrocnhs.Visual().plot.timeseries(
    Q_routed=model.dc.Q_routed,
    labels=["WSLO"],
    figsize=(12, 4)
)
```

---

## Output Description

HydroCNHS stores simulation results in the `model.dc` (data collector) object after `model.run()`. The primary output is `model.dc.Q_routed`, a dictionary keyed by gauge/subbasin name containing daily routed streamflow arrays in m^3/s (cms). Additional outputs include `model.dc.Q_local` (local runoff per subbasin), actual evapotranspiration, and soil moisture states. Use `parse_output.py` to export `Q_routed` to CSV with columns `date, Q_sim (cms)` and compute performance indicators (NSE, KGE, RMSE, r) against observed streamflow. ABM agent records (reservoir storage, diversion volumes) are accessible via the agent objects after the run.

---

## 14. Diagnostic Triplets Summary

See `diagnostics/triplets.yaml` for 18 symptom → diagnosis → remedy entries.

Key failure domains:
- **unit_conversion** (7 triplets): Silent errors from wrong input units
- **parameter_format** (3 triplets): YAML config mistakes
- **runtime** (3 triplets): Crashes during execution
- **silent_error** (3 triplets): Model runs but results are wrong
- **calibration** (2 triplets): GA convergence issues

---

## 15. File Structure

```
ki/
├── SKILL.md                    # This file — main entry point
├── tools/
│   ├── convert_climate_inputs.py  # ERA5/CMIP → model format
│   ├── convert_parameters.py      # Soil/land-use → GWLF/ABCD params
│   ├── build_model_config.py      # Generate model.yaml
│   ├── run_hydrocnhs.py           # Execute model or calibration
│   └── parse_output.py            # Extract results to CSV + metrics
├── docs/
│   ├── s1_climate_data_skill.md       # Climate data preparation
│   ├── s2_parameter_estimation_skill.md # Parameter estimation
│   ├── s3_model_configuration_skill.md  # Model config building
│   ├── s5_execution_skill.md           # Model execution
│   ├── s7_output_analysis_skill.md     # Output analysis
│   └── s8_calibration_skill.md         # Calibration workflow
└── diagnostics/
    └── triplets.yaml              # 18 diagnostic triplets
```
