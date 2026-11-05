# SURROGATE stage docs (not the QUINCY engine)

These five documents describe the old Python stand-in (`tools/run_quincy.py`,
`convert_forcing_to_quincy.py`, `convert_parameters_to_quincy.py`, `parse_output_quincy.py`):
an analytic re-implementation with a monthly step and no C-N-P pools. They are kept for the
record only. Numbers from that pipeline are NOT QUINCY results.

The real engine pipeline is documented in `../s0_configuration.md` … `../s5_validation.md`.

The stand-in's I/O and process contract (the KI's dag.yaml until 2026-10-07) is kept here as
`surrogate_quincy_analytic_dag.yaml`. Its scores (monthly, calibrated by differential evolution at
FI-Hyy 1996-2008, checked 2009-2014) are listed in `../../knowledge_infrastructure.yaml` under
`validation.surrogate_metrics_not_quincy` and are not QUINCY results.
