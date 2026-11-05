# s0 — Configuration: engine check and site choice

## Purpose
Prove the real engine works on this machine before any site run, and fix the site identity
(location, years, PFT) that every later stage uses.

## Inputs
- Engine binary `KISSPATH_HOME/engine_builds_20261006/QUINCY/src/x86_64-gfortran/bin/qs.bin`
  (qs-2026.04-public, built 2026-10-06, see `BUILD_LOG.md` next to it).
- Build-log self-test runs `run_builtin_test_canopy/`, `run_builtin_test_radiation/`.

## Outputs
- `PREFLIGHT_REPORT=` line (preflight), self-test run dirs with `run_manifest.json`.

## Procedure
1. `python preflight_check.py` — must exit 0. It also runs the test_canopy self-test.
2. Self-tests by hand (the engine check the public release allows; it ships no site example):
   ```
   PY=KISSPATH_PYTHON_ENV/bin/python
   $PY tools/run_quincy_engine.py --mode test_canopy --run_dir /tmp/q_can \
       --reference_dir KISSPATH_HOME/engine_builds_20261006/QUINCY/run_builtin_test_canopy
   $PY tools/run_quincy_engine.py --mode test_radiation --run_dir /tmp/q_rad \
       --reference_dir KISSPATH_HOME/engine_builds_20261006/QUINCY/run_builtin_test_radiation
   ```
   Exit 0 = every reference file (fort.10-17 response curves, engine log, stdout) is byte-identical.
3. Pick the site: a FLUXNET2015 site on disk (`KISSPATH_OBS/fluxnet/sites/`)
   gives both forcing and observations; check the engine's own site list
   (`src/data/fluxnet2_siteset_pft_info.csv`) for its PFT.

## Verification
- `run_manifest.json` → `"status": "ok"`, `reference_compare.differ == []`.
- `fort.10` first row `100.0 1.5741163 0.9536227 0.8413684` (PAR, A, GC, CI).

## Traps
- No `qs.namelist` → engine stops "open_nml: Could not open qs.namelist"; no lctlib in the run dir →
  stops at init (dt_quincy_035). The run tool writes/copies both.
- The engine exits 0 even when it stops on an error (dt_quincy_026).
- `pgrep -f qs.bin` also matches the agent's own process (its prompt names qs.bin) — kill only
  PIDs whose cwd is your run dir (dt_quincy_041).

## Example
2026-10-07: both self-tests reproduced the build-log runs byte for byte (10 files test_canopy,
2 files test_radiation).
