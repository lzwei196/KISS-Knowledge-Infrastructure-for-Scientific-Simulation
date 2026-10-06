# Surrogate stage docs (NOT the KINEROS2 model)

The seven files in this folder describe the **Python surrogate**: a lumped, daily, Green-Ampt +
two-reservoir re-implementation (`tools/run_kineros2.py`, `tools/convert_forcing_to_kineros2.py`,
`tools/convert_soil_to_kineros2.py`, `tools/parse_output_kineros2.py`) that this KI used before the
real USDA-ARS engine was installed (2026-10-06).

- Its daily basin runs (e.g. the Huaihe at Bengbu, 121,330 km2, NSE 0.851 recorded in the models DB)
  are **not KINEROS2 results** and are not a valid KINEROS2 use: the real model is an event model
  (one storm, minute steps) for small watersheds (hectares to a few km2).
- Never quote surrogate numbers as KINEROS2 skill. The real engine pipeline is documented in the
  stage docs one folder up (`docs/s1_*.md` ... `docs/s9_*.md`) and run by `tools/run_kineros2_engine.py`.

Kept for history and for comparing old runs only.
