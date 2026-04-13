# Stage 4: Assimilation Execution

## Purpose

Run the DART `filter` program to perform ensemble data assimilation.
This is the core stage that combines model predictions with observations
to produce improved state estimates.

## Inputs

| File | Format | Description |
|---|---|---|
| `input.nml` | Fortran namelist | All configuration namelists |
| `obs_seq.out` | obs_seq | Observation file with values |
| Ensemble states | NetCDF | Initial ensemble members |
| `prior_inf_mean.nc` | NetCDF | Prior inflation (if from restart) |
| `prior_inf_sd.nc` | NetCDF | Prior inflation SD (if from restart) |

## Outputs

| File | Format | Description |
|---|---|---|
| `obs_seq.final` | obs_seq | Observations with prior/posterior values |
| `preassim_mean.nc` | NetCDF | Prior ensemble mean |
| `preassim_sd.nc` | NetCDF | Prior ensemble spread |
| `analysis_mean.nc` | NetCDF | Posterior ensemble mean |
| `analysis_sd.nc` | NetCDF | Posterior ensemble spread |
| `output_mean.nc` | NetCDF | Final restart mean |
| `output_member_*.nc` | NetCDF | Individual member restarts |
| `dart_log.out` | Text | Execution log |

## Procedure

### Step 1: Configure Assimilation

Key namelist parameters in `input.nml`:

```fortran
&filter_nml
   ens_size                = 20          ! Number of ensemble members
   async                   = 0           ! 0=Fortran advance, 2=shell
   obs_sequence_in_name    = 'obs_seq.out'
   obs_sequence_out_name   = 'obs_seq.final'
   stages_to_write         = 'preassim', 'analysis', 'output'
   output_members          = .true.
   output_mean             = .true.
   output_sd               = .true.
   ! Inflation: [prior, posterior]
   inf_flavor              = 0, 0        ! 0=none, 2=adaptive, 4=RTPS
   inf_initial             = 1.0, 1.0
   inf_damping             = 0.9, 1.0
/

&assim_tools_nml
   cutoff                    = 0.2       ! Localization half-width
   sort_obs_inc              = .false.
   sampling_error_correction = .false.
/

&cov_cutoff_nml
   select_localization = 1               ! 1=Gaspari-Cohn
/
```

### Step 2: Run Filter

```bash
# Serial
./filter

# MPI (for large models)
mpirun -np 16 ./filter
```

### Step 3: Monitor Execution

Watch `dart_log.out` for progress:
```bash
tail -f dart_log.out
```

Key log messages:
- "obs assimilated = N, evaluated = M" — per-cycle summary
- "WARNING" — non-fatal issues
- "ERROR" — fatal, filter will stop

### Step 4: Examine Output

```bash
# Check obs_seq.final
wc -l obs_seq.final

# Examine analysis
ncdump -h analysis_mean.nc
ncdump -v state analysis_mean.nc | head -20

# Compare prior vs. analysis
ncdump -v state preassim_mean.nc > prior.txt
ncdump -v state analysis_mean.nc > posterior.txt
diff prior.txt posterior.txt
```

## Verification

1. **obs_seq.final exists**: Contains observations annotated with
   prior/posterior ensemble values and QC codes.

2. **Analysis differs from prior**: If `preassim_mean.nc` equals
   `analysis_mean.nc`, no observations were assimilated. Check QC codes.

3. **Ensemble spread**: The spread (SD) should be smaller after
   assimilation than before. If spread increases, check inflation settings.

4. **RMSE**: Compare analysis mean to truth (for OSSEs). RMSE should
   be smaller than the prior RMSE.

5. **QC distribution**: Most observations should have QC = 0 (assimilated).
   High QC > 0 rates indicate problems.

## Traps

1. **Filter divergence**: If RMSE grows unbounded over cycles, the filter
   has diverged. Causes: (a) too small ensemble, (b) no inflation,
   (c) localization too wide, (d) observation errors too small.
   Fix: increase ens_size, enable inflation (`inf_flavor=2`), or
   tighten localization (reduce `cutoff`).

2. **All observations rejected**: If QC = 7 for all obs, the
   `outlier_threshold` is too tight. Increase it (default: 3.0,
   try 5.0 or -1 to disable).

3. **Inflation blowup**: If inflation values grow very large (>10),
   the system is unstable. Reduce `inf_upper_bound`, increase
   `inf_damping`, or switch to RTPS (`inf_flavor=4`).

4. **Wrong observation types**: If `assimilate_these_obs_types` in
   `&obs_kind_nml` doesn't include your obs type, observations will
   be evaluated but not assimilated (QC = 5).

5. **Time window mismatch**: If `obs_window_days/seconds` in filter_nml
   is too narrow, observations outside the window are skipped (QC = 3).

6. **Localization cutoff units**: For `threed_sphere`, cutoff is in
   **radians**. 0.2 rad ≈ 1146 km. Using degrees by accident means
   0.2° ≈ 22 km — far too tight, rejecting most obs influence.

## Example

```bash
# Complete Lorenz 63 assimilation
cd DART/models/lorenz_63/work

# 1. Build (if not done)
./quickbuild.sh nompi

# 2. Generate synthetic observations
./perfect_model_obs

# 3. Run assimilation
./filter

# 4. Check output
ncdump -h analysis_mean.nc
head -30 obs_seq.final
cat dart_log.out | grep "obs assimilated"
```
