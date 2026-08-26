# Stage 5: Execution

## Purpose
Run the VELMA-inspired lumped daily four-layer hydrology engine implemented by `tools/run_velma.py`. This is the required model execution stage; do not replace it with a simplified equation or external approximation.

## Inputs
- Forcing JSON from Stage 1 with `prec_mm_d`, `temp_K`, and `srad_Wm2`.
- Parameter JSON from Stage 2 with layer properties and process parameters.
- Basin area in `km2`.
- Optional observed discharge for calibration mode.
- References: `SKILL.md`, `dag.yaml`, `docs/validation_convention.yaml`, and `diagnostics/triplets.yaml`.

## Outputs
- Simulation JSON with `dates`, `Q_sim_m3s`, `basin_area_km2`, `parameters`, and diagnostics.
- In calibration mode, the JSON also includes aligned `Q_obs_m3s`, best-fit parameters, calibration metadata, and metrics.

## Procedure
Run a forward simulation:

```bash
python tools/run_velma.py \
  --mode simulate \
  --forcing forcing.json \
  --params params.json \
  --basin-area-km2 121330 \
  --output simulation.json
```

Run calibration when observed discharge is available:

```bash
python tools/run_velma.py \
  --mode calibrate \
  --forcing forcing.json \
  --params params.json \
  --observed /path/to/observed_Q.csv \
  --basin-area-km2 121330 \
  --cal-start 1981-01-01 \
  --cal-end 1985-12-31 \
  --maxiter 80 \
  --popsize 20 \
  --output calibrated.json
```

The daily process order is documented in `dag.yaml` and implemented in `velma_4layer()`: snow, PET, ET, infiltration, percolation, lateral flow, baseflow, then fast/slow reservoir routing.

## Verification
- The command exits successfully and writes the requested JSON.
- `output.Q_sim_m3s` length equals `output.dates` length.
- `output.diagnostics.mean_Q_m3s` and `max_Q_m3s` are finite and non-negative.
- `output.diagnostics.final_sw_mm` has four finite layer storages.
- The console log has no `[CRITICAL] Mean simulated Q < 0.01 m3/s` or non-finite discharge warning.

## Traps
- `dt_velma_010`: calibration includes the first spin-up year.
- `dt_velma_012`: routing split near 1 creates flashy peaks and little baseflow.
- `dt_velma_014`: `k_base` and `klat4` too low let L4 storage grow without bound.
- `dt_velma_015`: numerical instability appears as NaN discharge or negative soil water.
- `dt_velma_016`: saturated backflow accounting can show a water-balance residual.
- `dt_velma_021` and `dt_velma_022`: initial soil water and SWE can distort early-year discharge.

## Example
For the Bengbu validation described in `SKILL.md`:

```bash
python tools/run_velma.py \
  --mode simulate \
  --forcing forcing_bengbu_1980_1990.json \
  --params params_bengbu.json \
  --basin-area-km2 121330 \
  --output simulation_bengbu.json
```
