# Stage 03 — Steady-Flow Execution (the real solver)

**Purpose.** Run the **actual** `RasSteady.exe` Intel-Fortran solver under WINE
to compute water-surface profiles. No physics is approximated.

**Inputs.** A prepared project directory containing at minimum:
`<prj>.rNN` (run file), `<prj>.gNN.hdf` (geometry HDF). The template ships both.

**Outputs.** `<prj>.pNN.tmp.hdf` populated with results under
`/Results/Steady/Output/...`, plus the legacy binary `<prj>.ONN`.

**Procedure (what `run_hecras.py` does).**
1. Copy the whole project to a temp workspace (copy-first).
2. Swap in any user-edited files (`forcing_files=`).
3. Remove stale results, then **seed** `<prj>.pNN.tmp.hdf` from `<prj>.gNN.hdf`.
4. `wine RasSteady.exe <prj>.rNN` from the workspace (`env -u LD_PRELOAD`).
5. Collect the populated results HDF + `.ONN` into `output_dir`.

```bash
python3 tools/run_hecras.py --project /tmp/myproj --prj MIXED --plan 01 --out /tmp/out
```

**Verification.** Success requires the banner `Finished Steady Flow Simulation`
**and** a results HDF > 60 kB (i.e. larger than the bare geometry seed).
`validate_outputs()` then checks WS finite and Q ≥ 0.

**Traps.**
- `HDF_ERROR trying to open HDF output file: <prj>.pNN.tmp.hdf` → the seed step
  was skipped. Copy `<prj>.gNN.hdf` → `<prj>.pNN.tmp.hdf` first (triplet
  `missing_plan_hdf_skeleton`).
- `wrong ELF class` / wine fails to start → a bad `LD_PRELOAD`; run with
  `env -u LD_PRELOAD` (triplet `wine_ld_preload`).
- Trailing `HDF5-DIAG` lines **after** "Finished" are harmless — do not treat as
  failure (triplet `hdf5_diag_after_finished`).
- No `.rNN` present → a brand-new project; the run file must be written by the
  GUI/`ras-commander` (triplet `missing_run_file`).

**Example output (Mixed Flow, Q=500):** 2 profiles × 19 cross sections,
WS 71.87→66.0 ft downstream, channel velocity up to 13.4 ft/s (supercritical).
