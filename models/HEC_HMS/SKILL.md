---
name: hec-hms
description: >-
  HEC-HMS public-domain rainfall-runoff method set (USACE HEC; SCS Curve Number loss, SCS
  dimensionless Unit Hydrograph transform, Muskingum channel…. Covers Precipitation-loss /
  runoff-volume computation (SCS Curve Number); Direct-runoff transform of excess rainfall
  to a hydrograph (SCS dimensionless Unit Hydrograph); Conceptual baseflow generation
  (Linear Reservoir recession store). Use when the task involves running, configuring,
  calibrating or interpreting HEC_HMS.
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

# HEC-HMS (Hydrologic Engineering Center — Hydrologic Modeling System) — Knowledge Infrastructure

**Package**: `hydrocraft-hec-hms` v1.0.0
**Model**: HEC-HMS 4.12 (USACE Hydrologic Engineering Center)
**Created by**: Jianyun Zhang Research Group, Hohai University
**Last updated**: 2026-03-28
**Stats**: 6 tools | 7 skill documents | 18 diagnostic triplets | ~2,800 lines of validated Python
**Validation status**: `production_validated` (Bengbu, Huai River, 1981-1990)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/HWSD/SKILL.md` for soil property documentation.
See `data_ki/ObservedQ/SKILL.md` for observed discharge data.


## Overview

This knowledge infrastructure enables autonomous rainfall-runoff simulation using HEC-HMS methodology on any gauged basin, **without the proprietary HEC-HMS GUI**. The 6 validated Python tools implement the core HEC-HMS algorithms (SCS-CN loss, SCS Unit Hydrograph transform, Muskingum routing, linear reservoir baseflow) and integrate with HydroCraft's forcing, soil, and observation infrastructure.

**What HEC-HMS does**: Event-based and continuous rainfall-runoff simulation. Computes:
- Precipitation losses (infiltration) via SCS Curve Number, Green-Ampt, or Initial+Constant
- Direct runoff transform via SCS Unit Hydrograph, Clark UH, Snyder UH, or ModClark
- Channel routing via Muskingum, Muskingum-Cunge, Modified Puls, or Lag
- Baseflow via Linear Reservoir, Recession, or Constant Monthly
- Snowmelt via Temperature Index or Energy Budget
- Evapotranspiration via Monthly Average, Priestley-Taylor, or Gridded
- Reservoir routing via specified release, elevation-storage-discharge

**Key difference from other HydroCraft models**: HEC-HMS is a lumped/semi-distributed event or continuous model. Unlike VIC (gridded, physically-based) or SWAT (HRU-based), HEC-HMS operates on subbasins connected by channel reaches. Each subbasin is treated as a lumped unit. The model is excellent for flood forecasting and design storm analysis but does not resolve spatial variability within subbasins.

---

## Installation

### Proprietary Binary (if available)

```
HEC-HMS 4.12:   <install_dir>/HEC-HMS/hec-hms.sh
Platform:        Linux x86-64 (Java 11+ required)
Source:          https://www.hec.usace.army.mil/software/hec-hms/
License:         US Government Public Domain (binary distribution)
CLI execution:   hec-hms.sh -script compute.py
```

### Python Implementation (HydroCraft)

```
Tools:           ki/tools/*.py
Dependencies:    numpy, pandas, xarray, netCDF4, geopandas, shapely, matplotlib, scipy
Python:          3.10+
```

HEC-HMS is proprietary Java software. The HydroCraft implementation provides equivalent
algorithms in Python for integration with the HydroCraft forcing/observation pipeline.
Core algorithms (SCS-CN, SCS UH, Muskingum) are public domain USDA/USACE methods.

### Test example

```
python3 ki/tools/run_hec_hms.py \
  --basin_shp /path/to/basin.shp \
  --forcing_dir /path/to/forcing/ \
  --soil_file /path/to/soil.img \
  --landcover_file /path/to/landcover.tif \
  --start_date 1980-01-01 --end_date 1990-12-31 \
  --output_dir /path/to/output/
```

---

## Pipeline

| # | Stage | Tool | Parallel | Notes |
|---|-------|------|----------|-------|
| 0 | Configuration | — | — | Set basin, period, resolution, paths |
| 1 | Domain Setup | — | — | Define subbasin(s) from DEM + shapefile |
| 2 | Soil Parameters | `convert_soil_to_hms.py` | Yes | HWSD → SCS CN, Soil Group, Green-Ampt params |
| 3 | Land Cover | `convert_soil_to_hms.py` | Yes | AVHRR → CN adjustment by land use |
| 4 | Forcing Conversion | `convert_forcing_to_hms.py` | Yes | CMFD/MSWX → HEC-HMS precipitation + PET |
| 5 | Model Parameters | — | — | Set loss, transform, routing, baseflow methods |
| 6 | Model Execution | `run_hec_hms.py` | No | Run SCS-CN + SCS UH + Muskingum + baseflow |
| 7 | Output Parsing | `parse_hms_output.py` | No | Extract discharge time series to CSV |
| 8 | Routing (optional) | — | — | Channel routing already integrated in run |

---

## Tools Reference

| # | Tool | Stage | Lines | Purpose |
|---|------|-------|-------|---------|
| 1 | `convert_forcing_to_hms.py` | s4 | ~450 | CMFD/MSWX NetCDF → daily precip (mm) + PET (mm) |
| 2 | `convert_soil_to_hms.py` | s2-s3 | ~350 | HWSD + AVHRR → SCS Curve Number + soil properties |
| 3 | `run_hec_hms.py` | s6 | ~600 | Execute SCS-CN + SCS UH + Muskingum + baseflow |
| 4 | `parse_hms_output.py` | s7 | ~250 | Parse output CSV → standardized discharge CSV |
| 5 | `validate_hms.py` | s7 | ~350 | Compare simulated vs observed Q, compute metrics |
| 6 | `calibrate_hms.py` | s5 | ~400 | Automated CN + baseflow calibration (GLUE-style) |

---

## Skill Knowledge

| # | Document | Stage | Knowledge Type |
|---|----------|-------|----------------|
| 1 | `s0_configuration_skill.md` | s0 | procedural |
| 2 | `s1_domain_setup_skill.md` | s1 | procedural |
| 3 | `s2_soil_parameters_skill.md` | s2-s3 | evaluative |
| 4 | `s4_forcing_conversion_skill.md` | s4 | evaluative |
| 5 | `s5_model_execution_skill.md` | s5-s6 | procedural |
| 6 | `s6_output_analysis_skill.md` | s7 | evaluative |
| 7 | `s7_calibration_skill.md` | s5 | evaluative |

---

## Critical Domain Knowledge

These are non-obvious facts that cause silent failures. Each is indexed as `dt_NNN` and cross-referenced in the diagnostic triplets.

### dt_101: Precipitation units — CMFD mm/day vs HEC-HMS mm or mm/hr

**CRITICAL**. CMFD provides precipitation in mm/day. HEC-HMS internal calculations
use mm for event mode or mm/hr for continuous mode. If running at daily timestep,
total precipitation per timestep is the daily value directly (mm). If running at
sub-daily timestep (e.g., hourly), divide by 24: `P_hr = P_day / 24`.

**Trap**: If you pass mm/day values to a sub-daily model step without dividing by the
number of timesteps per day, total volume will be N_timesteps × too large.

### dt_102: Temperature units — CMFD Kelvin vs HEC-HMS Celsius

**CRITICAL**. CMFD temperature is in Kelvin. HEC-HMS (and the SCS methods) expect
Celsius for snowmelt and PET calculations. Always subtract 273.15.

**Trap**: Passing Kelvin to Hargreaves PET yields wildly wrong evapotranspiration.

### dt_103: Curve Number must be 30-100 range

SCS Curve Number valid range is 30-100. Values below 30 indicate unrealistic zero
runoff. Values above 98 indicate impervious surface. CN=100 means all precipitation
becomes runoff (no loss).

**Trap**: If soil group lookup returns 0 or NaN, the CN calculation produces zero
runoff — the hydrograph is flat.

### dt_104: SCS Initial Abstraction ratio — 0.2 vs 0.05

The classic SCS-CN method uses Ia = 0.2 * S. Recent USDA research (Woodward et al. 2003)
recommends Ia = 0.05 * S for better fit. HEC-HMS 4.x allows configuring this ratio.

**Trap**: Using 0.2 in wet climates significantly underestimates runoff for small storms.
Using 0.05 in arid regions may overestimate runoff.

### dt_105: Unit Hydrograph peak time — Tc vs Tp

SCS UH uses time to peak Tp = 0.6 * Tc + D/2 where Tc is time of concentration
and D is the computational interval. If D is too large relative to Tp, the UH
is poorly defined.

**Trap**: Setting D > 0.29 * Tp causes the discrete UH to miss the peak. Rule of
thumb: D <= Tp/5.

### dt_106: Muskingum K and X constraints

Muskingum routing requires: 0 <= X <= 0.5 (typically 0.0-0.3) and K > 0.
Additionally, the Courant condition requires: 2KX <= dt <= 2K(1-X).

**Trap**: X > 0.5 causes negative routing coefficients → negative flows.
K too small relative to dt causes numerical instability.

### dt_107: Baseflow recession constant — Ratio vs Rate

HEC-HMS linear reservoir baseflow uses a recession constant (ratio, dimensionless,
0 < k < 1). This is NOT a rate constant. Values close to 1.0 mean slow recession
(persistent baseflow). Values close to 0.0 mean fast recession.

**Trap**: Confusing recession ratio with hydraulic conductivity (which has units) gives
completely wrong baseflow magnitudes.

### dt_108: Basin area units — km² vs m² vs acres

HEC-HMS project files can use different unit systems (SI metric, US customary).
When converting runoff depth (mm) to discharge (m³/s):
`Q = runoff_mm * area_km2 * 1000 / (dt_seconds)`

**Trap**: Using area in m² instead of km² gives 10^6 too large discharge.
Using area in acres without conversion gives wrong results entirely.

### dt_109: DSS file time conventions — midnight issues

HEC-DSS stores time as 2400 for midnight, not 0000 of the next day. When converting
to pandas datetime, 2400 must map to 00:00 of the next day.

**Trap**: Off-by-one-day errors in the entire time series if midnight convention is wrong.

---

## Validation

### Bengbu Basin, Huai River (Station 51080)

| Item | Value |
|------|-------|
| Basin | Bengbu, Huai River, China |
| Station | 51080 (drainage area ~121,330 km²) |
| Period | 1981-1990 (1980 spinup) |
| Forcing | CMFD 0.25° daily (precip, temp) |
| Soil | HWSD → SCS soil groups → Curve Number |
| Land cover | AVHRR 1km → CN adjustment |
| Loss method | SCS Curve Number (Ia = 0.05S) |
| Transform | SCS Unit Hydrograph |
| Baseflow | Linear Reservoir (recession) |

---

## Calibration Parameters

| Parameter | Range | Default | Sensitivity | Notes |
|-----------|-------|---------|-------------|-------|
| CN (Curve Number) | 30-100 | From HWSD+AVHRR | **Highest** | Controls total runoff volume |
| Ia ratio | 0.05-0.20 | 0.05 | High | Initial abstraction / S |
| Tp (time to peak) | 1-720 hr | From Tc | High | Controls peak timing |
| K (Muskingum K) | 0.5-240 hr | From reach length | Medium | Routing delay |
| X (Muskingum X) | 0.0-0.5 | 0.2 | Low | Routing attenuation |
| k_base (recession) | 0.5-0.99 | 0.95 | Medium | Baseflow persistence |
| q_base_init | 0-1000 m³/s | 50 | Low | Initial baseflow |

**Priority order for calibration**: CN > Ia_ratio > k_base > Tp > K > X > q_base_init

---

## HEC-HMS File Formats

### Project Structure (native HEC-HMS)

```
project.hms          # Project definition (name, description, units)
basin.basin          # Basin model: subbasins, reaches, junctions, reservoirs
met.met              # Meteorologic model: method, gauges, gridded data
control.control      # Control specifications: start/end dates, timestep
timeseries.gage      # Time series data specifications
data.dss             # Binary time series storage (HEC-DSS format)
run.run              # Simulation run configuration
```

### Basin File Format (.basin)

```
Basin: MyBasin
  Last Modified Date: 28 March 2026
  Last Modified Time: 10:00:00
  Unit System: Metric
End:

Subbasin: Sub1
  Canvas X: 100
  Canvas Y: 200
  Area: 500.0
  Downstream: J1
  Loss Rate Method: SCS Curve Number
  Curve Number: 75
  Transform Method: SCS Unit Hydrograph
  Lag Time: 3.5
  Baseflow Method: Linear Reservoir
  GW1 Initial Discharge: 10.0
  GW1 Recession Constant: 0.95
  GW1 Ratio to Peak: 0.1
End:

Junction: J1
  Canvas X: 150
  Canvas Y: 300
  Downstream: R1
End:

Reach: R1
  Canvas X: 200
  Canvas Y: 400
  Downstream: Outlet
  Route Method: Muskingum
  Muskingum K: 24.0
  Muskingum X: 0.2
  Muskingum Steps: 4
End:
```

### Meteorologic Model File (.met)

```
Meteorologic Model: MyMet
  Unit System: Metric
  Precipitation Method: Specified Hyetograph
  Evapotranspiration Method: Monthly Average
End:

Subbasin: Sub1
  Gage: Precip_Gage1
  ET Gage: ET_Gage1
End:
```

### Control Specifications (.control)

```
Control: SimControl
  Start Date: 01 January 1980
  Start Time: 00:00
  End Date: 31 December 1990
  End Time: 24:00
  Time Interval: 1440
End:
```

---

## Coupling Points

| # | Integration | Direction | Format | Notes |
|---|-------------|-----------|--------|-------|
| 1 | VIC → HEC-HMS | Input | NetCDF → CSV | VIC runoff as additional inflow |
| 2 | CMFD → HEC-HMS | Input | NetCDF → CSV | Precipitation + temperature |
| 3 | MSWX → HEC-HMS | Input | NetCDF → CSV | Alternative global forcing |
| 4 | HEC-HMS → CaMa-Flood | Output | CSV → NetCDF | Subbasin outflow for routing |
| 5 | HWSD → HEC-HMS | Input | Raster → CN table | Soil hydraulic groups |
| 6 | AVHRR → HEC-HMS | Input | Raster → CN table | Land cover classification |

---

## Data Requirements

| Data | Source | Status | Path |
|------|--------|--------|------|
| Precipitation | CMFD 0.25° | Available | `KISSPATH_ROOT/.../huai/Data_forcing_01dy_025deg/` |
| Temperature | CMFD 0.25° | Available | Same as above |
| Soil | HWSD China | Available | `KISSPATH_ROOT/.../soil/HWSD_China_Geo.img` |
| Land Cover | AVHRR 1km | Available | `KISSPATH_ROOT/.../landcover/AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif` |
| DEM | SRTM 90m | Available | `KISSPATH_ROOT/.../dem/china_dem_90m/china_dem_90m.tif` |
| Basin Shape | Bengbu | Available | `KISSPATH_ROOT/.../shp/bengbu_shp/bengbu_clip.shp` |
| Observation | Bengbu 51080 | Available | `KISSPATH_ROOT/.../obs/BB/51080_bengbu.txt` |

---

## Quick Start

### 1. Convert forcing data
```bash
python3 ki/tools/convert_forcing_to_hms.py \
  --forcing_dir KISSPATH_FORCING/huai/Data_forcing_01dy_025deg/ \
  --basin_shp KISSPATH_DATA/shp/bengbu_shp/bengbu_clip.shp \
  --start_date 1980-01-01 --end_date 1990-12-31 \
  --output_dir ./forcing_out/
```

### 2. Convert soil parameters
```bash
python3 ki/tools/convert_soil_to_hms.py \
  --soil_file KISSPATH_STATIC/HWSD_China_Geo.img \
  --landcover_file KISSPATH_DATA/landcover/AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif \
  --basin_shp KISSPATH_DATA/shp/bengbu_shp/bengbu_clip.shp \
  --output_file ./soil_params.json
```

### 3. Run model
```bash
python3 ki/tools/run_hec_hms.py \
  --forcing_csv ./forcing_out/basin_avg_forcing.csv \
  --soil_params ./soil_params.json \
  --basin_area_km2 121330 \
  --start_date 1980-01-01 --end_date 1990-12-31 \
  --output_csv ./sim_discharge.csv
```

### 4. Parse output
```bash
python3 ki/tools/parse_hms_output.py \
  --input_csv ./sim_discharge.csv \
  --output_csv ./discharge_daily.csv
```

### 5. Validate
```bash
python3 ki/tools/validate_hms.py \
  --sim_csv ./discharge_daily.csv \
  --obs_file KISSPATH_OBS/BB/51080_bengbu.txt \
  --start_date 1981-01-01 --end_date 1990-12-31 \
  --output_figure ./validation.png
```

### 6. Calibrate
```bash
python3 ki/tools/calibrate_hms.py \
  --forcing_csv ./forcing_out/basin_avg_forcing.csv \
  --obs_file KISSPATH_OBS/BB/51080_bengbu.txt \
  --basin_area_km2 121330 \
  --start_date 1981-01-01 --end_date 1990-12-31 \
  --n_samples 500 \
  --output_params ./calibrated_params.json
```

---

## Diagnostic Triplets Summary

| ID | Domain | Severity | Symptom (brief) |
|----|--------|----------|-----------------|
| dt_101 | unit_conversion | silent | Precip mm/day passed to sub-daily step without division |
| dt_102 | unit_conversion | silent | Temperature in Kelvin instead of Celsius |
| dt_103 | parameter_range | silent | CN outside 30-100 range |
| dt_104 | parameter_choice | medium | Ia ratio 0.2 vs 0.05 mismatch |
| dt_105 | numerical | medium | UH interval D > 0.29*Tp |
| dt_106 | numerical | error | Muskingum X > 0.5 or K < dt |
| dt_107 | parameter_units | silent | Recession constant confused with rate |
| dt_108 | unit_conversion | silent | Area km² vs m² in runoff conversion |
| dt_109 | format | medium | DSS midnight 2400 vs 0000 convention |
| dt_110 | unit_conversion | silent | Radiation W/m² vs MJ/m²/day for PET |
| dt_111 | parameter_range | silent | Green-Ampt suction head unrealistic |
| dt_112 | format | error | Missing basin-met-control linkage |
| dt_113 | numerical | medium | Negative runoff from CN < storm depth |
| dt_114 | unit_conversion | silent | Runoff mm to m³/s conversion error |
| dt_115 | runtime | error | Simulation period outside forcing period |
| dt_116 | parameter_range | medium | Lag time unrealistic for basin size |
| dt_117 | data_quality | medium | Missing precipitation days filled with zero |
| dt_118 | unit_conversion | silent | PET in mm/month vs mm/day |

---

## SCS Curve Number Method — Core Algorithm

The SCS-CN method is the default loss method in HEC-HMS:

```
S = 25400/CN - 254           # Maximum retention (mm)
Ia = lambda_ia * S            # Initial abstraction (mm), lambda_ia = 0.05 or 0.2
if P <= Ia:
    Q = 0                     # No runoff
else:
    Q = (P - Ia)² / (P - Ia + S)  # Runoff depth (mm)
Loss = P - Q                  # Total infiltration (mm)
```

### SCS Unit Hydrograph — Core Algorithm

```
Tp = 0.6 * Tc + D/2          # Time to peak (hr)
Qp = 2.08 * A / Tp           # Peak discharge (m³/s per mm of excess rain)
                              # A in km², Tp in hours
# Dimensionless UH ordinates (SCS):
t/Tp:  0.0  0.1  0.2  0.3  0.4  0.5  0.6  0.7  0.8  0.9  1.0
Q/Qp:  0.0  0.03 0.10 0.19 0.31 0.47 0.66 0.82 0.93 0.99 1.00
t/Tp:  1.1  1.2  1.3  1.4  1.5  1.6  1.8  2.0  2.2  2.4  2.6
Q/Qp:  0.99 0.93 0.86 0.78 0.68 0.56 0.39 0.28 0.207 0.147 0.107
t/Tp:  2.8  3.0  3.5  4.0  4.5  5.0
Q/Qp:  0.077 0.055 0.025 0.011 0.005 0.0
```

### Muskingum Routing — Core Algorithm

```
C1 = (dt - 2*K*X) / (2*K*(1-X) + dt)
C2 = (dt + 2*K*X) / (2*K*(1-X) + dt)
C3 = (2*K*(1-X) - dt) / (2*K*(1-X) + dt)
# C1 + C2 + C3 = 1.0 (conservation check)
O[t+1] = C1*I[t+1] + C2*I[t] + C3*O[t]
```

---

## File Structure

```
ki/
├── SKILL.md                          # This file
├── knowledge_infrastructure.yaml     # Formal schema
├── tools/
│   ├── convert_forcing_to_hms.py    # CMFD/MSWX → HEC-HMS forcing
│   ├── convert_soil_to_hms.py       # HWSD + AVHRR → CN + soil params
│   ├── run_hec_hms.py               # Execute SCS-CN + SCS UH + routing
│   ├── parse_hms_output.py          # Extract discharge CSV
│   ├── validate_hms.py              # Compare sim vs obs, compute metrics
│   └── calibrate_hms.py            # Automated GLUE-style calibration
├── docs/
│   ├── s0_configuration_skill.md
│   ├── s1_domain_setup_skill.md
│   ├── s2_soil_parameters_skill.md
│   ├── s4_forcing_conversion_skill.md
│   ├── s5_model_execution_skill.md
│   ├── s6_output_analysis_skill.md
│   └── s7_calibration_skill.md
├── diagnostics/
│   └── triplets.yaml
└── workflow/
    └── workflow.md
```
