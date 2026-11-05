# s10: Model Execution — Skill Document

## Purpose

Run the CE-QUAL-W2 binary with comprehensive preflight checks and post-run validation. The binary on this server is **v5** (`model/ce_qual_w2/bin/w2_v5`): it reads `w2_con.csv` from the current working directory (v4.x reads `w2_con.npt`; `run_w2.py` takes either) and is single-threaded.

## Prerequisites

- [ ] Control file in the run directory: `w2_con.csv` (v5) or `w2_con.npt` (v4.x)
- [ ] All referenced input files in the run directory (bth, met, qin, tin, qot)
- [ ] CE-QUAL-W2 binary compiled and accessible

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| Run directory | Path | s9 | Directory containing all input files |
| Binary path | Path | Installation | `model/ce_qual_w2/bin/w2_v5` |

## Procedure

### Step 1: Preflight checks

```bash
python tools/s10_execution/run_w2.py --run_dir <run_dir> --binary model/ce_qual_w2/bin/w2_v5
```

The tool automatically checks:
- A control file exists (`w2_con.csv` or `w2_con.npt`)
- Referenced input files: v4.x, all must exist; v5, a file named in `w2_con.csv` but absent is a WARNING (the control file also names files of options that are switched off; the binary stops with `w2.err` if it needs one)
- Binary is present and executable
- No path > 72 chars (dt_008)

### Step 2: Monitor runtime

Expected runtimes:

| Grid Size | Sim Period | Expected Runtime |
|-----------|-----------|-----------------|
| 20x20 | 1 year | 1-5 minutes |
| 50x50 | 1 year | 5-30 minutes |
| 100x100 | 1 year | 30-120 minutes |
| 500x100 | 1 year | 2-12 hours |

**DO NOT** kill the process if it seems slow. Check w2l.opt for timestep info.

### Step 3: Post-run validation

Check for:
1. Exit code 0 (success)
2. v5: `w2.err` is absent or empty (v5 writes its stop reasons there; a stale one is removed before the run). v4.x: w2l.opt has no STOP or ERROR lines
3. Output files exist and are non-empty (dt_025): v5 `snp.opt`, `tsr_<n>_seg<segment>.csv`, `spr.csv`; v4.x `snp_*.opt`, `tsr_*.opt`, `spr_*.opt`
4. No NaN in output (dt_023)

## Expected Outputs

| Output | Path | Verification |
|--------|------|-------------|
| Stop reasons | v5 `w2.err`; v4.x `w2l.opt` | Absent/empty; no STOP/ERROR lines |
| Snapshot | `snp_wb1.opt` | Non-empty, contains JDAY data |
| Time series | v5 `tsr_<n>_seg<segment>.csv`; v4.x `tsr_*.opt` | Non-empty |
| Spreadsheet | `spr_*.opt` | Non-empty |

## Validation Checks

1. v5: `test ! -s w2.err`. v4.x: `grep -i "STOP\|ERROR" w2l.opt` returns nothing (or only benign messages)
2. `ls -la snp*.opt tsr_*` shows non-zero file sizes (dt_025)
3. No NaN in output files: `grep -c "NaN" snp_*.opt tsr_*.opt` returns 0

## Common Pitfalls

| Pitfall | Triplet | Detection |
|---------|---------|-----------|
| Extremely slow runtime | dt_022 | Check w2l.opt for minimum timestep warnings |
| NaN/crash mid-simulation | dt_023 | Sharp bathymetry gradients or extreme forcing |
| NEGATIVE THICKNESS | dt_024 | Water level drops too low during drawdown |
| No output files | dt_025 | Missing output cards in w2_con.npt |
