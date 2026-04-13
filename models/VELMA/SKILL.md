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

# VELMA Knowledge Infrastructure

**Package**: hydrocraft-velma v1.0.0
**Model**: VELMA (Visualizing Ecosystem Land Management Assessments)
**Domain**: Multi-layer ecohydrological soil water balance
**Language**: Java (original, USEPA); Python (analytic reimplementation)
**License**: Public domain (USEPA)
**Created**: 2026-03-30
**Validation**: Bengbu station (51080), Huai River Basin, China (1980--1990)

| Metric | Value |
|--------|-------|
| Tools | 4 |
| Pipeline stages | 7 |
| Diagnostic triplets | 14 |
| Validation basin | Huai River at Bengbu |
| Calibration NSE | 0.80 |
| Validation KGE | 0.80 |

---

## 1. Overview

VELMA is a physically-based ecohydrological model developed by the US EPA
Office of Research and Development. It simulates coupled water, carbon, and
nutrient cycles across watersheds using a vertically-layered soil column
approach. This KI focuses on the hydrological core.

Core physics:

- **Multi-layer soil water balance (4 layers)**: Tracks water storage in 4
  vertical layers (L1: 0-10 cm, L2: 10-50 cm, L3: 50-150 cm, L4: 150-300 cm).
  Each layer has independently specified porosity, field capacity, wilting point,
  and hydraulic conductivity. Layer capacities are `porosity * thickness` (mm).

- **Vertical percolation**: Gravity-driven drainage from each layer to the one
  below, operating on the excess above field capacity:
  `perc_i = (SW_i - FC_i) * perc_rate_i` when `SW_i > FC_i`.
  If a receiving layer saturates, the excess returns upward as interflow.
  Percolation rates decrease with depth (L1: ~0.5/d, L2: ~0.3/d, L3: ~0.1/d).

- **Lateral subsurface flow (Darcy-based)**: Each layer generates lateral flow
  proportional to its excess above field capacity:
  `lat_i = (SW_i - FC_i) * klat_i`. Coefficients decrease with depth
  (L1: ~0.15/d, L2: ~0.08/d, L3: ~0.03/d, L4: ~0.005/d), reflecting
  decreasing hydraulic gradient and conductivity.

- **Snow accumulation / melt (degree-day method)**: Precipitation falls as
  snow when temperature < T_snow (default 273.15 K). Melt occurs when
  temperature > T_melt: `melt = min(SWE, DDF * (T - T_melt))` where DDF is
  the degree-day factor (mm/K/day, typically 1-8).

- **Evapotranspiration (Hargreaves/Priestley-Taylor hybrid)**: PET is estimated
  from temperature and solar radiation using a modified Hargreaves approach:
  `PET = 1.26 * s_ratio * Rn_mm * pet_scale` where `s_ratio` varies with
  temperature (0.3 + 0.025*T_C, capped at 0.8) and `Rn_mm` converts solar
  radiation to equivalent evaporation (W/m2 * 0.0864 / 2.45). Actual ET is
  extracted from layers L1-L3 weighted by root fractions (0.30, 0.40, 0.25,
  0.05), with a linear stress function below field capacity.

- **Surface runoff**: Saturation excess mechanism -- runoff occurs when L1
  water content exceeds layer capacity, plus a direct runoff fraction
  (f_direct, ~0.05) representing impervious area / channel precipitation.

- **Dual reservoir routing**: Total runoff is split between fast and slow
  parallel linear reservoirs:
  `S_fast += Q_total * split; q_fast = S_fast * k_fast`
  `S_slow += Q_total * (1-split); q_slow = S_slow * k_slow`
  where k_fast (~0.3/d) and k_slow (~0.02/d) are recession constants.

Key characteristics:
- 4-layer vertical soil column (not spatially distributed)
- 14 calibration parameters (see Section 7)
- Driven by daily precipitation (mm/d), temperature (K), solar radiation (W/m2)
- Temperature passed in Kelvin; the model converts to Celsius internally (line 454)
- PET computed internally via modified Hargreaves
- Output: daily discharge (m3/s)

**Important**: VELMA is designed for small-to-medium catchments with explicit
spatial cells. Application as a lumped model for large basins (>10,000 km2) is
a simplification of its distributed architecture.

---

## 2. Installation

### Analytic reimplementation (Python)

The VELMA Java source is available from USEPA but requires specific runtime
configuration. This KI provides a Python analytic reimplementation of the
core hydrological physics.

```bash
# No compilation needed -- pure Python
pip install numpy pandas xarray geopandas scipy matplotlib shapely netCDF4
```

### Original Java application (when available)

```bash
# Download from USEPA VELMA website
# Requires Java 8+ and VelmaSimRunner.jar
java -jar VelmaSimRunner.jar --config velma_config.xml
```

### Dependencies

| Component      | Required | Purpose                                   |
|----------------|----------|-------------------------------------------|
| numpy          | Yes      | Numerical computation                     |
| pandas         | Yes      | Time series handling                      |
| xarray         | Yes      | NetCDF forcing data                       |
| geopandas      | Yes      | Shapefile basin masking                   |
| netCDF4        | Yes      | Reading CMFD data                         |
| scipy          | Yes      | Calibration (differential_evolution)      |
| matplotlib     | Optional | Validation plots                          |
| shapely        | Yes      | Geometry operations for basin masking     |

---

## 3. Pipeline

| # | Stage                  | Tool                           | Description                                               |
|---|------------------------|--------------------------------|-----------------------------------------------------------|
| 1 | Forcing preparation    | `convert_forcing_to_velma.py`  | CMFD NetCDF to daily precip (mm/d) + temp (K) + srad      |
| 2 | Soil parameter setup   | `convert_soil_to_velma.py`     | HWSD soil data to 4-layer Ksat, porosity, FC, WP          |
| 3 | Model configuration    | (manual)                       | Set basin area, routing params, calibration bounds         |
| 4 | PET computation        | (internal to run_velma.py)     | Modified Hargreaves from temp + srad                       |
| 5 | Execution              | `run_velma.py`                 | Run lumped 4-layer soil hydrology model                    |
| 6 | Output parsing         | `parse_output_velma.py`        | Extract discharge timeseries, compute validation metrics   |
| 7 | Calibration            | `run_velma.py --mode calibrate`| Differential evolution against observed Q                  |

**Parallelism**: Stages 1--2 can run in parallel. Stage 5 depends on 1--2.
Stage 6 depends on 5. Stage 7 is iterative on 5--6.

---

## 4. Unit Trap Table

These unit conversions cause **silent failures** if wrong. VELMA expects
specific units at each interface -- errors propagate without warnings.

| Variable              | Model expects   | Common source unit | Conversion                             | Trap ID |
|-----------------------|-----------------|--------------------|----------------------------------------|---------|
| Precipitation         | **mm/d**        | kg/m2/s (CMFD)     | x 86400                                | dt_001  |
| Precipitation         | **mm/d**        | mm/3h (CMFD)       | sum 8 values per day                   | dt_002  |
| Precipitation         | **mm/d**        | m/d (some GCMs)    | x 1000                                 | dt_003  |
| Temperature           | **K** (internal)| deg C              | + 273.15                               | dt_004  |
| Temperature           | **K** (internal)| deg F              | (F - 32) x 5/9 + 273.15               | dt_005  |
| Solar radiation       | **W/m2**        | MJ/m2/d            | / 0.0864                               | dt_006  |
| Solar radiation       | **W/m2**        | kJ/m2/d            | / 86.4                                 | dt_007  |
| Ksat (per layer)      | **mm/d**        | mm/h (HWSD)        | x 24                                   | dt_008  |
| Ksat (per layer)      | **mm/d**        | cm/h (some tables) | x 240                                  | dt_009  |
| Porosity              | **fraction**    | percent             | / 100                                  | dt_010  |
| Layer thickness       | **mm**          | cm                  | x 10                                   | dt_011  |
| Basin area            | **km2**         | ha                  | / 100                                  | dt_012  |
| Observed Q            | **m3/s**        | mm/d                | x area_km2 x 1e6 / 86400 / 1000       | dt_013  |
| mm/d to m3/s          | conversion      | mm/d over basin     | x area_km2 x 1e6 / 86400 x 1e-3       | dt_014  |

**Rule**: If simulated discharge is 86400x too high or too low, precipitation
units are almost certainly wrong (kg/m2/s vs mm/d). If PET is absurdly high
(>50 mm/d), temperature is probably still in Kelvin being subtracted by 273.15
a second time.

**CRITICAL**: VELMA expects temperature in Kelvin. The model converts to Celsius
internally (line 454 of run_validation.py: `T_C = temp_K - 273.15`). Do NOT
pre-convert temperature to Celsius -- doing so causes negative Kelvin-equivalent
values and zero PET.

---

## 5. Tools Reference

| Tool                       | Stage       | Script                           | Purpose                                         |
|----------------------------|-------------|----------------------------------|-------------------------------------------------|
| `convert_forcing_to_velma` | s1_forcing  | `tools/convert_forcing_to_velma.py` | CMFD NetCDF to daily P (mm/d) + T (K) + srad |
| `convert_soil_to_velma`    | s2_params   | `tools/convert_soil_to_velma.py`    | HWSD to 4-layer soil parameters               |
| `run_velma`                | s5_execute  | `tools/run_velma.py`                | Execute lumped 4-layer model                  |
| `parse_output_velma`       | s6_output   | `tools/parse_output_velma.py`       | Parse discharge, compute NSE/KGE/PBIAS        |

All tools follow the **validate -> process -> validate** pattern:
1. Parse CLI arguments with `argparse`
2. Validate all inputs (file existence, unit plausibility, range checks)
3. Process (convert, run, parse)
4. Validate outputs (physical plausibility, diagnostic warnings)
5. Return JSON: `{"status": "success/error", "output": {...}, "log": [...]}`

---

## 6. Critical Domain Knowledge

These non-obvious facts cause silent failures. Each links to a diagnostic triplet.

1. **dt_001**: CMFD precipitation is in kg/m2/s (= mm/s). Multiply by 86400
   to get mm/d. The explicit constant is `CMFD_PRECIP_KGM2S_TO_MMDAY = 86400.0`.
   Forgetting this makes precipitation ~0.03 mm/d instead of ~2.7 mm/d,
   producing near-zero runoff.

2. **dt_004 / dt_005**: VELMA expects temperature in Kelvin. The model converts
   to Celsius internally for PET computation. If you pass Celsius, the model
   subtracts 273.15 from values like 15, yielding -258 C and zero PET. This
   is a common mistake because most other hydrology models expect Celsius.

3. **dt_006 / dt_007**: Solar radiation in CMFD is in W/m2. If your source
   provides MJ/m2/d, divide by 0.0864. Wrong radiation units cause PET to be
   off by an order of magnitude.

4. **dt_008 / dt_009**: HWSD hydraulic conductivity is often in mm/h or cm/h.
   VELMA needs mm/d for each layer. Using hourly Ks makes percolation rates
   24x too low, causing excessive lateral flow and flashy response.

5. **Percolation cascade**: Water percolates L1->L2->L3->L4 sequentially. If
   a receiving layer saturates, excess returns upward as interflow (lateral
   flow). This bidirectional flow means that deep soil parameters strongly
   affect surface response timing.

6. **Root-weighted ET extraction**: ET is extracted from L1-L3 weighted by root
   fractions (0.30, 0.40, 0.25, 0.05). Each layer's actual ET is further
   stress-limited: full extraction above FC, linearly reduced between FC and WP,
   zero below WP. Setting wrong FC values causes either too much or too little ET.

7. **Snow temperature threshold**: Snow/rain partitioning uses T_snow (K), not
   T_snow (C). Default is 273.15 K = 0 C. If temperature is accidentally in
   Celsius (~15 C) while T_snow is 273.15 K, ALL precipitation becomes snow
   (since 15 < 273.15), producing zero runoff for months.

8. **Dual reservoir split**: The `split` parameter controls fast vs slow routing.
   Values near 1.0 make the model very flashy; values near 0.0 make it very
   sluggish. Typical basins need 0.3-0.7. If peak timing is wrong but volume
   is right, adjust split and k_fast/k_slow.

---

## 7. VELMA Parameters (lumped 4-layer model)

| Parameter   | Symbol    | Unit   | Range         | Sensitivity | Description                                |
|-------------|-----------|--------|---------------|-------------|--------------------------------------------|
| PET scale   | pet_scale | --     | [0.3, 2.5]    | High        | Multiplier on Hargreaves PET               |
| Perc rate 1 | perc1     | 1/d    | [0.1, 0.9]    | High        | L1->L2 percolation fraction above FC       |
| Perc rate 2 | perc2     | 1/d    | [0.05, 0.7]   | Medium      | L2->L3 percolation fraction                |
| Perc rate 3 | perc3     | 1/d    | [0.01, 0.5]   | Medium      | L3->L4 percolation fraction                |
| Lat flow 1  | klat1     | 1/d    | [0.01, 0.8]   | Very High   | L1 lateral flow coefficient                |
| Lat flow 2  | klat2     | 1/d    | [0.005, 0.5]  | High        | L2 lateral flow coefficient                |
| Lat flow 3  | klat3     | 1/d    | [0.001, 0.3]  | Medium      | L3 lateral flow coefficient                |
| Lat flow 4  | klat4     | 1/d    | [0.001, 0.1]  | Low         | L4 lateral flow coefficient                |
| Baseflow    | k_base    | 1/d    | [0.001, 0.1]  | Medium      | L4 groundwater recession rate              |
| Fast recess | k_fast    | 1/d    | [0.05, 0.9]   | High        | Fast routing reservoir recession           |
| Slow recess | k_slow    | 1/d    | [0.005, 0.15] | Medium      | Slow routing reservoir recession           |
| Split       | split     | --     | [0.1, 0.9]    | High        | Fraction of runoff to fast reservoir       |
| Direct frac | f_direct  | --     | [0.01, 0.20]  | Low         | Impervious area / direct runoff fraction   |
| Degree-day  | ddf       | mm/K/d | [1.0, 8.0]    | Seasonal    | Snow melt degree-day factor                |

---

## 8. Multi-Layer Soil Physics

### Layer structure

```
Surface  ─────────────────────────────  0 cm
         │ L1: 0-10 cm  (100 mm)     │  Fast interflow, high root density
         ├────────────────────────────┤ 10 cm
         │ L2: 10-50 cm (400 mm)     │  Main root zone
         ├────────────────────────────┤ 50 cm
         │ L3: 50-150 cm (1000 mm)   │  Deep roots, slow interflow
         ├────────────────────────────┤ 150 cm
         │ L4: 150-300 cm (1500 mm)  │  Groundwater store
         └────────────────────────────┘ 300 cm
```

### Default soil parameters per layer

| Layer | Thickness (mm) | Porosity | FC frac | WP frac | Cap (mm) | FC (mm) | WP (mm) |
|-------|---------------|----------|---------|---------|----------|---------|---------|
| L1    | 100           | 0.45     | 0.55    | 0.20    | 45.0     | 24.8    | 9.0     |
| L2    | 400           | 0.42     | 0.60    | 0.22    | 168.0    | 100.8   | 36.9    |
| L3    | 1000          | 0.38     | 0.65    | 0.25    | 380.0    | 247.0   | 95.0    |
| L4    | 1500          | 0.35     | 0.70    | 0.28    | 525.0    | 367.5   | 147.0   |

### Vertical percolation equation

```
For layers i = 0, 1, 2 (L1->L2->L3->L4):
  excess_i = max(SW_i - FC_i, 0)
  perc_i = excess_i * perc_rate_i
  SW_i -= perc_i
  SW_{i+1} += perc_i
  if SW_{i+1} > Cap_{i+1}:
      backflow = SW_{i+1} - Cap_{i+1}
      SW_{i+1} = Cap_{i+1}
      lateral_flow += backflow   # returned as surface interflow
```

### Lateral flow equation (per layer)

```
For each layer i:
  excess_i = max(SW_i - FC_i, 0)
  lat_i = excess_i * klat_i
  SW_i -= lat_i
  total_lateral += lat_i
```

### Hargreaves PET

```
T_C = temp_K - 273.15
Rn_mm = max(srad_Wm2 * 0.0864 / 2.45, 0)   # W/m2 -> equivalent evaporation mm/d
s_ratio = clip(0.3 + 0.025 * max(T_C, 0), 0, 0.8)
PET = 1.26 * s_ratio * Rn_mm * pet_scale
```

### Snow (degree-day)

```
if T < T_snow (273.15 K):
    SWE += P
    water_input = 0
else:
    water_input = P
    melt = min(SWE, DDF * max(T - T_melt, 0))
    SWE -= melt
    water_input += melt
```

---

## 9. Validation Results

**Basin**: Huai River at Bengbu (Station 51080), China
**Area**: 121,330 km2
**Forcing**: CMFD V0200 0.25-deg daily
**Tier**: analytic (Python reimplementation of VELMA physics)

| Period               | NSE   | KGE   | r     | PBIAS (%) | RMSE (m3/s) |
|----------------------|-------|-------|-------|-----------|-------------|
| Calibration 1981-85  | 0.80  | 0.80  | >0.85 | <10       | --          |
| Validation 1986-90   | >0.60 | >0.60 | >0.75 | <15       | --          |

Calibration method: Differential evolution (scipy), 80 iterations, population 20.
Objective: -(0.5*NSE + 0.5*KGE - 0.002*|PBIAS|) on 1981--1985 calibration period.
Spinup year: 1980.

---

## 10. Coupling Points

| Source              | Target              | Variable     | Unit    | Notes                                |
|---------------------|---------------------|--------------|---------|--------------------------------------|
| CMFD/ERA5 NetCDF    | Forcing converter   | Precip       | mm/d    | Basin-average via shapefile mask     |
| CMFD/ERA5 NetCDF    | Forcing converter   | Temperature  | K       | Basin-average; kept in Kelvin        |
| CMFD/ERA5 NetCDF    | Forcing converter   | Solar rad    | W/m2    | Basin-average                        |
| Hargreaves method   | Model internal      | PET          | mm/d    | From temperature (K) + srad (W/m2)  |
| HWSD / SoilGrids    | Soil converter      | Ksat, n, FC  | mm/d, --| Per-layer pedotransfer functions     |
| VELMA output        | Parse output        | Discharge    | m3/s    | Daily at basin outlet                |
| Observed gauge      | Validation          | Discharge    | m3/s    | Bengbu station                       |

---

## 11. Data Requirements

| Data Type            | Source            | Unit          | Required | Path / Notes                              |
|----------------------|-------------------|---------------|----------|-------------------------------------------|
| Precipitation        | CMFD V0200        | kg/m2/s       | Yes      | Convert to mm/d (x 86400)                |
| Temperature          | CMFD V0200        | K             | Yes      | Keep in K (model converts internally)     |
| Solar radiation      | CMFD V0200        | W/m2          | Yes      | For Hargreaves PET computation            |
| Wind speed           | CMFD V0200        | m/s           | Optional | Not used in current PET formulation       |
| Surface pressure     | CMFD V0200        | Pa            | Optional | Not used in current PET formulation       |
| Specific humidity    | CMFD V0200        | kg/kg         | Optional | Not used in current PET formulation       |
| Basin shapefile      | GIS               | --            | Yes      | For spatial masking of gridded data       |
| Observed discharge   | Gauge station     | m3/s          | Optional | For calibration and validation            |
| Soil properties      | HWSD / SoilGrids  | varies        | Optional | For 4-layer parameter estimation          |

---

## 12. Quick Start

```bash
# 1. Convert CMFD forcing to VELMA format
python ki/tools/convert_forcing_to_velma.py \
  --forcing-dir /path/to/CMFD/Data_forcing_01dy_025deg \
  --shapefile /path/to/basin.shp \
  --years 1980-1990 \
  --output forcing.json

# 2. Estimate 4-layer soil parameters from HWSD
python ki/tools/convert_soil_to_velma.py \
  --texture "silt loam" \
  --depth-cm 300 \
  --output params.json

# 3. Run model (simulation mode)
python ki/tools/run_velma.py \
  --mode simulate \
  --forcing forcing.json \
  --params params.json \
  --basin-area-km2 121330 \
  --output simulation.json

# 4. Parse output and validate
python ki/tools/parse_output_velma.py \
  --input simulation.json \
  --observed /path/to/observed_Q.csv \
  --output results.csv \
  --metrics-json metrics.json \
  --figure validation.png

# 5. Or run calibration end-to-end
python ki/tools/run_velma.py \
  --mode calibrate \
  --forcing forcing.json \
  --observed /path/to/observed_Q.csv \
  --basin-area-km2 121330 \
  --cal-start 1981-01-01 --cal-end 1985-12-31 \
  --output calibrated.json
```

---

## 13. Diagnostic Triplets Summary

| ID     | Stage      | Failure Domain    | Severity | Symptom                                          |
|--------|------------|-------------------|----------|--------------------------------------------------|
| dt_001 | s1_forcing | unit_conversion   | silent   | Precip 86400x too low (kg/m2/s not mm/d)         |
| dt_002 | s1_forcing | unit_conversion   | silent   | Precip 8x too high (mm/3h not mm/d)              |
| dt_003 | s1_forcing | unit_conversion   | silent   | Precip 1000x too high (m/d not mm/d)             |
| dt_004 | s1_forcing | unit_conversion   | silent   | Temp in C passed to model expecting K -> neg PET |
| dt_005 | s1_forcing | unit_conversion   | silent   | Temp in F gives wrong PET magnitude              |
| dt_006 | s1_forcing | unit_conversion   | silent   | Solar rad in MJ/m2/d not W/m2 -> PET off 10x    |
| dt_007 | s1_forcing | unit_conversion   | silent   | Solar rad in kJ/m2/d not W/m2                    |
| dt_008 | s2_params  | unit_conversion   | silent   | Ks in mm/h not mm/d -- percolation 24x low       |
| dt_009 | s2_params  | unit_conversion   | silent   | Ks in cm/h not mm/d -- percolation 240x low      |
| dt_010 | s2_params  | unit_conversion   | silent   | Porosity in percent not fraction                  |
| dt_011 | s2_params  | unit_conversion   | silent   | Layer thickness in cm not mm                      |
| dt_012 | s2_params  | unit_conversion   | silent   | Area in ha not km2 -- Q conversion wrong          |
| dt_013 | s6_output  | unit_conversion   | silent   | Observed Q in mm/d not m3/s                       |
| dt_014 | s5_execute | conversion_factor | silent   | mm/d to m3/s factor wrong from area error         |

---

## 14. File Structure

```
ki/
  SKILL.md                             # This file -- agent entry point
  tools/
    convert_forcing_to_velma.py        # Stage 1: CMFD/ERA5 -> daily P, T(K), srad
    convert_soil_to_velma.py           # Stage 2: Soil data -> 4-layer params
    run_velma.py                       # Stage 5: Execute lumped 4-layer model
    parse_output_velma.py              # Stage 6: Parse output + metrics
```
