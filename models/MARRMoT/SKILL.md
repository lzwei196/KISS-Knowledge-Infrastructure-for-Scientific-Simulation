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

# MARRMoT Knowledge Infrastructure

**Package**: hydrocraft-marrmot v1.0.0
**Model**: MARRMoT v2.1.2 (Modular Assessment of Rainfall-Runoff Models Toolbox)
**Domain**: Conceptual rainfall-runoff hydrology
**Language**: MATLAB / GNU Octave (with Python BMI interface)
**License**: GNU GPL v3
**Created**: 2026-03-25

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/HWSD/SKILL.md` for soil property documentation.
See `data_ki/ObservedQ/SKILL.md` for observed discharge data.


## Overview

MARRMoT is a MATLAB/Octave toolbox containing **47 unique conceptual hydrological
model structures** with standardized parameter ranges and robust numerical solvers.
It enables objective comparison of lumped rainfall-runoff models under identical
numerical and data conditions.

Key characteristics:

- 47 model structures ranging from 1-parameter/1-store to 24-parameter/6-store
- 111 reusable flux functions (evaporation, baseflow, infiltration, percolation, etc.)
- 8 unit hydrograph routing methods (half/full triangle, gamma, uniform, delay)
- Object-oriented architecture: all models inherit from `MARRMoT_model` superclass
- Implicit Euler ODE solver with Newton-Raphson + fallback strategies
- Built-in calibration via CMA-ES optimiser
- Built-in objective functions: KGE, NSE, RMSE, inverse-KGE, log-NSE, etc.
- Python interface via BMI (Basic Model Interface) using oct2py bridge
- Docker support for containerised execution
- All fluxes computed in mm/d; storages in mm

---

## Installation

### Option A: MATLAB (native)

Requires MATLAB R2016b+ (R2021b+ recommended) with Optimization Toolbox.

```bash
git clone https://github.com/wknoben/MARRMoT
# In MATLAB: addpath(genpath('MARRMoT/MARRMoT'))
```

### Option B: GNU Octave

Requires Octave 6.4.0+ with `optim` package.

```bash
apt-get install octave octave-optim
git clone https://github.com/wknoben/MARRMoT
# In Octave: addpath(genpath('MARRMoT/MARRMoT'))
# pkg load optim  % auto-loaded by MARRMoT_model constructor
```

### Option C: Docker (Octave-based)

```bash
docker build -t marrmot .
docker run -v $PWD:/data --entrypoint octave marrmot /data/run_script.m
```

### Option D: Python BMI bridge

```bash
pip install oct2py numpy scipy
# Requires Octave installed on system
```

### Dependencies

| Component     | Required          | Purpose                          |
|---------------|-------------------|----------------------------------|
| MATLAB/Octave | Yes               | Core runtime                     |
| Optim Toolbox | Yes (calibration) | CMA-ES, fsolve, lsqnonlin       |
| oct2py        | Python BMI only   | MATLAB/Octave-Python bridge      |
| numpy/scipy   | Python BMI only   | Numerical support                |
| Docker        | Optional          | Containerised execution          |

### Test installation

```matlab
m = feval('m_01_collie1_1p_1s');
m.theta = 100;
m.input_climate = [ones(365,1)*5, ones(365,1)*2, ones(365,1)*15];
m.delta_t = 1;
m.S0 = 50;
m.get_output();
% Should print water balance summary
```

---

## Pipeline

The MARRMoT workflow converts global hydrometeorological data into
catchment-scale rainfall-runoff simulations using one of 47 model structures.

| # | Stage                  | Tool                       | Description                                           |
|---|------------------------|----------------------------|-------------------------------------------------------|
| 1 | Forcing preparation    | `convert_forcing.py`       | Convert global met data to [P, Ep, T] in mm/d and C   |
| 2 | Parameter setup        | `convert_parameters.py`    | Map soil/land properties to model parameter ranges     |
| 3 | Model selection        | (manual)                   | Choose from 47 model structures                       |
| 4 | Initial conditions     | (manual)                   | Set S0 vector (typically zeros or spin-up)             |
| 5 | Execution              | `run_marrmot.py`           | Run model via Octave subprocess                       |
| 6 | Output parsing         | `parse_output.py`          | Extract Q, Ea, storage to CSV                         |
| 7 | Validation             | `parse_output.py`          | Compute NSE, KGE, PBIAS against observations          |
| 8 | Calibration            | `run_marrmot.py` (loop)    | CMA-ES or Monte Carlo parameter optimisation          |
| 9 | Multi-model comparison | (manual)                   | Compare structures using consistent metrics           |

**Parallelism**: Stages 1-2 can run in parallel. Stages 3-4 are manual decisions.
Stage 5 depends on 1-4. Stages 6-7 depend on 5. Stage 8 is iterative on 5-7.

---

## Unit Trap Table

These are the critical unit conversions that cause **silent failures** if wrong.
Every value enters the model in specific units; no internal conversion is performed.

| Variable            | MARRMoT expects | Common source unit | Conversion                          | Trap ID |
|---------------------|-----------------|--------------------|-------------------------------------|---------|
| Precipitation       | mm/d            | mm/3h (CMFD)       | sum 8 values per day                | dt_001  |
| Precipitation       | mm/d            | kg/m2/s (ERA5)     | x 86400                             | dt_002  |
| Precipitation       | mm/d            | m/d (some GCMs)    | x 1000                              | dt_003  |
| PET                 | mm/d            | W/m2 (net rad)     | Penman-Monteith or Hargreaves       | dt_004  |
| PET                 | mm/d            | mm/month           | / days_in_month                     | dt_005  |
| Temperature         | deg C           | K (ERA5/CMFD)      | - 273.15                            | dt_006  |
| Temperature         | deg C           | deg F              | (F - 32) x 5/9                     | dt_007  |
| Storage (Smax)      | mm              | m                  | x 1000                              | dt_008  |
| Time step (delta_t) | days            | hours              | / 24                                | dt_009  |
| Streamflow (obs)    | mm/d            | m3/s               | x 86400 / (area_km2 x 1e6) x 1000  | dt_010  |

---

## Tools Reference

| Tool                  | Stage       | Script                           | Lines | Purpose                                         |
|-----------------------|-------------|----------------------------------|-------|--------------------------------------------------|
| `convert_forcing`     | s1_forcing  | `tools/convert_forcing.py`       | ~300  | Global met data to MARRMoT climate array         |
| `convert_parameters`  | s2_params   | `tools/convert_parameters.py`    | ~280  | Soil/land data to model parameter vector         |
| `run_marrmot`         | s5_execute  | `tools/run_marrmot.py`           | ~250  | Execute model via Octave subprocess              |
| `parse_output`        | s6_output   | `tools/parse_output.py`          | ~250  | Parse Octave output to CSV with metrics          |

---

## Critical Domain Knowledge

These non-obvious facts cause silent failures. Each is linked to a diagnostic triplet.

1. **dt_001 / dt_002 / dt_003**: Precipitation units must be mm/d. ERA5 provides
   kg/m2/s (multiply by 86400). CMFD provides mm/3h (sum 8 per day). GCMs may
   provide m/d (multiply by 1000). Wrong units produce runoff 1000x too high/low.

2. **dt_004 / dt_005**: PET must be pre-computed externally. MARRMoT does NOT compute
   PET from radiation. Common trap: passing radiation (W/m2) as PET. Use Hargreaves
   or Penman-Monteith to convert. Monthly PET must be divided by days_in_month.

3. **dt_006**: Temperature in Kelvin silently produces wrong snow/rain partitioning
   in models with temperature thresholds (m_06, m_12, m_37, etc.). No error raised.

4. **dt_009**: delta_t must match the actual time step of forcing data. If forcing is
   daily but delta_t=24 (hours), all fluxes are scaled by 24x. Always use delta_t=1
   for daily data.

5. **dt_011**: Input climate array column order is [P, Ep, T], NOT [P, T, Ep].
   Swapping Ep and T is silent and produces nonsensical evaporation.

6. **dt_012**: Initial storage S0 vector length must equal number of stores. Too few
   elements cause MATLAB index error; too many are silently ignored. Check
   `m.numStores` before setting S0.

7. **dt_013**: Newton-Raphson solver may fail silently on stiff problems (high Smax
   with very low initial storage). Increase `resnorm_maxiter` to 12+ or check
   `solverSteps` output for solver fallback warnings.

8. **dt_014**: Water balance check is printed to console but NOT enforced. A water
   balance error > 1 mm indicates numerical problems, but the model does not stop.

9. **dt_015**: Unit hydrograph routing assumes delta_t matches the routing time base.
   Using sub-daily time steps with daily UH parameters shifts the hydrograph peak.

---

## Validation

### Test case: Buffalo River, Tennessee, USA

- **Model**: m_01_collie1_1p_1s (simplest, 1 parameter)
- **Period**: Included in MARRMoT_example_data.mat
- **Source**: BMI test case data

### HyMOD benchmark (m_29_hymod_5p_5s)

- **Parameters**: [Smax=200, b=0.5, a=0.7, kf=0.1, ks=0.01]
- **Typical KGE**: 0.6-0.85 after calibration on daily streamflow
- **Typical NSE**: 0.5-0.80

---

## Calibration Parameters

For HyMOD (m_29), the most commonly used benchmark model:

| Parameter | Symbol | Range       | Unit  | Sensitivity | Description                    |
|-----------|--------|-------------|-------|-------------|--------------------------------|
| Smax      | S_max  | [1, 2000]   | mm    | High        | Maximum soil moisture storage  |
| b         | b      | [0, 10]     | -     | Medium      | Distribution function shape    |
| a         | alpha  | [0, 1]      | -     | High        | Flow split fast/slow           |
| kf        | k_f    | [0, 1]      | 1/d   | Medium      | Fast reservoir rate constant   |
| ks        | k_s    | [0, 1]      | 1/d   | Low         | Slow reservoir rate constant   |

For other models, parameter ranges are defined in each model file's `parRanges`
property. Run `m = feval('m_XX_name'); m.parRanges` to retrieve bounds.

---

## Coupling Points

| Source              | Target           | Variable     | Unit    | Notes                          |
|---------------------|------------------|--------------|---------|--------------------------------|
| ERA5/CMFD/MSWX      | MARRMoT forcing  | Precip       | mm/d    | Aggregated to daily            |
| Hargreaves/PM        | MARRMoT forcing  | PET          | mm/d    | Pre-computed externally        |
| ERA5/CMFD            | MARRMoT forcing  | Temperature  | deg C   | Mean daily                     |
| MARRMoT output Q     | Routing model    | Streamflow   | mm/d    | Convert to m3/s for routing    |
| Observed discharge   | Validation       | Streamflow   | mm/d    | Convert from m3/s using area   |
| HWSD/SoilGrids       | Parameters       | Soil props   | various | Map to Smax, percolation rates |

---

## Data Requirements

| Data Type            | Source            | Status    | Path / Notes                             |
|----------------------|-------------------|-----------|------------------------------------------|
| Precipitation        | ERA5 / CMFD       | Required  | Must convert to mm/d                     |
| Temperature          | ERA5 / CMFD       | Required  | Must convert to deg C                    |
| PET                  | Pre-computed      | Required  | Hargreaves from Tmin/Tmax or PM          |
| Observed streamflow  | GRDC / local      | Optional  | For calibration/validation, convert mm/d |
| Catchment area       | Shapefile / known | Optional  | For m3/s <-> mm/d conversion             |
| Soil properties      | HWSD / SoilGrids  | Optional  | For parameter estimation                 |

---

## Quick Start

```bash
# 1. Prepare forcing
python tools/convert_forcing.py \
  --input /path/to/era5_daily.nc \
  --output forcing.csv \
  --lat 35.5 --lon 117.3 \
  --start 2000-01-01 --end 2010-12-31

# 2. Estimate parameters from soil data
python tools/convert_parameters.py \
  --model m_29_hymod_5p_5s \
  --soil-data /path/to/hwsd.csv \
  --output params.json

# 3. Run model
python tools/run_marrmot.py \
  --forcing forcing.csv \
  --model m_29_hymod_5p_5s \
  --params params.json \
  --output run_output.json

# 4. Parse and validate output
python tools/parse_output.py \
  --input run_output.json \
  --observed /path/to/observed_q.csv \
  --output results.csv \
  --figure validation.png
```

---

## Diagnostic Triplets Summary

| ID     | Stage      | Failure Domain    | Severity | Symptom (short)                           |
|--------|------------|-------------------|----------|-------------------------------------------|
| dt_001 | s1_forcing | unit_conversion   | silent   | Precip 1000x too high (mm/3h not mm/d)    |
| dt_002 | s1_forcing | unit_conversion   | silent   | Precip wrong from kg/m2/s                  |
| dt_003 | s1_forcing | unit_conversion   | silent   | Precip wrong from m/d                      |
| dt_004 | s1_forcing | unit_conversion   | silent   | PET given as radiation W/m2                |
| dt_005 | s1_forcing | unit_conversion   | silent   | Monthly PET not divided by days            |
| dt_006 | s1_forcing | unit_conversion   | silent   | Temperature in K not C                     |
| dt_007 | s1_forcing | unit_conversion   | silent   | Temperature in F not C                     |
| dt_008 | s2_params  | unit_conversion   | silent   | Storage parameter in m not mm              |
| dt_009 | s5_execute | parameter_format  | degraded | delta_t mismatch (hours vs days)           |
| dt_010 | s6_output  | unit_conversion   | silent   | Observed Q in m3/s not mm/d               |
| dt_011 | s1_forcing | parameter_format  | silent   | Climate columns swapped [P,T,Ep]           |
| dt_012 | s5_execute | parameter_format  | fatal    | S0 length != numStores                     |
| dt_013 | s5_execute | runtime           | degraded | Solver fails on stiff ODE                  |
| dt_014 | s5_execute | silent_error      | silent   | Water balance error not enforced            |
| dt_015 | s5_execute | parameter_format  | degraded | UH time base vs delta_t mismatch           |

---

## File Structure

```
ki/
  SKILL.md                           # This file (agent entry point)
  tools/
    convert_forcing.py               # Stage 1: Global met -> MARRMoT climate
    convert_parameters.py            # Stage 2: Soil data -> parameter vector
    run_marrmot.py                   # Stage 5: Execute model via Octave
    parse_output.py                  # Stage 6: Parse output + compute metrics
  docs/
    s1_forcing_preparation.md        # Forcing data conversion skill
    s2_parameter_estimation.md       # Parameter mapping skill
    s3_model_selection.md            # Model selection guide
    s5_execution.md                  # Model execution skill
    s6_output_analysis.md            # Output parsing and validation skill
  diagnostics/
    triplets.yaml                    # 15+ diagnostic triplets
```

---

## All 47 Model Structures

| ID  | Name                    | Params | Stores | Based on              |
|-----|-------------------------|--------|--------|-----------------------|
| m_01 | collie1                | 1      | 1      | Collie River 1       |
| m_02 | wetland                | 1      | 1      | Wetland model         |
| m_03 | collie2                | 2      | 1      | Collie River 2       |
| m_04 | newzealand1            | 1      | 1      | New Zealand           |
| m_05 | ihacres                | 7      | 2      | IHACRES               |
| m_06 | alpine1                | 2      | 2      | Alpine model          |
| m_07 | gr4j                   | 4      | 2      | GR4J                  |
| m_08 | us1                    | 2      | 2      | US model 1            |
| m_09 | susannah1              | 6      | 2      | Susannah Brook 1      |
| m_10 | susannah2              | 6      | 2      | Susannah Brook 2      |
| m_11 | collie3                | 2      | 2      | Collie River 3       |
| m_12 | alpine2                | 6      | 2      | Alpine model 2        |
| m_13 | hillslope              | 7      | 2      | Hillslope model       |
| m_14 | topmodel               | 7      | 2      | TOPMODEL              |
| m_15 | plateau                | 5      | 2      | Plateau model         |
| m_16 | newzealand2            | 1      | 2      | New Zealand 2         |
| m_17 | penman                 | 4      | 2      | Penman model          |
| m_18 | simhyd                 | 7      | 3      | SIMHYD                |
| m_19 | australia              | 8      | 3      | Australia model       |
| m_20 | gsfb                   | 3      | 2      | GSFB                  |
| m_21 | flexb                  | 9      | 4      | FLEX-B                |
| m_22 | vic                    | 10     | 5      | VIC                   |
| m_23 | lascam                 | 11     | 3      | LASCAM                |
| m_24 | mopex1                 | 7      | 3      | MOPEX 1               |
| m_25 | tcm                    | 6      | 4      | TCM                   |
| m_26 | flexis                 | 12     | 6      | FLEX-IS               |
| m_27 | tank                   | 8      | 4      | TANK (Sugawara)       |
| m_28 | xinanjiang             | 12     | 4      | Xinanjiang            |
| m_29 | hymod                  | 5      | 5      | HyMOD                 |
| m_30 | mopex2                 | 5      | 3      | MOPEX 2               |
| m_31 | mopex3                 | 6      | 4      | MOPEX 3               |
| m_32 | mopex4                 | 5      | 3      | MOPEX 4               |
| m_33 | sacramento             | 11     | 5      | Sacramento            |
| m_34 | flexis2                | 16     | 6      | FLEX-IS 2             |
| m_35 | mopex5                 | 12     | 5      | MOPEX 5               |
| m_36 | modhydrolog            | 15     | 5      | MODHYDROLOG           |
| m_37 | hbv96                  | 15     | 5      | HBV-96                |
| m_38 | tank2                  | 17     | 6      | TANK 2                |
| m_39 | mcrm                   | 16     | 5      | MCRM                  |
| m_40 | smar                   | 8      | 6      | SMAR                  |
| m_41 | nam                    | 10     | 6      | NAM                   |
| m_42 | hycymodel              | 12     | 6      | HYCYMODEL             |
| m_43 | gsmsocont              | 8      | 3      | GSM-SOCONT            |
| m_44 | echo                   | 16     | 6      | ECHO                  |
| m_45 | prms                   | 18     | 6      | PRMS                  |
| m_46 | classic                | 20     | 5      | CLASSIC               |
| m_47 | ihm19                  | 24     | 4      | IHM19                 |
