# S7: Execution — Skill Document

## Purpose

Execute the SFINCS binary with preflight validation, log monitoring, and output verification. SFINCS is a Fortran binary that reads from the current working directory.

## Prerequisites

- sfincs.inp and ALL referenced files in the run directory
- SFINCS binary compiled and executable at `model/sfincs/bin/sfincs`
- Sufficient disk space for output (estimate: 4 * mmax * nmax * n_output_steps bytes)

## Inputs

| Input | Type | Required |
|-------|------|----------|
| Run directory | directory | Yes |
| SFINCS binary path | file | Yes |
| OMP threads | number | Optional (default: 4) |
| Timeout | number | Optional (default: 7200s) |

## Procedure

1. **Preflight checks** (run_sfincs.py does these automatically):
   - sfincs.inp exists in run_dir
   - All referenced files (dep, msk, ind, man, precip, bnd, src, etc.) exist
   - Mask has active cells > 0 (dt_019)
   - dt satisfies CFL (dt_009)
   - outputformat = net is set (dt_018)

2. **Execute**: `python run_sfincs.py --run_dir <dir>`
   - Sets OMP_NUM_THREADS for parallel execution
   - Sets CWD to run_dir (CRITICAL — dt_017)

3. **Runtime estimation**:
   | Active cells | Period | dt | Estimated runtime |
   |-------------|--------|-----|------------------|
   | 50,000 | 10 days | 10s | ~1 minute |
   | 250,000 | 30 days | 5s | ~10 minutes |
   | 1,000,000 | 30 days | 2s | ~2 hours |
   | 5,000,000 | 10 days | 1s | ~12 hours |

4. **Check outputs**:
   - sfincs_map.nc should exist (gridded output)
   - sfincs_his.nc should exist if observation points were defined
   - sfincs.log should not contain error messages

## Expected Outputs

| Output | Path | Verification |
|--------|------|-------------|
| sfincs_map.nc | `{run_dir}/sfincs_map.nc` | Exists, size > 0 |
| sfincs_his.nc | `{run_dir}/sfincs_his.nc` | Exists if obs points defined |
| sfincs.log | `{run_dir}/sfincs.log` | No error messages |
| run_summary.json | `{run_dir}/run_summary.json` | exit_code = 0 |

## Validation Checks

1. Exit code = 0
2. sfincs_map.nc exists and has non-zero size
3. No NaN values in output (check with `ncdump -h`)
4. Runtime is within expected range (if 10x too long, see dt_011)

## Common Pitfalls

- **dt_017**: Not running from the directory containing sfincs.inp. The tool handles this.
- **dt_009**: NaN crash from CFL violation. Reduce dt in sfincs.inp.
- **dt_019**: Output all zeros because mask has no active cells. Check mask file.
- **dt_018**: No sfincs_map.nc because outputformat was not set to "net".
- Process appears stuck: SFINCS may not print progress for several minutes. Check if it is still running (ps) before killing.
