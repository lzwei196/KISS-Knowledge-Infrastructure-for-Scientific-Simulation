# s5 Execution

## Purpose

Run the lumped daily KINEROS2 analytic implementation. This stage performs Green-Ampt infiltration, soil moisture accounting, gravity drainage, fast/slow reservoir routing, and conversion from runoff depth to outlet discharge.

## Inputs

- Stage 1 forcing JSON with `dates`, `prec_mm_d`, and `temp_deg_c`.
- Stage 2 parameter JSON with all eight parameters.
- Basin area in `km2`.
- Basin latitude in degrees.

## Outputs

- A simulation JSON containing `output.dates`, `output.Q_sim_m3s`, `output.basin_area_km2`, selected `parameters`, summary discharge stats, and log lines.
- Daily discharge is in `m3/s`.

## Procedure

1. Confirm dependencies and the runner smoke test:

   ```bash
   python preflight_check.py
   ```

2. Run the model in simulation mode:

   ```bash
   python tools/run_kineros2.py \
     --mode simulate \
     --forcing work/forcing.json \
     --params work/params.json \
     --basin-area-km2 121330 \
     --latitude 33 \
     --output work/simulation.json
   ```

3. Preserve the JSON output for stage 6 parsing. It is the canonical output format for this KI.

## Verification

Inspect stdout or `work/simulation.json`. A successful run has `status: success`, a `Q_sim_m3s` array with the same length as the forcing dates, finite nonnegative discharge, and an output check line reporting mean and max discharge.

Run a JSON syntax check if needed:

```bash
python -m json.tool work/simulation.json >/dev/null
```

## Traps

- `dt_kineros2_008`: A forcing JSON key mismatch causes `tools/run_kineros2.py` to fail before simulation.
- `dt_kineros2_012`: Wrong basin area or conversion factor makes simulated and observed discharge differ by orders of magnitude.
- `dt_kineros2_019`: Negative discharge indicates routing instability or missing non-negativity guards.
- `dt_kineros2_021`: For the original Fortran path, missing input files trigger Fortran I/O errors; this KI's Python path checks `--forcing` and `--params`.
- `dt_kineros2_022`: Missing Python dependencies prevent execution or calibration.

## Example

Use the generated forcing and soil files from stages 1 and 2:

```bash
python tools/run_kineros2.py \
  --mode simulate \
  --forcing work/forcing_1980_1990.json \
  --params work/params_silt_loam.json \
  --basin-area-km2 121330 \
  --latitude 33 \
  --output work/simulation_bengbu.json
```
