# Stage 6: Model Execution

## Purpose

Build and execute the CLM5/CTSM model binary, either through the CIME case
management system or standalone via LILAC. This stage handles compilation,
job submission, runtime monitoring, and error capture.

## Prerequisites

- Stages 0–5 complete (case configured, surface data, forcing, namelists)
- Fortran compiler, MPI, NetCDF, ESMF installed and configured
- Sufficient disk space (~10 GB per simulation year for history files)
- Job scheduler access (PBS, SLURM) for HPC, or local resources

## Inputs

| Input | Description | Source |
|---|---|---|
| Case directory | Complete CIME case | Stage 0 |
| lnd_in namelist | CLM configuration | Stage 5 (auto-generated) |
| Surface dataset | PFT/soil data | Stage 1 / inputdata |
| Forcing streams | DATM configuration | Stage 2 |
| Initial conditions | finidat file (optional) | inputdata or spinup |

## Procedure

### Step 1: Pre-flight checks

Before building/submitting, verify the environment:

```bash
cd /path/to/case

# Check case status
./xmlquery --listall | head -20

# Preview namelists without building
./preview_namelists

# Check that input data is available
./check_input_data
```

### Step 2: Build the model

```bash
# Standard build (parallel)
./case.build

# Clean build (if previous build exists)
./case.build --clean-all
./case.build
```

Build time: 10–30 minutes depending on compiler and physics options.

### Step 3: Submit the job

```bash
# Submit to job scheduler
./case.submit

# Or run interactively (single processor, for debugging)
./case.submit --no-batch
```

### Step 4: Monitor execution

```bash
# Check job status
./xmlquery RUNDIR
tail -f /path/to/rundir/cesm.log.*

# Check timing
cat /path/to/case/timing/cesm_timing.*
```

### Alternative: Use the execution wrapper

```bash
python ki/tools/run_clm.py \
    --action submit \
    --case-dir /path/to/case \
    --timeout 7200
```

Or create and run in one step:

```bash
python ki/tools/run_clm.py \
    --action create-and-run \
    --ctsm-root /path/to/ctsm \
    --case-name test_run \
    --compset I2000Clm60Sp \
    --res f09_g17 \
    --timeout 14400
```

## Outputs

| Output | Location | Description |
|---|---|---|
| History files | `$RUNDIR/*.clm2.h0.*.nc` | Monthly averages (default) |
| Restart files | `$RUNDIR/*.clm2.r.*.nc` | Model state for restart |
| Log files | `$RUNDIR/cesm.log.*` | Execution log |
| Timing files | `$CASEDIR/timing/` | Performance timing |
| Short-term archive | `$DOUT_S_ROOT/` | Archived output |

### History File Naming

```
$CASE.clm2.h0.YYYY-MM.nc     # Monthly average (default h0)
$CASE.clm2.h1.YYYY-MM-DD.nc  # Daily or custom frequency
$CASE.clm2.h0a.YYYY-MM.nc    # Accumulated fields (CTSM 5.4+)
$CASE.clm2.h0i.YYYY-MM.nc    # Instantaneous fields (CTSM 5.4+)
```

## Verification

1. **Build success**: Check that `cesm.exe` exists in the build directory
2. **Run completion**: `cesm.log` should end with "SUCCESSFUL TERMINATION"
3. **History files**: At least one `.h0.` file should be created
4. **Physical checks**: Open h0 file and verify GPP > 0, temperature in
   reasonable range (200–340 K), no NaN values in major fields
5. **Timing**: Check `cesm_timing` for reasonable SYPD (simulated years
   per day) — typical: 5–50 SYPD for f09 on modern HPC

## Common Traps

### dt_009: Insufficient spinup (DEGRADED)

Running BGC mode from cold start without spinup produces transient
artifacts that persist for decades. Soil carbon pools take 200–600
years to equilibrate.

**Fix**: Use `CLM_ACCELERATED_SPINUP=on` for initial 100+ years, then
switch to normal mode for final equilibration.

### dt_010: Surface dataset file not found (FATAL)

The surface dataset path in `lnd_in` must match an existing file.
If you change resolution or PFT configuration without updating the
surface dataset path, CLM5 fails immediately at startup.

**Fix**: Run `./check_input_data` before submitting. Use
`./xmlchange LND_DOMAIN_FILE=...` if needed.

### dt_012: NetCDF dimension mismatch (FATAL)

If forcing files have different spatial dimensions than the domain
file, CLM5 crashes with "dimension mismatch" errors. This occurs
when mixing resolutions or using custom single-point forcing with
the wrong domain.

### dt_015: Namelist syntax error (FATAL)

Fortran namelists require specific formatting: strings in single
quotes, logicals as `.true.`/`.false.`, arrays as comma-separated
values. A misplaced quote or wrong type causes a parse error at
startup.

### Memory and I/O issues

- CLM5 at f09 requires ~4–8 GB per MPI task for BGC mode
- History output at daily frequency generates ~50 GB/year at f09
- Restart files are ~2 GB each at f09

## Example

Run a 5-year simulation at single-point Harvard Forest:

```bash
python ki/tools/run_clm.py \
    --action status \
    --case-dir ~/cases/US-Ha1

# If healthy, submit
python ki/tools/run_clm.py \
    --action submit \
    --case-dir ~/cases/US-Ha1 \
    --timeout 3600
```
