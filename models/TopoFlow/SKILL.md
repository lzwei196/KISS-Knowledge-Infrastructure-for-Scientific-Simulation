---
name: topoflow
description: >-
  TopoFlow 3.6. Covers Spatially-distributed watershed hydrologic response to climatic
  forcing over a D8 raster; Channel routing (kinematic / diffusive / dynamic wave) with
  Manning or Law-of-Wall friction; Infiltration and runoff partitioning (Green-Ampt,
  Smith-Parlange, 1-D Richards, Beven); Snowmelt (degree-day or energy balance). Use when
  the task involves running, configuring, calibrating or interpreting TopoFlow.
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

# TopoFlow 3.6 Knowledge Infrastructure

| Field             | Value                                      |
|-------------------|--------------------------------------------|
| Package           | topoflow-ki                                |
| Version           | 1.0.0                                      |
| Target Model      | TopoFlow 3.6                               |
| Domain            | Spatially-distributed hydrology            |
| Author            | Scott D. Peckham (model); KI auto-dissect  |
| Created           | 2026-03-25                                 |
| Validation Status | Treynor Iowa (June 1967 events)            |

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/HWSD/SKILL.md` for soil property documentation.
See `data_ki/ObservedQ/SKILL.md` for observed discharge data.


## 1. Overview

TopoFlow 3.6 is a spatially-distributed, D8-based hydrologic model written in
Python.  It uses a plug-and-play component architecture coupled through the
**EMELI** (Experimental Modeling Environment for Linking and Interoperability)
framework.  Each physical process (meteorology, infiltration, channel routing,
snowmelt, evapotranspiration, saturated zone, glaciers, diversions) is
implemented as an independent component that exposes a **Basic Model Interface
(BMI)** for standardized initialization, time-stepping, and data exchange.

TopoFlow routes water over a D8 (steepest-descent) flow grid using kinematic,
diffusive, or dynamic wave approximations with Manning or Law-of-Wall friction.
Infiltration options include Green-Ampt, Smith-Parlange, Richards 1-D, and
Beven methods.  Snow processes use either degree-day or energy-balance methods.
Evapotranspiration uses Priestley-Taylor or full energy balance.

The model reads pipe-delimited `.cfg` configuration files (one per component),
binary RTG grids, text time-series files, and NetCDF files.  Outputs are
written as NetCDF grid stacks (2-D fields over time) and pixel time-series
(outlet hydrographs).

---

## 2. Installation

```bash
# Create virtual environment
python -m venv /path/to/venv
source /path/to/venv/bin/activate

# Install from source
cd /path/to/topoflow36
pip install -e .

# Verify
python -c "import topoflow; print('TopoFlow imported OK')"
```

**Dependencies** (from setup.py / requirements.txt):

| Package   | Version   | Purpose                        |
|-----------|-----------|--------------------------------|
| numpy     | >=1, <2   | Array computation              |
| scipy     | any       | Interpolation, ODE solvers     |
| netCDF4   | any       | NetCDF I/O                     |
| cfunits   | any       | Unit conversion in EMELI       |
| GDAL      | optional  | Geospatial transforms          |
| matplotlib| optional  | Plotting / diagnostics         |

**Test after install:**

```bash
python -m topoflow \
  --cfg_prefix=June_20_67 \
  --cfg_directory=/path/to/examples/Treynor_Iowa_30m/__No_Infil_June_20_67_Rain \
  --driver_comp_name=topoflow_driver
```

Success indicator: console output ending with "Finished. (MM/DD/YYYY HH:MM:SS)"
and `*_0D-Q.txt` output files created.

---

## 3. Pipeline Stages

| Stage | Name                  | Tool                     | Description                                       |
|-------|-----------------------|--------------------------|---------------------------------------------------|
| s0    | Acquire Source        | (manual / git clone)     | Clone topoflow36 repository                       |
| s1    | Domain Setup          | —                        | Prepare DEM, compute D8 codes, slopes, areas      |
| s2    | Meteorology Forcing   | `convert_forcing.py`     | Convert global reanalysis to TopoFlow met input    |
| s3    | Soil / Infiltration   | `convert_soil_params.py` | Map HWSD/SoilGrids to Green-Ampt or Richards params|
| s4    | Channel Geometry      | —                        | Derive width, angle, Manning's n, sinuosity grids  |
| s5    | Component Selection   | —                        | Write provider file selecting process methods      |
| s6    | Configuration         | —                        | Generate all `.cfg` files with correct units       |
| s7    | Execution             | `run_topoflow.py`        | Run the coupled model via EMELI framework          |
| s8    | Output Parsing        | `parse_output.py`        | Extract hydrographs, grids, summary metrics        |
| s9    | Validation            | —                        | Compare to observations, compute NSE/KGE/PBIAS     |

**Parallelism:** Stages s2, s3, s4 can run in parallel once s1 is complete.
Stages s5 and s6 depend on s2-s4.  Stage s7 depends on s6.

---

## 4. Unit Trap Table

These conversions are the most common source of **silent failures** in
TopoFlow.  The model expects specific internal units that differ from common
data sources.

| Variable            | Common Source Unit | TopoFlow Internal Unit | Conversion Factor         | Failure Mode                        |
|---------------------|--------------------|------------------------|---------------------------|-------------------------------------|
| Precipitation (P)   | mm/day (ERA5)      | mm/hr                  | ÷ 24                     | 24x overestimate → instant flooding |
| Precipitation (P)   | kg/m²/s (GLDAS)    | mm/hr                  | × 3600                   | Near-zero rain if unconverted       |
| Precipitation (P)   | mm/hr (cfg input)  | m/s (internal)         | ÷ 3.6e6 (auto by model)  | Do NOT pre-convert to m/s           |
| Air Temperature     | K (ERA5)           | °C                     | − 273.15                 | Unrealistic ET and snowmelt         |
| Relative Humidity   | 0–1 fraction       | 0–1 fraction           | None                     | If given as %, divide by 100        |
| Wind Speed (u_z)    | m/s                | m/s                    | None                     | Check measurement height matches    |
| Saturated K (Ks)    | mm/hr (databases)  | m/s                    | ÷ 3.6e6                  | Infiltration wildly wrong           |
| Soil Porosity (θs)  | % (some sources)   | dimensionless 0–1      | ÷ 100                    | Crashes or nonsense water content   |
| Manning's n         | s/m^(1/3)          | s/m^(1/3)              | None                     | Ensure not inverted (1/n ≠ n)       |
| Channel Width       | m                  | m                      | None                     | Must be > 0 everywhere              |
| Slope               | m/m (dimensionless)| m/m                    | None                     | Must be > 0; flat cells cause div/0 |
| DEM Elevation       | m                  | m                      | None                     | Check datum consistency             |
| Capillary Length (G) | cm (literature)   | m                      | ÷ 100                    | Green-Ampt infiltration wrong       |
| ET rate             | mm/day             | mm/hr (in cfg)         | ÷ 24                     | Over/under-estimate of ET           |
| Timestep (dt)       | seconds            | seconds                | None                     | Too large → CFL violation, instab.  |

---

## 5. Configuration File Format

TopoFlow uses **pipe-delimited `.cfg` text files** with the format:

```
variable_name | value | type | description
```

Each component has its own `.cfg` file.  A **provider file** (`*_providers.txt`)
maps component types to specific implementations:

```
# comp_type       component
meteorology       tf_meteorology
channels          tf_channels_kin_wave
infil             tf_infil_green_ampt
snow              tf_snow_degree_day
evap              tf_evap_priestley_taylor
satzone           tf_satzone_darcy_layers
diversions        tf_diversions_fraction_method
ice               tf_ice_gc2d
hydro_model       topoflow_driver
```

**Input variable types** (set per variable in `.cfg`):

| Type           | Description                         | File Extension |
|----------------|-------------------------------------|----------------|
| Scalar         | Single constant value               | (inline)       |
| Grid           | 2-D spatial grid                    | .rtg / .nc     |
| Time_Series    | 1-D temporal array                  | .txt           |
| Grid_Sequence  | Time-varying 2-D grids              | .rts / .nc     |

---

## 6. Input Files

| File                     | Format       | Purpose                              |
|--------------------------|--------------|--------------------------------------|
| `*_DEM.rtg`              | RTG binary   | Digital elevation model              |
| `*_flow.rtg`             | RTG binary   | D8 flow direction codes              |
| `*_slope.rtg`            | RTG binary   | Slope grid (m/m)                     |
| `*_area.rtg`             | RTG binary   | Contributing area grid               |
| `*_rain_rates.txt`       | Text         | Precipitation time series (mm/hr)    |
| `*_providers.txt`        | Text         | Component selection map              |
| `*_topoflow.cfg`         | CFG          | Driver configuration                 |
| `*_meteorology.cfg`      | CFG          | Meteorology parameters               |
| `*_channels_*.cfg`       | CFG          | Channel routing parameters           |
| `*_infil_*.cfg`          | CFG          | Infiltration parameters              |
| `*_snow_*.cfg`           | CFG          | Snow process parameters              |
| `*_evap_*.cfg`           | CFG          | Evapotranspiration parameters        |
| `*_satzone_*.cfg`        | CFG          | Saturated zone parameters            |
| `*_outlets.txt`          | Text         | Pixel coordinates for time-series    |

**RTG Binary Format:**
Little-endian, row-major float32 array of shape (nrows, ncols).  Accompanied
by a `.rti` header file specifying grid dimensions, cell size, and data type.

---

## 7. Output Files

| File                     | Format   | Key Variables                    |
|--------------------------|----------|----------------------------------|
| `*_0D-Q.txt`             | Text     | Outlet discharge (m³/s) vs time  |
| `*_0D-d.txt`             | Text     | Outlet depth (m) vs time         |
| `*_0D-u.txt`             | Text     | Outlet velocity (m/s) vs time    |
| `*_2D-Q.nc`              | NetCDF   | Spatiotemporal discharge grids   |
| `*_2D-d.nc`              | NetCDF   | Spatiotemporal depth grids       |
| `*_2D-v0.nc`             | NetCDF   | Infiltration rate grids (m/s)    |
| `*_report.txt`           | Text     | Run summary with peak Q, volumes |

**Key CSDMS Output Variable Names:**

| Standard Name                                                  | Symbol   | Unit   |
|----------------------------------------------------------------|----------|--------|
| `basin_outlet_water_x-section__volume_flow_rate`               | Q_outlet | m³/s   |
| `basin_outlet_water_x-section__peak_time_of_volume_flow_rate`  | T_peak   | min    |
| `channel_water_x-section__volume_flow_rate`                    | Q        | m³/s   |
| `atmosphere_water__precipitation_leq-volume_flux`              | P        | m/s    |
| `soil_surface_water__infiltration_volume_flux`                 | v0       | m/s    |
| `snowpack__depth`                                              | hs       | m      |
| `land_surface_water__evaporation_volume_flux`                  | ET       | m/s    |
| `soil_water_sat-zone_top_surface__elevation`                   | h_table  | m      |

---

## 8. Component Methods

### 8.1 Channel Routing

| Method           | Component Name                | Equation                       |
|------------------|-------------------------------|--------------------------------|
| Kinematic Wave   | `tf_channels_kin_wave`        | ∂A/∂t + ∂Q/∂x = q_lat         |
| Diffusive Wave   | `tf_channels_diff_wave`       | + pressure gradient term       |
| Dynamic Wave     | `tf_channels_dynam_wave`      | Full Saint-Venant equations    |

Friction: Manning (`n`) or Law of Wall (`z0`).

### 8.2 Infiltration

| Method           | Component Name                | Key Parameters                 |
|------------------|-------------------------------|--------------------------------|
| Green-Ampt       | `tf_infil_green_ampt`         | Ks, Ki, θs, θi, G             |
| Smith-Parlange   | `tf_infil_smith_parlange`     | Ks, Ki, θs, θi, G, γ          |
| Richards 1-D     | `tf_infil_richards_1d`        | Ks, Ki, θs, θi, θr, pB, λ, c  |
| Beven            | `tf_infil_beven`              | Ks, Ki, θs, θi, G, λ_c        |

### 8.3 Evapotranspiration

| Method           | Component Name                | Key Parameters                 |
|------------------|-------------------------------|--------------------------------|
| Priestley-Taylor | `tf_evap_priestley_taylor`    | α (1.26 default), K_soil      |
| Energy Balance   | `tf_evap_energy_balance`      | Full energy budget             |
| Read from File   | `tf_evap_read_file`           | Pre-computed ET rates          |

### 8.4 Snowmelt

| Method           | Component Name                | Key Parameters                 |
|------------------|-------------------------------|--------------------------------|
| Degree-Day       | `tf_snow_degree_day`          | c0 (melt factor), T0 (threshold)|
| Energy Balance   | `tf_snow_energy_balance`      | Full energy balance            |

---

## 9. Critical Domain Knowledge

These are **non-obvious facts** that cause silent failures if violated:

1. **Precipitation must be in mm/hr in .cfg, not m/s.**  TopoFlow internally
   converts mm/hr → m/s.  If you pre-convert to m/s, the model will apply the
   conversion again, producing near-zero rainfall.

2. **Infiltration Ks must be in m/s, not mm/hr.**  Database values (e.g., HWSD)
   are typically in mm/hr.  Forgetting the ÷3.6e6 conversion produces wildly
   excessive infiltration that swallows all rainfall.

3. **Slope grid must have no zero values.**  Zero slopes cause division-by-zero
   in Manning's equation.  Use a minimum floor of 1e-6 m/m.

4. **Capillary length G is in meters, not cm.**  Literature values for Green-Ampt
   wetting front suction are commonly in cm.  Failure to convert by ÷100
   produces infiltration 100x too large.

5. **Temperature must be in °C, not Kelvin.**  ERA5 provides temperature in K.
   If fed directly, all freezing/thaw/snowmelt logic breaks silently because
   273 °C triggers no snow and extreme evaporation.

6. **D8 flow codes must be consistent with the DEM.**  If you modify the DEM
   (e.g., pit-filling) you must recompute D8 codes, slopes, and areas.
   Stale D8 grids produce incorrect flow routing with no error message.

7. **RTG grid dimensions must exactly match the .rti header.**  Mismatched
   nrows/ncols between the binary data and the header causes silent data
   corruption — the model reads shifted values.

8. **Component timesteps must satisfy CFL condition.**  Channel dt should be
   small enough that water does not traverse more than one cell per step.
   Typical safe value: 2–6 seconds for 30m grids.

9. **Provider file component names are case-sensitive.**  A typo like
   `tf_Channels_kin_wave` silently falls back to defaults or crashes.

---

## 10. Tools Reference

| Tool ID              | Script                   | Stage | Purpose                                  |
|----------------------|--------------------------|-------|------------------------------------------|
| convert_forcing      | `tools/convert_forcing.py`| s2   | Global reanalysis → TopoFlow met format  |
| convert_soil_params  | `tools/convert_soil_params.py`| s3 | HWSD/SoilGrids → infiltration parameters |
| run_topoflow         | `tools/run_topoflow.py`  | s7    | Execute model with preflight checks      |
| parse_output         | `tools/parse_output.py`  | s8    | Extract hydrographs and metrics to CSV   |

---

## 11. Example: Treynor Iowa Test Case

The bundled example uses the **Treynor watershed** in Iowa (30m DEM):

- **Site:** Nishnabotna River tributary near Treynor, IA
- **DEM:** 29 × 44 cells at 30m resolution
- **Events:** June 7, 1967 and June 20, 1967 rainfall
- **Run directory:** `topoflow/examples/Treynor_Iowa_30m/`

```bash
# Run the no-infiltration June 20 test
python -m topoflow \
  --cfg_prefix=June_20_67 \
  --cfg_directory=topoflow/examples/Treynor_Iowa_30m/__No_Infil_June_20_67_Rain \
  --driver_comp_name=topoflow_driver
```

Expected peak discharge at outlet: ~1–5 m³/s depending on infiltration method.

---

## 12. Calibration Parameters

| Parameter     | Component   | Range           | Sensitivity | Notes                         |
|---------------|-------------|-----------------|-------------|-------------------------------|
| Manning's n   | Channels    | 0.01 – 0.20    | High        | Dominates timing and peak     |
| Ks            | Infiltration| 1e-7 – 1e-3 m/s| High        | Controls runoff volume        |
| θs            | Infiltration| 0.30 – 0.55    | Medium      | Soil storage capacity         |
| θi            | Infiltration| 0.10 – 0.40    | Medium      | Initial moisture state        |
| G             | Infiltration| 0.01 – 1.0 m   | Medium      | Wetting front suction (G-A)   |
| α (P-T)       | ET          | 1.0 – 1.74     | Medium      | Priestley-Taylor coefficient  |
| c0            | Snow        | 1–8 mm/°C/day  | Medium      | Degree-day melt factor        |
| Channel width | Channels    | 0.5 – 50 m     | High        | Affects velocity and depth    |
| dt            | All         | 1 – 60 sec     | High        | Stability (CFL condition)     |
| K_soil        | ET          | 0.4 – 2.0 W/m/K| Low        | Soil thermal conductivity     |

---

## 13. Diagnostic Triplets Summary

See `diagnostics/triplets.yaml` for full details.

| ID     | Severity | Domain           | Summary                                    |
|--------|----------|------------------|--------------------------------------------|
| dt_001 | silent   | unit_conversion  | Precip in wrong units → flood or drought   |
| dt_002 | silent   | unit_conversion  | Ks in mm/hr instead of m/s                 |
| dt_003 | fatal    | parameter_format | Zero slope causes division by zero         |
| dt_004 | silent   | unit_conversion  | Capillary length G in cm not m             |
| dt_005 | silent   | unit_conversion  | Temperature in K not °C                    |
| dt_006 | silent   | data_consistency | Stale D8 codes after DEM modification      |
| dt_007 | silent   | parameter_format | RTG/RTI dimension mismatch                 |
| dt_008 | degraded | runtime          | CFL violation from too-large timestep      |
| dt_009 | fatal    | parameter_format | Provider file typo / case error            |
| dt_010 | silent   | unit_conversion  | Soil porosity as percentage not fraction   |
| dt_011 | degraded | runtime          | NetCDF output missing time variable        |
| dt_012 | silent   | unit_conversion  | ET in mm/day instead of mm/hr              |
| dt_013 | fatal    | dependency       | cfunits not installed → EMELI crash        |
| dt_014 | silent   | data_consistency | Outlet pixel outside flow domain           |
| dt_015 | degraded | runtime          | Channel width zero at some cells           |
| dt_016 | silent   | unit_conversion  | Wind speed height mismatch                 |
| dt_017 | silent   | parameter_format | Manning's n inverted (using 1/n)           |

---

## 14. Quick Start (6-Step Pipeline)

```bash
# 1. Install
python -m venv tf_venv && source tf_venv/bin/activate
pip install -e /path/to/topoflow36

# 2. Prepare domain (DEM → D8 codes, slopes, areas)
python -c "
from topoflow.components.d8_global import d8_component
d = d8_component()
d.initialize(cfg_file='my_d8.cfg')
d.update()
d.finalize()
"

# 3. Prepare met forcing
python ki/tools/convert_forcing.py \
  --source era5 --lat 41.17 --lon -95.62 \
  --start 1967-06-20 --end 1967-06-21 \
  --output_dir ./met_input/

# 4. Prepare soil parameters
python ki/tools/convert_soil_params.py \
  --source hwsd --lat 41.17 --lon -95.62 \
  --method green_ampt --output_dir ./soil_input/

# 5. Run model
python ki/tools/run_topoflow.py \
  --cfg_prefix=Test1 \
  --cfg_directory=./cfg/ \
  --driver_comp_name=topoflow_driver

# 6. Parse output
python ki/tools/parse_output.py \
  --output_dir=./output/ \
  --prefix=Test1 \
  --format csv
```

---

## 15. File Structure

```
ki/
├── SKILL.md                          # This file
├── tools/
│   ├── convert_forcing.py            # s2: Met forcing converter
│   ├── convert_soil_params.py        # s3: Soil parameter converter
│   ├── run_topoflow.py              # s7: Execution wrapper
│   └── parse_output.py              # s8: Output parser
├── docs/
│   ├── s1_domain_setup.md           # DEM and D8 preparation
│   ├── s2_met_forcing.md            # Meteorology forcing
│   ├── s3_soil_parameters.md        # Soil and infiltration
│   ├── s4_channel_geometry.md       # Channel setup
│   ├── s5_execution.md             # Running the model
│   └── s6_output_analysis.md       # Output interpretation
└── diagnostics/
    └── triplets.yaml                # 17 diagnostic triplets
```
