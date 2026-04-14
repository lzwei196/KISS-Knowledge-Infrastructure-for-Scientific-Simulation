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

# TOPMODEL BMI (NOAA-OWP) — Knowledge Infrastructure

**Package**: `hydrocraft-topmodel` v1.0.0
**Model**: TOPMODEL BMI (Beven & Kirkby 1979, NOAA-OWP C implementation)
**Created by**: Jianyun Zhang Research Group, Hohai University
**Last updated**: 2026-03-28
**Stats**: 4 tools | 6 skill documents | 18 diagnostic triplets | ~2,000 lines of validated Python
**Validation status**: see `knowledge_infrastructure.yaml`

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/HWSD/SKILL.md` for soil property documentation.
See `data_ki/ObservedQ/SKILL.md` for observed discharge data.


## Overview

This knowledge infrastructure enables autonomous simulation of rainfall-runoff
using TOPMODEL on any watershed, without manual data preparation. The tools
replace the standard manual workflow with a Python pipeline that integrates
with HydroCraft's forcing, observation, and soil databases.

**What TOPMODEL does**: A physically-based, semi-distributed watershed model
that predicts:
- Saturation-excess overland flow (variable contributing area)
- Subsurface (baseflow) drainage via exponential transmissivity profile
- Unsaturated zone percolation
- Evapotranspiration from root zone deficit
- Channel routing via time-delay histogram
- Optional infiltration excess (Green-Ampt) overland flow

**Key concept**: Uses the topographic wetness index (TWI = ln(a/tanB)) distribution
to represent spatial variability of soil moisture deficit across the catchment,
without requiring a full 2D grid. A single subcatchment is characterized by
its TWI histogram.

**Model lineage**: Beven & Kirkby (1979) FORTRAN → Keith Beven (1985/1995)
→ Fred Ogden C port (2009) → NOAA-OWP BMI adaptation (2021)
→ GitHub: https://github.com/NOAA-OWP/topmodel

---

## Installation

### Build from source

```bash
cd source/repo/src/
make clean && make
cd ..
# Binary: ./run_bmi
```

### Dependencies

- GCC (tested 8.3.1+)
- GNU Make
- libm (math library, standard)

### Test run (Taegu Pyungkwang River demo)

```bash
cd source/repo/
./run_bmi
# Produces: topmod.out, hyd.out
```

---

## Critical Units — ALL internal units are METERS and HOURS

| Variable | Internal Unit | CMFD Unit | Conversion |
|----------|--------------|-----------|------------|
| rain | **m/hr** | mm/day | ÷ 24,000 (mm→m then day→hr) |
| pe (PET) | **m/hr** | — (compute) | Must derive PET from temp/rad |
| Qobs | **m/hr** | m³/s | Q/(area_m² × 3600) then ×1 |
| dt | **hours** | — | Typically 1 hr |
| szm | **m** | — | Calibration parameter |
| t0 | **m/hr** | — | Ln(T0) often calibrated |
| td | **hr** | — | Time delay parameter |
| chv | **m/hr** | — | Channel velocity |
| rv | **m/hr** | — | Overland flow velocity |
| srmax | **m** | — | Max root zone deficit |
| Q0 | **m/hr** | — | Initial subsurface flow |
| sr0 | **m** | — | Initial root zone deficit |
| xk0 | **m/hr** | — | Surface hydraulic cond. |
| hf | **m** | — | Wetting front suction |
| dist_from_outlet | **m** | — | Channel distance |
| Qout | **m/hr** | — | Output discharge |

### UNIT TRAP TABLE — Common silent errors

| Trap ID | What goes wrong | Symptom | Fix |
|---------|----------------|---------|-----|
| UT-01 | Precip left as mm/day | Discharge 24,000× too high | Divide by 24,000 |
| UT-02 | Precip converted to m/day not m/hr | Discharge 24× too high | Divide by 24 |
| UT-03 | Precip as mm/hr not m/hr | Discharge 1,000× too high | Divide by 1,000 |
| UT-04 | PE left as mm/day | ET massively too high, no runoff | Divide by 24,000 |
| UT-05 | Qobs in m³/s not m/hr | NSE meaningless | Q_mhr = Q_m3s / (area_m2) |
| UT-06 | Channel distance in km not m | Routing delay wrong | Multiply by 1,000 |
| UT-07 | dt in seconds not hours | All fluxes wrong | Use hours |
| UT-08 | TWI distribution doesn't sum to 1 | Water balance error | Normalize |

---

## Pipeline (7 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | (manual) | Select basin, period, forcing source |
| 1 | Forcing prep | `convert_forcing_to_topmodel` | CMFD/MSWX → inputs.dat (rain, PE in m/hr) |
| 2 | TWI generation | `generate_twi_subcat` | DEM + basin → subcat.dat (TWI histogram) |
| 3 | Parameter setup | `generate_params` | Soil/landcover → params.dat |
| 4 | Config assembly | (manual) | Write topmod.run |
| 5 | Execution | `run_topmodel` | Build and run binary |
| 6 | Output analysis | `parse_topmodel_output` | Parse hyd.out → CSV, compute metrics |

---

## Input Files

### topmod.run (configuration)

```
1                          <- stand_alone flag (1=TRUE)
Catchment Name             <- title string
data/inputs.dat            <- path to forcing file
data/subcat.dat            <- path to subcatchment topo data
data/params.dat            <- path to parameters
topmod.out                 <- output file path
hyd.out                    <- hydrograph output path
```

Line 1 must be `1` for standalone mode, `0` for BMI framework coupling.

### inputs.dat (forcing time series)

```
950  1.0                   <- nstep  dt(hours)
  0.0010000  0.0000619  0.0000328   <- rain(m/hr)  pe(m/hr)  Qobs(m/hr)
  0.0010000  0.0000647  0.0000325
  ...
```

- First line: number of time steps, time step size in hours
- Each subsequent line: rain, PE, Qobs — all in **meters/hour**
- Qobs is optional (used only for calibration/comparison in results())

### subcat.dat (topographic index distribution)

```
1  1  0                    <- num_sub_catchments  imap  yes_print_output
Basin Name                 <- subcatchment name
30  1                      <- num_topodex_values  area(fraction, usually 1.0)
0.000001 9.382756          <- dist_area_lnaotb  lnaotb (TWI value)
0.000005 9.076504
...                        <- 30 rows: area fraction and ln(a/tanB)
3                          <- num_channels
0.0  500.  0.5  1000.  1.0  1500.  <- cum_dist_area  dist_from_outlet(m) pairs
$mapfile.dat               <- map file (not used if imap=0)
```

- TWI values ordered from HIGH to LOW
- dist_area_lnaotb[1] should be ~0 (upper limit)
- All dist_area values should sum to ~1.0
- dist_from_outlet in METERS

### params.dat (model parameters)

```
Basin Name
0.032  5.0  50.  3600.0  3600.0  0.05  0.0000328  0.002  0  1.0  0.02  0.1
```

Parameters in order:
szm(m), t0(m/hr), td(hr), chv(m/hr), rv(m/hr), srmax(m),
Q0(m/hr), sr0(m), infex(0/1), xk0(m/hr), hf(m), dth(-)

---

## Output Files

### topmod.out

Contains per-timestep: it, p, ep, Q[it], quz, qb, sbar, qof
Plus water balance summary at end.

### hyd.out

Two columns per timestep: Q_simulated  Q_observed (both in m/hr)

---

## Key Equations

### Saturation deficit
```
deficit_local[i] = sbar + szm * (tl - lnaotb[i])
```
Where `tl` = areal integral of ln(a/tanB), `sbar` = mean catchment deficit.

### Baseflow
```
qb = szq * exp(-sbar / szm)
```
Where `szq = t0 * exp(-tl)` (initialized in init()).

### Unsaturated zone drainage
```
uz = stor_unsat_zone[i] / (deficit_local[i] * td * dt)
```

### Evapotranspiration
```
ea = ep * (1 - deficit_root_zone[i] / srmax)
```

### Total discharge
```
Qout = qb + qof    (then routed through time-delay histogram)
```

---

## Tools Reference

| Tool | Stage | Script Path | Purpose |
|------|-------|-------------|---------|
| `convert_forcing_to_topmodel` | s1 | `tools/convert_forcing_to_topmodel.py` | CMFD/MSWX NetCDF → inputs.dat |
| `generate_twi_subcat` | s2 | `tools/generate_twi_subcat.py` | DEM + basin shapefile → subcat.dat |
| `run_topmodel` | s5 | `tools/run_topmodel.py` | Build, configure, and execute TOPMODEL |
| `parse_topmodel_output` | s6 | `tools/parse_topmodel_output.py` | Parse hyd.out, compute NSE/KGE/PBIAS |

---

## Calibration Parameters

The following parameters are typically calibrated (in order of sensitivity):

1. **szm** (m): Controls baseflow recession shape. Range: 0.001–0.1
2. **t0** (m/hr): Saturated transmissivity. Range: 0.1–100. Often use ln(t0).
3. **srmax** (m): Root zone capacity. Range: 0.001–0.5
4. **td** (hr): Unsaturated zone delay. Range: 1–100
5. **Q0** (m/hr): Initial flow. Estimate from observed baseflow.
6. **sr0** (m): Initial root zone deficit. Usually 0–srmax.

### Default parameter set (after Beven)

```
szm=0.032, t0=5.0, td=50.0, chv=3600, rv=3600,
srmax=0.05, Q0=0.0000328, sr0=0.002, infex=0
```

---

## Converting model output to m³/s

TOPMODEL outputs discharge in **m/hr** (depth per unit area per hour).
To convert to volumetric discharge (m³/s):

```
Q_m3s = Q_mhr * basin_area_m2 / 3600
```

For Bengbu basin (~121,330 km²):
```
Q_m3s = Q_mhr * 121330e6 / 3600
```

---

## Potential Evapotranspiration (PE)

TOPMODEL requires PE as input. Since CMFD does not provide PE directly,
compute using Hargreaves or Penman-Monteith:

### Hargreaves (simplified, for daily PE):
```
PE_mm_day = 0.0023 * (T_mean + 17.8) * (T_max - T_min)^0.5 * Ra
```
Where Ra = extraterrestrial radiation (MJ/m²/day), T in °C.

Then convert: `PE_m_hr = PE_mm_day / 24000`

### From CMFD variables available:
- temp (K) → T_celsius = temp - 273.15
- srad (W/m²) → shortwave radiation
- wind (m/s), pres (Pa), shum (kg/kg) → for Penman-Monteith

---

## TWI Computation

The topographic wetness index ln(a/tanB) requires:
1. DEM (filled, pit-removed)
2. Flow direction grid
3. Contributing area (a) per unit contour length
4. Local slope (tanB)

For each cell: TWI = ln(a / tan(slope))

The distribution is then binned into a histogram (typically 10–30 classes)
with the fraction of catchment area in each TWI class.

---

## Limitations

- **Lumped model**: Single subcatchment, no spatial gridding
- **Shallow soils**: Assumes shallow, highly permeable soils
- **Humid climates**: Not suited for long dry periods
- **Moderate topography**: TWI concept breaks down in very flat or steep terrain
- **No snow**: No snowmelt module in standard TOPMODEL
- **PE must be provided**: Model does not compute PET internally
