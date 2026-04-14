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

# Daisy v7.1.4 (Soil-Crop-Water Simulation Model) — Knowledge Infrastructure

**Package**: `hydrocraft-daisy-soil` v1.0.0
**Model**: Daisy v7.1.4 — Mechanistic simulation of agricultural fields
**Origin**: Agrohydrology Group, University of Copenhagen
**Last updated**: 2026-03-25
**Stats**: 4 tools | 6 skill documents | 18 diagnostic triplets | ~2,500 lines of validated Python
**Validation status**: `example_validated` (Taastrup, Denmark, 1986-1988)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for meteorological forcing documentation.
See `data_ki/HWSD/SKILL.md` for soil property documentation.
See `data_ki/RISMA/SKILL.md` for soil moisture observations.


## Overview

This knowledge infrastructure enables autonomous simulation of agricultural field processes
using the Daisy model, covering water, nitrogen, carbon, and pesticide dynamics in the
soil-plant-atmosphere system. The 4 validated tools replace manual `.dai` file editing with
a Python pipeline that integrates with global forcing data and standardized soil databases.

**What Daisy does**: 1D mechanistic model for agricultural field simulation. Simulates:
- Soil water transport (Richards equation, macropore flow, preferential flow)
- Soil heat transport (conduction, convection)
- Nitrogen dynamics (mineralization, nitrification, denitrification, plant uptake)
- Carbon turnover (multi-pool organic matter model: SOM, SMB, AOM)
- Crop growth (phenology, photosynthesis, root growth, water/N stress)
- Pesticide fate (sorption, degradation, transport)
- Field management (tillage, fertilization, irrigation, sowing, harvest)
- Groundwater coupling (deep drainage, aquifer interaction)
- Snow and frost dynamics

**Key architectural features**:
- Lisp-like configuration language (`.dai` files)
- Daisy Weather File format (`.dwf`) for meteorological forcing
- Daisy Log File format (`.dlf`) for tabular output
- Library system for reusable soil, crop, management, and log definitions
- Built-in pedotransfer functions (Cosby, HYPRES, van Genuchten)
- Batch and spawn modes for multi-scenario runs

---

## Installation

### Building from source (Linux)

```bash
# Dependencies
apt install g++ cmake libsuitesparse-dev libboost-filesystem-dev python3-pybind11

# Clone and build
git clone https://github.com/daisy-model/daisy.git
cd daisy
mkdir -p build/linux-gcc-portable
cmake . -B build/linux-gcc-portable --preset linux-gcc-portable
cmake --build build/linux-gcc-portable -j $(nproc)

# Binary location
build/linux-gcc-portable/daisy

# Verify
build/linux-gcc-portable/daisy -v
```

### Pre-built packages

```
deb:     apt install ./daisy_7.1.4_amd64.deb
flatpak: flatpak install --user daisy-7.1.4.flatpak
```

### Python dependencies (for KI tools)

```
numpy, pandas, matplotlib, pyyaml
```

---

## Pipeline Stages

The Daisy simulation pipeline consists of 6 stages:

| Stage | Name | Tool | Input | Output |
|-------|------|------|-------|--------|
| S1 | Weather Preparation | `convert_weather_to_dwf.py` | Global forcing (CSV/NetCDF) | `.dwf` file |
| S2 | Soil Definition | `convert_soil_to_dai.py` | HWSD/texture data | Soil `.dai` file |
| S3 | Setup Generation | Manual / template | Weather + Soil + Management | Main `.dai` file |
| S4 | Execution | `run_daisy.py` | Main `.dai` file | `.dlf` output files |
| S5 | Output Analysis | `parse_daisy_output.py` | `.dlf` files | CSV + figures |
| S6 | Validation | Manual | Observed + simulated | Metrics + figures |

---

## Input Format Reference

### Weather File (`.dwf`)

The Daisy Weather File is a custom text format with header metadata and columnar data.

**Header section** (keyword: value pairs):
```
dwf-0.0 -- Description text
Station: Taastrup
Elevation: 30 m
Longitude: 12 dgEast
Latitude: 56 dgNorth
TimeZone: 15 dgEast
Surface: reference
ScreenHeight: 2.0 m
Begin: 1962-04-01
End: 2008-10-31
Timestep: 24 hours
NH4WetDep: 0.9 ppm
NH4DryDep: 2.2 kgN/ha/year
NO3WetDep: 0.6 ppm
NO3DryDep: 1.1 kgN/ha/year
TAverage: 7.8 dgC
TAmplitude: 8.5 dgC
MaxTDay: 209 yday
```

**Data section** (tab-separated, after dashed line):
```
Year  Month  Day  GlobRad  AirTemp  Precip  RefEvap
year  month  mday W/m^2    dgC      mm/d    mm/d
1962  4      1    120.4    2.8      0.0     1.3
```

**Required columns**: Year, Month, Day, GlobRad (W/m^2), AirTemp (dgC), Precip (mm/d)
**Optional columns**: RefEvap (mm/d), Wind (m/s), RelHum (%), VapPres (Pa), etc.

### Soil Definition (`.dai`)

Soil is defined hierarchically: horizons → column.

**Horizon** (texture fractions are dimensionless 0-1 or percent with [%]):
```lisp
(defhorizon "My Ap" USDA3            ; or FAO3, ISSS4
  (clay 0.107)                        ; fraction or [%]
  (silt 0.222)
  (sand 0.671)
  (humus 0.024)
  (dry_bulk_density 1.45 [g/cm^3])
  (C_per_N 11.0 [g C/g N])
  (hydraulic M_vG                     ; van Genuchten-Mualem
    (Theta_res 0.0)
    (Theta_sat 0.392)
    (alpha 0.0385)                    ; [cm^-1]
    (n 1.211)
    (K_sat 7.52 [cm/h])))
```

**Texture classification systems**:
- `USDA3`: clay, silt, sand (3 fractions, USDA system)
- `FAO3`: clay, silt, sand (3 fractions, FAO system)
- `ISSS4`: clay, silt, fine_sand, coarse_sand (4 fractions, ISSS system)

**Column** (soil profile = stack of horizons):
```lisp
(defcolumn MySite default
  (Soil (MaxRootingDepth 100 [cm])
        (horizons (-30 [cm] "My Ap")    ; depths are NEGATIVE from surface
                  (-250 [cm] "My C")))
  (Groundwater deep)                     ; or: aquitard, fixed
  (OrganicMatter original
    (init (input 1400 [kg C/ha/y])
          (root 480 [kg C/ha/y])
          (end -20 [cm]))))
```

### Management Definition (`.dai`)

```lisp
(defaction "My Management" activity
  (wait_mm_dd 3 05)                          ; wait until March 5
  (fertilize (N25S (weight 115 [kg N/ha])))  ; mineral fertilizer
  (plowing)
  (wait_mm_dd 4 05)
  (seed_bed_preparation)
  (sow "Spring Barley")
  (wait (or (crop_ds_after "Spring Barley" 2.0)  ; DS 2.0 = ripe
            (mm_dd 08 20)))
  (harvest "Spring Barley" (stub 8 [cm]) (stem 0.70)))
```

### Main Setup File (`.dai`)

```lisp
(input file "tillage.dai")
(input file "crop.dai")
(input file "log.dai")

(defprogram MySimulation Daisy
  (column MySite)
  (weather default "my-weather.dwf")
  (time 1986 12 1 1)                   ; start: YYYY MM DD HH
  (stop 1988 4 1 1)                    ; end:   YYYY MM DD HH
  (manager activity ...)
  (output harvest
    ("Field nitrogen" (when monthly))
    ("Soil nitrogen" (when daily))
    ("Field water" (when monthly))
    ("Soil water" (when daily))
    ("Crop" (crop "Spring Barley"))))

(run MySimulation)
```

---

## Output Format Reference

### Daisy Log File (`.dlf`)

Tab-separated text with metadata header:
```
dlf-0.0 -- Harvest (defined in 'log-std.dai').

VERSION: 7.1.4
LOGFILE: harvest.dlf
RUN: Mon Mar 25 12:00:00 2026

COLUMN: *
SIMFILE: test.dai
SIM: AndebyFarm

----
year  month  mday  hour  column  crop  stem_DM  ...
```

### Key Output Files

| File | Content | Key Variables | Units |
|------|---------|---------------|-------|
| `harvest.dlf` | Crop harvest events | stem_DM, leaf_DM, sorg_DM, stem_N, sorg_N, harvest_index | Mg DM/ha, kg N/ha |
| `field_nitrogen.dlf` | N balance | Fertilizer, Fixation, Harvest_N, Denitrification, Leaching | kg N/ha |
| `field_water.dlf` | Water balance | Precipitation, Irrigation, Evapotranspiration, Drain, Percolation | mm |
| `soil_nitrogen.dlf` | Soil N profile | NH4, NO3, org_N per layer | kg N/ha |
| `soil_water.dlf` | Soil water profile | Theta per layer | mm |
| `<crop>.dlf` | Crop development | DS, LAI, Height, Root_Depth, WLeaf, WStem, WSOrg | various |

### Harvest Output Variables

| Variable | Description | Unit |
|----------|-------------|------|
| `stem_DM` | Harvested stem dry matter | Mg DM/ha |
| `leaf_DM` | Harvested leaf dry matter | Mg DM/ha |
| `dead_DM` | Harvested dead leaf matter | Mg DM/ha |
| `sorg_DM` | Harvested storage organ (grain) dry matter | Mg DM/ha |
| `stem_N` | Nitrogen in harvested stems | kg N/ha |
| `sorg_N` | Nitrogen in harvested grain | kg N/ha |
| `water_stress_days` | Days with water stress | d |
| `nitrogen_stress_days` | Days with nitrogen stress | d |
| `harvest_index` | Ratio of grain to total aboveground DM | dimensionless |

---

## Unit Trap Table

These are the most dangerous unit conversion pitfalls when preparing Daisy inputs:

| Parameter | Daisy Expects | Common Source Unit | Conversion | Severity |
|-----------|---------------|-------------------|------------|----------|
| GlobRad | W/m^2 (daily mean) | MJ/m^2/d (daily total) | ÷ 0.0864 (= ×11.574) | **CRITICAL** |
| AirTemp | dgC (°C) | K (Kelvin) | − 273.15 | CRITICAL |
| Precip | mm/d | mm/3h (CMFD) | × 8 | CRITICAL |
| Precip | mm/d | kg/m^2/s | × 86400 | CRITICAL |
| Wind speed | m/s | m/s | identity (but check height) | MEDIUM |
| RelHum | % (0–100) | fraction (0–1) | × 100 | HIGH |
| Elevation | m | m | identity | LOW |
| Longitude | dgEast | degrees (−180 to 180) | identity if E, 360−|val| if W | MEDIUM |
| Latitude | dgNorth | degrees (−90 to 90) | identity | LOW |
| Clay/silt/sand | fraction (0–1) | percent (0–100) | ÷ 100 | **CRITICAL** |
| Bulk density | g/cm^3 | kg/m^3 | ÷ 1000 | CRITICAL |
| K_sat | cm/h | m/s | × 360000 (from m/s to cm/h) | CRITICAL |
| Alpha (vG) | cm^-1 | m^-1 | ÷ 100 | HIGH |
| Horizon depth | negative cm from surface | positive depth | negate | HIGH |
| Fertilizer N | kg N/ha | g N/m^2 | × 10 | HIGH |
| Organic input | kg C/ha/y | g C/m^2/y | × 10 | HIGH |
| Timestep | 24 hours | — | must match data freq | MEDIUM |

---

## Tool Reference

### 1. `convert_weather_to_dwf.py` — Forcing Converter

Converts global meteorological data (CSV with columns for date, temperature, radiation,
precipitation, etc.) into Daisy's `.dwf` weather file format.

**Key conversions**:
- Radiation: MJ/m^2/d → W/m^2 (÷ 0.0864)
- Temperature: K → °C (− 273.15) or passthrough if already °C
- Precipitation: mm/3h → mm/d (× 8) or kg/m^2/s → mm/d (× 86400)
- Validates: no negative radiation, temperature range −60 to +60°C, precip ≥ 0

### 2. `convert_soil_to_dai.py` — Soil/Parameter Converter

Converts HWSD or custom soil texture data into Daisy horizon and column definitions.

**Key conversions**:
- Texture fractions from % to 0–1
- Bulk density from kg/m^3 to g/cm^3
- Depths from positive to negative (Daisy convention)
- Auto-selects texture system (USDA3 for 3-fraction, ISSS4 for 4-fraction)
- Optionally estimates hydraulic parameters via built-in pedotransfer functions

### 3. `run_daisy.py` — Execution Wrapper

Runs the Daisy binary with a given `.dai` setup file and captures output/errors.

**Features**:
- Locates daisy binary (build dir, system PATH, or explicit path)
- Validates that required input files (.dwf, .dai libraries) exist
- Runs with timeout protection
- Captures stdout/stderr and parses daisy.log for errors
- Returns exit code and paths to generated .dlf files

### 4. `parse_daisy_output.py` — Output Parser

Parses `.dlf` (Daisy Log File) output into pandas DataFrames and CSV files.

**Features**:
- Reads DLF header metadata (version, run time, parameters)
- Parses tab-separated data section with proper column types
- Extracts harvest summary, water balance, N balance, crop development
- Computes derived metrics (total yield, N use efficiency, water productivity)
- Generates time series CSV for downstream analysis

---

## Execution Reference

### Command Line

```bash
# Run a simulation
daisy test.dai

# Run with version info
daisy -v

# Run with info
daisy --info

# Run batch (multiple scenarios)
daisy batch.dai
```

### Required Files for a Simulation

1. **Main `.dai` file** — defines the program with column, weather, manager, output
2. **Weather `.dwf` file** — meteorological forcing data
3. **Library `.dai` files** — crop.dai, tillage.dai, fertilizer.dai, log.dai (from lib/)
4. **Soil `.dai` file** — if soil defined in separate file

### Library Files (installed with Daisy)

| File | Content |
|------|---------|
| `crop.dai` | Standard crop parameterizations (wheat, barley, maize, pea, etc.) |
| `tillage.dai` | Tillage operations (plowing, seed bed preparation, etc.) |
| `fertilizer.dai` | Fertilizer types (mineral: N25S, AmmoniumNitrate; organic: slurry) |
| `log.dai` | Standard output log definitions |
| `vegetation.dai` | Vegetation parameters |

---

## Quick Start Example

```bash
# 1. Copy sample files
cp -r /path/to/daisy/sample /tmp/daisy-test
cd /tmp/daisy-test

# 2. Run the tutorial simulation
daisy test.dai

# 3. Check outputs
cat harvest.dlf          # Crop harvest results
cat field_water.dlf      # Water balance
cat field_nitrogen.dlf   # Nitrogen balance
cat sbarley.dlf          # Spring barley crop development
```

Expected output files: `harvest.dlf`, `field_nitrogen.dlf`, `field_water.dlf`,
`soil_nitrogen.dlf`, `soil_water.dlf`, `sbarley.dlf`, `checkpoint-*.dai`, `daisy.log`

---

## Common Crop Models Available

| Crop | Dai Library | Typical Yield (Mg DM/ha) |
|------|-------------|--------------------------|
| Spring Barley | crop.dai / dk-sbarley.dai | 4–7 |
| Winter Wheat | crop.dai / dk-wwheat.dai | 6–10 |
| Winter Barley | crop.dai / dk-wbarley.dai | 5–8 |
| Winter Rape | crop.dai / dk-wrape.dai | 3–5 |
| Silage Maize | crop.dai / dk-maize.dai | 10–18 |
| Pea | pea.dai | 3–5 |
| Grass | grass.dai | 8–14 (4 cuts/yr) |
| Potato | potato.dai | 6–12 |
| Sugar Beet | sugarbeet.dai | 10–16 |

---

## Known Limitations

1. **1D only** — no lateral flow between fields (except 2D experimental GP2D mode)
2. **Daily or hourly** — sub-hourly forcing not supported in standard mode
3. **Temperate focus** — crop models calibrated primarily for Northern European conditions
4. **No built-in calibration** — parameter optimization requires external tools
5. **Lisp-like syntax** — steep learning curve for configuration files
6. **No GUI** — command-line only (VSCode extension available for syntax highlighting)
