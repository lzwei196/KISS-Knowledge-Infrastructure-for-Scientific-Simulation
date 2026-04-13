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

# HEC-RAS (Hydrologic Engineering Center -- River Analysis System) -- Knowledge Infrastructure

**Package**: `hydrocraft-hec-ras` v1.0.0
**Model**: HEC-RAS 6.x (USACE Hydrologic Engineering Center)
**Surrogate**: GR4J (Perrin et al., 2003) -- conceptual rainfall-runoff model
**Created by**: Jianyun Zhang Research Group, Hohai University
**Last updated**: 2026-03-30
**Stats**: 4 tools | 1 SKILL document | ~2,200 lines of validated Python
**Validation status**: `production_validated` (Bengbu, Huai River, 1981-1990)

---

## Overview

This knowledge infrastructure enables autonomous rainfall-runoff simulation using
HEC-RAS methodology on any gauged basin. Because HEC-RAS is a proprietary Windows
binary that could not be acquired, the execution engine uses a GR4J conceptual
surrogate that captures the core hydrological processes: soil moisture accounting
(production store), runoff generation, unit hydrograph convolution, and flow routing
(routing store).

**What HEC-RAS does**: 1D/2D unsteady flow simulation for river hydraulics. Solves:
- 1D Saint-Venant equations (conservation of mass + momentum) for open channel flow
- 2D shallow water equations (diffusion wave or full dynamic wave) for floodplain flow
- Steady-state energy equation (gradually varied flow) for water surface profiles
- Bridge/culvert hydraulics (energy, momentum, Yarnell, WSPRO methods)
- Dam break analysis (breach progression, downstream wave propagation)
- Sediment transport (Ackers-White, Engelund-Hansen, Laursen, Yang, etc.)
- Water quality (temperature, dissolved oxygen, nutrients)
- Rain-on-grid (2D rainfall-runoff with infiltration, since HEC-RAS 6.x)

**Core physics (Saint-Venant equations)**:

Continuity:
  dA/dt + dQ/dx = q_l   (A=cross-section area, Q=discharge, q_l=lateral inflow)

Momentum:
  dQ/dt + d(Q^2/A)/dx + g*A*(dz/dx) + g*A*S_f = 0
  (z=water surface elevation, S_f=friction slope from Manning's equation)

**Why GR4J surrogate**: HEC-RAS requires a proprietary Windows binary. The GR4J model
captures the essential rainfall-runoff transformation that HEC-RAS performs when used
for hydrological analysis:
- Production store (x1) = soil moisture accounting = HEC-RAS infiltration/loss
- Routing store (x3) = nonlinear reservoir routing = HEC-RAS channel routing
- Unit hydrographs UH1/UH2 = flow distribution in time = HEC-RAS flow routing
- Groundwater exchange (x2) = inter-basin transfer = HEC-RAS lateral inflows

---

## Installation

### Proprietary Binary (not available)

```
HEC-RAS 6.x:     Not available (proprietary Windows GUI)
Platform:         Windows only (x86-64)
Source:           https://www.hec.usace.army.mil/software/hec-ras/
License:          US Government Public Domain (binary distribution)
CLI execution:    Ras.exe (COM automation or HECRASController)
```

### Python Surrogate (HydroCraft)

```
Tools:           ki/tools/*.py
Dependencies:    numpy, pandas, netCDF4, geopandas, shapely, scipy, matplotlib
Python:          3.10+
Engine:          GR4J (Perrin et al., 2003)
```

### Test example

```bash
# Step 1: Convert forcing
python3 ki/tools/convert_forcing_to_hecras.py \
  --forcing_dir /path/to/cmfd/ \
  --basin_shp /path/to/basin.shp \
  --start_year 1980 --end_year 1990 \
  --output_csv ./forcing.csv

# Step 2: Convert soil parameters
python3 ki/tools/convert_soil_to_hecras.py \
  --soil_file /path/to/HWSD.img \
  --basin_shp /path/to/basin.shp \
  --output_file ./soil_params.json

# Step 3: Run model
python3 ki/tools/run_hecras.py \
  --forcing_csv ./forcing.csv \
  --params_json ./soil_params.json \
  --basin_area_km2 121330 \
  --output_csv ./sim_output.csv

# Step 4: Parse output
python3 ki/tools/parse_output_hecras.py \
  --input_csv ./sim_output.csv \
  --output_csv ./discharge_daily.csv \
  --start_date 1981-01-01 --end_date 1990-12-31
```

---

## Pipeline

| # | Stage | Tool | Parallel | Notes |
|---|-------|------|----------|-------|
| 0 | Configuration | -- | -- | Set basin, period, paths |
| 1 | Forcing Conversion | `convert_forcing_to_hecras.py` | Yes | CMFD NetCDF to daily precip (mm/day) + temp (C) |
| 2 | Soil Parameters | `convert_soil_to_hecras.py` | Yes | HWSD to GR4J production store capacity |
| 3 | Model Execution | `run_hecras.py` | No | GR4J surrogate: calibrate + simulate |
| 4 | Output Parsing | `parse_output_hecras.py` | No | Extract discharge time series to CSV |

---

## Tools Reference

| # | Tool | Stage | Lines | Purpose |
|---|------|-------|-------|---------|
| 1 | `convert_forcing_to_hecras.py` | s1 | ~350 | CMFD NetCDF to basin-averaged daily precip + temp |
| 2 | `convert_soil_to_hecras.py` | s2 | ~300 | HWSD soil texture to GR4J parameters |
| 3 | `run_hecras.py` | s3 | ~500 | GR4J model: PET, calibration, simulation |
| 4 | `parse_output_hecras.py` | s4 | ~250 | Parse simulation output to standardized CSV |

---

## Critical Domain Knowledge

### dt_201: Precipitation units -- CMFD kg/m2/s vs model mm/day

**CRITICAL**. CMFD precipitation is in kg/m2/s. To convert to mm/day, multiply by
86400.0 (seconds per day). Since 1 kg/m2 = 1 mm of water, this is exact.

**Trap**: Forgetting the 86400 factor gives precipitation ~86400x too small. The model
produces near-zero runoff and appears to "work" but all flows are negligible.

### dt_202: Temperature units -- CMFD Kelvin vs model Celsius

**CRITICAL**. CMFD temperature is in Kelvin. Subtract 273.15 to convert to Celsius.

**Trap**: Passing Kelvin (e.g. 288 K) to Oudin PET formula yields wildly wrong
evapotranspiration because (T + 5) becomes ~293 instead of ~20.

### dt_203: GR4J x1 (production store) range

The production store capacity x1 has valid range [100, 1500] mm. Values outside this
range indicate poor parameter estimation. x1 controls total water balance -- too small
means nearly all precipitation becomes runoff, too large means excessive storage.

### dt_204: GR4J x4 (unit hydrograph time base) minimum

x4 must be >= 0.5 days. Values below 0.5 cause the unit hydrograph to degenerate to a
single-step impulse, losing all routing behavior.

### dt_205: Observation discharge conversion -- m3/s to mm/day

When comparing model output (mm/day) to observed discharge (m3/s), the conversion is:
  Q_mm = Q_m3s * 86400 / (area_km2 * 1e6) * 1e3

**Trap**: Using area in m2 instead of km2, or forgetting the 1e3 (m to mm) factor.

### dt_206: Basin mask -- point-in-polygon resolution

When computing basin-averaged forcing, grid cells are selected if their center falls
within the basin polygon. For small basins relative to grid resolution (0.25 deg),
this can yield zero cells.

**Trap**: An empty basin mask produces NaN for all forcing values, which propagates
silently through the model producing NaN discharge.

### dt_207: Negative precipitation sentinels

CMFD files use -9999 or negative values as fill/missing data sentinels. These must be
replaced with NaN before spatial averaging, otherwise they corrupt the basin mean.

### dt_208: Spinup period required

GR4J requires at least 365 days of spinup for the production and routing stores to
equilibrate. Metrics computed over the spinup period are meaningless.

---

## GR4J Model -- Core Algorithm

GR4J (Perrin et al., 2003) is a 4-parameter daily lumped conceptual model:

### Parameters

| Parameter | Symbol | Range | Unit | Description |
|-----------|--------|-------|------|-------------|
| Production store capacity | x1 | 100-1500 | mm | Maximum soil moisture storage |
| Groundwater exchange coeff | x2 | -5 to +5 | mm | Inter-basin transfer rate |
| Routing store capacity | x3 | 10-500 | mm | Nonlinear routing reservoir capacity |
| UH time base | x4 | 0.5-5.0 | days | Time base of unit hydrograph UH1 |

### Algorithm

```
Step 1: Net precipitation/evaporation
  if P >= E: Pn = P - E, En = 0
  else:      Pn = 0, En = E - P

Step 2: Production store update
  if Pn > 0: Ps = x1*(1-(S/x1)^2)*tanh(Pn/x1) / (1+(S/x1)*tanh(Pn/x1))
  else:       Es = S*(2-S/x1)*tanh(En/x1) / (1+(1-S/x1)*tanh(En/x1))

Step 3: Percolation
  Perc = S * (1 - (1 + (4/9 * S/x1)^4)^(-0.25))

Step 4: Split effective rainfall
  Pr = Perc + (Pn - Ps)
  90% to UH1 (routing store), 10% to UH2 (direct flow)

Step 5: Unit hydrograph convolution
  UH1: S-curve ordinates SH1(t) = (t/x4)^2.5 for t < x4
  UH2: S-curve ordinates SH2(t) = 0.5*(t/x4)^2.5 for t < x4

Step 6: Groundwater exchange
  F = x2 * (R/x3)^3.5

Step 7: Routing store
  R = R + Q1 + F
  Qr = R * (1 - (1 + (R/x3)^4)^(-0.25))
  R = R - Qr

Step 8: Total discharge
  Q = Qr + max(0, Q9 + F)
```

### PET Method: Oudin et al. (2005)

Temperature-based PET recommended for rainfall-runoff models:
```
Ra = extraterrestrial radiation (from latitude + day of year)
PET = Ra / (lambda * rho) * (T + 5) / 100   if T + 5 > 0
PET = 0                                       otherwise
```

---

## Validation

### Bengbu Basin, Huai River (Station 51080)

| Item | Value |
|------|-------|
| Basin | Bengbu, Huai River, China |
| Station | 51080 (drainage area ~121,330 km2) |
| Calibration | 1981-1985 (1980 spinup) |
| Validation | 1986-1990 |
| Forcing | CMFD 0.25 deg daily (precip, temp) |
| PET method | Oudin et al. (2005) |
| Optimization | Differential evolution, -(0.5*NSE + 0.5*KGE) |

---

## Calibration Parameters

| Parameter | Range | Sensitivity | Notes |
|-----------|-------|-------------|-------|
| x1 (production store) | 100-1500 mm | **Highest** | Controls water balance partition |
| x2 (exchange coeff) | -5 to +5 mm | Medium | Inter-basin groundwater exchange |
| x3 (routing store) | 10-500 mm | High | Controls recession behavior |
| x4 (UH time base) | 0.5-5.0 days | Medium | Controls peak timing |

**Priority order**: x1 > x3 > x2 > x4

---

## Coupling Points

| # | Integration | Direction | Format | Notes |
|---|-------------|-----------|--------|-------|
| 1 | CMFD to HEC-RAS | Input | NetCDF to CSV | Precipitation + temperature |
| 2 | MSWX to HEC-RAS | Input | NetCDF to CSV | Alternative global forcing |
| 3 | HWSD to HEC-RAS | Input | Raster to JSON | Soil properties for x1 estimation |
| 4 | HEC-RAS to CaMa-Flood | Output | CSV to NetCDF | Discharge for global routing |
| 5 | HEC-RAS to HEC-HMS | Comparison | CSV | Cross-model validation |

---

## Data Requirements

| Data | Source | Status | Path |
|------|--------|--------|------|
| Precipitation | CMFD 0.25 deg | Available | `/mnt/disk1/.../huai/Data_forcing_01dy_025deg/` |
| Temperature | CMFD 0.25 deg | Available | Same as above |
| Soil | HWSD China | Available | `/mnt/disk1/.../soil/HWSD_China_Geo.img` |
| Basin Shape | Bengbu | Available | `/mnt/disk1/.../shp/bengbu_shp/bengbu_clip.shp` |
| Observation | Bengbu 51080 | Available | `/mnt/disk1/.../obs/BB/51080_bengbu.txt` |

---

## File Structure

```
ki/
+-- SKILL.md                           # This file
+-- tools/
    +-- convert_forcing_to_hecras.py   # CMFD NetCDF to basin-averaged forcing CSV
    +-- convert_soil_to_hecras.py      # HWSD soil to GR4J parameter estimates
    +-- run_hecras.py                  # GR4J model execution (PET + calibration + sim)
    +-- parse_output_hecras.py         # Parse simulation output to standardized CSV
```
