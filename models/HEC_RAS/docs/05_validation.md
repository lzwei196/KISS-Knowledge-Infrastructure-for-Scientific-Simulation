# Stage 05 — Validation

**Purpose.** Quantify how well the real HEC-RAS solution matches **observed**
water-surface elevations, giving the KI its `real` validation tier.

**Inputs.**
- Results HDF from `run_hecras.py`.
- A flow file `.fNN` containing `Observed WS=` lines (the Mixed Flow example
  ships 19 observed WS values for profile PF1 @ Q=500 cfs).

**Outputs.** Metrics (`NSE/KGE/PBIAS/RMSE/r`, `max_abs_err_ft`) via
`ki_tools_common.metrics.all_metrics`, and a comparison figure
(`figures/s8_validation.png`, observed = black, simulated = `#2563EB`).

**Procedure.**
```bash
python3 tools/validate_hecras.py --hdf out/MIXED.p01.tmp.hdf \
        --flow examples/MixedFlowSteady/MIXED.f01 --profile-index 0 \
        --figure figures/s8_validation.png
```

**Verification / accepted result.**

| Metric | Value |
|--------|-------|
| NSE    | 0.9965 |
| KGE    | 0.977 |
| RMSE   | 0.096 ft |
| PBIAS  | −0.09 % |
| r      | 0.999 |
| max abs err | 0.28 ft |

Tier = **real**: the reference is independent observed water-surface data, not a
self-generated or analytic target. The solver also reproduces the correct
mixed-flow regime (supercritical upstream → subcritical downstream).

**Traps.**
- Match `--profile-index` to the profile the observed WS were measured at
  (PF1 = index 0 here). Comparing observed PF1 against computed PF2 inflates RMSE.
- Observed WS and geometry must share the **unit system** (ft here).
- `Observed WS=` value is the field after the empty 4th comma field — the parser
  takes the last numeric token per line to be robust to layout drift.

**Analytic cross-check (optional).** For internal consistency, verify the
energy-head identity `EG ≈ WS + α·V²/2g` from the parsed output — the solver
should satisfy it to within rounding at every cross section.

## Discharge-only obs sites (e.g. Bengbu) — metric is N/A by domain

Steady-flow validation requires **observed water-surface elevation** (`Observed WS=`
lines in a `.fNN`). For a site whose only observation is **discharge** (e.g. Bengbu
ObservedQ, peaks 3810/6812 m³/s), the steady fidelity metric is **N/A by domain**:
discharge is the model's *forcing input*, not a product, and the HDF `discharge_out`
is merely the conserved pass-through of that input — comparing it to observed Q is
circular. To obtain a Q-vs-Q routing fidelity metric you must run **unsteady**
HEC-RAS, which needs the plan-HDF skeleton written by Ras.exe under **Wine Mono**
(currently absent on this server: `~/.wine/drive_c/windows/mono` not installed — see
triplet `unsteady_needs_mono`). `validate_hecras.py` now returns
`{"status": "N/A_domain", ...}` in this case instead of raising, so the result is
reported as an honest domain-N/A rather than a null/failed fit. See also
format_spec known_issue `validating_wrong_variable`.
