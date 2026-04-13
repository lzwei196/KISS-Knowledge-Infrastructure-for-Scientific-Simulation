# s4 — wflow Execution Skill Document

## Purpose

Execute wflow_sbm via Julia subprocess. This stage calls the Julia runtime, loads the Wflow.jl package, and runs the model. Understanding Julia's JIT compilation behavior and memory management is essential to avoid misdiagnosing normal behavior as errors.

## Prerequisites

- Stages s1-s3 complete (staticmaps.nc, forcing.nc, wflow_sbm.toml all exist)
- Julia binary installed and accessible
- Wflow.jl package installed in Julia environment

## Inputs

| Name | Type | Source | Description |
|------|------|--------|-------------|
| wflow_sbm.toml | file | s3 | Model configuration |
| Julia binary | executable | installation | Julia 1.10+ |
| Julia environment | directory | installation | Contains Wflow.jl |

## Procedure

1. Run preflight checks via `run_wflow.py --toml /path/to/wflow_sbm.toml`
2. The tool checks: Julia exists, TOML exists, referenced files exist
3. Julia subprocess is launched with `--threads=auto` for parallelism
4. **EXPECT 30-60 SECOND DELAY** on first run (JIT compilation — dt_w009)
5. Monitor stdout for progress messages
6. After completion, verify output files exist and are non-empty

### Runtime Expectations

| Basin Size | Resolution | Period | Expected Runtime |
|-----------|-----------|--------|-----------------|
| Small (<1000 km2) | 0.25 deg | 10 years | 1-5 min |
| Medium (1000-50000 km2) | 0.25 deg | 10 years | 5-15 min |
| Large (>50000 km2) | 0.25 deg | 10 years | 15-30 min |
| Any | 0.1 deg | 10 years | 2-5x above |

### Memory Requirements

wflow loads entire domain into memory. Approximate RAM needed:

| Grid cells | Years | RAM needed |
|-----------|-------|-----------|
| 100 | 10 | ~500 MB |
| 1000 | 10 | ~2 GB |
| 10000 | 10 | ~8 GB |
| 50000 | 10 | ~32 GB |

## Expected Outputs

| Output | Path | Verification |
|--------|------|-------------|
| output_grid.nc | outputs/<run>/wflow_output/output_grid.nc | Non-empty, has q_river variable |
| output_scalar.nc | outputs/<run>/wflow_output/output_scalar.nc | Has Q at gauge points |
| output.csv | outputs/<run>/wflow_project/output.csv | CSV with discharge column |
| outstates.nc | outputs/<run>/wflow_project/outstates.nc | Final state for restart |

## Validation Checks

1. Exit code is 0
2. stdout contains progress messages (no empty stdout)
3. output_grid.nc exists and is > 1 MB
4. Discharge values are physically plausible (positive, not NaN)
5. Simulation period matches TOML calendar

## Common Pitfalls

- **dt_w009**: 30-60s silence on first run is NORMAL (JIT compilation)
- **dt_w007**: OutOfMemoryError for large domains — reduce resolution
- **dt_w021**: "Package Wflow not found" — wrong Julia environment
- **dt_w023**: NetCDF library conflict — unset LD_LIBRARY_PATH
- **dt_w014**: BoundsError — flow direction problem at boundary
- DO NOT kill the process during the initial 60s silence — it is compiling
