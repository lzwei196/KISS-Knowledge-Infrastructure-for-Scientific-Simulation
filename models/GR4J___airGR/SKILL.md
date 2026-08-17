---
name: gr4j-airgr
description: >-
  GR4J. Covers Daily lumped catchment rainfall-runoff transform (P, PE -> Qsim);
  Production (soil-moisture) store with interception, evaporation, percolation; Two unit
  hydrographs (UH1 slow 90%, UH2 fast direct 10%); Nonlinear routing store;
  Inter-catchment groundwater exchange (X2). Use when the task involves running,
  configuring, calibrating or interpreting GR4J___airGR.
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

# GR4J (airGR) — Knowledge Infrastructure

**Package**: `hydrocraft-gr4j-airgr` v1.0.0
**Model**: GR4J daily lumped rainfall-runoff model via airGR R package v1.7.8
**Created by**: Jianyun Zhang Research Group, Hohai University
**Last updated**: 2026-03-25
**Stats**: 4 tools | 5 skill documents | 15+ diagnostic triplets | ~1,500 lines of validated Python
**Validation status**: `production_validated` (airGR L0123001 built-in dataset)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/HWSD/SKILL.md` for soil property documentation.
See `data_ki/ObservedQ/SKILL.md` for observed discharge data.


## Overview

This knowledge infrastructure enables fully autonomous simulation of catchment rainfall-runoff processes using the GR4J model (Perrin et al., 2003) implemented in the airGR R package. The 4 validated Python tools replace manual R workflow steps with a Python pipeline that integrates directly with HydroCraft's forcing, routing, and calibration infrastructure.

**What GR4J does**: Four-parameter daily lumped conceptual hydrological model. Simulates:
- Production store: soil moisture accounting (interception, evaporation, percolation)
- Two unit hydrographs (UH1: 90% routed, UH2: 10% direct)
- Routing store: nonlinear outflow from routed branch
- Inter-catchment groundwater exchange
- Total runoff = routed flow (QR) + direct flow (QD)

**Key difference from other HydroCraft models**: GR4J operates on a lumped catchment (single spatial unit), not gridded. All inputs are catchment-average values in mm/day. It can optionally couple with CemaNeige for snow processes. The Fortran core is wrapped by R functions in airGR.

**Model Reference**: Perrin, C., Michel, C. and Andreassian, V. (2003). Improvement of a parsimonious model for streamflow simulation. Journal of Hydrology, 279(1-4), 275-289.

---

## Installation

### R Package

```
airGR v1.7.8:  CRAN package (R >= 3.5.0)
Install:       install.packages("airGR")
Source:        https://github.com/cran/airGR
Fortran core:  src/frun_GR4J.f90 (compiled via R CMD INSTALL)
```

### Dependencies (R)

```
Depends: R (>= 3.5.0)
Imports: graphics, grDevices, stats, utils
Suggests: knitr, rmarkdown, caRamel, DEoptim, testthat
```

### Python dependencies (HydroCraft tools)

```
rpy2, numpy, pandas, matplotlib
```

### Test example

```
data(L0123001)  # Built-in fictional catchment
  BasinObs:  DatesR, P [mm/d], T [degC], E [mm/d], Qls [l/s], Qmm [mm/d]
  BasinInfo: code, name, area [km2], HypsoData [m]
  Period:    1984-01-01 to 2005-12-31 (daily)
```

**Validated**: GR4J runs successfully on L0123001 data. Calibration yields NSE > 0.90.

---

## Model Parameters

GR4J has exactly **4 free parameters**:

| Parameter | Symbol | Unit | Description | Typical Range |
|-----------|--------|------|-------------|---------------|
| X1 | Prod store capacity | mm | Maximum capacity of production (soil moisture) store | 100 - 1200 |
| X2 | Exchange coefficient | mm/d | Inter-catchment groundwater exchange coefficient | -5 - 3 |
| X3 | Routing store capacity | mm | Maximum capacity of routing store | 20 - 300 |
| X4 | UH time constant | d | Time base of unit hydrographs | 1.1 - 2.9 |

### Parameter Constraints
- X1 >= 0.01 mm (enforced by RunModel_GR4J)
- X3 >= 0.01 mm (enforced by RunModel_GR4J)
- X4 >= 0.5 d (enforced by RunModel_GR4J)
- X2 can be negative (catchment loses water to groundwater)

### Parameter Transformation (for calibration)
The calibration uses transformed parameters to ensure unconstrained optimization:
- X1: log transform (real = exp(transformed))
- X2: sinh transform (real = sinh(transformed))
- X3: log transform (real = exp(transformed))
- X4: linear rescaling to [0.5, 39.5] range

---

## Pipeline (7 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | (manual) | Catchment selection, period, forcing source |
| 1 | Forcing preparation | `convert_forcing_to_gr4j` | Global forcing (CMFD/ERA5) to airGR input format (P, PE in mm/d) |
| 2 | Catchment parameters | `convert_catchment_params` | HWSD soil data + DEM to catchment properties |
| 3 | Model execution | `run_gr4j` | Run GR4J via rpy2 with warmup, calibration, simulation |
| 4 | Calibration | `run_gr4j` (calibration mode) | Calibration_Michel with NSE/KGE objective |
| 5 | Output parsing | `parse_gr4j_output` | Extract Qsim, store levels, fluxes to CSV |
| 6 | Validation | `parse_gr4j_output` (validation mode) | Compute NSE, KGE, PBIAS, plot observed vs simulated |

### Parallelism

Stages 1 and 2 can run in parallel after stage 0.
Stage 3 depends on 1 and 2.
Stage 4 depends on 3 (uses same tool with calibrate=True).
Stage 5 depends on 3 or 4.
Stage 6 depends on 5.

---

## Input/Output Specification

### Inputs (all catchment-average, daily)

| Variable | Unit | Source | Notes |
|----------|------|--------|-------|
| DatesR | POSIXt | Time series dates | Must be continuous, no gaps |
| Precip (P) | mm/day | CMFD, ERA5, gauge | Must be >= 0, no NA allowed |
| PotEvap (E) | mm/day | Oudin formula or pre-computed | Must be >= 0, no NA allowed |
| Qobs | mm/day | Gauged streamflow (for calibration) | NA values allowed |
| TempMean (T) | degC | Required only if computing PE via PE_Oudin | Mean daily air temperature |

### PE_Oudin Formula (if PotEvap not pre-computed)

```
PE_Oudin(JD, Temp, Lat, LatUnit="deg")
  JD:   Julian day of year (1-366)
  Temp: daily mean air temperature [degC]
  Lat:  catchment latitude [degrees or radians]
  Returns: PE [mm/day]
```

### Unit Conversion from CMFD to airGR

| CMFD Variable | CMFD Unit | airGR Variable | airGR Unit | Conversion |
|---------------|-----------|----------------|------------|------------|
| prec | mm/3hr | Precip | mm/day | sum 8 timesteps per day |
| temp | K | TempMean | degC | subtract 273.15 |
| shum + pres | kg/kg, Pa | PotEvap | mm/day | Use PE_Oudin(JD, T_degC, lat) |
| srad | W/m2 | (not used) | - | GR4J uses PE, not radiation directly |
| wind | m/s | (not used) | - | GR4J uses PE, not wind directly |

### Unit Conversion from Discharge

| Source | Source Unit | Target | Target Unit | Conversion |
|--------|-----------|--------|-------------|------------|
| Gauge | m3/s | Qmm | mm/day | Q_m3s * 86400 / (area_km2 * 1e6) * 1000 |
| Gauge | l/s | Qmm | mm/day | Q_ls / 1000 * 86400 / (area_km2 * 1e6) * 1000 |
| VIC routing | mm/day | Qmm | mm/day | Direct (same unit) |

---

## Unit Trap Table (CRITICAL)

These unit mismatches cause **silent failures** — the model runs but produces garbage.

| Trap ID | Source | Expected by GR4J | Wrong Value | Correct Value | Symptom |
|---------|--------|-------------------|-------------|---------------|---------|
| UT-001 | CMFD temp in K | degC | 293.15 | 20.0 | PE ~300 mm/d, all water evaporates |
| UT-002 | Precip in m/day | mm/day | 0.005 | 5.0 | Near-zero runoff, extreme drought |
| UT-003 | Precip in mm/3hr not aggregated | mm/day | 2.5 (3hr value) | 20.0 (daily sum) | Runoff 1/8 of expected |
| UT-004 | Q_obs in m3/s | mm/day | 100 | 0.86 | NSE = -infinity during calibration |
| UT-005 | Q_obs in l/s not converted | mm/day | 100000 | 0.86 | Calibration fails completely |
| UT-006 | Area in m2 used for conversion | km2 expected | 1e8 | 100 | Q_mm off by factor 1e6 |
| UT-007 | PE from Penman in mm/month | mm/day | 150 | 5.0 | Store depletes instantly |
| UT-008 | Negative PE values | >= 0 | -2.0 | 0.0 | Warning, then truncation artifacts |

---

## Tools Reference

| Tool | Stage | Script Path | Lines | Purpose |
|------|-------|-------------|------:|---------|
| `convert_forcing_to_gr4j` | s1 | `tools/convert_forcing_to_gr4j.py` | ~250 | CMFD/ERA5/gauge to airGR format (P, PE in mm/d) |
| `convert_catchment_params` | s2 | `tools/convert_catchment_params.py` | ~200 | HWSD soil + DEM to catchment area, hypsometry |
| `run_gr4j` | s3-s4 | `tools/run_gr4j.py` | ~350 | Execute GR4J via rpy2 (simulation + calibration) |
| `parse_gr4j_output` | s5-s6 | `tools/parse_gr4j_output.py` | ~300 | Extract results to CSV, compute metrics, plot |

**Total**: 4 tools, ~1,100 lines of validated Python code.

---

## Skill Knowledge

| Stage | Topic | Skill Document |
|-------|-------|----------------|
| s1 | Forcing preparation, unit conversions | `docs/s1_forcing_preparation.md` |
| s2 | Catchment parameter extraction | `docs/s2_catchment_parameters.md` |
| s3 | Model execution and warmup | `docs/s3_model_execution.md` |
| s4 | Calibration procedure | `docs/s4_calibration.md` |
| s5 | Output analysis and validation | `docs/s5_output_analysis.md` |

---

## Critical Domain Knowledge

These non-obvious facts cause **silent failures** if violated. Each has a corresponding diagnostic triplet.

### 1. All fluxes in mm/day, NOT m3/s (dt_001)

GR4J operates entirely in mm/day (water depth equivalent over catchment area). Precipitation, potential evapotranspiration, and simulated discharge are all in mm/day. Observed discharge for calibration MUST be converted from m3/s or l/s to mm/day using: `Qmm = Q_m3s * 86400 / (area_km2 * 1e6) * 1000`. Using m3/s directly causes NSE = -infinity.

### 2. Temperature must be in Celsius for PE_Oudin (dt_002)

The PE_Oudin function expects temperature in degrees Celsius. CMFD provides temperature in Kelvin. Forgetting to subtract 273.15 causes PE values of ~300 mm/day (instead of ~5 mm/day), draining all soil moisture instantly.

### 3. Warm-up period is essential (dt_006)

GR4J has two stores (production and routing) plus unit hydrograph states. Default initialization sets production store to 30% and routing store to 50% capacity. Without a warm-up period of at least 1 year, the first months/years of simulation are unreliable. airGR auto-selects 1 year of warm-up by default.

### 4. No missing values in precipitation or PE (dt_007)

airGR does NOT allow NA values in Precip or PotEvap. Any NA causes an error. Gap-fill forcing data BEFORE creating InputsModel. Observed discharge (Qobs) CAN contain NA values.

### 5. Calibration uses transformed parameter space (dt_008)

Calibration_Michel operates in transformed parameter space (log/sinh transforms). Direct parameter values cannot be used as starting points — they must be transformed first via TransfoParam_GR4J(). The search grid covers a wide range by default.

### 6. IndPeriod must be integer type (dt_009)

R's seq() creates numeric vectors by default. IndPeriod_Run and IndPeriod_WarmUp must be integer vectors. Use `as.integer(seq(...))` or `seq.int(...)`. Non-integer indices cause a hard error.

### 7. Daily precipitation must be positive sums, not rates (dt_010)

GR4J expects daily total precipitation in mm, not instantaneous rates. When aggregating sub-daily data, SUM the values (not average). Averaging 3-hourly precipitation gives 1/8 of the correct daily total.

### 8. X4 minimum is 0.5, not 0 (dt_011)

The unit hydrograph time constant X4 has a hard floor at 0.5 days. Values below 0.5 are silently clipped with a warning. During calibration, the parameter transform ensures X4 stays in [0.5, 39.5].

---

## Model Architecture (Fortran Core)

The GR4J Fortran subroutine (`frun_GR4J.f90`) implements the following water balance:

```
For each daily time step:
  1. Net rainfall/evaporation
     If P >= E: PN = P - E, EN = 0
     If P <  E: PN = 0, EN = E - P

  2. Production store (soil moisture accounting)
     PS = fraction of PN entering store (tanh function of store level / X1)
     ES = actual evaporation from store (tanh function of EN / X1)
     Update store: S = S + PS - ES

  3. Percolation from production store
     PERC = S * (1 - (1 + (S/(9/4*X1))^4)^(-0.25))
     S = S - PERC

  4. Total effective rainfall
     PR = PN - PS + PERC

  5. Split into two branches
     PRUH1 = 0.9 * PR  (slow routed branch)
     PRUH2 = 0.1 * PR  (fast direct branch)

  6. Unit hydrograph convolution
     UH1: S-curve with time base X4 (20 ordinates max)
     UH2: S-curve with time base 2*X4 (40 ordinates max)

  7. Groundwater exchange
     EXCH = X2 * (R/X3)^3.5
     R = routing store level

  8. Routing store
     R = R + Q9 + EXCH  (Q9 = UH1 output)
     QR = R * (1 - (1 + (R/X3)^4)^(-0.25))
     R = R - QR

  9. Direct branch
     QD = max(0, Q1 + EXCH)  (Q1 = UH2 output)

  10. Total discharge
      Q = QR + QD [mm/day]
```

### State Variables (67 total)
- St(1): Production store level [mm]
- St(2): Routing store level [mm]
- StUH1(1:20): UH1 states [mm]
- StUH2(1:40): UH2 states [mm]
- 5 additional internal states

### Output Variables (18 per timestep)
| Index | Name | Description | Unit |
|-------|------|-------------|------|
| 1 | PotEvap | Input PE | mm/d |
| 2 | Precip | Input P | mm/d |
| 3 | Prod | Production store level | mm |
| 4 | Pn | Net rainfall | mm/d |
| 5 | Ps | Part filling production store | mm/d |
| 6 | AE | Actual evapotranspiration | mm/d |
| 7 | Perc | Percolation | mm/d |
| 8 | PR | Effective rainfall | mm/d |
| 9 | Q9 | UH1 outflow | mm/d |
| 10 | Q1 | UH2 outflow | mm/d |
| 11 | Rout | Routing store level | mm |
| 12 | Exch | Potential exchange | mm/d |
| 13 | AExch1 | Actual exchange branch 1 | mm/d |
| 14 | AExch2 | Actual exchange branch 2 | mm/d |
| 15 | AExch | Total actual exchange | mm/d |
| 16 | QR | Routing store outflow | mm/d |
| 17 | QD | Direct flow after exchange | mm/d |
| 18 | Qsim | Simulated discharge | mm/d |

---

## Calibration

### Calibration_Michel Algorithm
1. **Grid screening**: Test predefined parameter combinations on a coarse grid
2. **Steepest descent**: Local search from best grid point, with adaptive step size
3. **Convergence**: Step size shrinks until < 0.01 in transformed space

### Available Criteria
| Criterion | Function | Best Value | Use Case |
|-----------|----------|------------|----------|
| NSE | ErrorCrit_NSE | 1.0 | General flow simulation |
| KGE | ErrorCrit_KGE | 1.0 | Balanced bias/correlation/variability |
| KGE2 | ErrorCrit_KGE2 | 1.0 | Modified KGE (CV ratio) |
| RMSE | ErrorCrit_RMSE | 0.0 | Absolute error |

### Typical Calibrated Values (literature)
| Catchment Type | X1 [mm] | X2 [mm/d] | X3 [mm] | X4 [d] |
|---------------|---------|-----------|---------|--------|
| Humid temperate | 200-500 | 0.5-2.0 | 50-150 | 1.5-2.5 |
| Semi-arid | 500-1200 | -2.0-1.0 | 100-300 | 1.5-3.0 |
| Tropical wet | 100-400 | 1.0-3.0 | 20-100 | 1.0-2.0 |

---

## CemaNeige Snow Module (Optional)

For snow-affected catchments, GR4J can be coupled with CemaNeige:
- Function: `RunModel_CemaNeigeGR4J`
- Additional parameters: 2 (CTG: degree-day factor, Kf: snowpack inertia)
- Additional inputs: TempMean [degC], HypsoData [m], ZInputs [m]
- Total parameters when coupled: 6 (4 GR4J + 2 CemaNeige)

**WIRED INTO `run_gr4j.py` (use `--snow`).** For any cold-region / snowmelt-driven
catchment (winter precip falls as snow, hydrograph driven by a spring/summer
freshet), run with `--snow` (alias for `--model cemaneige_gr4j`). The CemaNeige
variant needs the `TempMean_degC` column (written by `convert_forcing_to_gr4j` by
default) and runs as a single elevation layer if no HypsoData is supplied.

**WHY IT MATTERS (HYDAT 08NH120 Moyie R., BC, 2026-06-23):** plain GR4J on this
alpine snowmelt basin calibrated to NSE 0.14 only, with X2 forced to +7.3 mm/d
(far outside the typical −5..3 range) to import phantom groundwater faking the
spring freshet. Adding `--snow` lifted calibration NSE to 0.80 / validation 0.77
and returned X2 to a physical +0.34. Diagnostic tell: if your best-fit X2 is large
and you're on a cold catchment, you are missing snow — switch to `--snow`.
Calibration example (6-param, CemaNeige adds X5=CTG, X6=Kf):
```
run_gr4j.py --forcing forcing_gr4j.csv --output sim.csv --mode calibration --snow \
            --start 2006-01-01 --end 2010-12-31 --criterion NSE --meta-json p.json
# then simulate with the calibrated 6 params: --mode simulation --snow --x1..--x6
```

**ELEVATION LAYERS (`--hypso-json`, added 2026-07-13, Lancang 允景洪):** by default
CemaNeige runs as a SINGLE elevation layer at the forcing elevation, which smears
snow across the full relief. For high-relief basins (>1500 m relief — e.g. the
Lancang at Jinghong spans ~550-5,500 m), pass the catchment-params JSON written by
`convert_catchment_params` (must contain the 101-point `hypsometry` array from the
basin-masked DEM): `--snow --hypso-json catchment_params.json [--nlayers 5]`.
airGR then extrapolates T and P over the elevation bands
(DataAltiExtrapolation_Valery) with ZInputs = median(HypsoData), so only the cold
fraction of the basin accumulates snow. Ascending, exactly-101-value hypsometry is
enforced by the tool.

---

## References

- Perrin, C., Michel, C. and Andreassian, V. (2003). Improvement of a parsimonious model for streamflow simulation. Journal of Hydrology, 279(1-4), 275-289.
- Oudin, L., Hervieu, F., Michel, C., Perrin, C., Andreassian, V., Anctil, F. and Loumagne, C. (2005). Which potential evapotranspiration input for a lumped rainfall-runoff model? Part 2. Journal of Hydrology, 303(1-4), 290-306.
- Valery, A., Andreassian, V. and Perrin, C. (2014). As simple as possible but not simpler: What is useful in a temperature-based snow-accounting routine? Journal of Hydrology, 517, 1176-1187.
