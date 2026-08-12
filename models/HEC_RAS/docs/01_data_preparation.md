# Stage 01 — Data Preparation (discharge & project setup)

**Purpose.** Assemble a runnable HEC-RAS steady project: a template geometry +
the discharges and boundary conditions for the case of interest. HEC-RAS forcing
is **discharge**, not meteorology.

**Inputs.**
- A template project (bundled: `examples/MixedFlowSteady/` — `MIXED.{prj,g01,g01.hdf,f01,p01,r01}`).
- Target discharges (cfs, or m³/s with `--in-units m3/s`), one per profile.
- Optional: an `ObservedQ` CSV (`data_ki/ObservedQ/SKILL.md`) for design peaks.
- Optional: boundary slopes, Manning n scaling.

**Outputs.** A working project directory with an edited run file `.rNN`,
ready for `run_hecras.py`.

**Procedure.**
1. `prepare_steady_run.py --out-dir DIR --flows Q1,Q2 [--dn-slope S] [--mann-scale K]`
   copies the template and applies edits via the ingestion tools.
2. Or build flows from observed discharge:
   `convert_flow_to_hecras.py --run DIR/MIXED.r01 --out DIR/MIXED.r01 \
        --observedq Q.csv --quantiles 0.5,0.9,0.99 --in-units m3/s`

**Verification.** Each tool prints a `validation` block; discharges must be
positive and < 5×10⁶ cfs (the unit-error guard). Confirm the run file still has a
`Section - Flow Data` block with your discharges.

**Traps.**
- Feeding m³/s into an English project under-states flow ~35×. Always set
  `--in-units` to the *source* units; the project unit system is in the `.prj`.
- HEC-RAS is not rainfall-runoff: do **not** use `load_daily_forcing` (precip).
- Brand-new geometry needs a run file the GUI/`ras-commander` must write — the
  copy-first template path only re-parameterises an existing project.

**Example.**
```bash
python3 tools/prepare_steady_run.py --out-dir /tmp/p --flows 600,1200 --dn-slope 0.0008
# -> /tmp/p ready; hand to run_hecras.py
```
