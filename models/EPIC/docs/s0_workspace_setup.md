# EPIC0810 Stage 0 — Workspace Setup

## Purpose
Build a clean directory containing every file the EPIC0810 binary expects, with the
two compatibility fixes the binary needs (SOIL38K alias, SOL alpha-code sanitization).

## Inputs
- Template directory: `/home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent/_work_v2/EPIC/source/repo/epic1102_example_files_20221002/`
- Binary: `/home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent/_work_v2/EPIC/source/repo/epic0810.x`
- Target workspace path (e.g. `/tmp/epic_run_<uuid>/`)

## Outputs
A workspace directory containing:
- `epic0810.x` (executable)
- All `*COM.DAT`, `*USEL.DAT` list/database files
- `EPICCONT.DAT`, `EPICRUN.DAT`, `EPICFILE.DAT`, `PRNT1102.DAT`, `PARM1102.DAT`, …
- `SOIL35K.DAT` and a copy named `SOIL38K.DAT` (the binary opens 38K, not 35K)
- `umstead.SIT`, `umstead.SOL` (alpha-code sanitized), `umstead.OPC`
- `NCRDU.DLY`, `NCCLAYTO.WP1`, `NCCLAYTO.WND`

## Procedure
1. Validate template files exist
2. `mkdir -p workspace`
3. Copy each REQUIRED_TEMPLATE_FILES into workspace
4. Copy binary in and `chmod +x`
5. Copy `SOIL35K.DAT` -> `SOIL38K.DAT`
6. For every `.SOL` in workspace, run `sanitize_sol()` to replace alpha
   tokens with `0.00` (preserves column widths)

## Verification
- `ls workspace/SOIL38K.DAT` exists
- `grep "[A-Za-z]" workspace/umstead.SOL | head` shows only the header line
- `file workspace/epic0810.x` returns ELF executable
- All files in REQUIRED_TEMPLATE_FILES are present

## Traps
- Forgetting SOIL38K.DAT alias → `forrtl: severe (29): file not found, unit 39, file fort.39`
- Skipping SOL sanitization → `forrtl: severe (64): input conversion error, unit 24`
- Copying binary without `chmod +x` → `Permission denied` from subprocess

## Example
```python
from tools.run_epic_workspace import setup_workspace
ws = setup_workspace("/tmp/epic_run1")
print("Workspace ready at", ws)
```
