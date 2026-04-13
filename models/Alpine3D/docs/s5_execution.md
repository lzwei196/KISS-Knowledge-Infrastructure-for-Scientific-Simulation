# S5 — Running Alpine3D

## Purpose

Execute the Alpine3D model with validated configuration and inputs. Handle
parallelism options, monitor progress, and manage restarts.

## Inputs

| Item | Format | Source | Required |
|------|--------|--------|----------|
| io.ini | INI file | Stage s0 configuration | Yes |
| Meteorological data | SMET files | Stage s2 output | Yes |
| Initial snow profiles | .sno files | Stage s3 output | Yes |
| DEM + land-use grids | ARC ASCII | Stage s0 output | Yes |
| Alpine3D binary | Executable | Build step | Yes |

## Outputs

| File | Format | Path |
|------|--------|------|
| Gridded fields | ARC ASCII | `output/grids/YYYYMMDDHHMI_PARAM.asc` |
| Time series at POIs | SMET | `output/{poi_id}_meteo.smet` |
| Snow profiles at POIs | PRO | `output/{poi_id}.pro` |
| Snow state for restart | SMET .sno | `output/snowfiles/*.sno` |
| Console log | Text | `stdouterr.log` (if redirected) |

## Procedure

### 1. Pre-flight Validation

Use the wrapper tool to validate before running:

```bash
python tools/run_alpine3d.py \
    --iofile ./setup/io.ini \
    --startdate 2014-10-01T01:00 \
    --enddate 2015-09-30T00:00 \
    --np-ebalance 4 --np-snowpack 4 \
    --dry-run
```

This checks:
- ALPINE3D = TRUE in [SnowpackAdvanced]
- DEM and land-use grid dimensions match
- PSUM accumulation period matches timestep
- GEO_HEAT and ROUGHNESS_LENGTH in valid ranges
- np-ebalance ≤ DEM nrows
- Input files exist

### 2. Choose Parallelism Mode

| Mode | Flag | Best For | Scaling |
|------|------|----------|---------|
| Sequential | (default) | Small domains, debugging | 1 core |
| OpenMP | `--parallel openmp` | Workstations, <32 cores | Good to ~16 cores |
| MPI | `--parallel mpi` | Clusters, >32 cores | Excellent |
| Hybrid | OpenMP + MPI | Large HPC jobs | Best for large domains |

**Rule of thumb for np-ebalance**: Use min(ncores, nrows_DEM).
**Rule of thumb for np-snowpack**: Use min(ncores, nrows_DEM).

### 3. Run the Simulation

```bash
# Sequential run
python tools/run_alpine3d.py \
    --iofile ./setup/io.ini \
    --startdate 2014-10-01T01:00 \
    --enddate 2015-09-30T00:00

# OpenMP parallel run
python tools/run_alpine3d.py \
    --iofile ./setup/io.ini \
    --startdate 2014-10-01T01:00 \
    --enddate 2015-09-30T00:00 \
    --parallel openmp --ncores 8 \
    --np-ebalance 8 --np-snowpack 8

# Direct invocation (without wrapper)
alpine3d --iofile=./setup/io.ini \
    --np-ebalance=4 --np-snowpack=4 \
    --enable-eb \
    --startdate=2014-10-01T01:00 --enddate=2015-09-30T00:00 \
    > stdouterr.log 2>&1
```

### 4. Using the Launch Script (run.sh)

The bundled `run.sh` handles SLURM, MPI, and OpenMP setup:

```bash
# Edit run.sh header:
PARALLEL=OPENMP     # N, OPENMP, MPI, or MPI_SGE
NCORES=8
BEGIN="2014-10-01T01:00"
END="2015-09-30T00:00"
REDIRECT_LOGS=Y

# Submit to SLURM
sbatch run.sh
```

### 5. Monitor Progress

```bash
# Watch the log
tail -f stdouterr.log

# Check output grid generation
ls -lt output/grids/ | head -10

# Monitor memory usage (Alpine3D can be memory-intensive)
watch -n 5 'ps aux | grep alpine3d | head -3'
```

### 6. Restart from Checkpoint

If the simulation fails or is interrupted:

```bash
# 1. Copy the latest snow state files to input
cp output/snowfiles/*.sno input/snowfiles/

# 2. Find the last successful timestep
ls -lt output/grids/ | head -5
# e.g., 201501150000_SWE.asc → restart from 2015-01-15T00:00

# 3. Run with --restart flag and updated start date
alpine3d --iofile=./setup/io.ini \
    --restart \
    --startdate=2015-01-15T00:00 --enddate=2015-09-30T00:00 \
    --np-ebalance=4 --np-snowpack=4
```

### 7. Runtime Estimation

| Domain Size | Resolution | Period | Cores | Approximate Time |
|-------------|-----------|--------|-------|-----------------|
| 5×5 km | 25 m | 1 year | 1 | 2–6 hours |
| 5×5 km | 25 m | 1 year | 8 | 30–90 min |
| 20×20 km | 100 m | 1 year | 1 | 1–3 hours |
| 20×20 km | 100 m | 1 year | 16 | 10–30 min |
| 50×50 km | 250 m | 10 years | 32 | 6–24 hours |

## Verification

```bash
# Check return code
echo $?   # 0 = success

# Verify output grids were created
ls output/grids/ | wc -l
echo "Expected: ~365 files per parameter per year"

# Check last grid file timestamp
ls -lt output/grids/ | head -3

# Quick sanity check on SWE
python3 -c "
with open('output/grids/$(ls output/grids/*SWE* | tail -1)') as f:
    for _ in range(6): f.readline()
    vals = [float(v) for line in f for v in line.split() if float(v) != -9999]
    print(f'SWE: mean={sum(vals)/len(vals):.1f}, max={max(vals):.1f} kg/m²')
"

# Check time series output
wc -l output/*.smet
```

## Traps

| Issue | Symptom | Fix |
|-------|---------|-----|
| np-ebalance > nrows | Crash at startup | Reduce to ≤ nrows |
| Missing .sno file for pixel | "Cannot read snow file" | Generate all .sno files |
| ALPINE3D = FALSE | Wrong spatial patterns | Set to TRUE |
| Disk full | Crash mid-simulation | Reduce output frequency |
| MPI library mismatch | Startup failure | Match MPI build/runtime |
| SIGKILL (OOM) | Killed by OS | Reduce domain or resolution |

## Example

```bash
# Complete run for Dischma test case
cd ~/sim/Dischma/setup

python tools/run_alpine3d.py \
    --iofile ./io.ini \
    --startdate 2014-10-01T01:00 \
    --enddate 2014-12-31T00:00 \
    --np-ebalance 2 --np-snowpack 2 \
    --enable-eb \
    --parallel openmp --ncores 4

# Expected output:
# {"status": "success", "return_code": 0, "elapsed_seconds": 180.5, ...}
```
