# EPIC0810 Stage 3 — Execution

## Purpose
Run the `epic0810.x` binary in a prepared workspace and collect its outputs.

## Inputs
- Workspace directory (built by Stage 0)
- Site ID matching `EPICRUN.DAT` line (default `umstead_0`)
- Start year, NBYR (number of years), timeout

## Outputs
- `<site_id>.OUT` — main human-readable report
- `<site_id>.ACY` — annual crop yield table
- `<site_id>.DGN` — daily general output
- `<site_id>.ANN` — annual summary
- `<site_id>.ACN`, `.ACO`, `.ABR`, `.APS`, `.DCN`, ... (toggled by PRNT1102.DAT)

## Procedure
```python
from tools.run_epic_workspace import (
    setup_workspace, update_epiccont, update_epicrun, run, validate_outputs
)

ws = setup_workspace("/tmp/epic_run1")
update_epiccont(ws, start_year=1930, nbyr=15)
update_epicrun(ws, site_id="umstead_0",
               nsit=2, nsol=3, nops=3, ndly=2)
result = run(ws, site_id="umstead_0", timeout=600)
print(result["status"], result.get("return_code"))
for e in validate_outputs(ws, "umstead_0"):
    print(e)
```

The `run()` helper:
1. Sets the binary executable bit
2. Calls `subprocess.run([bin], cwd=ws, stdin=DEVNULL, stdout=PIPE, stderr=PIPE, timeout=timeout)`
3. Lists non-empty `<site_id>.*` files in the workspace
4. Returns dict {status, return_code, stdout, stderr, outputs}

## Verification
- `result["status"] == "completed"`
- `result["return_code"] == 0`
- `<site_id>.OUT` is at least a few KB
- `umstead_0.OUT` contains the string `EPIC0810` near the top
- The annual block of OUT contains rows like `PRCP(mm)`, `ET(mm)`, `Q(mm)`, `WBMC(kg/ha)`

## Traps
- **stdin not closed** → the binary stops at a Fortran PAUSE prompt waiting forever.
  Always pass `stdin=subprocess.DEVNULL`.
- **Binary path baked into config** → epic0810 is loaded from the workspace dir;
  do NOT call it from elsewhere — relative paths in `EPICFILE.DAT` assume `cwd=ws`.
- **Timeout too short** → 15 simulated years on an 80-year mixed forest takes
  ~10–60 s. Set `timeout >= 300` to be safe; longer for multi-decade runs.
- **Stale outputs from previous run** → `setup_workspace` does NOT delete the
  directory; if you re-run a site, old `<site_id>.*` files may persist. Either
  use a fresh workspace or `rm <site_id>.*` first.

## Example
```bash
python tools/run_epic_workspace.py --workspace /tmp/epic_run1 \
    --site-id umstead_0 --start-year 1930 --nbyr 15 --timeout 600
```
