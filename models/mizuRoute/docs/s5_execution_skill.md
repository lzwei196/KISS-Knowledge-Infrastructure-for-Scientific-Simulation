# Stage 5: Running mizuRoute

## Purpose
Execute the mizuRoute Fortran binary with proper validation before and after.

## Prerequisites
- [ ] mizuRoute binary compiled: `model/mizuRoute/mizuRoute-main/route/bin/mizuroute.exe`
- [ ] Control file generated (Stage 4)
- [ ] All input files exist and are readable

## Procedure
```bash
python tools/s5_execution/run_mizuroute.py \
  --control_file <control_path> \
  --exe model/mizuRoute/mizuRoute-main/route/bin/mizuroute.exe
```

## Expected Runtimes

| Basin size | Reaches | IRF | KWE | MC | DW |
|-----------|---------|-----|-----|----|----|
| < 1,000 km2 | 20-100 | <10s | <30s | <30s | <60s |
| 1,000-10,000 km2 | 100-500 | <30s | <2min | <2min | <5min |
| 10,000-100,000 km2 | 500-2000 | <2min | <10min | <10min | <30min |
| > 100,000 km2 | 2000+ | <5min | <30min | <30min | hours |

Per year of simulation. Multiply by number of years.

## Error Interpretation

| Error message | Triplet | Action |
|--------------|---------|--------|
| `Cannot open file` | dt_m002 | Check paths in control file |
| `Variable not found` | dt_m004 | Check vname_* matches NetCDF |
| `CFL violation` | dt_m009 | Reduce dt or use IRF/KWT |
| `MPI_ABORT` | dt_m012 | Check network connectivity |
| Segfault / no output | dt_m017 | Check path lengths (<120 chars) |

## Output Files
mizuRoute writes NetCDF files to `output_dir` with the naming pattern:
`<fname_output>.mizuroute.h.YYYY-MM-DD-SSSSS.nc`

Key variables: `IRFroutedRunoff`, `dlayRunoff`, `KWTroutedRunoff` (depending on method)
