# Stage 4: Model Execution

## Purpose

Compile and run the EF5/CREST model, including configuration assembly, binary execution, and runtime monitoring. This stage ties together all prepared inputs (grids, forcing, parameters) into a single simulation run.

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| EF5 binary | Compiled from source (Stage 0) | `bin/ef5` executable |
| control.txt | Assembled from Stages 1-3 | Complete configuration file |
| DEM, DDM, FAM | Stage 1 | Basin topology grids |
| Precip grids | Stage 2 | Timestamped precipitation |
| PET grids | Stage 2 | Timestamped PET |
| Parameter grids | Stage 3 | WM, B, IM, FC grids |
| Observation CSV | External | Optional: for calibration/validation |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Gauge time series | Text/CSV | Simulated (and observed) discharge at each gauge |
| Grid outputs | TIF/ASC | Spatial fields (streamflow, soil moisture, etc.) |
| State files | TIF | Model state at TIME_STATE for restart |

## Procedure

### Step 1: Compile EF5 (if needed)

```bash
cd /path/to/EF5
autoreconf --force --install
./configure
make CXXFLAGS="-O3 -fopenmp"
# Binary: bin/ef5
```

**Dependencies**: libgeotiff-dev, libtiff-dev, zlib1g-dev, g++, autotools

### Step 2: Assemble control.txt

Complete configuration file structure:

```ini
# 1. Basic grids
[Basic]
DEM=/data/basin/DEM.asc
DDM=/data/basin/DDM.asc
FAM=/data/basin/FAM.asc
PROJ=geographic
ESRIDDM=true
SELFFAM=true

# 2. Precipitation
[PrecipForcing precip]
TYPE=ASC
UNIT=mm/h
FREQ=3h
LOC=/data/basin/precip/
NAME=precip_YYYYMMDDHHUU.asc

# 3. PET
[PETForcing pet]
TYPE=ASC
UNIT=mm/d
FREQ=d
LOC=/data/basin/pet/
NAME=pet_YYYYMMDD.asc

# 4. Gauge
[Gauge outlet]
LON=117.38
LAT=32.95
OBS=/data/basin/obs/discharge.csv
BASINAREA=121330
OUTPUTTS=TRUE

# 5. Basin
[Basin basin1]
GAUGE=outlet

# 6. CREST parameters
[CrestParamSet params1]
GAUGE=outlet
wm=1.0
b=1.0
im=5.0
ke=0.8
fc=1.0
iwu=50.0
wm_grid=/data/basin/params/wm.tif
fc_grid=/data/basin/params/fc.tif

# 7. Routing parameters (Linear Reservoir)
[LRParamSet route1]
GAUGE=outlet
COEM=500.0
RIVER=200.0
UNDER=1000.0
LEAKO=0.5
LEAKI=0.02
TH=10.0
ISO=0.0
ISU=0.0

# 8. Task
[Task run1]
STYLE=SIMU
MODEL=CREST
ROUTING=LR
BASIN=basin1
PRECIP=precip
PET=pet
PARAM_SET=params1
ROUTING_PARAM_SET=route1
OUTPUT=/data/basin/output/
TIMESTEP=1h
TIME_BEGIN=200101010000
TIME_END=200112312300
TIME_WARMEND=200103010000

# 9. Execute
[Execute]
TASK=run1
```

### Step 3: Run EF5

```bash
# Simple run
ef5 control.txt

# With OpenMP parallelization
OMP_NUM_THREADS=4 ef5 control.txt

# Using wrapper tool
python run_ef5.py --binary bin/ef5 --control control.txt --threads 4
```

### Step 4: Monitor execution

EF5 prints progress to stdout:
```
********************************************************
**   Ensemble Framework For Flash Flood Forecasting   **
**                   Version 1.2.3                     **
********************************************************
Using CREST SM State Grid ...
```

Typical runtime: 1-60 minutes depending on basin size, resolution, and time period.

### Step 5: Check outputs

```bash
ls /data/basin/output/
# Should contain gauge time series files and optionally grid outputs
```

## Verification

1. **Successful exit**: EF5 returns exit code 0
2. **Output files exist**: Check for time series and/or grid files
3. **Output values reasonable**: Discharge should be physically plausible
4. **No warnings**: Check stdout for "not found", "less than 0", or NaN warnings

```bash
# Quick check
python run_ef5.py --binary bin/ef5 --control control.txt --log run_log.json
cat run_log.json | python -m json.tool
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Missing grid file | "File not found" error, crash | Check all paths in control.txt are absolute and correct |
| Wrong projection | Gauge not snapping to grid | Verify PROJ matches grid CRS |
| Time step too large | Numerical instability, spikes | Reduce TIMESTEP (try 15u or 5u for small basins) |
| No forcing files in period | Zero discharge output | Check TIME_BEGIN/END overlap with forcing file dates |
| NAME template mismatch | "File not found" for forcing | Verify date tokens in NAME match actual filenames |
| OUTPUT dir doesn't exist | Silent failure | Create output directory before running |
| ROUTING not set | Uses water balance only (no discharge) | Add ROUTING=LR or ROUTING=KW |
| ROUTING_PARAM_SET missing | Crash when routing enabled | Must specify routing params when ROUTING is set |
| BASINAREA mismatch | Gauge snaps to wrong cell | Check BASINAREA matches reality; EF5 searches nearby cells |
| Config section name case | Section not found | Section types are case-insensitive, but referenced names must match exactly |

## Example: Full run command

```bash
# Create output directory
mkdir -p /data/bengbu/output/

# Run with 4 threads
OMP_NUM_THREADS=4 /path/to/ef5/bin/ef5 /data/bengbu/control.txt

# Check results
wc -l /data/bengbu/output/*.csv
```
