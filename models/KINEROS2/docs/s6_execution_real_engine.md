# s6 Execution -- the real KINEROS2 engine

## Purpose
Run the official USDA-ARS KINEROS2 program (K2shell, version 25-Oct-2019, ARS-SWRC/KINEROS2 commit
f0bbae2, built with gfortran) headless, and decide honestly whether the run worked.

## Inputs
Parameter file, rainfall file (optional only for injection-only runs), run length `--tfin` (min),
time step `--dt` (min), flags `--courant`, `--sediment`, multipliers (`--mult ks=0.5,g=1.5` or `--mult-file`).

## Outputs
In `--out-dir`: the engine's `.out` report, `kin.fil` used, `engine_stdout.txt`, any PRINT=3 CSV,
one `hydrograph_<type>_<id>.csv` per PRINT=2 element, and `run_result.json` (status, failures,
binary path + sha256, input hashes, event summary + SI conversion, event water balance, outlet peak,
tabular summary, engine warnings).

## Procedure
1. `python3 preflight_check.py` (binary present, ELF, and the EX1 sample reproduces).
2. Official samples: `tools/run_kineros2_engine.py --example ex1 --check --out-dir out/ex1` and `--example wg11`.
3. Any case: `tools/run_kineros2_engine.py --par case.par --rain storm.pre --tfin 360 --dt 3 --courant --mult ks=0.5,g=1.5 --out-dir out/case`.
4. Binary: `--binary`, else `$KINEROS2_BIN`, else models DB `binary_path`, else
   `KISSPATH_HOME/engine_builds_20261006/KINEROS2/build_github/k2`.
   Under the hood: inputs are copied to a fresh `_k2ws_*` folder under short names, `kin.fil` is written
   (`par,pre,out,"title",tfin,dt,Y|N,Y|N,mult|N,Y`), then `k2 -b kin.fil`.

## Verification
- Exit codes: 0 success | 2 input validation failed | 3 the engine reported a failure | 4 binary missing |
  5 `--check` mismatch with the build log values.
- Success = output contains "Event Volume Summary" AND no `error -` / `STOP error` / Fortran runtime
  message in the output or stdout. The engine's own exit status is ALWAYS 0 (dt_kineros2_027).
- `event_water_balance.residual_pct_of_rain` should be < 1 % (the engine prints the same check).
- Proven 2026-10-06: EX1 and WG11 reproduce every build-log value to rel 1e-4 (in fact exactly);
  negative tests: missing SAT -> 2, missing particle density -> 3, decreasing rain depth -> 3, missing binary -> 4.

## Traps
- The engine exits 0 on every error (dt_kineros2_027); a space after a kin.fil comma breaks a file name (dt_kineros2_028).
- kin.fil fields are 150 characters; the tool copies inputs to short names (dt_kineros2_050).
- One run takes < 0.1 s for both samples; a huge tfin/dt ratio is the only way to make it slow.
- Courant N keeps the user step for computation; the "Time step distribution (100,75,50%)" line tells
  you which step would have been accurate (dt_kineros2_051).
- `tools/run_kineros2.py` is the Python SURROGATE, not this engine (dt_kineros2_046).

## Example
```
python3 tools/run_kineros2_engine.py --example wg11 --check --out-dir out/wg11
# outlet CHANNEL 27: peak 668.4023 cu ft/s at 64.7 min ... EXAMPLE wg11: reproduced
```
