# S1 Installation

## Purpose
Verify that this KI can run the real Pywr package and GLPK solver before any reservoir workflow stage is attempted. This is the mandatory first check described in `../SKILL.md` and `../workflow/pywr_workflow.md`.

## Inputs
- Pywr-capable Python: `KISSPATH_HOME/桌面/test/hydro-claude/python_env/bin/python3`
- Tool: `../tools/s1_installation/verify_pywr_installation.py`
- KI preflight: `../preflight_check.py`
- Diagnostics: `../diagnostics/triplets.yaml`

## Outputs
- JSON status from `verify_pywr_installation.py` with `pywr`, `solver`, `dependencies`, `status`, and `message`.
- Exit code `0` for OK, `1` when Pywr is missing, `2` when GLPK is unavailable, and `3` for partial dependency coverage.

## Procedure
Run from the KI root:

```bash
cd KISSPATH_KI_ROOT/Pywr/knowledge_infrastructure
python preflight_check.py
"KISSPATH_HOME/桌面/test/hydro-claude/python_env/bin/python3" tools/s1_installation/verify_pywr_installation.py
```

If using another shell variable:

```bash
KI=KISSPATH_KI_ROOT/Pywr/knowledge_infrastructure
PYWR_PYTHON="KISSPATH_HOME/桌面/test/hydro-claude/python_env/bin/python3"
"$PYWR_PYTHON" "$KI/tools/s1_installation/verify_pywr_installation.py"
```

## Verification
- Confirm the JSON has `"status": "OK"`.
- Confirm `solver.available` is `true` and the solver name is GLPK-compatible.
- Confirm dependencies used later in this KI are installed: `pandas`, `geopandas`, `xarray`, `netCDF4`, and `matplotlib`.

## Traps
- `dt_pywr_001`: GLPK missing or not reachable. Remedy is to install or expose GLPK, then rerun `tools/s1_installation/verify_pywr_installation.py`.
- Do not switch to `KISSPATH_PYTHON_ENV/bin/python` for Pywr runs unless it also imports `pywr`; `../SKILL.md` states the Pywr-capable interpreter is separate.

## Example
```bash
cd KISSPATH_KI_ROOT/Pywr/knowledge_infrastructure
"KISSPATH_HOME/桌面/test/hydro-claude/python_env/bin/python3" tools/s1_installation/verify_pywr_installation.py
```
