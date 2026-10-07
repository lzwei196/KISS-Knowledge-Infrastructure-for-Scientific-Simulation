# WASP SURROGATE (analytic Python stand-in) - NOT EPA WASP

Until 2026-10-06 this KI had only a Python re-implementation of a few WASP-style processes:
a sinusoidal seasonal temperature, a steady-state Streeter-Phelps DO, a logistic thermocline
profile and Carlson TSI (`tools/run_wasp.py`, `convert_forcing_to_wasp.py`,
`convert_parameters_to_wasp.py`, `parse_output_wasp.py`). Since 2026-10-07 the KI's default route
is the real US EPA WASP 8.5.0 engine (`tools/run_wasp_engine.py`).

This folder keeps the stand-in's own papers:
- `surrogate_wasp_analytic_dag.yaml` - its I/O and process contract (the KI's dag.yaml until 2026-10-07)
- `s1_forcing_preparation.md` ... `s4_output_parsing.md` - its stage docs
  (`../s5_calibration.md` and `../s6_tsi_analysis.md` are surrogate-only too)

Use the stand-in only when a task asks for it, and label every number it gives "surrogate".
Its old scores (Lake Erie, mostly tributary-stream samples, dt_wasp_035) are kept in
`knowledge_infrastructure.yaml` under `validation.surrogate_metrics_not_wasp`.
