> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model. Doing so produces
> scientifically invalid results and defeats the purpose of the KI.
>
> Before starting, run: `python preflight_check.py` (in this KI directory)
> to verify that the model binary/package and required data are available.

---

# VIC Model Automated Run Skill

## 📖 Description

This skill is used to automate the VIC hydrological model run, covering the complete workflow from basin shapefile to runoff output. It supports any basin — just provide a basin boundary shapefile.

## 🎯 Use Cases

- Quick setup of VIC model for a new basin
- Standardized VIC parameter preparation workflow
- Automated VIC execution and post-processing

## ⚡ Quick Start

### Prerequisites

1. **Basin boundary file**: Shapefile format (.shp and accompanying files)
2. **Meteorological data**: CMFD 0.1-degree 3-hourly data (located at `data/forcing/Data_forcing_03hr_010deg/`)
3. **Python environment**: Must use the designated virtual environment

### Basic Usage

```bash
# 🔴 Pitfall 1: Must activate the correct Python virtual environment first!
source /Users/yc/Desktop/project/python_env/bin/activate

# 1. Prepare basin shapefile
# 🔴 Pitfall 2: Shapefile naming may follow one of two formats:
#    - data/shp/{basin_name}_shp/{basin_name}_clip.shp (e.g., bengbu)
#    - data/shp/{basin_name}_shp/{basin_name}.shp (e.g., wangjiaba)
# Point the environment variable VIC_BASIN_SHP at the actual .shp file (do not edit config_paths.py in the KI)

# 2. Set the basin name with environment variables (do not edit config_paths.py in the KI)
#    config_paths.py and the configured stage-script copies read VIC_BASIN_NAME
export BASIN_NAME="your_basin_name"
export VIC_BASIN_NAME="$BASIN_NAME"
export VIC_BASIN_SHP="/path/to/your_basin.shp"
export CONFIGURED_SCRIPTS_DIR="KISSPATH_OUTPUTS/$BASIN_NAME/vic_temp/configured_scripts"
cd /Volumes/Expansion2t/hydro-model-workspace/scripts

# 3. Run the configuration script (must be in the virtual environment)
python config_paths.py

# 4. Manually run VIC preparation and simulation steps from the configured copies that
#    config_paths.py wrote to outputs/${BASIN_NAME}/vic_temp/configured_scripts/ (the KI is never changed)
# See the "Complete Workflow" section below
```

---

## 📋 Complete Workflow (Manual Execution Recommended)

### 🔴 Important: Execution Order

**Critical order**:
```
Step 1 (Grid) → Step 2 (Soil params) → Step 3 (Vegetation params) → Step 4 (Meteorological data) → Step 5 (Config check) → Step 6 (Run VIC) → Step 7 (Post-processing to NC)
```

**Reason for this order**:
- `process_forcing.py` needs to read `SOIL_PARAM_COMPLETE.txt` to obtain grid coordinates, **soil must come before forcing**
- Vegetation parameters only depend on the grid file and can be executed any time after soil

### 🔴 Important: Correct Path Structure

**All outputs should be organized under a basin-specific directory**:

```
outputs/{basin_name}/
├── vic_temp/              # VIC intermediate files
│   ├── grid/             # Grid files
│   ├── forcing/          # Meteorological data
│   │   ├── forcing_1d/   # Clipped NC files
│   │   └── forcing_final/# VIC input forcing files
│   ├── soil/             # Soil parameters
│   ├── veg/              # Vegetation parameters
│   └── logs/             # Logs
├── vic_result/           # VIC model output
└── cama_input/           # Converted CaMa input (optional)
```

### Step 0: Environment Preparation

```bash
# 🔴🔴🔴 Most important: Activate Python virtual environment (must be done every time a new terminal is opened) 🔴🔴🔴
source /Users/yc/Desktop/project/python_env/bin/activate

# Set working directory
cd /Volumes/Expansion2t/hydro-model-workspace

# Set basin name (environment variable)
export BASIN_NAME="your_basin_name"
# config_paths.py and every stage script read VIC_BASIN_NAME; set it before configuration and every stage
export VIC_BASIN_NAME="$BASIN_NAME"

# Set as needed (environment variables the code really reads; do not edit scripts in the KI):
# export VIC_BASIN_SHP=/path/to/basin.shp          # basin boundary (s1_grid, config_paths.py)
# export VIC_CMFD_DIR=/path/to/cmfd                # CMFD input folder for forcing_1d.py
# export VIC_YEAR_START=1979 VIC_YEAR_END=1980     # forcing_1d.py years; when both are set, also written to global param STARTYEAR/ENDYEAR/FORCEYEAR
# export VIC_START_DATE=1979-01-01 VIC_END_DATE=1980-12-31   # process_forcing.py period
# export VIC_FORCING_PREFIX=huai_01dy_025deg_      # forcing file name prefix (process_forcing.py and global param FORCING1)
# export VIC_RES=0.25                              # grid resolution (same for all stages)
# export VIC_ELEV_NC=... VIC_PREC_ANNUAL_NC=... VIC_SOIL_RASTER=...   # inputs of fill_parameters1.py
# export VIC_GLOBAL_PARAM_TEMPLATE=...             # global param template (config_paths.py)
# Do not set VIC_OUT_ROOT: config_paths.py always uses KISSPATH_OUTPUTS

# Configured-copies folder (absolute path, same as CONFIGURED_SCRIPTS_DIR in config_paths.py)
export CONFIGURED_SCRIPTS_DIR="KISSPATH_OUTPUTS/$BASIN_NAME/vic_temp/configured_scripts"

# Run the configuration script first (writes the stage-script copies and the global param file; does not change the KI)
(cd scripts && python config_paths.py)
```

### 🔴 Summary of Common Pitfalls (Must Read)

1. **Python environment**: Must execute `source /Users/yc/Desktop/project/python_env/bin/activate` before running any Python script

2. **Shapefile naming**: Check whether the actual file name is `{basin}.shp` or `{basin}_clip.shp`, and set it with `export VIC_BASIN_SHP=<actual .shp path>` (do not edit config_paths.py in the KI)

3. **Time range**: Set with environment variables (do not edit scripts in the KI); export them before configuration and every stage:
   - `VIC_YEAR_START`, `VIC_YEAR_END`: read by forcing_1d.py; when both are set, config_paths.py also writes them to STARTYEAR, ENDYEAR, FORCEYEAR in the global param file
   - `VIC_START_DATE`, `VIC_END_DATE`: read by process_forcing.py
   - Global parameter file: check STARTYEAR, ENDYEAR, FORCEYEAR after the run

4. **GRID_NC_PATH in forcing_1d.py**: built from `VIC_BASIN_NAME` and `VIC_RES`; do not edit the script in the KI:
   ```
   outputs/{basin}/vic_temp/grid/grid_{basin}_025deg.nc
   ```

5. **Global parameter file**: After running config_paths.py, **manual verification is required**:
   - FROZEN_SOIL must be `FALSE` (not a path)
   - LAI_SRC must be `FROM_VEGPARAM` (without extra path)
   - FORCING1 prefix must match actual file names (usually `huai_01dy_025deg_`)

---

## 🌊 CaMa-Flood Integration

After VIC post-processing is complete, if you need to run the CaMa-Flood river routing model, please refer to the **`cama-flood-integration`** skill.

---

## 📋 VIC Complete Workflow

### Step 1: Generate Basin Grid (0.25°)

```bash
cd "$CONFIGURED_SCRIPTS_DIR/s1_grid" && python make_basin_grid_nc.py   # copy written by config_paths.py; the KI is not changed
```

**Output**: `outputs/${BASIN_NAME}/vic_temp/grid/grid_${BASIN_NAME}_025deg.nc`

**Check**:
```bash
ls -lh outputs/${BASIN_NAME}/vic_temp/grid/
# Should see a grid_xxx_025deg.nc file
```

### Step 2: Generate Soil Parameters (Before Forcing Processing)

**⚠️ Important Order**: Soil parameters must be generated first, because the forcing processing script needs to read the soil parameter file to obtain grid coordinate information.

#### 2.1 Generate Soil Parameter Framework

```bash
cd "$CONFIGURED_SCRIPTS_DIR/s3_soil" && python fill_parameters1.py
```

**Output**: `outputs/${BASIN_NAME}/vic_temp/soil/SOIL_PARAM_FINAL.txt`

#### 2.2 Interpolation to Fill Soil Parameters

```bash
cd "$CONFIGURED_SCRIPTS_DIR/s3_soil" && python fill_parameters2.py
```

**Output**: `outputs/${BASIN_NAME}/vic_temp/soil/SOIL_PARAM_COMPLETE.txt`

### Step 3: Process Meteorological Data (Depends on Soil Parameters)

**⚠️ Dependency**: This step must be executed after soil parameters are generated, because `process_forcing.py` needs to read `SOIL_PARAM_COMPLETE.txt` to obtain accurate grid latitude/longitude coordinates.

#### 3.1 Clip CMFD Data to Basin Extent

```bash
cd "$CONFIGURED_SCRIPTS_DIR/s2_forcing" && python forcing_1d.py
```

**Output**: `outputs/${BASIN_NAME}/vic_temp/forcing/forcing_1d/*.nc` (96 files)

**Key Points**:
- This step clips from 0.1-degree CMFD data to the basin grid
- Automatically handles NaN values at boundary grid points

#### 3.2 Generate VIC Forcing Files

```bash
cd "$CONFIGURED_SCRIPTS_DIR/s2_forcing" && python process_forcing.py
```

**Output**: `outputs/${BASIN_NAME}/vic_temp/forcing/forcing_final/huai_01dy_025deg_*.txt` (one file per grid point)

**⚠️ Important**: Check path configuration
- `INPUT_DATA_DIR`: Should point to `forcing_1d/`
- `OUTPUT_FORCING_DIR`: Should point to `forcing_final/`
- `SOIL_PARAM_FILE`: Should point to `SOIL_PARAM_COMPLETE.txt` (must exist)

### Step 4: Generate Vegetation Parameters

```bash
cd "$CONFIGURED_SCRIPTS_DIR/s4_veg" && python process_vegetation_detailed.py
```

**Output**: `outputs/${BASIN_NAME}/vic_temp/veg/vic_veg_param_final.txt`

### Step 5: Configure and Check Global Parameter File

```bash
# config_paths.py already ran in Step 0; if you changed environment variables since, run it again (it only writes copies and the global param file, never the KI)
(cd /Volumes/Expansion2t/hydro-model-workspace/scripts && python config_paths.py)
```

**Output**: `outputs/${BASIN_NAME}/vic_temp/global_param_${BASIN_NAME}.txt`

**⚠️ Critical Configuration Checks**:

Edit `outputs/${BASIN_NAME}/vic_temp/global_param_${BASIN_NAME}.txt` and verify:

1. **Time settings** (adjust as needed):
```
STARTYEAR               2024
STARTMONTH              01
STARTDAY                01
ENDYEAR                 2024
ENDMONTH                12
ENDDAY                  31
```

2. **Forcing path** (file name prefix must match actual files):
```
FORCING1                /path/to/forcing_final/huai_01dy_025deg_
```

3. **Time step** (must match forcing data):
```
MODEL_STEPS_PER_DAY     8
FORCE_STEPS_PER_DAY     8
```

4. **Output path** (should be under basin-specific directory):
```
RESULT_DIR              /path/to/outputs/${BASIN_NAME}/vic_result/
```

5. **Parameter file paths** (ensure all paths are correct):
```
SOIL                    /path/to/outputs/${BASIN_NAME}/vic_temp/soil/SOIL_PARAM_COMPLETE.txt
VEGPARAM                /path/to/outputs/${BASIN_NAME}/vic_temp/veg/vic_veg_param_final.txt
```

### Step 6: Run VIC Model

```bash
# Create output directory
mkdir -p outputs/${BASIN_NAME}/vic_result

# Run VIC
/Volumes/Expansion2t/hydro-model-workspace/model/VIC-5.1.0/vic/drivers/classic/vic_classic.exe \
  -g outputs/vic_temp/global_param_${BASIN_NAME}.txt
```

**Expected Output**:
- `outputs/${BASIN_NAME}/vic_result/huaihe_fluxes_*.txt` (one file per grid point)
- Run time: a few seconds to a few minutes (depending on number of grid points and simulation duration)

**Check Output**:
```bash
ls outputs/${BASIN_NAME}/vic_result/*.txt | wc -l
# Should equal the number of grid points
```

### Step 7: VIC Post-processing (Convert to NetCDF)

**Execute only when CaMa-Flood input is needed**

```bash
cd scripts/vic_post
python process_${BASIN_NAME}.py
```

**Output**: `outputs/${BASIN_NAME}/cama_input/${BASIN_NAME}_runoff_1d_YYYY.nc`

**⚠️ Path Configuration**: Ensure path variables in the script are correct:
- `INPUT_DIR`: VIC output directory
- `OUTPUT_DIR`: CaMa input directory

---

## 🔧 Common Issues and Solutions

### ⚠️ Issue 0: FROZEN_SOIL Parameter Error

**Error**: `is neither TRUE nor FALSE`

**Cause**: The FROZEN_SOIL entry in the global parameter file is followed by a path instead of a boolean value

**Solution**:
```bash
# Check the global parameter file
grep FROZEN_SOIL outputs/${BASIN_NAME}/vic_temp/global_param_${BASIN_NAME}.txt

# Should display:
# FROZEN_SOIL             FALSE   # Not simulating frozen soil

# If it shows a path, manually modify it to the format above
```

**Root Cause Fix**:
- The template file `docs/vic_param/global_param_huaihe_cama.txt` has been fixed
- Re-run `python scripts/config_paths.py` to generate a new global parameter file

### Issue 1: Forcing Files Not Found

**Error**: `Unable to open File .../forcing_XX.XXXX_XXX.XXXX`

**Cause**: The FORCING1 prefix in the global parameter file does not match actual file names

**Solution**:
```bash
# Check actual file names
ls outputs/${BASIN_NAME}/vic_temp/forcing/forcing_final/ | head -1

# Example output: huai_01dy_025deg_31.1250_115.6250
# Then FORCING1 should be set to: .../forcing_final/huai_01dy_025deg_
```

### Issue 2: Insufficient Time Steps

**Error**: `Not enough records in forcing file`

**Cause**: The simulation period in the global parameter file exceeds the forcing data range

**Solution**: Ensure STARTYEAR/ENDYEAR are consistent with the forcing data time range

### Issue 3: Path Confusion

**Error**: Various "file does not exist" errors

**Cause**: Output files scattered across different directories (vic_temp vs. ${BASIN_NAME}/vic_temp)

**Solution**:
1. Consistently use `outputs/${BASIN_NAME}/` as the basin-specific root directory
2. Check path configuration in all scripts
3. Create symbolic links or move files manually if necessary

### Issue 4: Vegetation Parameter Root Zone Fractions Sum > 1

**Warning**: `Root zone fractions sum to more than 1`

**Cause**: Normal behavior; VIC will automatically normalize

**Solution**: No action needed — this is a warning, not an error

---

## 📊 Output Description

### VIC Model Output Files

**Location**: `outputs/${BASIN_NAME}/vic_result/huaihe_fluxes_LAT_LON.txt`

**Format**: ASCII text, column-separated

**Main Variables**:
- `OUT_PREC`: Precipitation
- `OUT_RUNOFF`: Surface runoff
- `OUT_BASEFLOW`: Baseflow
- `OUT_EVAP`: Evapotranspiration
- `OUT_SOIL_MOIST`: Soil moisture
- etc. (see OUTVAR configuration in the global parameter file)

### NetCDF Output (Post-processing)

**Location**: `outputs/${BASIN_NAME}/cama_input/${BASIN_NAME}_runoff_1d_YYYY.nc`

**Variables**:
- `Runoff`: Total runoff (OUT_RUNOFF + OUT_BASEFLOW)
- Unit: mm/day
- Dimensions: (time, lat, lon)

---

## 🎓 New Basin Adaptation Guide

### 1. Prepare Basin Data

```bash
# Create basin directory
mkdir -p data/shp/${BASIN_NAME}_shp

# Copy shapefile (ensure .shp, .shx, .dbf, .prj, etc. are included)
cp /path/to/your/basin.shp data/shp/${BASIN_NAME}_shp/${BASIN_NAME}_clip.shp
# ... other accompanying files
```

### 2. Set the basin name (do not edit files inside the KI)

```bash
export BASIN_NAME="your_basin_name"      # Change to your basin name
export VIC_BASIN_NAME="$BASIN_NAME"      # the stage scripts read this variable
# then run config_paths.py as in Step 0 to write the configured_scripts copies
```

### 3. Create VIC Post-processing Script

Copy and modify an existing script:
```bash
cd scripts/vic_post
cp process_bengbu.py process_${BASIN_NAME}.py
```

Edit the new script and modify the following variables:
```python
# Input/output paths
INPUT_DIR = f"/path/to/outputs/{BASIN_NAME}/vic_result"
OUTPUT_DIR = f"/path/to/outputs/{BASIN_NAME}/cama_input"

# Grid definition (automatically obtained from shapefile, or set manually)
NX = 24        # Number of grid points in east-west direction
NY = 16        # Number of grid points in north-south direction
WEST = 111.875   # West boundary
EAST = 117.625   # East boundary
NORTH = 34.875  # North boundary
SOUTH = 31.125  # South boundary
GRID_SIZE = 0.25  # Resolution

# File name prefix (adjust according to actual forcing file names)
FILE_PREFIX = "huaihe_fluxes_"
OUTPUT_NC_PREFIX = f"{BASIN_NAME}_runoff_1d_"
```

### 4. Follow the "Complete Workflow"

Start from Step 0 and execute all steps sequentially.

---

## 💡 Best Practices

### 1. Path Management
- ✅ Use basin-specific directory `outputs/${BASIN_NAME}/`
- ✅ Maintain consistent path structure
- ❌ Avoid hardcoded absolute paths

### 2. Configuration Management
- ✅ Check all path configurations before running
- ✅ Verify forcing file name prefix
- ✅ Confirm time range consistency

### 3. Debugging Strategy
- ✅ Execute step by step, checking output at each step
- ✅ Save log files
- ✅ Use `ls -lh` to verify file generation

### 4. Data Validation
- ✅ Check that the number of grid points is correct
- ✅ Verify time series length
- ✅ Check that value ranges are reasonable

---

## 📚 References

- VIC model documentation: https://vic.readthedocs.io/
- CMFD meteorological data: http://www.tpdc.ac.cn/
- Project README: `/Volumes/Expansion2t/hydro-model-workspace/README.md`

---

## ✨ Version History

- **v1.1** (2025-02-01):
  - Corrected path structure description
  - Clarified workflow order
  - Added common issue solutions
  - Improved new basin adaptation guide

- **v1.0** (2025-01-31): Initial release

---

## 📧 Maintenance Information

**Skill Path**: `/Volumes/Expansion2t/hydro-model-workspace/skills/vic-auto-run/`

**Core Scripts**: See subdirectories under `scripts/`

**Dependencies**:
- VIC 5.0.1+
- Python 3.8+
- Virtual environment: `/Users/yc/Desktop/project/python_env/`
