# Stage 5: Model Execution

## Purpose

Run the EF5 binary to perform hydrologic simulation, calibration, or basin processing. This stage requires all preceding stages (basic grids, forcing, parameters, config) to be complete.

## Inputs

| Input | Source |
|-------|--------|
| `control.txt` | Stage 4 (configuration assembly) |
| EF5 binary (`bin/ef5`) | Compiled from source |
| Basic grids (DEM, DDM, FAM) | Stage 1 |
| Forcing grids (precip, PET, temp) | Stage 2 |
| Parameter grids | Stage 3 |
| Observed data (for calibration) | External |

## Outputs

| Output | Description |
|--------|-------------|
| Gauge time series | CSV files per gauge with datetime and streamflow (m³/s) |
| Gridded outputs | GeoTIFF grids of selected variables (streamflow, SM, SWE, etc.) |
| State files | Model state grids at specified time (for warm restart) |
| Calibration results | CSV with parameter sets and objective function values |

## Procedure

### 1. Pre-flight validation

```bash
python tools/run_ef5.py --binary bin/ef5 --control control.txt
# This runs preflight checks before execution
```

Or manually:
```bash
# Check binary
./bin/ef5 --help 2>&1 | head -5

# Quick config check
grep -c "\[" control.txt  # Should show number of sections
```

### 2. Run simulation

```bash
# Default: reads control.txt from current directory
cd /path/to/workspace
./bin/ef5

# Or specify control file
./bin/ef5 /path/to/control.txt
```

### 3. Run with OpenMP parallelism

```bash
# Set number of threads
export OMP_NUM_THREADS=4
./bin/ef5 control.txt
```

### 4. Common execution modes

#### Standard simulation
```ini
[Task run]
STYLE=SIMU
MODEL=CREST
ROUTING=KW
# ... (full config)
```

#### Simulation with warm-up period
```ini
[Task run]
STYLE=SIMU
TIME_BEGIN=200801010000    # Start of warm-up
TIME_WARMEND=200901010000  # End of warm-up (output starts here)
TIME_END=200912312300      # End of simulation
```

#### Save model states for restart
```ini
[Task run]
STYLE=SIMU
STATES=/path/to/states/
TIME_STATE=200907010000    # Save state at this time
```

#### Calibration with DREAM
```ini
[Task calibrate]
STYLE=CALI_DREAM
MODEL=CREST
ROUTING=KW
PARAM_SET=myparams
ROUTING_PARAM_SET=myroute
CALI_PARAM=mycali
ROUTING_CALI_PARAM=myroutecali
# ... other settings
```

#### Generate gridded output
```ini
[Task run]
STYLE=SIMU
OUTPUT_GRIDS=STREAMFLOW|SOILMOISTURE|MAXSTREAMFLOW
# ... other settings
```

### 5. DEM preprocessing mode

```bash
# Generate flow direction and accumulation from raw DEM
./bin/ef5 -z DEM.tif -d DDM.tif -a FAM.tif -p    # pit-fill + process
./bin/ef5 -z DEM.tif -d DDM.tif -a FAM.tif -s     # slope computation
```

## Verification

### Check output was produced
```bash
# Check for gauge time series output
ls -la /path/to/output/*.csv

# Check for gridded output (if OUTPUT_GRIDS specified)
ls -la /path/to/output/*.tif | head -20

# Check file sizes (non-zero)
find /path/to/output/ -name "*.csv" -size 0 -print
```

### Check output values
```python
import csv
# Read first gauge output
with open("output/gauge_outlet.csv") as f:
    reader = csv.reader(f)
    for i, row in enumerate(reader):
        if i < 5:
            print(row)
        if i > 0:
            q = float(row[1])
            assert q >= 0, f"Negative streamflow at {row[0]}"
            assert q < 100000, f"Unrealistic streamflow {q} at {row[0]}"
```

### Check runtime
- Small basin (~1000 cells), 1 year, hourly: < 10 seconds
- Medium basin (~10,000 cells), 1 year, hourly: < 2 minutes
- Continental scale, 1 year, hourly: may require hours

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| No [Execute] section | EF5 prints header and exits silently | Add `[Execute]\nTASK=taskname` |
| Wrong control file path | "Failed to open config file" | Check path; default is `control.txt` in CWD |
| Missing forcing files | Zero precipitation/PET, dry simulation | Verify LOC path and NAME pattern match actual files |
| Gauge outside DEM domain | Gauge not found, no output | Check gauge LON/LAT within DEM extent |
| BASINAREA mismatch | Gauge snaps to wrong cell | Verify basin area matches FAM-derived area at gauge |
| Timestep too large for routing | Numerical instability, oscillations | Reduce TIMESTEP (try 5u for small basins) |
| No routing specified | EF5 may crash or use default LR | Always specify ROUTING=KW or ROUTING=LR |
| State path doesn't exist | State files not written | Create STATES directory before running |
| Memory overflow on large domain | Segfault or OOM kill | Reduce domain size or use CLIP_BASIN first |
| Binary not executable | "Permission denied" | `chmod +x bin/ef5` |

## Example

```bash
# Complete workflow
cd /data/ef5_run/

# Verify binary works
./bin/ef5 2>&1 | head -3
# Expected: "Ensemble Framework For Flash Flood Forecasting"

# Create output directory
mkdir -p output

# Run
./bin/ef5 control.txt 2>&1 | tee run.log

# Check results
echo "Output files:"
ls -la output/
echo "First lines of gauge output:"
head -5 output/*.csv
```
