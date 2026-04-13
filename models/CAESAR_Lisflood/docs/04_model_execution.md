# Stage 4: Model Execution

## Purpose

Compile and run the HAIL-CAESAR model binary, including pre-flight checks, OpenMP configuration, and post-flight output validation.

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| Source code | HAIL-CAESAR repository | C++ source in `src/`, headers in `include/` |
| Parameter file | From Stage 3 | `.params` file with all settings |
| DEM | From Stage 1 | ASCII grid elevation file |
| Rainfall file | From Stage 2 | Headerless text rainfall timeseries |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Binary | `bin/HAIL-CAESAR.exe` | Compiled executable |
| Timeseries | `.dat` text file | Discharge and sediment time series |
| Rasters | `.asc` files | Water depth, elevation, etc. at save intervals |
| Console output | STDOUT | Runtime progress and diagnostics |

## Procedure

### Step 1: Compile the model

```bash
cd /path/to/HAIL-CAESAR
make clean
make -j4
```

This produces `bin/HAIL-CAESAR.exe`. Requirements:
- g++ with C++11 support
- OpenMP runtime (usually included with g++)

Compilation flags (from Makefile):
- `-std=c++11`: C++11 standard
- `-fopenmp`: OpenMP parallelisation
- `-DOMP_COMPILE_FOR_PARALLEL`: Enable parallel code paths

### Step 2: Pre-flight checks

Before running, verify:
1. Binary exists: `ls -la bin/HAIL-CAESAR.exe`
2. DEM file exists at the path specified in parameter file
3. Rainfall file exists at the path specified
4. Output directory exists: `mkdir -p ./results/`
5. Parameter file is correctly formatted (no syntax errors)

### Step 3: Configure OpenMP (optional)

```bash
export OMP_NUM_THREADS=4    # Set to number of cores
```

The model will report thread count at startup:
```
Your system has: 4 PROCESSORS available and 4 THREADS to use!
```

### Step 4: Run the model

```bash
./bin/HAIL-CAESAR.exe /path/to/input_data/ parameter_file.params
```

**Arguments**:
1. Path to directory containing all input files (DEM, rainfall, etc.)
2. Name of the parameter file (must be in that directory)

The model will:
1. Print parameter values to STDOUT
2. Load DEM and supplementary data
3. Enter the main simulation loop
4. Print cycle counter (model minutes elapsed)
5. Write output files at specified intervals
6. Print "THE SIMULATION IS FINISHED!" when done

### Step 5: Monitor runtime

The model prints the current simulation minute to STDOUT. Expected runtime depends on:
- Grid cells: Primary factor (scales ~linearly)
- Resolution: Finer DEMs need smaller Courant numbers = more timesteps
- Hydro-only vs erosion: Erosion roughly doubles runtime
- Parallelism: Near-linear scaling up to ~8 cores

Rough benchmarks (single core):
- 7,200 cells (Boscastle 50m), 72hr: ~2-5 minutes
- 700,000 cells (Boscastle 5m), 48hr: ~2-3 hours
- 1M+ cells: Consider reducing resolution or using parallel

### Step 6: Post-flight validation

After the model finishes:

1. Check return code (0 = success)
2. Verify timeseries file exists and has data:
   ```bash
   wc -l results/output.dat
   head results/output.dat
   ```
3. Verify raster files were created:
   ```bash
   ls results/WaterDepths*.asc | wc -l
   ```
4. Check for reasonable values (no NaN, no extreme values)

## Verification

| Check | Expected | Problem if not |
|-------|----------|----------------|
| Return code | 0 | Model crashed (check STDERR) |
| Timeseries rows | > 0 | No output produced |
| Peak discharge | > 0 m3/s | No water entering catchment |
| Max water depth | < 100m | Numerical instability |
| Raster count | duration / raster_interval | Missing output timesteps |

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Wrong number of arguments | "No parameter file supplied" | Need exactly 2 args: path and param file |
| Relative path issues | "No terrain DEM found" | `read_path` in params should be relative to binary location, or use absolute paths |
| Permission denied | Can't execute binary | `chmod +x bin/HAIL-CAESAR.exe` |
| Segfault / core dump | Memory issues with large DEMs | Reduce DEM size or increase stack size (`ulimit -s unlimited`) |
| Model hangs (no output) | Timestep too small, tiny flow amounts | Increase `hflow_threshold`, check DEM for closed basins |
| OMP_NUM_THREADS=1 | Slow on multi-core system | `export OMP_NUM_THREADS=N` |
| Output dir doesn't exist | No files written | Create with `mkdir -p` before running |

## Example

Using the `run_caesar.py` wrapper:

```bash
python run_caesar.py \
    --source_dir /path/to/HAIL-CAESAR \
    --data_dir ./test/input_data/boscastle/boscastle_input_data/ \
    --param_file boscastle_test_72hr_50m_u.params \
    --num_threads 4
```

Or directly:

```bash
cd /path/to/HAIL-CAESAR
make
mkdir -p test/results/boscastle50m_72_u/
./bin/HAIL-CAESAR.exe ./test/input_data/boscastle/boscastle_input_data/ boscastle_test_72hr_50m_u.params
```
