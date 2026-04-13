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

# SWAP v4.2.0 (Soil-Water-Atmosphere-Plant) — Knowledge Infrastructure

**Package**: `hydrocraft-swap-soil` v1.0.0
**Model**: SWAP v4.2.0
**Developer**: Wageningen University and Research (WUR), The Netherlands
**Last updated**: 2026-03-28
**Stats**: 5 tools | 6 skill documents | 17 diagnostic triplets | ~1,200 lines of validated Python
**Validation status**: `analytic` (Hupselbrook case, Netherlands, 2002-2004)

---

## Overview

This knowledge infrastructure enables autonomous simulation of vadose zone water, solute, and heat transport using SWAP (Soil-Water-Atmosphere-Plant) on any field site worldwide, **without manual data preparation**. The 5 validated tools replace the standard manual SWAP workflow with a Python pipeline that integrates with HydroCraft's forcing, soil, and observation infrastructure.

**What SWAP does**: 1D vertical transport model for variably saturated soils. Simulates:
- Soil water flow (Richards' equation with Mualem-van Genuchten hydraulics)
- Evapotranspiration (Penman-Monteith, crop factors, or reference ET)
- Crop growth (simple, WOFOST general, WOFOST grass)
- Solute transport (convection-dispersion, adsorption, decay)
- Heat transport (analytical or numerical)
- Snow accumulation and melt
- Macropore flow (bypass flow, dual-permeability)
- Drainage (Hooghoudt, Ernst, multi-level systems)
- Irrigation scheduling (deficit-based, fixed, or managed)

**Key difference from other HydroCraft models**: SWAP operates at field scale (1D vertical column, single point), not gridded. It couples with WOFOST for detailed crop growth and can interface with regional groundwater models.

---

## Installation

### Binary (built from source)

```
SWAP v4.2.0:  Built via Meson + Fortran compiler (gfortran or Intel ifx)
Source:       github.com/SWAP-model/swap
Platform:     Linux x86-64, Windows x86-64
Dependencies: ttutil library v4.2.7 (auto-downloaded by Meson build)
```

### Build from source

```bash
cd source/repo
meson setup builddir
meson compile -C builddir
# Binary: builddir/swap
```

### Test case

```
tests/cases/1.hupselbrook/     # Hupselbrook, Netherlands
  swap.swp                     # Main configuration file
  283.met                      # Daily meteorological data (KNMI station 283)
  grassd.crp, maizes.crp, potatod.crp  # Crop parameter files
  swap.dra                     # Drainage configuration
  run_swap.sh                  # Execution script
```

**Validated**: SWAP runs successfully on Hupselbrook. Water balance for 2002:
- Rain+snow: 84.18 cm, Transpiration: 38.17 cm, Soil evaporation: 16.69 cm, Drainage: 22.11 cm

---

## Pipeline (8 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | (manual) | Site selection, period, forcing source |
| 1 | Met forcing | `convert_forcing_to_swap` | CMFD/MSWX → SWAP .met format (unit conversions) |
| 2 | Soil parameters | `convert_soil_to_swap` | HWSD → van Genuchten parameters for .swp file |
| 3 | Config assembly | (manual with templates) | Build .swp, .crp, .dra, .bbc from parameters |
| 4 | Execution | `run_swap` | Run SWAP binary with preflight checks |
| 5 | Output parsing | `parse_swap_output` | Extract .blc/.inc/.csv results to structured CSV |
| 6 | Visualization | `plot_swap_results` | Water balance, soil moisture profiles, ET timeseries |
| 7 | Validation | (manual) | Compare against observations |

---

## Unit Trap Table (CRITICAL — read before preparing ANY input)

These are the most common silent-failure unit conversions. Getting any one wrong produces
plausible but incorrect results with no error message.

| Variable | External Source | SWAP Expects | Conversion | Trap |
|----------|---------------|--------------|------------|------|
| Radiation (Rad) | W/m² (CMFD), W/m² (MSWX) | kJ/m²/d | × 86.4 (daily) or × period_seconds/1000 | ×1000 internal to J/m²/d |
| Temperature | K (CMFD/MSWX) | °C | − 273.15 | Must subtract, not divide |
| Humidity (Hum) | kg/kg specific (CMFD), kg/kg (MSWX) | kPa (vapor pressure) | Convert via Clausius-Clapeyron | NOT relative humidity 0-1 |
| Rainfall (Rain) | mm/day (CMFD), mm/3hr (MSWX) | mm/d | CMFD: direct; MSWX: ×8 | Internal: ×0.1 to cm |
| Wind speed | m/s | m/s at measurement height | Direct, but specify ALTW correctly | Default ALTW=10m |
| ETref | mm/d | mm/d | Direct (only if SWETR=1) | Not needed if SWETR=0 |
| Pressure head | Positive depth (some DBs) | Negative cm (unsaturated) | Negate and convert to cm | Sign convention critical |
| Ksat | m/d, m/s | cm/d | × 100 (m/d), × 8.64e6 (m/s) | Orders of magnitude error |
| Bulk density | kg/m³, g/cm³ | mg/cm³ (= kg/m³) | g/cm³ × 1000 | Range: 100-10000 |
| Drain spacing | m | m (some params in cm) | Check parameter docs carefully | Mix of m and cm units |
| Irrigation depth | mm | mm in .swp file | Direct | But internal conversion to cm |
| Solute concentration | mg/L | mg/cm³ (= mg/mL = g/L) | mg/L ÷ 1000 | 3 orders of magnitude |
| Soil depth | m (HWSD) | cm (SWAP) | × 100 | All depths in cm |

### Internal conversion chain (executed by SWAP automatically):

```
Input .met file:
  Rad (kJ/m²/d)  →  × 1000  →  J/m²/d  (readmeteo.f90)
  Rain (mm/d)     →  × 0.1   →  cm/d    (readmeteo.f90)
  Hum (kPa)       →  direct  →  kPa     (used in Penman-Monteith)
  Tmin, Tmax (°C) →  direct  →  °C      (+ 273.15 for some calcs)
  Wind (m/s)      →  direct  →  m/s     (height-adjusted in penmon.f90)
```

---

## Input File Reference

### .met file (Meteorological forcing)

```
* Comment lines start with * or !
Station,DD,MM,YYYY,Rad,Tmin,Tmax,Hum,Wind,Rain,ETref,Wet
'STA',01,01,2002,3810.0,-3.2,-0.1,0.523764,4.9,0.000,0.4,0.000
```

| Column | Units | Range | Description |
|--------|-------|-------|-------------|
| Station | string | — | Station identifier in quotes |
| DD | integer | 1-31 | Day of month |
| MM | integer | 1-12 | Month |
| YYYY | integer | — | Year |
| Rad | kJ/m²/d | 0-50000 | Global solar radiation |
| Tmin | °C | -50..50 | Minimum air temperature |
| Tmax | °C | -50..60 | Maximum air temperature |
| Hum | kPa | 0-10 | Actual vapor pressure |
| Wind | m/s | 0-150 | Wind speed at ALTW height |
| Rain | mm/d | 0-1000 | Daily precipitation |
| ETref | mm/d | 0-100 | Reference ET (only if SWETR=1) |
| Wet | fraction | 0-1 | Wet duration fraction of day |

### .swp file (Main configuration)

Key-value format with `*` comment lines. Sections:
1. General (paths, period, output switches)
2. Meteorology (met file, Penman-Monteith params)
3. Crop (rotation schedule, crop file references)
4. Soil water (initial conditions, discretization, MvG params, numerics)
5. Lateral drainage (Hooghoudt/Ernst or flux tables)
6. Bottom boundary (GWL, flux, free drainage, etc.)
7. Heat flow (analytical or numerical)
8. Solute transport (CDE parameters)

### .crp file (Crop parameters)

Three types: simple (CROPTYPE=1), WOFOST general (CROPTYPE=2), WOFOST grass (CROPTYPE=3).
Contains: development stages, LAI tables, root growth, water stress functions (Feddes/de Jong van Lier), oxygen stress, salt stress, interception.

### .dra file (Drainage)

Three methods: DRAMET=1 (flux-GWL table), DRAMET=2 (Hooghoudt/Ernst equations), DRAMET=3 (multi-level resistance).

### .bbc file (Bottom boundary)

Eight options: SWBOTB=1 (prescribed GWL), 2 (prescribed flux), 3 (aquifer head), 4 (GWL-flux relation), 5 (prescribed pressure head), 6 (zero flux), 7 (free drainage), 8 (free outflow).

---

## Output File Reference

| Extension | Content | Key Variables |
|-----------|---------|---------------|
| .blc | Detailed yearly water balance | Rain, interception, runoff, transpiration, evaporation, drainage, bottom flux (all in cm) |
| .bal | Summary yearly water balance | Same as .blc, condensed |
| .inc | Water balance increments (daily) | Cumulative fluxes per output interval (cm) |
| .vap | Soil profiles at output dates | z(cm), theta(-), h(cm), K(cm/d) |
| .ate | Soil temperature profiles | z(cm), T(°C) |
| .wba | Cumulative daily water balance | Running totals of all flux components (cm) |
| .sba | Cumulative daily solute balance | Solute mass components (mg/cm²) |
| .end | End conditions (restart file) | Final h, theta, T per compartment |
| .csv | Custom CSV output | User-selected variables via INLIST_CSV |
| .crp | Crop growth output | DVS, LAI, biomass, rooting depth |

---

## Critical Domain Knowledge

### 1. Humidity is vapor pressure, NOT relative humidity
SWAP .met files expect actual vapor pressure in kPa. This is NOT relative humidity (0-1 or 0-100%). To convert from specific humidity (kg/kg) as in CMFD/MSWX:
```python
e_sat = 0.6108 * exp(17.27 * T_C / (T_C + 237.3))  # kPa, Magnus formula
e_actual = q * P / (0.622 + 0.378 * q)                # kPa, from specific humidity
```
Where T_C is temperature in °C, q is specific humidity (kg/kg), P is pressure in kPa.

### 2. Radiation must be in kJ/m²/d
CMFD and MSWX provide radiation in W/m² (instantaneous). For daily SWAP input:
```python
Rad_kJ = Rad_Wm2 * 86400 / 1000  # W/m² → kJ/m²/d
```
SWAP internally converts kJ/m²/d → J/m²/d (×1000) for Penman-Monteith.

### 3. Pressure heads are NEGATIVE in unsaturated zone
All h values above the water table are negative. h = 0 at saturation, h < 0 above.
Common mistake: entering positive values from databases that store |h|.

### 4. Depth convention: surface = 0, downward = negative
Soil depths in SWAP are measured from the surface (z = 0) downward (z < 0).
Compartment boundaries: -1, -2, ..., -200 cm (typical profile).

### 5. All path and file names MUST be lowercase on Linux
SWAP on Linux requires all file references in .swp to be lowercase. Windows is case-insensitive but Linux is not. This causes silent "file not found" errors.

### 6. Time step control is critical for convergence
DTMIN (1e-7 to 0.1 d) and DTMAX (dtmin to 1 d) control Richards' equation solver.
Too large DTMAX → oscillations/non-convergence. Too small DTMIN → excessive runtime.
Recommended: DTMIN=1e-6, DTMAX=0.04 for standard cases.

### 7. Mualem-van Genuchten parameter ranges
Typical sandy soil:  ORES=0.01-0.05, OSAT=0.35-0.45, ALFA=0.02-0.05, NPAR=1.5-3.0
Typical clay soil:   ORES=0.05-0.10, OSAT=0.40-0.55, ALFA=0.005-0.02, NPAR=1.1-1.5
Ksat: sand 10-100 cm/d, clay 0.1-10 cm/d

### 8. Water balance closure check
The .blc file provides In/Out totals. Sum(In) - Sum(Out) should equal storage change.
Deviation > 0.01 cm indicates numerical issues. Check CRITDEVH1CP and MAXIT.

### 9. Crop rotation dates must not overlap
Each crop period (CROPSTART to CROPEND) must not overlap with adjacent crops.
Between crops, the soil is treated as bare.

---

## Tool Reference

| Tool | Script | Purpose | Key Inputs | Key Outputs |
|------|--------|---------|------------|-------------|
| convert_forcing_to_swap | `tools/convert_forcing_to_swap.py` | CMFD/MSWX → .met | NetCDF forcing, lat/lon | .met file |
| convert_soil_to_swap | `tools/convert_soil_to_swap.py` | HWSD → MvG params | HWSD raster, lat/lon | Soil parameter table |
| run_swap | `tools/run_swap.py` | Execute SWAP binary | .swp file, binary path | Exit code, output files |
| parse_swap_output | `tools/parse_swap_output.py` | Extract results to CSV | SWAP output dir | Structured CSV files |
| plot_swap_results | `tools/plot_swap_results.py` | Visualization | Parsed CSV files | PNG figures |

---

## Diagnostic Quick Reference

| ID | Symptom | Root Cause | Fix |
|----|---------|-----------|-----|
| dt_001 | Extreme ET, soil dries instantly | Radiation in W/m² instead of kJ/m²/d | ÷ (86400/1000) |
| dt_002 | Extreme evaporation, no transpiration | Humidity as RH fraction instead of kPa | Convert via Magnus |
| dt_003 | Waterlogged soil, unrealistic runoff | Rainfall in mm/3hr not aggregated to mm/d | Sum 3hr → daily |
| dt_004 | Temperature sum never reached | Temperature in K instead of °C | − 273.15 |
| dt_005 | No drainage, GWL at surface | Ksat in m/s instead of cm/d | × 8.64e6 |
| dt_006 | "File not found" on Linux | Uppercase characters in file paths | Lowercase all paths |
| dt_007 | Convergence failure, tiny timesteps | DTMAX too large for clay soils | Reduce DTMAX to 0.01 |
| dt_008 | Zero crop growth | CROPSTART after actual emergence | Check dates match reality |
| dt_009 | Oscillating water table | GWLCONV too loose | Tighten to 1-10 cm |
| dt_010 | All water drains immediately | ORES/OSAT swapped or unrealistic | Check MvG parameter order |
