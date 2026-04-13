# Stage 4: Model Execution

## Purpose

Run the ELMFIRE binary with preflight validation, monitor execution, and perform post-run output checks. This stage bridges input preparation and output analysis.

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| `elmfire.data` | Stage 3 | Fortran namelist configuration |
| Landscape rasters | Stage 1 | dem, slp, asp, fbfm40, cc, ch, cbh, cbd, adj, phi |
| Weather rasters | Stage 2 | ws, wd, m1, m10, m100 |
| ELMFIRE binary | Build/Docker | `elmfire_2025.1002` executable |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `time_of_arrival_*.bil/.tif` | Raster | Fire arrival time (seconds) |
| `spread_rate_*.bil/.tif` | Raster | Rate of spread (ft/min) |
| `flin_*.bil/.tif` | Raster | Fireline intensity (kW/m) |
| `flame_length_*.bil/.tif` | Raster | Flame length (feet) |
| `fire_size_stats_*.csv` | CSV | Cumulative area and perimeter |

## Procedure

### Step 1: Preflight checks

```bash
# 1. Verify binary exists
which elmfire_2025.1002 || echo "Binary not in PATH"

# 2. Verify all input files
for f in asp slp dem fbfm40 cc ch cbh cbd adj phi ws wd m1 m10 m100; do
    test -f ./inputs/${f}.tif || echo "MISSING: ${f}.tif"
done

# 3. Verify output directory exists
mkdir -p ./outputs ./scratch

# 4. Verify GDAL is available
which gdal_translate || echo "GDAL not in PATH"
```

### Step 2: Execute ELMFIRE

```bash
# Single process (small domains, testing)
elmfire_2025.1002 ./inputs/elmfire.data

# MPI parallel (production, large domains)
mpirun -np 4 elmfire_2025.1002 ./inputs/elmfire.data

# Docker execution
docker run -v $(pwd):/run elmfire \
    mpirun -np 4 elmfire_2025.1002 /run/inputs/elmfire.data
```

### Step 3: Using the run wrapper

```bash
python run_elmfire.py \
    --namelist ./inputs/elmfire.data \
    --np 4 \
    --binary elmfire_2025.1002 \
    --timeout 3600
```

The wrapper performs:
1. All preflight checks above
2. Creates missing directories
3. Runs the binary with timeout
4. Validates output file existence
5. Reports summary JSON with timing

### Step 4: Convert BIL to GeoTIFF (if CONVERT_TO_GEOTIFF = .FALSE.)

```bash
A_SRS="EPSG: 32610"
for f in ./outputs/*.bil; do
    gdal_translate -a_srs "$A_SRS" \
        -co "COMPRESS=DEFLATE" -co "ZLEVEL=9" \
        $f ./outputs/$(basename $f .bil).tif
done
```

### Step 5: Generate fire isochrones

```bash
gdal_contour -i 3600 \
    ./outputs/time_of_arrival_IWX001_CASE0001.tif \
    ./outputs/hourly_isochrones.shp
```

### Step 6: Post-run validation

```bash
# Check fire actually spread
python -c "
import csv
with open('./outputs/fire_size_stats_IWX001.csv') as f:
    rows = list(csv.DictReader(f))
    last = rows[-1]
    area = float(list(last.values())[3])  # Area(acres)
    print(f'Final area: {area:.1f} acres')
    if area < 1:
        print('WARNING: Fire barely spread — check inputs')
"
```

## Verification

1. **Output files exist**: At least `time_of_arrival_*.bil` should be present
2. **Fire size > 0**: Check fire_size_stats CSV for non-zero area
3. **No errors in stderr**: Check MPI output for errors or warnings
4. **Runtime reasonable**: Tutorial 01 should complete in < 30 seconds
5. **Time of arrival range**: Max TOA should be close to SIMULATION_TSTOP

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Binary not in PATH | "command not found" | `export PATH=$ELMFIRE_BASE_DIR/build/linux/bin:$PATH` |
| Missing MPI | mpirun not found | `apt install openmpi-bin` or use single-process |
| Raster dimension mismatch | Segfault | Resample all rasters to identical extent |
| Outputs directory missing | No output files | `mkdir -p ./outputs` |
| Scratch directory missing | GDAL conversion fails | `mkdir -p ./scratch` |
| CFL instability | Simulation hangs | Increase cell size or reduce TARGET_CFL |
| Ignition on NODATA pixel | Zero fire area | Move ignition to valid pixel |

## Example

Running Tutorial 01 (constant wind):

```bash
cd tutorials/01-constant-wind

# Full pipeline
./01-run.sh

# Or step-by-step
mkdir -p inputs outputs scratch
cp elmfire.data.in inputs/elmfire.data

# Create constant rasters (15 mph wind, fuel model 102)
# ... (see 01-run.sh for GDAL commands)

# Run
elmfire_2025.1002 ./inputs/elmfire.data

# Convert outputs
for f in ./outputs/*.bil; do
    gdal_translate -a_srs "EPSG: 32610" $f ./outputs/$(basename $f .bil).tif
done

# Create hourly fire perimeter contours
gdal_contour -i 3600 ./outputs/time_of_arrival*.tif ./outputs/hourly_isochrones.shp
```

Expected output for Tutorial 01:
- Fire spreads as an ellipse elongated in the downwind (south) direction
- Area: ~200–400 acres after 5.5 hours
- Max spread rate: ~150–250 ft/min in grassland with 15 mph wind
- No crown fire (canopy cover = 0%)
