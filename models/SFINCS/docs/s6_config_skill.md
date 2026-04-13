# S6: Configuration — Skill Document

## Purpose

Generate the main SFINCS configuration file (sfincs.inp) with all simulation parameters. The most critical parameter is the computational timestep `dt`, which must satisfy the CFL stability condition.

## Prerequisites

- grid_info.json from s1_domain
- sfincs.dep, sfincs.msk, sfincs.ind from s2_topobathy
- sfincs.man from s3_roughness (or uniform manning value)
- Forcing files from s4_forcing
- Optional structure files from s5_structures

## Inputs

| Input | Type | Required |
|-------|------|----------|
| grid_info.json | JSON | Yes |
| Start/end dates | string | Yes |
| Manning's n or man file | number/file | Yes (default: 0.04) |
| Precipitation file | NetCDF | Optional |
| Boundary condition files | text | Optional |
| Output interval | number | Optional (default: 3600s) |

## Procedure

1. **Run tool**: `generate_sfincs_inp.py --grid_info <json> --start_date <date> --end_date <date> --output_dir <dir>`
   - Add `--precip_file`, `--src_file`, `--dis_file` etc. as needed

2. **CFL timestep calculation**:
   ```
   dt_max = dx / sqrt(g * h_max)
   ```
   Where g=9.81 m/s2, h_max is assumed max flood depth (10m default).
   Use dt = 0.75 * dt_max for safety.

   | dx (m) | h_max=5m | h_max=10m | h_max=20m |
   |--------|---------|----------|----------|
   | 10 | 1.4s | 1.0s | 0.7s |
   | 25 | 3.6s | 2.5s | 1.8s |
   | 50 | 7.1s | 5.1s | 3.6s |
   | 100 | 14.3s | 10.1s | 7.1s |
   | 200 | 28.5s | 20.2s | 14.3s |

3. **Key parameters in sfincs.inp**:
   - `outputformat = net` — ALWAYS include this (dt_018)
   - `advection = 0` — disable unless needed (dt_010)
   - `alpha = 0.75` — momentum damping (increase to 0.9 if oscillating)
   - `qinf = 0.0` — infiltration in mm/hr (increase for permeable soils)

4. **Copy all input files to run directory**: sfincs.inp references files by name (relative to CWD). All files must be in the same directory.

## Expected Outputs

| Output | Path | Verification |
|--------|------|-------------|
| sfincs.inp | `{output_dir}/sfincs.inp` | Contains all required parameters |

## Validation Checks

1. `dt` satisfies CFL: dt < dx / sqrt(9.81 * 10) (dt_009)
2. `outputformat = net` is present (dt_018)
3. `tstart < tstop` (time range makes sense)
4. All referenced files (depfile, mskfile, etc.) exist in the output directory
5. Either precipitation or boundary conditions are specified (otherwise no water input)

## Common Pitfalls

- **dt_009**: dt too large -> NaN crash. Tool auto-computes CFL-safe value.
- **dt_017**: Running from wrong directory. SFINCS reads from CWD.
- **dt_018**: Missing outputformat -> binary output instead of NetCDF.
- **dt_010**: advection=1 with low alpha -> oscillations. Use advection=0 by default.
