---
name: rhessys
description: >-
  RHESSys 7.4. Covers Daily coupled water, carbon and nitrogen cycling at watershed scale;
  Soil moisture redistribution, runoff production, saturated subsurface throughflow,
  overland flow; Evapotranspiration (interception, soil/litter evaporation, canopy
  transpiration); Snowpack energy-balance accumulation and melt. Use when the task
  involves running, configuring, calibrating or interpreting RHESSys.
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

# RHESSys Knowledge Infrastructure

**Package:** `rhessys-ki` v1.0.0
**Model:** RHESSys (Regional Hydro-Ecologic Simulation System) v7.4 / 5.14.3
**Domain:** Hydrology, Ecohydrology, Biogeochemistry
**Language:** C (501 source files)
**Build:** GNU Make
**Last Updated:** 2026-03-25

| Metric | Value |
|--------|-------|
| Tools | 4 |
| Skill Documents | 5 |
| Diagnostic Triplets | 20 |
| Validation Status | HJ Andrews Watershed 8 |

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/HWSD/SKILL.md` for soil property documentation.
See `data_ki/ObservedQ/SKILL.md` for observed discharge data.


## 1. Overview

RHESSys is a GIS-based, hydro-ecological modeling framework that simulates
coupled water, carbon, and nitrogen cycling at the watershed scale. It couples
a quasi-distributed hydrological model (based on TOPMODEL concepts) with
biogeochemical cycling routines derived from Biome-BGC. The model operates on a
hierarchical spatial structure:

```
World
  └── Basin
        └── Hillslope
              └── Zone (climate)
                    └── Patch (hydrologic response unit)
                          └── Canopy Stratum (vegetation layer)
```

Key capabilities:
- Coupled water/carbon/nitrogen cycling at daily/hourly timesteps
- Lateral redistribution of water and dissolved nutrients
- Explicit vegetation dynamics (growth, allocation, mortality, phenology)
- Snowpack energy balance and accumulation/melt
- Fire spread modeling (optional WMFire coupling)
- Groundwater routing and stream network routing
- NetCDF or ASCII climate forcing inputs

---

## 2. Installation

### Prerequisites

- C compiler (clang or gcc with C99 support)
- GNU Make
- NetCDF library (`libnetcdf-dev`)
- Flex and Bison (for output filter parser)
- glib-2.0 (for unit tests)
- Python 3 (for functional tests and tools)

### Build from Source

```bash
cd source/repo/rhessys
make clean
make
# Binary produced: rhessys7.4
make install  # installs to /usr/local/bin
```

### Quick Test

```bash
cd source/repo/Testing
../rhessys/rhessys7.4 \
  -t tecfiles/tec.test \
  -w worldfiles/w8TC.world \
  -whdr worldfiles/w8TC.hdr \
  -r flowtables/w8TC.flow \
  -pre out/test \
  -st 1988 10 1 1 -ed 2000 10 1 1 \
  -b -g
```

---

## 3. Pipeline Stages

| Stage | Name | Tool | Input | Output |
|-------|------|------|-------|--------|
| s0 | Configuration | manual | User settings | Config JSON |
| s1 | Domain Setup | manual | DEM, shapefile | Worldfile, flow table |
| s2 | Climate Forcing | `convert_forcing.py` | Global gridded data | ASCII `.tmax/.tmin/.rain` |
| s3 | Soil Parameters | `convert_soil_params.py` | HWSD/SoilGrids | `soil_*.def` files |
| s4 | Vegetation Params | manual | Literature/LULC maps | `veg_*.def` files |
| s5 | Parameter Defs | manual | Calibration | All `.def` files |
| s6 | Model Execution | `run_rhessys.py` | All inputs | Raw output files |
| s7 | Output Parsing | `parse_output.py` | Raw output | CSV time series |
| s8 | Validation | manual | Observations + output | Metrics, figures |

**Stage Dependencies:**
- s2, s3, s4, s5 can proceed in parallel (all feed into s6)
- s6 depends on s1 through s5
- s7 depends on s6
- s8 depends on s7

---

## 4. Input File Formats

### 4.1 World File (`.world`)

Hierarchical text file defining the spatial domain. Each object (basin, hillslope,
zone, patch, stratum) is defined by a block of `value   variable_name` pairs.

```
1               world_id
1               num_basins
1               basin_ID
548397.0        x
4878998.0       y
574.0           z
1               basin_parm_ID
2               num_hillslopes
...
```

**Key variables per patch:**
| Variable | Unit | Description |
|----------|------|-------------|
| `area` | m^2 | Patch area |
| `slope` | degrees | Surface slope |
| `aspect` | degrees | Surface aspect |
| `soil_depth` | m | Total soil depth |
| `sat_deficit` | m (water) | Saturation deficit |
| `unsat_storage` | m (water) | Unsaturated zone storage |
| `rz_storage` | m (water) | Root zone storage |
| `snowpack.water_equivalent_depth` | m (water) | Snow water equivalent |
| `litter_cs.litr1c` | kg C/m^2 | Labile litter carbon |
| `soil_cs.soil1c` | kg C/m^2 | Fast soil carbon |

### 4.2 Climate Forcing Files (ASCII)

One file per variable, daily values with a date header:
```
1988 10 1 01
15.2
14.8
16.1
...
```

| Variable | File Extension | Unit | Description |
|----------|---------------|------|-------------|
| Maximum temperature | `.tmax` | deg C | Daily Tmax |
| Minimum temperature | `.tmin` | deg C | Daily Tmin |
| Precipitation | `.rain` | m/day | **TRAP: m/day, NOT mm/day** |

**CRITICAL UNIT TRAP:** Precipitation MUST be in **meters/day**, not mm/day.
If you supply mm/day, streamflow will be 1000x too high. See `dt_001`.

### 4.3 Soil Definition File (`.def`)

```
5.0     pore_size_index             (dimensionless)
0.218   porosity_0                  (m^3/m^3)
0.1     porosity_decay              (1/m)
3.0     Ksat_0                      (m/day)
3.0     m                           (m, transmissivity decay parameter)
0.12    soil_depth                  (m)
0.435   psi_air_entry               (m, or kPa depending on version)
...
```

### 4.4 Vegetation Definition File (`.def`)

```
1       veg_parm_ID
4.0     epc.max_lai                 (m^2/m^2)
0.5     epc.proj_sla                (m^2/kg C)
0.002   epc.leaf_turnover           (1/day)
12.0    epc.height_to_stem_coef     (m per kg C/m^2)
...
```

### 4.5 Temporal Event Control (TEC) File

```
1989 10 1 1 print_daily_on
1989 10 1 2 print_daily_growth_on
```

Events: `print_daily_on/off`, `print_monthly_on/off`, `print_yearly_on/off`,
`print_daily_growth_on/off`, `redefine_world`, `redefine_world_thin_remain`, etc.

### 4.6 Flow Table

Binary/text routing table specifying patch-to-patch connectivity, gamma
(proportion of outflow to each neighbor), and total gamma for each patch.

---

## 5. Output Format

### 5.1 Legacy Output (ASCII)

Files named `<prefix>_<level>.<timestep>`:
- `test_basin.daily` — Basin-aggregated daily output
- `test_patch.daily` — Per-patch daily output
- `test_basin.yearly` — Basin yearly summaries

### 5.2 CSV Output (via Output Filter)

Configured by YAML filter file (`-of filter.yml`):
```yaml
filter:
  timestep: daily
  output:
    format: csv
    path: "../Testing/out"
    filename: "test_basin_daily"
  basin:
    ids: 1
    variables:
      - patch.streamflow
      - patch.transpiration_sat_zone
      - patch.evaporation
```

### 5.3 Key Output Variables

| Variable | Unit | Level | Description |
|----------|------|-------|-------------|
| `streamflow` | m/day (per m^2 basin) | basin | Total basin streamflow |
| `evaporation` | m/day | basin/patch | Total evaporation |
| `transpiration_sat_zone` | m/day | basin/patch | Transpiration from sat zone |
| `transpiration_unsat_zone` | m/day | basin/patch | Transpiration from unsat zone |
| `sat_deficit` | m | patch | Saturation deficit |
| `unsat_storage` | m | patch | Unsaturated zone storage |
| `rz_storage` | m | patch | Root zone storage |
| `snowpack.water_equivalent_depth` | m | patch | SWE |
| `detention_store` | m | patch | Surface detention |
| `cs.leafc` | kg C/m^2 | stratum | Leaf carbon |
| `cs.net_psn` | kg C/m^2/day | stratum | Net photosynthesis |
| `epv.proj_lai` | m^2/m^2 | stratum | Projected LAI |
| `streamflow_NO3` | kg N/m^2/day | basin | Nitrate in streamflow |
| `streamflow_DON` | kg N/m^2/day | basin | DON in streamflow |
| `soil_cs.totalc` | kg C/m^2 | patch | Total soil carbon |
| `litter_cs.totalc` | kg C/m^2 | patch | Total litter carbon |

**CRITICAL UNIT TRAP:** Streamflow output is in **m/day per unit basin area**,
not m^3/s. To convert to m^3/s: `Q_m3s = streamflow * basin_area / 86400`.
See `dt_002`.

---

## 6. Unit Trap Table

| Variable | Model Expects | Common Source Unit | Conversion | Triplet |
|----------|--------------|-------------------|------------|---------|
| Precipitation | m/day | mm/day | / 1000 | dt_001 |
| Streamflow output | m/day/m^2 | m^3/s | * area / 86400 | dt_002 |
| Temperature | deg C | K | - 273.15 | dt_003 |
| Soil depth | m | cm | / 100 | dt_004 |
| Ksat | m/day | cm/hr | * 0.24 | dt_005 |
| Porosity | m^3/m^3 | % | / 100 | dt_006 |
| Slope | degrees | radians | * 180/pi | dt_007 |
| Aspect | degrees | radians | * 180/pi | dt_007 |
| Area | m^2 | km^2 | * 1e6 | dt_008 |
| LAI | m^2/m^2 | — | dimensionless | — |
| Carbon pools | kg C/m^2 | g C/m^2 | / 1000 | dt_009 |
| Nitrogen pools | kg N/m^2 | g N/m^2 | / 1000 | dt_009 |
| Psi air entry | m | kPa | context-dependent | dt_010 |

---

## 7. Tools Reference

| Tool | File | Lines | Stage | Purpose |
|------|------|-------|-------|---------|
| `convert_forcing.py` | `tools/convert_forcing.py` | ~200 | s2 | Convert global met data to RHESSys ASCII |
| `convert_soil_params.py` | `tools/convert_soil_params.py` | ~180 | s3 | Convert HWSD/SoilGrids to `.def` files |
| `run_rhessys.py` | `tools/run_rhessys.py` | ~160 | s6 | Execute RHESSys binary with validation |
| `parse_output.py` | `tools/parse_output.py` | ~200 | s7 | Parse RHESSys output to clean CSV |

---

## 8. Critical Domain Knowledge

1. **Precipitation units are m/day** — Not mm/day. This is the #1 cause of
   unrealistic streamflow. Always divide mm/day inputs by 1000. (`dt_001`)

2. **Streamflow output is depth/time over basin area** — To get volumetric
   discharge (m^3/s), multiply by basin area (m^2) and divide by 86400. (`dt_002`)

3. **Worldfile is whitespace-sensitive** — Values must appear before their
   variable names, separated by whitespace. Extra blank lines or wrong ordering
   will cause silent misassignment. (`dt_011`)

4. **Spin-up is critical for carbon/nitrogen** — BGC pools (soil C, litter C,
   plant N) need 200-500 years of spin-up to reach steady state. Without it,
   vegetation dies or explodes. Use `-vegspinup` flag. (`dt_012`)

5. **The `-s` flag scales m and Ksat simultaneously** — The sensitivity
   parameters multiply the default soil hydraulic parameters. Setting them to 1.0
   uses defaults; values of 0 will crash the model. (`dt_013`)

6. **TEC file must have events AFTER start date** — Events scheduled before
   `-st` are ignored. If `print_daily_on` is before start date, no output is
   produced. (`dt_014`)

7. **Flow table must match worldfile patches** — Every patch in the worldfile
   must appear in the flow table. Mismatches cause segfaults. (`dt_015`)

8. **NetCDF climate requires compile flag** — The model must be compiled with
   `-DLIU_NETCDF_READER` to use gridded NetCDF forcing. Without it, only ASCII
   is supported. (`dt_016`)

9. **Canopy stratum cover fractions must sum to <= 1.0** — If they exceed 1.0
   per patch, water interception is over-counted and the water balance breaks.
   (`dt_017`)

10. **Provide BOTH Kdown_direct AND Kdown_diffuse** — If only one is given,
    RHESSys silently ignores both and uses constant clear-sky radiation. In
    humid climates this causes vegetation collapse in 3-5 years via drought
    mortality. Use `tools/split_kdown.py` (Erbs 1982) to partition total Kdown.
    (`dt_019`)

11. **Generate daytime_rain_duration for humid/monsoon basins** — Without
    this file, RHESSys defaults rain_duration = 86400 s (all day) for ANY
    precipitation. This zeros transpiration on every rainy day, suppressing
    annual ET by 3-10x in monsoon climates. Run `tools/gen_rain_duration.py`
    and add `daytime_rain_duration` to the station file's non-critical daily
    sequences. (`dt_022`)

12. **Patch canopy_stratum_daily_F.c line 1160 before compiling** — RHESSys 7.4
    has a typo: `if (rnet_evap_day < ZERO) rnet_evap_night = 0.0;` should be
    `rnet_evap_day = 0.0`. Without this fix, cloudy days zero transpiration
    regardless of radiation. Change the line and recompile. (`dt_021`)

13. **Chinese obs files are ISO-8859-1, not UTF-8** — All local obs/*.txt files
    from national Chinese archives use Latin-1 encoding. Use `open(f, encoding='latin-1')`.
    Default UTF-8 raises UnicodeDecodeError at the station name column. (`dt_023`)

14. **Use strptime, not fromisoformat, for Chinese obs date strings** — Files use
    non-zero-padded dates ('1982-7-4'). `fromisoformat()` silently drops ~85% of
    rows (only months 10-12 and days 10-31 parse), giving obs_Q that is 5-10x too
    low. Use `datetime.strptime(s, '%Y-%m-%d')`. (`dt_024`)

---

## 9. Calibration Parameters (Priority Order)

| Parameter | Range | Sensitivity | Location |
|-----------|-------|-------------|----------|
| `m` (transmissivity decay) | 0.01–20.0 m | Very High | `-s` flag, soil.def |
| `Ksat_0` (saturated conductivity) | 0.001–100 m/day | Very High | `-s` flag, soil.def |
| `soil_depth` | 0.5–5.0 m | High | `-s` flag, soil.def |
| `pore_size_index` | 0.1–0.8 | High | `-svalt` flag, soil.def |
| `psi_air_entry` | 0.01–3.0 m | High | `-svalt` flag, soil.def |
| `gw_loss_coeff` | 0.0–0.5 | Medium | `-gw` flag |
| `sat_to_gw_coeff` | 0.0–0.5 | Medium | `-gw` flag |
| `epc.max_lai` | 1.0–12.0 m^2/m^2 | Medium | veg.def |
| `epc.leaf_turnover` | 0.0001–0.01 1/day | Medium | veg.def |

---

## 10. Quick Start (6 Steps)

```bash
# Step 1: Build the model
cd source/repo/rhessys && make

# Step 2: Convert forcing data
python ki/tools/convert_forcing.py \
  --input forcing_data.csv \
  --output-dir Testing/clim \
  --prefix w8_daily \
  --start-date "1988-10-01"

# Step 3: Create soil definitions
python ki/tools/convert_soil_params.py \
  --input hwsd_data.csv \
  --output-dir Testing/defs \
  --prefix soil_sandyloam

# Step 4: Run the model
python ki/tools/run_rhessys.py \
  --binary rhessys/rhessys7.4 \
  --worldfile Testing/worldfiles/w8TC.world \
  --worldhdr Testing/worldfiles/w8TC.hdr \
  --tecfile Testing/tecfiles/tec.test \
  --flowtable Testing/flowtables/w8TC.flow \
  --prefix Testing/out/test \
  --start "1988 10 1 1" --end "2000 10 1 1" \
  --basin --grow

# Step 5: Parse output
python ki/tools/parse_output.py \
  --input Testing/out/test_basin.daily \
  --output Testing/out/test_basin_parsed.csv \
  --level basin --timestep daily

# Step 6: Validate
# Compare parsed streamflow to observed data
```

---

## 11. Diagnostic Triplets Summary

| ID | Stage | Domain | Severity | Symptom |
|----|-------|--------|----------|---------|
| dt_001 | s2 | unit_conversion | silent | Precip 1000x too high |
| dt_002 | s7 | unit_conversion | silent | Streamflow unit mismatch |
| dt_003 | s2 | unit_conversion | silent | Temperature in K not C |
| dt_004 | s3 | unit_conversion | silent | Soil depth in cm not m |
| dt_005 | s3 | unit_conversion | silent | Ksat in cm/hr not m/day |
| dt_006 | s3 | unit_conversion | silent | Porosity as % not fraction |
| dt_007 | s1 | unit_conversion | silent | Slope/aspect radians vs degrees |
| dt_008 | s1 | unit_conversion | silent | Area km^2 vs m^2 |
| dt_009 | s5 | unit_conversion | silent | C/N pools g vs kg |
| dt_010 | s3 | unit_conversion | silent | Psi air entry units |
| dt_011 | s1 | format_error | fatal | Worldfile ordering/whitespace |
| dt_012 | s6 | initialization | silent | Missing BGC spin-up |
| dt_013 | s6 | parameter_error | fatal | Zero sensitivity multiplier |
| dt_014 | s6 | configuration | silent | TEC events before start |
| dt_015 | s6 | format_error | fatal | Flow table/worldfile mismatch |
| dt_016 | s6 | build_error | fatal | NetCDF compile flag missing |
| dt_017 | s5 | parameter_error | silent | Cover fraction > 1.0 |
| dt_018 | s6 | runtime | fatal | Negative sat deficit crash |
| dt_019 | s3 | climate_forcing | silent | Kdown_direct provided without Kdown_diffuse → always clear-sky |
| dt_020 | s3 | climate_forcing | moderate | tmax−tmin constant → MTCLIM cloud correction broken |
| dt_021 | s4 | source_code_bug | critical | canopy_stratum_daily_F.c line 1160 typo → trans=0 on cloudy days |
| dt_022 | s4 | missing_input | critical | No daytime_rain_duration file → trans=0 on all rainy days |
| dt_023 | s7 | obs_file_encoding | critical | Chinese obs files are ISO-8859-1 → UnicodeDecodeError with default UTF-8 open() |
| dt_024 | s7 | obs_date_parsing | silent | Non-zero-padded dates ('1982-7-4') → fromisoformat() silently drops ~85% of obs days |

See `diagnostics/triplets.yaml` for full symptom-diagnosis-remedy entries.

### Scale mismatch caveat for specific discharge comparison (Bengbu)

When comparing a small-domain RHESSys model (156 km²) to a large basin gauge (Bengbu 51080: 121,000 km²), the specific discharge comparison (mm/yr) assumes uniform runoff generation across the full gauge drainage area. Results for Cal15:
- NSE = 0.390, r = 0.952, PBIAS = +22.3% (9 years, 1982-1990)
- r = 0.952 confirms the physics are correct (interannual dynamics captured)
- PBIAS = +22% systematic wet bias → soil storage parameters need calibration
- Calibrating against the full-basin gauge corrects for basin-average response,
  not necessarily the sub-basin physics. Use with awareness of this scale gap.

---

## 12. File Structure

```
ki/
  SKILL.md                          # This file
  tools/
    convert_forcing.py              # Met forcing converter (s2)
    convert_soil_params.py          # Soil parameter converter (s3)
    run_rhessys.py                  # Execution wrapper (s6)
    parse_output.py                 # Output parser (s7)
  docs/
    01_domain_setup.md              # Domain/worldfile creation
    02_climate_forcing.md           # Climate data preparation
    03_soil_vegetation_params.md    # Parameter definition files
    04_model_execution.md           # Running the model
    05_output_analysis.md           # Parsing and analyzing results
  diagnostics/
    triplets.yaml                   # 18 diagnostic triplets
```
