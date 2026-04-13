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

# GEOtop Knowledge Infrastructure

| Field            | Value                                                    |
|------------------|----------------------------------------------------------|
| Package          | GEOtop v3.0                                              |
| Domain           | Hydrology / Land-surface energy-water balance             |
| Language          | C++11                                                    |
| Build System      | CMake 3.0+ (also Meson)                                 |
| Last Updated      | 2026-03-25                                               |
| Tools             | 4                                                        |
| Skill Documents   | 5                                                        |
| Diagnostic Triplets| 20                                                      |

---

## 1. Overview

GEOtop is a physically-based, distributed model of the mass and energy balance of the
hydrological cycle. It couples the energy budget at the land surface with the water budget
in the soil, accounting for snow/glacier dynamics, vegetation, radiation, and turbulent
heat fluxes. The model is designed for complex terrain (mountain catchments) where
topographic effects on radiation, wind, and snow redistribution are important.

**Key capabilities:**
- Coupled energy-water balance solved at sub-hourly time steps (default 900 s)
- 3D Richards equation for unsaturated/saturated zone flow
- Multi-layer snow model with compaction, melt, albedo aging
- Glacier module with accumulation/ablation
- Vegetation energy partitioning (two-layer canopy + ground)
- Radiation model with sky view factor, cast shadows, horizon obstruction
- Blowing snow redistribution (PBSM parameterization)
- Point (1D column) and distributed (3D catchment) simulation modes

**Primary use cases:**
- Alpine/mountain hydrology with snow and permafrost
- Soil temperature and moisture profile simulation
- Surface energy balance studies (radiation, sensible/latent heat)
- Evapotranspiration and soil-vegetation-atmosphere transfer

---

## 2. Installation

### Binary Build (CMake)
```bash
cd /path/to/geotop/source/repo
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=RELEASE
make -j$(nproc)
# Binary: build/geotop
```

### Optional Flags
| Flag               | Purpose                                      |
|--------------------|----------------------------------------------|
| `-DWITH_METEOIO=ON`| Enable MeteoIO library for met interpolation |
| `-DMETEOIO_DIR=...`| Path to MeteoIO installation prefix          |
| `-DWITH_OMP=ON`    | Enable OpenMP parallelization (Meson only)   |
| `-DMUTE_GEOLOG=ON` | Suppress log output                          |

### Dependencies
- C++11 compiler (GCC >= 4.8, Clang >= 3.3)
- CMake >= 3.0
- No external library dependencies (all included in source tree)
- Optional: MeteoIO, OpenMP, numdiff (for tests)

### Test
```bash
cd build && ctest -R Matsch_B2_Ref_007 --output-on-failure
```

---

## 3. Pipeline Stages

| Stage | Name                    | Depends On       | Parallel | Description                                     |
|-------|-------------------------|------------------|----------|-------------------------------------------------|
| s0    | Configuration           | --               | --       | Set basin location, period, resolution, paths   |
| s1    | Domain / Grid Setup     | --               | yes      | Define DEM, slope, aspect, sky view factor maps |
| s2    | Soil Parameters         | s1               | yes      | Derive Van Genuchten params from HWSD/SoilGrids |
| s3    | Vegetation / Land Cover | s1               | yes      | Classify land cover, set LSAI, root depth       |
| s4    | Meteorological Forcing  | s1               | yes      | Convert CMFD/MSWX/ERA5 to meteoXXXX.txt format |
| s5    | Model Parameters        | s2, s3           | no       | Write geotop.inpts with all 455+ keywords       |
| s6    | Model Execution         | s4, s5           | no       | Run `./geotop <sim_folder>`                     |
| s7    | Output Parsing          | s6               | no       | Extract time series from output-tabs/            |
| s8    | Validation              | s7               | no       | Compare with observations, compute metrics      |

**Stages s1-s4 can run in parallel** since they prepare independent input files.

---

## 4. Tool Reference

| Stage | Tool Script                     | Lines | Purpose                                       |
|-------|---------------------------------|-------|-----------------------------------------------|
| s4    | `tools/convert_forcing.py`      | ~350  | Convert global met data to GEOtop meteo CSV   |
| s2    | `tools/convert_soil.py`         | ~280  | Convert HWSD/SoilGrids to GEOtop soil CSV     |
| s6    | `tools/run_geotop.py`           | ~200  | Execute GEOtop binary with timeout/logging     |
| s7    | `tools/parse_output.py`         | ~300  | Extract basin/point/soil outputs to tidy CSV   |

---

## 5. Critical Domain Knowledge

### 5.1 Unit Trap: Soil Layer Thickness in MILLIMETERS (dt_001)
GEOtop expects soil layer thickness `Dz` in **millimeters**, not meters.
A 10 cm layer = 100 mm. If you write 0.1 (meters), the model creates a 0.1 mm layer
and the Richards solver diverges within seconds.

### 5.2 Unit Trap: Hydraulic Conductivity in m/s (dt_002)
Van Genuchten `Kh` and `Kv` are in **m/s** (not mm/hr or cm/day).
HWSD often reports Ksat in cm/day: divide by 86400 and then by 100.
Typical range: 1E-7 to 1E-3 m/s.

### 5.3 Unit Trap: Alpha in 1/mm (dt_003)
Van Genuchten `alpha` in the soil file is in **1/mm** (not 1/cm or 1/m).
Literature values are usually in 1/cm: divide by 10 to convert to 1/mm.
The test case uses alpha=0.00131 (1/mm) which is 0.0131 (1/cm).

### 5.4 Unit Trap: Precipitation in mm (dt_004)
Meteorological forcing `Iprec` is **precipitation intensity in mm** over the time step.
If your forcing is in mm/hr and time step is 900 s, multiply by 0.25.
If forcing is in m/s (like some reanalyses), multiply by 1000*dt.

### 5.5 Unit Trap: Relative Humidity in PERCENT (dt_005)
`RelHum` in meteo files must be **0-100 (percent)**, not 0-1 fraction.
ERA5 provides specific humidity (kg/kg) which needs conversion.
CMFD provides as percent already.

### 5.6 Date Format is DD/MM/YYYY hh:mm (dt_006)
GEOtop uses European date format: day first, then month.
Using MM/DD/YYYY silently misparses dates.
The InitDate/EndDate in geotop.inpts and the Date column in meteo files must match.

### 5.7 Nodata Value is -9999 (dt_007)
Missing values in meteo files must be exactly `-9999` (not NaN, -999, or blank).
GEOtop silently uses 0 for unrecognized nodata, causing flat temperature/radiation.

### 5.8 Vegetation Height in mm (dt_008)
`VegHeight` is in **millimeters**. A 4 m tree = 4000 mm.
The test case uses VegHeight=400 mm for meadow grass (0.4 m).

### 5.9 geotop.inpts Uses TAB Separators (dt_009)
The configuration file uses `key<TAB>=<TAB>value` format.
Some editors convert tabs to spaces, which may cause parse failures.
Comments start with `!`.

### 5.10 Horizon Files Are Required for Radiation (dt_010)
If `FlagSkyViewFactor=1` and `HorizonMeteoStationFile` is set, the horizon file
must exist. Missing it silently sets all horizon angles to 0, overpredicting solar input.

---

## 6. Input File Specifications

### 6.1 geotop.inpts (Main Configuration)
- **Format**: Key-value pairs, TAB-separated, `!` comments
- **455+ keywords** defined in `src/geotop/keywords.h`
- Controls simulation period, physics toggles, file paths, all parameters

### 6.2 meteoXXXX.txt (Meteorological Forcing)
- **Format**: CSV with header row
- **Columns**: Date, JDfrom0, Iprec(mm), WindSp(m/s), WindDir(deg), RelHum(%), AirT(C), Swglobal(W/m2), CloudTrans(0-1), [LWin(W/m2), DewT(C), AirPress(mbar)]
- **Nodata**: -9999
- **One file per station**: meteo0001.txt, meteo0002.txt, ...

### 6.3 soilXXXX.txt (Soil Properties)
- **Format**: CSV with header row
- **Columns**: Dz(mm), Kh(m/s), Kv(m/s), vwc_r(-), vwc_w(-), vwc_fc(-), vwc_s(-), alpha(1/mm), n(-), stor(1/m)
- **One row per layer**, top to bottom
- **One file per point**: soil0001.txt, soil0002.txt, ...

### 6.4 DEM and Maps (ESRI ASCII Grid)
- dem.txt, slope.txt, aspect.txt, sky.txt, curvature.txt
- Standard ESRI ASCII format: ncols, nrows, xllcorner, yllcorner, cellsize, NODATA_value

### 6.5 horizonXXXX.txt
- **Columns**: AngleFromNorthClockwise(deg), HorizonHeight(deg)
- Azimuth angles (0-360) and corresponding horizon elevation angles

---

## 7. Output File Specifications

### 7.1 Basin-Averaged (output-tabs/basin.txt)
- CSV with columns: Date, JDfrom0, TimeFromStart, Prain, Psnow, Pnet, Tair, Tsurface,
  Evap, Transpiration, LE, H, SW, LW, SWin, LWin, MassBalError, MeanTimeStep
- Units: mm for water fluxes, W/m2 for energy, C for temperature, s for time step

### 7.2 Point Output (output-tabs/pointXXXX.txt)
- Same structure as basin but for single observation points
- Higher resolution temporal output available

### 7.3 Soil Profiles (output-tabs/soilTzXXXX.txt, thetaliqXXXX.txt, etc.)
- Matrix format: rows=time steps, columns=soil layers
- soilTz: temperature (C), thetaliq: volumetric water content (-), thetaice: ice content (-), psiz: matric potential (mm)

### 7.4 Snow Profiles (output-tabs/snowTXXXX.txt, snowDepthXXXX.txt, etc.)
- Matrix format: rows=time steps, columns=snow layers
- Temperature (C), depth (mm), ice content (kg/m2), liquid content (kg/m2)

### 7.5 Discharge (output-tabs/discharge.txt)
- Time series of catchment discharge
- Units: m3/s

---

## 8. Calibration Parameters (Priority Order)

| Priority | Parameter                    | Typical Range    | Units    | Sensitivity          |
|----------|------------------------------|------------------|----------|----------------------|
| 1        | NormalHydrConductivity (Kv)  | 1E-7 to 1E-3    | m/s      | Controls infiltration|
| 2        | AlphaVanGenuchten            | 0.0001-0.01      | 1/mm     | Retention curve shape|
| 3        | NVanGenuchten                | 1.1-3.0          | -        | Retention curve shape|
| 4        | SnowCorrFactor               | 0.5-2.0          | -        | Precipitation bias   |
| 5        | ThresTempRain/Snow           | -5 to 5          | C        | Rain-snow partition  |
| 6        | SoilRoughness                | 10-1000          | mm       | Surface runoff       |
| 7        | MinStomatalRes               | 10-200           | s/m      | Transpiration rate   |
| 8        | LSAI                         | 0.5-8.0          | m2/m2    | Canopy interception  |
| 9        | FreshSnowReflVis             | 0.7-0.95         | -        | Snow melt timing     |
| 10       | InitWaterTableDepth          | 100-5000         | mm       | Initial soil moisture|

---

## 9. Diagnostic Triplets Summary

| Failure Domain   | Count | Silent | Fatal | Degraded |
|------------------|-------|--------|-------|----------|
| unit_conversion  | 8     | 7      | 1     | 0        |
| parameter_format | 4     | 1      | 2     | 1        |
| file_structure   | 3     | 1      | 2     | 0        |
| runtime          | 3     | 0      | 2     | 1        |
| initialization   | 2     | 2      | 0     | 0        |
| **Total**        | **20**| **11** | **7** | **2**    |

55% of failures are **silent** -- the model runs without error but produces wrong results.
See `diagnostics/triplets.yaml` for full symptom-diagnosis-remedy entries.

---

## 10. Coupling Points

### Upstream Data Sources
| Source            | Variables                          | Tool                    |
|-------------------|------------------------------------|-------------------------|
| CMFD/MSWX/ERA5   | AirT, Precip, Wind, RH, SW, LW    | `convert_forcing.py`    |
| HWSD/SoilGrids   | Sand/Silt/Clay, Ksat, BD, OC      | `convert_soil.py`       |
| SRTM/MERIT DEM   | Elevation grid                     | External GIS processing |
| MODIS/AVHRR      | Land cover, LSAI                   | External classification |

### Downstream Models
| Model             | Variable Provided                   | Format                  |
|-------------------|------------------------------------|-------------------------|
| River routing     | Surface runoff, baseflow            | CSV time series         |
| Crop models       | Soil moisture, soil temperature     | CSV profiles            |
| Glacier models    | Snow/glacier mass balance           | CSV time series         |
| Atmospheric models| Surface fluxes (H, LE, LW)         | CSV time series         |

---

## 11. File Structure

```
ki/
|-- SKILL.md                          # This file
|-- tools/
|   |-- convert_forcing.py            # s4: Met data -> GEOtop meteo CSV
|   |-- convert_soil.py               # s2: HWSD/SoilGrids -> GEOtop soil CSV
|   |-- run_geotop.py                 # s6: Execute model binary
|   |-- parse_output.py               # s7: Extract outputs to tidy CSV
|-- docs/
|   |-- s1_domain_setup.md            # Domain/DEM preparation
|   |-- s2_soil_parameters.md         # Soil parameter derivation
|   |-- s4_forcing_preparation.md     # Met forcing conversion
|   |-- s6_model_execution.md         # Running the model
|   |-- s7_output_parsing.md          # Interpreting and extracting outputs
|-- diagnostics/
|   |-- triplets.yaml                 # 20 symptom-diagnosis-remedy entries
```

---

## 12. Validation Results

### Test Site: Matsch Valley Station B2 (South Tyrol, Italy)
- **Location**: 46.668N, 10.579E, elevation 1480 m
- **Period**: October 2009 (1 month)
- **Forcing**: In-situ meteorological observations (hourly)
- **Land cover**: Alpine meadow (VegHeight=400 mm, LSAI=4)
- **Soil**: 16 layers, 10-150 mm thickness, total depth 1000 mm
- **Time step**: 900 s

Reference test case from GEOtop repository (`tests/1D/Matsch_B2_Ref_007`).
This is a point simulation (1D column) exercising energy balance, water balance,
and snow processes over a representative Alpine grassland site.
