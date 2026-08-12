# Stage 05 — Run execution

## Purpose
Stage all input files in a self-contained workspace and execute the
EPIC 1102 binary (Windows PE32 console EXE) via Wine.

## Inputs
- Workspace directory
- Run name prefix
- Output directory
- Optional: path to the EPIC binary

## Outputs
- `<output_dir>/<run>_0.OUT` — echo + summaries
- `<output_dir>/<run>_0.ACY` — annual crop yield
- `<output_dir>/<run>_0.ANN` — annual general summary
- `<output_dir>/<run>_0.DGN/.DWC/.DCN/.DGZ/...` — daily/annual subsystems

## Procedure
1. Workspace must contain ALL of:
   - `.DAT` parameter/database files (stage via templates/)
   - User `.SIT`, `.SOL`, `.OPC`, `.DLY`, `.WP1`, `.WND`
   - Correct `EPICRUN.DAT`, `EPICCONT.DAT`, list-COM files
   - Copy of the EPIC `.exe` binary
2. `cd workspace && wine ./epic1102-official_release.exe`.
3. On non-zero exit, dump last 30 lines of stdout/stderr and raise.
4. On success, copy `<run>*` outputs to the output directory.

## Verification
- Exit code 0.
- `<run>_0.OUT` contains `EPIC1102 v2025-05-25`.
- `<run>_0.ANN` has at least NBYR data rows.
- `<run>_0.ACY` has at least NBYR × #crops rows.

## Traps
- **Must run from CWD** (EPIC_006).
- **Wine uninitialized**: run `wine wineboot` once (EPIC_011).
- **Case sensitivity**: keep filenames exactly as in templates.
- **Long paths** (>256 chars) confuse Wine. Keep workspace short.
- **Parallel runs** in same `~/.wine` prefix collide: use `WINEPREFIX`.

## Example
```bash
python tools/run_epic.py --workspace /tmp/epic_run \
    --run-name raleigh --output-dir /tmp/epic_output
```
