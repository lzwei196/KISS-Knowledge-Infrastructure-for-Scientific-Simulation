# Stage 7: Troubleshooting Guide

## Purpose

Diagnose and resolve common CISM failures. This document supplements the
diagnostic triplets (diagnostics/triplets.yaml) with deeper explanations
and step-by-step resolution procedures.

## Common Failure Categories

### 1. Build Failures

**Missing NetCDF**:
```
CMake Error: CISM_NETCDF_DIR must be defined
```
Fix: `cmake -DCISM_NETCDF_DIR=/usr ...` or wherever NetCDF is installed.
Check: `dpkg -l | grep netcdf` or `locate libnetcdff.a`.

**Missing BLAS**:
```
undefined reference to `dgemm_`
```
Fix: Install libblas-dev and add `-DCISM_EXTRA_LIBS=-lblas`.

**Fortran module incompatibility**:
```
Fatal Error: Cannot read module file 'glimmer_log.mod'
```
Fix: Clean build directory (`rm -rf builds/serial/*`) and rebuild.

### 2. Runtime Crashes

**Segmentation fault on large grids**:
Cause: Stack overflow from large Fortran arrays.
Fix: `ulimit -s unlimited` before running.

**SLAP solver failure**:
```
SLAP:  *** WARNING ***  IUNIT =  0  I1 =  100
```
Cause: Serial solver struggling with HO problem.
Fix: Increase `glissade_maxiter`, reduce `dt`, or switch to
`which_ho_sparse=3` (parallel PCG).

**NaN in velocity/temperature**:
Cause: CFL violation or extreme parameter values.
Fix:
1. Reduce `dt` (halve it and retry)
2. Check `default_flwa` is in range 1e-18 to 1e-15
3. Ensure `geothermal` is negative
4. Start with `temperature=0` to isolate dynamics

### 3. Silent Errors (Model Runs but Wrong Results)

**Ice volume too large or growing unbounded**:
Check: acab units (dt_001). Should be m/yr, not mm/yr.
Check: default_flwa is reasonable (dt_002).

**Zero velocity everywhere**:
Check: dycore setting. Is ice thick enough? (ice_limit)
Check: If dycore=2, is which_ho_sparse set correctly? (dt_005)
Check: If evolution=0 with Glissade, switch to 3 (dt_007).

**Temperature stays at artm everywhere**:
Check: temperature option. 0 = overwrite with artm each step (dt_011).
Use temperature=1 for prognostic.

**Config section has no effect**:
Check: Exact section name spelling (dt_014). CISM silently ignores
unknown sections. Common mistakes:
- `[HO_options]` instead of `[ho_options]`
- `[Parameters]` instead of `[parameters]`
- `[cf_input]` instead of `[CF input]`

### 4. I/O Problems

**Output file empty or has no time steps**:
Check: output frequency (dt_009).
Fix: `frequency = 1` for debugging, then increase.

**Cannot read input file**:
Check: [CF input] name path relative to working directory.
Check: `time = 1` (1-based index, not 0-based).
Check: Dimensions in input match [grid] section (dt_020).

### 5. Performance Issues

**Extremely slow HO solver**:
- Reduce `glissade_maxiter` (default 300 is high)
- Use `which_ho_precond = 2` (SIA-based preconditioner)
- Consider `which_ho_approx = 4` (DIVA) instead of 2 (Blatter-Pattyn)
- Increase `dt` if CFL allows

**Memory errors on large domains**:
- Use MPI parallelism (`CISM_MPI_MODE=ON`)
- Reduce output variable list
- Output less frequently

## Diagnostic Flowchart

```
Model crashes?
├── Yes
│   ├── CMake/build error → Check NetCDF, BLAS, compiler
│   ├── Segfault → ulimit -s unlimited
│   ├── NaN detected → Reduce dt, check parameters
│   └── Solver failure → Reduce dt, increase maxiter
└── No (runs but wrong results)
    ├── Ice growing unbounded → Check acab units (dt_001)
    ├── No ice dynamics → Check flwa (dt_002), dycore, evolution
    ├── Temperature wrong → Check geothermal sign (dt_003), temp option
    ├── Output empty → Check frequency (dt_009)
    └── Config ignored → Check section spelling (dt_014)
```

## Verification

After resolving an issue:
- [ ] Model runs to completion (exit code 0)
- [ ] Output has expected number of time steps
- [ ] Ice volume is in reasonable range
- [ ] Velocities are non-zero where ice exists
- [ ] Temperature profile is physically reasonable
