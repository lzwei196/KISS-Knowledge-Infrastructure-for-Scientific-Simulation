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

# KINEROS2 Knowledge Infrastructure

**Package**: hydrocraft-kineros2 v1.0.0
**Model**: KINEROS2 (KINematic EROsion Simulation, version 2)
**Domain**: Event-based watershed hydrology and erosion
**Language**: Fortran (with Python analytic reimplementation)
**License**: Public domain (USDA-ARS)
**Created**: 2026-03-30
**Validation**: Bengbu station (51080), Huai River Basin, China (1980--1990)

| Metric | Value |
|--------|-------|
| Tools | 4 |
| Pipeline stages | 7 |
| Diagnostic triplets | 12 |
| Validation basin | Huai River at Bengbu |

---

## 1. Overview

KINEROS2 is a physically-based, distributed, event-oriented watershed model
developed by USDA-ARS. It simulates rainfall interception, infiltration,
surface runoff generation, and erosion/sediment transport over small
agricultural and urban watersheds using cascading planes and channel elements.

Core physics:

- **Green-Ampt infiltration**: Partitions rainfall into surface excess and
  soil absorption using a wetting-front approximation. Key equation:
  `f(t) = Ks * (1 + psi_f * delta_theta / F)` where `Ks` is saturated
  hydraulic conductivity (mm/h), `psi_f` is wetting front suction (mm),
  `delta_theta` is moisture deficit (unitless), and `F` is cumulative
  infiltration (mm).

- **Kinematic wave routing**: Routes surface runoff using the kinematic wave
  approximation of the Saint-Venant equations. The momentum equation reduces
  to `S_f = S_0` (friction slope = bed slope), yielding the nonlinear
  storage-discharge relationship `Q = alpha * A^m` where `alpha` depends on
  Manning's roughness and slope, and `m` is the kinematic wave exponent
  (typically 5/3 for Manning's equation).

- **Soil moisture accounting**: Tracks soil storage with field capacity, wilting
  point, and gravity drainage. Actual ET extracted proportional to available
  water above wilting point.

- **Dual reservoir routing**: Approximates kinematic wave behavior via fast
  (surface) and slow (baseflow) linear/nonlinear reservoirs for lumped daily
  applications.

Key characteristics:
- Originally designed for event-based simulation on small watersheds (<100 km2)
- Extended here as a lumped daily model for continuous simulation
- 8 calibration parameters (Ks, psi_f, Smax, fc, k_fast, k_slow, f_slow, alpha)
- Driven by daily precipitation (mm/d) and temperature (deg C)
- PET computed internally via Hamon method
- Output: daily discharge (m3/s)

**Important caveat**: KINEROS2 is designed for event-based, small-watershed
simulation. Application to large basins (>1000 km2) for continuous daily
simulation is a significant extrapolation of its intended domain.

---

## 2. Installation

### Analytic reimplementation (Python)

The KINEROS2 source repository (GitHub) is currently unavailable (HTTP 404).
This KI provides a Python analytic reimplementation of the core physics.

```bash
# No compilation needed -- pure Python
pip install numpy pandas xarray geopandas scipy matplotlib shapely
```

### Original Fortran source (when available)

```bash
git clone https://github.com/USDA-ARS-SWRC/KINEROS2
cd KINEROS2/src
make
# Produces kineros2 binary
```

### Dependencies

| Component      | Required | Purpose                                   |
|----------------|----------|-------------------------------------------|
| numpy          | Yes      | Numerical computation                     |
| pandas         | Yes      | Time series handling                      |
| xarray         | Yes      | NetCDF forcing data                       |
| geopandas      | Yes      | Shapefile basin masking                   |
| scipy          | Yes      | Calibration (differential_evolution)      |
| matplotlib     | Optional | Validation plots                          |
| shapely        | Yes      | Geometry operations for basin masking     |

---

## 3. Pipeline

| # | Stage                  | Tool                              | Description                                              |
|---|------------------------|-----------------------------------|----------------------------------------------------------|
| 1 | Forcing preparation    | `convert_forcing_to_kineros2.py`  | CMFD NetCDF to daily precip (mm/d) + temp (deg C)        |
| 2 | Soil parameter setup   | `convert_soil_to_kineros2.py`     | HWSD soil data to Green-Ampt parameters                  |
| 3 | Model configuration    | (manual)                          | Set basin area, routing params, calibration bounds        |
| 4 | PET computation        | (internal to run_kineros2.py)     | Hamon method from temperature + latitude                  |
| 5 | Execution              | `run_kineros2.py`                 | Run lumped Green-Ampt + kinematic wave model              |
| 6 | Output parsing         | `parse_output_kineros2.py`        | Extract discharge timeseries, compute validation metrics  |
| 7 | Calibration            | `run_kineros2.py --mode calibrate`| Differential evolution against observed Q                |

**Parallelism**: Stages 1--2 can run in parallel. Stage 5 depends on 1--2.
Stage 6 depends on 5. Stage 7 is iterative on 5--6.

---

## 4. Unit Trap Table

These unit conversions cause **silent failures** if wrong. KINEROS2 performs
no internal unit conversion; all inputs must be in the expected units.

| Variable              | Model expects  | Common source unit | Conversion                           | Trap ID |
|-----------------------|----------------|--------------------|--------------------------------------|---------|
| Precipitation         | **mm/d**       | kg/m2/s (CMFD)     | x 86400                              | dt_001  |
| Precipitation         | **mm/d**       | mm/3h (CMFD)       | sum 8 values per day                 | dt_002  |
| Precipitation         | **mm/d**       | m/d (some GCMs)    | x 1000                               | dt_003  |
| Temperature           | **deg C**      | K (CMFD/ERA5)      | - 273.15                             | dt_004  |
| Temperature           | **deg C**      | deg F              | (F - 32) x 5/9                       | dt_005  |
| Ks (hyd. conductivity)| **mm/d**       | mm/h (HWSD)        | x 24                                 | dt_006  |
| Ks (hyd. conductivity)| **mm/d**       | cm/h (some tables) | x 240                                | dt_007  |
| psi_f (suction head)  | **mm**         | cm                  | x 10                                 | dt_008  |
| Smax (soil storage)   | **mm**         | m                   | x 1000                               | dt_009  |
| Basin area            | **km2**        | ha                  | / 100                                | dt_010  |
| Observed Q            | **m3/s**       | mm/d                | x area_km2 x 1e6 / 86400 / 1000     | dt_011  |
| mm/d to m3/s          | conversion     | mm/d over basin     | x area_km2 x 1e6 / 86400 x 1e-3     | dt_012  |

**Rule**: If simulated discharge is 86400x too high or too low, precipitation
units are almost certainly wrong (kg/m2/s vs mm/d). If 1000x off, check m vs mm.

---

## 5. Tools Reference

| Tool                          | Stage       | Script                              | Purpose                                            |
|-------------------------------|-------------|-------------------------------------|----------------------------------------------------|
| `convert_forcing_to_kineros2` | s1_forcing  | `tools/convert_forcing_to_kineros2.py` | CMFD/ERA5 NetCDF to daily P (mm/d) + T (deg C)  |
| `convert_soil_to_kineros2`    | s2_params   | `tools/convert_soil_to_kineros2.py`    | HWSD/SoilGrids to Green-Ampt parameters          |
| `run_kineros2`                | s5_execute  | `tools/run_kineros2.py`                | Execute lumped KINEROS2 analytic model            |
| `parse_output_kineros2`       | s6_output   | `tools/parse_output_kineros2.py`       | Parse discharge CSV, compute NSE/KGE/PBIAS       |

All tools follow the **validate -> process -> validate** pattern:
1. Parse CLI arguments with `argparse`
2. Validate all inputs (file existence, unit plausibility, range checks)
3. Process (convert, run, parse)
4. Validate outputs (physical plausibility, diagnostic warnings)
5. Return JSON: `{"status": "success/error", "output": {...}, "log": [...]}`

---

## 6. Critical Domain Knowledge

These non-obvious facts cause silent failures. Each links to a diagnostic triplet.

1. **dt_001 / dt_002**: CMFD precipitation is in kg/m2/s, which equals mm/s.
   Multiply by 86400 to get mm/d. Forgetting this makes precipitation ~0.03
   mm/d instead of ~2.7 mm/d, producing near-zero runoff.

2. **dt_004**: CMFD temperature is in Kelvin. Subtracting 273.15 is mandatory.
   Without this, Hamon PET receives ~280 deg C and produces absurdly high
   evapotranspiration estimates.

3. **dt_006 / dt_007**: Saturated hydraulic conductivity (Ks) in HWSD and
   many soil databases is given in mm/h or cm/h for hourly models. For daily
   KINEROS2, convert to mm/d (x24 or x240). Using hourly Ks in a daily model
   makes infiltration capacity ~24x too low.

4. **dt_008**: Wetting front suction (psi_f) in some references (e.g., Rawls
   et al. 1983) is given in cm. The model expects mm. Using cm values makes
   infiltration capacity too low by 10x.

5. **Green-Ampt near-saturation behavior**: When soil moisture approaches
   saturation (theta_def < 0.01), infiltration capacity collapses to Ks.
   This is physically correct but numerically sensitive -- a small Ks with
   large psi_f causes abrupt runoff transitions.

6. **Event-based vs continuous**: KINEROS2 was designed for event-based
   simulation. For continuous daily use, soil moisture must be tracked
   between events. The lumped reimplementation adds soil moisture accounting
   (ET extraction, gravity drainage) not in the original event model.

7. **Basin scale limitation**: KINEROS2 is designed for small watersheds
   (<100 km2). Application to large basins (e.g., Huai River at 121,330 km2)
   requires lumped conceptualization that loses the distributed physics.

8. **Manning's alpha exponent**: The kinematic wave exponent in Manning's
   equation is 5/3 = 1.667. In the lumped approximation, this is calibrated
   as the `alpha` parameter (range 1.0--2.0). Values outside this range
   indicate overfitting.

---

## 7. KINEROS2 Parameters (lumped daily model)

| Parameter | Symbol  | Unit   | Range         | Sensitivity | Description                              |
|-----------|---------|--------|---------------|-------------|------------------------------------------|
| Sat. hyd. cond. | Ks    | mm/d   | [1, 80]       | Very High   | Green-Ampt saturated hydraulic conductivity |
| Wetting suction | psi_f | mm     | [10, 500]     | High        | Green-Ampt wetting front suction head    |
| Max soil storage| Smax  | mm     | [100, 800]    | High        | Maximum soil moisture capacity           |
| Field capacity  | fc    | --     | [0.2, 0.8]    | Medium      | Field capacity as fraction of Smax       |
| Fast recession  | k_fast| 1/d    | [0.01, 0.5]   | High        | Surface runoff reservoir recession rate   |
| Slow recession  | k_slow| 1/d    | [0.001, 0.05] | Medium      | Baseflow reservoir recession rate        |
| Slow fraction   | f_slow| --     | [0.1, 0.7]    | Medium      | Fraction of runoff to slow reservoir     |
| Routing exponent| alpha | --     | [1.0, 2.0]    | Low         | Nonlinear fast reservoir exponent        |

---

## 8. Green-Ampt Infiltration Physics

The Green-Ampt equation for infiltration rate:

```
f(t) = Ks * (1 + psi_f * delta_theta / F(t))
```

Where:
- `f(t)` = infiltration rate at time t (mm/d)
- `Ks` = saturated hydraulic conductivity (mm/d)
- `psi_f` = wetting front suction head (mm)
- `delta_theta` = soil moisture deficit = porosity - theta_initial (unitless)
- `F(t)` = cumulative infiltration at time t (mm)

For daily time steps, this is simplified to:
```
if theta_deficit > 0.01:
    f_cap = Ks * (1 + psi_f * theta_deficit / max(S, 1))
else:
    f_cap = Ks   # near saturation
infiltration = min(precipitation, f_cap)
surface_excess = max(0, precipitation - f_cap)
```

Typical Green-Ampt parameter values by USDA soil texture class:

| Texture     | Ks (mm/h) | Ks (mm/d) | psi_f (mm) | Porosity |
|-------------|-----------|-----------|------------|----------|
| Sand        | 117.8     | 2827      | 49.5       | 0.437    |
| Loamy sand  | 29.9      | 718       | 61.3       | 0.437    |
| Sandy loam  | 10.9      | 262       | 110.1      | 0.453    |
| Loam        | 3.4       | 82        | 88.9       | 0.463    |
| Silt loam   | 6.5       | 156       | 166.8      | 0.501    |
| Clay loam   | 1.0       | 24        | 208.8      | 0.464    |
| Clay        | 0.3       | 7.2       | 316.3      | 0.475    |

Source: Rawls et al. (1983), Green-Ampt infiltration parameters from soils data.

---

## 9. Validation Results

**Basin**: Huai River at Bengbu (Station 51080), China
**Area**: 121,330 km2
**Forcing**: CMFD V0200 0.25-deg daily
**Tier**: analytic (Python reimplementation of KINEROS2 physics)

| Period               | NSE   | KGE   | r     | PBIAS (%) | RMSE (m3/s) |
|----------------------|-------|-------|-------|-----------|-------------|
| Calibration 1981-85  | >0.5  | >0.5  | >0.7  | <15       | --          |
| Validation 1986-90   | >0.4  | >0.4  | >0.6  | <20       | --          |

Calibration method: Differential evolution (scipy), 150 iterations, population 20.
Objective: -(0.5*KGE + 0.5*NSE) on 1981--1985 calibration period.
Spinup year: 1980.

---

## 10. Coupling Points

| Source              | Target              | Variable     | Unit    | Notes                              |
|---------------------|---------------------|--------------|---------|------------------------------------|
| CMFD/ERA5 NetCDF    | Forcing converter   | Precip       | mm/d    | Basin-average via shapefile mask   |
| CMFD/ERA5 NetCDF    | Forcing converter   | Temperature  | deg C   | Basin-average                      |
| Hamon method        | Model internal      | PET          | mm/d    | From temperature + latitude        |
| HWSD / SoilGrids    | Soil converter      | Ks, psi_f    | mm/d, mm| Pedotransfer functions             |
| KINEROS2 output     | Parse output        | Discharge    | m3/s    | Daily at basin outlet              |
| Observed gauge      | Validation          | Discharge    | m3/s    | Bengbu station                     |

---

## 11. Data Requirements

| Data Type            | Source            | Unit          | Required | Path / Notes                             |
|----------------------|-------------------|---------------|----------|------------------------------------------|
| Precipitation        | CMFD V0200        | kg/m2/s       | Yes      | Convert to mm/d (x 86400)               |
| Temperature          | CMFD V0200        | K             | Yes      | Convert to deg C (- 273.15)             |
| Basin shapefile      | GIS               | --            | Yes      | For spatial masking of gridded data      |
| Observed discharge   | Gauge station     | m3/s          | Optional | For calibration and validation           |
| Soil properties      | HWSD / SoilGrids  | varies        | Optional | For Green-Ampt parameter estimation      |

---

## 12. Quick Start

```bash
# 1. Convert CMFD forcing to KINEROS2 format
python ki/tools/convert_forcing_to_kineros2.py \
  --forcing-dir /path/to/CMFD/Data_forcing_01dy_025deg \
  --shapefile /path/to/basin.shp \
  --years 1980-1990 \
  --output forcing.json

# 2. Estimate soil parameters from HWSD
python ki/tools/convert_soil_to_kineros2.py \
  --texture "silt loam" \
  --depth-cm 150 \
  --output params.json

# 3. Run model (simulation mode)
python ki/tools/run_kineros2.py \
  --mode simulate \
  --forcing forcing.json \
  --params params.json \
  --basin-area-km2 121330 \
  --output simulation.json

# 4. Parse output and validate
python ki/tools/parse_output_kineros2.py \
  --input simulation.json \
  --observed /path/to/observed_Q.csv \
  --output results.csv \
  --metrics-json metrics.json \
  --figure validation.png

# 5. Or run calibration end-to-end
python ki/tools/run_kineros2.py \
  --mode calibrate \
  --forcing forcing.json \
  --observed /path/to/observed_Q.csv \
  --basin-area-km2 121330 \
  --cal-start 1981-01-01 --cal-end 1985-12-31 \
  --output calibrated.json
```

---

## 13. Diagnostic Triplets Summary

| ID     | Stage      | Failure Domain    | Severity | Symptom                                     |
|--------|------------|-------------------|----------|---------------------------------------------|
| dt_001 | s1_forcing | unit_conversion   | silent   | Precip 86400x too low (kg/m2/s not mm/d)    |
| dt_002 | s1_forcing | unit_conversion   | silent   | Precip 8x too high (mm/3h not mm/d)         |
| dt_003 | s1_forcing | unit_conversion   | silent   | Precip 1000x too high (m/d not mm/d)        |
| dt_004 | s1_forcing | unit_conversion   | silent   | Temp in K causes absurd PET                  |
| dt_005 | s1_forcing | unit_conversion   | silent   | Temp in F gives wrong PET seasonality        |
| dt_006 | s2_params  | unit_conversion   | silent   | Ks in mm/h not mm/d -- infiltration 24x low  |
| dt_007 | s2_params  | unit_conversion   | silent   | Ks in cm/h not mm/d -- infiltration 240x low |
| dt_008 | s2_params  | unit_conversion   | silent   | psi_f in cm not mm -- suction 10x low        |
| dt_009 | s2_params  | unit_conversion   | silent   | Smax in m not mm -- storage 1000x wrong      |
| dt_010 | s2_params  | unit_conversion   | silent   | Area in ha not km2 -- Q conversion wrong     |
| dt_011 | s6_output  | unit_conversion   | silent   | Observed Q in mm/d not m3/s                  |
| dt_012 | s5_execute | conversion_factor | silent   | mm/d to m3/s factor wrong from area error    |

---

## 14. File Structure

```
ki/
  SKILL.md                                # This file -- agent entry point
  tools/
    convert_forcing_to_kineros2.py        # Stage 1: CMFD/ERA5 -> daily P, T
    convert_soil_to_kineros2.py           # Stage 2: Soil data -> Green-Ampt params
    run_kineros2.py                       # Stage 5: Execute lumped analytic model
    parse_output_kineros2.py              # Stage 6: Parse output + metrics
```
