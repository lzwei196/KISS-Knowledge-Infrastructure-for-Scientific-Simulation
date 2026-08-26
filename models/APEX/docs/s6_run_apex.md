# S6 Run APEX

## Purpose

Run the real APEX0806 Windows binary under Wine inside the workspace. This stage is the execution boundary: do not substitute a Python approximation for the model.

## Inputs

- A prepared workspace with `APEXFILE.DAT`, `APEXRUN.DAT`, `APEXCONT.DAT`, and the files referenced by the COM/list files
- `tools/s6_run_apex.py`
- `reference/APEX0806.exe` or a workspace-local `APEX0806.exe`
- Wine on `PATH`

## Outputs

- Per-run APEX outputs such as `OUTPUT.OUT`, `OUTPUT.ACY`, `OUTPUT.SAD`, `OUTPUT.MSW`, `OUTPUT.SUS`, and `OUTPUT.MAN`
- `EPICERR.DAT` if the binary writes an error log
- A Python result dictionary when using `tools.s6_run_apex.run()`

## Procedure

```bash
cd KISSPATH_KI_ROOT/APEX/knowledge_infrastructure
python preflight_check.py
python tools/s6_run_apex.py --workspace /tmp/apex_ws --timeout 600
```

`tools/s6_run_apex.py` copies `reference/APEX0806.exe` into the workspace if needed, deletes stale run outputs first, then runs:

```python
subprocess.run(["wine", "./APEX0806.exe"], cwd=workspace, capture_output=True, text=True, timeout=timeout)
```

## Verification

```bash
ls -lh /tmp/apex_ws/*.OUT /tmp/apex_ws/*.ACY
test ! -s /tmp/apex_ws/EPICERR.DAT || cat /tmp/apex_ws/EPICERR.DAT
```

Success is a non-empty per-run output file and a clean `EPICERR.DAT`; do not rely on the process return code alone.

## Traps

- `diagnostics/triplets.yaml:conout_wine_error` - do not launch APEX0806 with `nohup wine APEX0806.exe &`; use the Python subprocess capture pattern.
- `diagnostics/triplets.yaml:zero_exit_silent_crash` - APEX can return exit code 0 even after severe errors.
- `diagnostics/triplets.yaml:fert_code_pause` - APEX0806 fertilizer codes 92/93 can block forever in a Fortran `PAUSE`.
- `diagnostics/triplets.yaml:apex0806_opc_tillage_151_pause` - tillage code 151 is absent from this APEX0806 `TILLCOM.DAT`.
- `diagnostics/triplets.yaml:file_missing_uppercase` - exact filename case matters for every file opened by the binary.

## Example

```bash
python tools/s6_run_apex.py --workspace /tmp/apex_bengbu --timeout 600
python tools/s7_parse_output.py --workspace /tmp/apex_bengbu --out /tmp/apex_bengbu/results.csv
```
