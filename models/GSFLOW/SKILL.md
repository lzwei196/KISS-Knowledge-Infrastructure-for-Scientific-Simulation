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

# GSFLOW — Coupled Groundwater and Surface-Water Flow Model

## 1. Model Overview

GSFLOW (Groundwater and Surface-water FLOW) is a USGS coupled hydrological model
that integrates the Precipitation-Runoff Modeling System (PRMS-V) with MODFLOW-2005/NWT
to simultaneously simulate surface-water flow, unsaturated-zone flow, and
saturated groundwater flow. It operates on a **daily timestep** and is designed for
watershed-scale applications ranging from a few km² to several thousand km².

**Key capabilities:**
- Surface runoff, interflow, and baseflow generation (PRMS)
- Saturated groundwater flow with Newton-Raphson solver (MODFLOW-NWT)
- Coupled stream-aquifer interaction via SFR/UZF packages
- Lake dynamics and agricultural water use
- Snow accumulation and melt
- Evapotranspiration from canopy, soil, and groundwater

**Version:** 2.3.1 (current repository: gsflow_v2)
**Language:** Fortran 90 (with C utilities)
**License:** Public domain (USGS)
**Build:** gfortran + gcc → single `gsflow` executable

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/HWSD/SKILL.md` for soil property documentation.
See `data_ki/ObservedQ/SKILL.md` for observed discharge data.


## 2. Installation

### 2.1 Prerequisites
- gfortran (≥8.0) and gcc
- Python 3.8+ with: numpy, pandas, flopy, pygsflow, pymake, shapely, rasterio
- Optional: netCDF4 (for forcing data processing)

### 2.2 Compile from Source
```bash
cd GSFLOW/source/repo/autotest
chmod +x make_linux_gfortran.sh
sed -i -e 's/\r$//' make_linux_gfortran.sh
./make_linux_gfortran.sh
# Binary: ./gsflow
```

### 2.3 Manual Makefile Build
```bash
cd GSFLOW/source/repo/GSFLOW/src
make clean && make
# Binary: ../bin/gsflow
```

### 2.4 Conda Environment
```bash
conda env create -f etc/environment.yml
conda activate pygsflow
```

---

## 3. Execution

### 3.1 Command Line
```bash
gsflow <control_file>
# If no argument, looks for file named "control" in current directory
```

### 3.2 Model Modes
| Mode | Control Parameter | Description |
|------|-------------------|-------------|
| `GSFLOW5` | `model_mode = GSFLOW5` | Coupled PRMS + MODFLOW |
| `PRMS5` | `model_mode = PRMS5` | PRMS surface-water only |
| `MODFLOW` | `model_mode = MODFLOW` | MODFLOW groundwater only |

### 3.3 Python Interface (pygsflow)
```python
import gsflow
gs = gsflow.GsflowModel.load_from_file("control_file.control")
gs.run_model(gsflow_exe="path/to/gsflow")
```

---

## 4. Pipeline Stages

| # | Stage | Key Tools | Inputs | Outputs |
|---|-------|-----------|--------|---------|
| 0 | Configuration | - | Basin info, period | Control file skeleton |
| 1 | Domain Setup | DEM + shapefile | DEM, basin boundary | HRU delineation, MODFLOW grid |
| 2 | Soil Parameters | HWSD/SoilGrids | Soil data, HRU map | Soil hydraulic params |
| 3 | Vegetation/Land Cover | AVHRR/MODIS | Land cover raster | Vegetation type per HRU |
| 4 | Meteorological Forcing | CMFD/MSWX converter | NetCDF forcing grids | PRMS data file or .day files |
| 5 | Model Parameters | Parameter builder | Soil+veg+basin info | PRMS .params + MODFLOW packages |
| 6 | Model Execution | run_gsflow.py | Control + all inputs | Model output files |
| 7 | Output Parsing | parse_output.py | CSV/binary output | Extracted time series |
| 8 | Routing (optional) | - | Already included in GSFLOW | Streamflow at outlet |

**Parallelism:** Stages 1–4 can run in parallel. Stage 5 requires 1–3. Stage 6 requires 4–5.

---

## 5. Input File Formats

### 5.1 Control File (.control)
Plain text with `####` delimiters between parameter blocks.
```
GSFLOW control file - Sagehen Creek
####
model_mode
1
4
GSFLOW5
####
start_time
6
1
1980
10
1
0
0
0
####
end_time
6
1
1990
9
30
0
0
0
####
data_file
1
4
./input/prms/sagehen.data
####
param_file
5
4
./input/prms/prms.params
./input/prms/gis.params
./input/prms/gsflow.params
./input/prms/gvr.params
./input/prms/ncascade.params
####
modflow_name
1
4
./input/modflow/sagehen.nam
####
```
Each block: parameter_name, n_values, data_type (1=int, 2=float, 4=string), then values.

### 5.2 Data File (.data)
Time-series observations/forcing at station locations.
```
Sagehen Creek watershed data
// Comments start with // or /*
####
tmax 2
tmin 2
precip 2
runoff 1
####
1969 10 1 0 0 0  66.00  63.00  38.00  36.00  0.00  0.00  10.60
1969 10 2 0 0 0  59.00  58.00  31.00  30.00  0.01  0.00   9.50
```
Format: year month day hour min sec val1 val2 ... valN

### 5.3 Parameter File (.params)
```
PRMS parameter file
** Dimensions **
####
nrain
2
####
nhru
128
####
** Parameters **
####
ssr2gw_rate
1
nssr
128
2
0.2567
0.2730
...
####
```
Block: param_name, n_dimensions, dimension_name(s), n_values, data_type, values.

### 5.4 Pre-processed Climate Files (.day)
One value per HRU per day (climate_hru module):
```
tmax.day generated by write_climate_hru
########################################
1980 10 1 0 0 0  55.2  54.8  53.1  52.5 ... (128 values)
1980 10 2 0 0 0  57.1  56.3  55.0  54.2 ...
```

### 5.5 MODFLOW Name File (.nam)
```
LIST  26  ../output/modflow/sagehen.mf.list
BAS6   8  ../input/modflow/sagehen.bas
DIS   11  ../input/modflow/sagehen.dis
LPF   12  ../input/modflow/sagehen.lpf
SFR   15  ../input/modflow/sagehen.sfr
UZF   14  ../input/modflow/sagehen.uzf
```

---

## 6. Unit Trap Table

**CRITICAL:** GSFLOW uses US customary units internally. All conversions must be
verified at each interface boundary.

| Variable | GSFLOW Internal | CMFD Source | Conversion | Trap |
|----------|----------------|-------------|------------|------|
| Temperature | °F (default) or °C | Kelvin | K→°F: (K-273.15)×9/5+32; K→°C: K-273.15 | `temp_units=0` → °F; `temp_units=1` → °C |
| Precipitation | inches/day (default) or mm/day | mm/day | mm→in: ×0.03937 (÷25.4) | `precip_units=0` → inches; `precip_units=1` → mm |
| Solar radiation | Langleys/day (cal/cm²/day) | W/m² | W/m²→Ly/day: ×2.065 (×86400/41868) | Underestimate by 2× if not converted |
| Runoff (obs) | cfs or cms | m³/s | Use as-is if cms | `runoff_units=0` → cfs; `runoff_units=1` → cms |
| Streamflow out | cfs (basin_cfs) | - | cfs→cms: ×0.028317 | Output in `basin_cfs` variable |
| Length (MODFLOW) | feet or meters | meters | Set LENUNI=2 for meters | MODFLOW LENUNI parameter |
| Time (MODFLOW) | days | - | Set ITMUNI=4 for days | MODFLOW ITMUNI parameter |
| Elevation | feet or meters | meters | Must match DEM units | Mismatch → wrong lapse rates |
| Area | acres | km² | km²→acres: ×247.105 | `hru_area` in acres |
| ET | inches/day | - | Computed internally | Select et_module in control file |

### Silent Failure Modes (Unit Conversions)
1. **1000× precip error:** Forgetting mm→inches conversion when precip_units=0 → extreme flooding
2. **Temperature offset:** Using °C data with temp_units=0 (°F) → all snow melts immediately
3. **Solar radiation:** Using W/m² directly as Langleys → 2× underestimate → low ET
4. **Elevation mismatch:** DEM in meters, params in feet → wrong temperature lapse rates
5. **Area units:** HRU areas must be in acres for PRMS internal calculations

---

## 7. Key Control Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model_mode` | str | GSFLOW5 | Run mode: GSFLOW5, PRMS5, MODFLOW |
| `start_time` | 6 int | - | Start date: Y M D H Min S |
| `end_time` | 6 int | - | End date: Y M D H Min S |
| `data_file` | str | - | Path to PRMS data file |
| `param_file` | str[] | - | Paths to parameter files |
| `modflow_name` | str | - | Path to MODFLOW name file |
| `temp_module` | str | temp_1sta | Temperature distribution module |
| `precip_module` | str | precip_1sta | Precipitation distribution module |
| `solrad_module` | str | ddsolrad | Solar radiation module |
| `et_module` | str | potet_jh | Potential ET module |
| `srunoff_module` | str | srunoff_smidx | Surface runoff module |
| `strmflow_module` | str | strmflow | Streamflow routing module |
| `soilzone_module` | str | soilzone | Soil zone module |
| `model_output_file` | str | - | PRMS listing output |
| `gsflow_output_file` | str | - | GSFLOW water budget output |
| `csv_output_file` | str | - | CSV output file path |
| `basinOutON_OFF` | int | 0 | Basin summary: 0=off, 1=on |
| `basinOutVars` | int | 0 | Number of basin output variables |
| `basinOutVar_names` | str[] | - | Names of output variables |
| `basinOut_freq` | int | 1 | Output frequency (1=daily,...6=yearly) |
| `nhruOutON_OFF` | int | 0 | HRU-level output: 0=off, 1=on |
| `print_debug` | int | 0 | Debug level (-2 to 9) |
| `parameter_check_flag` | int | 0 | Validate parameters: 0=off, 1=on |

---

## 8. Key Output Variables

### 8.1 Basin-level Variables (CSV output)
| Variable | Units | Description |
|----------|-------|-------------|
| `basin_cfs` | ft³/s | Streamflow at basin outlet |
| `basin_ppt` | inches | Area-weighted precipitation |
| `basin_tmax` | °F or °C | Area-weighted max temperature |
| `basin_tmin` | °F or °C | Area-weighted min temperature |
| `basin_potet` | inches | Potential evapotranspiration |
| `basin_actet` | inches | Actual evapotranspiration |
| `basin_sroff` | inches | Surface runoff |
| `basin_ssflow` | inches | Subsurface (interflow) |
| `basin_gwflow` | inches | Groundwater discharge |
| `basin_stflow` | inches | Total streamflow (inches) |
| `basin_soil_moist` | inches | Soil moisture storage |
| `basin_recharge` | inches | Groundwater recharge |
| `basin_snow` | inches | Snowpack water equivalent |

### 8.2 Output Frequencies
| Code | Frequency |
|------|-----------|
| 1 | Daily |
| 2 | Monthly |
| 3 | Daily + Monthly |
| 4 | Mean Monthly |
| 5 | Mean Yearly |
| 6 | Yearly |

### 8.3 MODFLOW Output
- Head files (`.hds`): Groundwater head per layer/cell
- Budget files (`.cbc`): Cell-by-cell flow budgets
- Listing file (`.list`): Volumetric water budget summaries
- SFR gage files: Streamflow at specified segments
- UZF output: Unsaturated zone fluxes

---

## 9. Critical Domain Knowledge

### 9.1 PRMS HRU Concept
GSFLOW discretizes the landscape into Hydrologic Response Units (HRUs).
Each HRU has uniform: slope, aspect, elevation, soil type, vegetation type.
HRUs are NOT grid cells — they can be irregular polygons (sub-basins, hillslopes).
The MODFLOW component uses a regular finite-difference grid.
The coupling maps HRU ↔ MODFLOW cells through the GVR (Gravity Reservoir) concept.

### 9.2 Cascading Flow
PRMS routes water through a cascade of HRUs (upslope → downslope).
Parameters: `hru_up_id`, `hru_down_id`, `hru_pct_up`, `cascade_flg`.
If cascades are not set correctly, water does not reach the stream segments.

### 9.3 MODFLOW Stress Periods
GSFLOW uses internal daily stress periods for coupling.
The `modflow_time_zero` control parameter MUST precede `start_time`.
Typically set to the day before start_time.

### 9.4 Convergence Issues
The coupled PRMS-MODFLOW iteration can fail to converge.
Symptom: "FAILED TO MEET SOLVER CONVERGENCE" in listing file.
Remedy: Increase max_iterations, relax closure criteria, or switch to NWT solver.

### 9.5 Spinup Requirements
GSFLOW needs 1–3 years of spinup to initialize:
- Soil moisture profile
- Snowpack
- Groundwater heads
- Unsaturated zone storage
Discard spinup period from analysis.

### 9.6 Climate Module Selection
| Module | Use Case | Input |
|--------|----------|-------|
| `climate_hru` | Pre-processed gridded data | .day files (1 value/HRU/day) |
| `temp_1sta` / `precip_1sta` | Single station with lapse | .data file stations |
| `temp_dist2` / `precip_dist2` | Multiple stations, IDW | .data file stations |
| `xyz_dist` | XYZ distribution | .data file stations |

For **gridded forcing** (CMFD, MSWX): use `climate_hru` module with pre-processed .day files.

### 9.7 Calibration Parameters (Priority Order)
1. `soil_moist_max` — Maximum soil moisture capacity (inches)
2. `soil_rechr_max` — Maximum recharge zone capacity (inches)
3. `ssr2gw_rate` — Subsurface → groundwater rate (fraction/day)
4. `slowcoef_lin` — Linear interflow coefficient
5. `gwflow_coef` — Groundwater discharge coefficient
6. `smidx_coef` / `smidx_exp` — Surface runoff coefficients
7. `rain_cbh_adj` / `snow_cbh_adj` — Precipitation adjustment factors
8. `tmax_cbh_adj` / `tmin_cbh_adj` — Temperature adjustment factors
9. `jh_coef` — Jensen-Haise PET coefficient (if et_module=potet_jh)
10. `hru_percent_imperv` — Impervious fraction

---

## 10. Tool Reference

| Tool | Lines | Stage | Purpose |
|------|-------|-------|---------|
| `convert_forcing_to_gsflow.py` | ~320 | s4 | CMFD/MSWX NetCDF → PRMS .day files |
| `convert_soil_params.py` | ~250 | s2 | HWSD → PRMS soil parameters |
| `run_gsflow.py` | ~180 | s6 | Execute GSFLOW binary with validation |
| `parse_gsflow_output.py` | ~280 | s7 | Extract CSV time series from output |
| `build_control_file.py` | ~200 | s0 | Generate GSFLOW control file |

---

## 11. Example Problems (Bundled)

| Example | Basin | Mode | Features |
|---------|-------|------|----------|
| sagehen | Sagehen Creek, CA | GSFLOW/PRMS/MODFLOW | Primary test case, 128 HRUs |
| sagehen_restart | Sagehen Creek | GSFLOW | Restart capability demo |
| tahoe_restart | Lake Tahoe, CA/NV | GSFLOW | Lake dynamics + restart |
| Ag_EP1a/1b | Sagehen Creek | GSFLOW | AG package (irrigation) |
| Ag_EP2a/2b | Sagehen Creek | GSFLOW | AG package (advanced) |
| acfb_dyn_params | ACF Basin, GA | PRMS | Dynamic parameters |
| acfb_water_use | ACF Basin, GA | PRMS | Water use module |
| Ex_prob1a/1b/2/3 | Synthetic | GSFLOW | Simple test problems |

---

## 12. Diagnostic Triplets Summary

### Unit Conversion Traps
- **Precip mm→inches:** 25.4× error if not converted (precip_units=0)
- **Temp K→°F:** Wrong snow/ET if units mismatch
- **Solar W/m²→Langleys:** 2× ET error if not converted
- **Elevation ft/m mismatch:** Wrong lapse rate corrections

### Parameter Format Traps
- **Dimension mismatch:** Parameter array length ≠ declared dimension → crash
- **Missing ####:** Delimiter required between every parameter block
- **Wrong data type code:** 1=int, 2=real, 4=string — swap causes silent errors

### Runtime Traps
- **MODFLOW non-convergence:** NWT solver usually more robust than PCG
- **Negative soil moisture:** Check soil_moist_max and rechr parameters
- **Missing cascade definitions:** Water pools in HRUs, no streamflow generated
- **modflow_time_zero after start_time:** GSFLOW aborts

### Path Resolution Traps
- **Windows backslashes on Linux:** Control/nam files from Windows examples need path fixes
- **Relative path base:** Paths in control file are relative to control file location

---

## 13. Coupling Points

### Upstream Models
- **Gridded climate data** (CMFD, MSWX, ERA5) → convert to .day files via climate_hru
- **Watershed delineation** (pygsflow, GIS) → HRU/cascade parameters

### Downstream Models
- **CaMa-Flood:** GSFLOW streamflow → river routing
- **Water quality models:** GSFLOW baseflow/runoff partitioning

### Internal Coupling (PRMS ↔ MODFLOW)
- PRMS → MODFLOW: Gravity drainage (recharge) via UZF package
- MODFLOW → PRMS: Groundwater discharge, stream gains/losses via SFR
- Exchange arrays: `EXCHANGE`, `DELTAVOL`, `LAKEVOL`

---

## 14. Quick-Start: Run Sagehen Example

```bash
# 1. Build
cd /path/to/gsflow_v2/autotest
chmod +x make_linux_gfortran.sh && ./make_linux_gfortran.sh

# 2. Fix paths for Linux
cd /path/to/gsflow_v2/GSFLOW/data/sagehen
python3 -c "
import gsflow
gs = gsflow.GsflowModel.load_from_file('windows/gsflow.control')
gs.control.set_values('modflow_name', ['./input/modflow/sagehen.nam'])
gs.write_input()
"

# 3. Run
./gsflow windows/gsflow.control

# 4. Check output
ls output/prms/  # PRMS output files
ls output/modflow/  # MODFLOW output files
```

---

## 15. Validation Reference

### Sagehen Creek (Built-in)
- Location: Sierra Nevada, California
- Area: ~27 km² (128 HRUs)
- Period: 1969–2007 (example: 1980–1996)
- Observed: USGS streamflow gage
- Expected NSE: 0.5–0.8 (calibrated)

### Bengbu Basin (Huai River, China)
- Station: 51080 (Bengbu)
- Area: ~121,330 km²
- Period: 1980–1990 (1980 spinup, validate 1981–1990)
- Forcing: CMFD 0.25° daily
- Note: Requires full GSFLOW setup with MODFLOW grid — complex for large basins.
  Alternative: Run PRMS-only mode for surface-water validation.

---

## 16. File Organization Convention

```
project/
├── control/
│   └── gsflow.control          # Control file
├── input/
│   ├── prms/
│   │   ├── basin.data          # Station observations
│   │   ├── prms.params         # PRMS parameters
│   │   ├── gsflow.params       # Coupling parameters
│   │   ├── gvr.params          # GVR cell mapping
│   │   ├── tmax.day            # Pre-processed climate
│   │   ├── tmin.day
│   │   ├── precip.day
│   │   └── swrad.day
│   └── modflow/
│       ├── model.nam           # MODFLOW name file
│       ├── model.dis           # Discretization
│       ├── model.bas           # Basic package
│       ├── model.upw           # Upstream weighting
│       ├── model.nwt           # NWT solver
│       ├── model.sfr           # Streamflow routing
│       ├── model.uzf           # Unsaturated zone
│       └── model.oc            # Output control
└── output/
    ├── prms/
    │   ├── gsflow.out          # Listing file
    │   └── basin_summary.csv   # Basin outputs
    └── modflow/
        ├── model.list          # MODFLOW listing
        └── model.hds           # Head solution
```
