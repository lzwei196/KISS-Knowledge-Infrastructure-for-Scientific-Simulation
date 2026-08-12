# Stage 02 — Geometry & Roughness Editing

**Purpose.** Modify channel roughness (Manning n) and expansion/contraction
coefficients in a HEC-RAS geometry (`.gNN`) — the controls that most affect
computed water-surface elevation for a fixed discharge.

**Inputs.** A geometry file `.gNN` (text, keyword/comma-delimited). The relevant
blocks:
```
#Sta/Elev= 4
       0      80       0      70      20      70      20      80   <- station,elev pairs
#Mann= 3 ,0,0
       0               0       0    .015       0      20               0   <- station,n triplets
Exp/Cntr=0.3,0.1
```

**Outputs.** An edited `.gNN` with the same column layout (copy-first; values
replaced in place, never regenerated from a dict).

**Procedure.**
- Scale all roughness: `edit_geometry.py --geom in.g01 --out out.g01 --mann-scale 1.2`
- Set a uniform n: `--mann-set 0.035`
- Set exp/contr: `--exp 0.3 --contr 0.1`

**Verification.** The tool's `validate_outputs()` rejects any Manning n outside
0.005–0.5 (physical range). Re-run the solver and confirm WS rises with larger n.

**Traps.**
- Manning n is **dimensionless and identical in English & SI** — never "convert"
  it between unit systems. The 1.486 vs 1.0 conveyance factor lives inside the
  solver.
- Editing the `.gNN` text does **not** automatically reach the solver: the run
  file `.rNN` is derived from the geometry HDF. For parametric n on an *existing*
  run file, edit the run-file roughness block (the geometry HDF must be rebuilt by
  `preprocess_geometry.py` for `.gNN` edits to take effect end-to-end).
- Field widths matter in the flattened run file; the editor preserves them.

**Example.**
```bash
python3 tools/edit_geometry.py --geom examples/MixedFlowSteady/MIXED.g01 \
        --out /tmp/rougher.g01 --mann-scale 1.5
```
