# s4 PET Computation

## Purpose

Compute potential evapotranspiration internally with the Hamon method from daily mean temperature and basin latitude. This stage has no separate CLI; it is executed inside `tools/run_kineros2.py` before the Green-Ampt and routing calculations.

## Inputs

- `temp_deg_c` from the stage 1 forcing JSON.
- Dates from the same forcing JSON; `tools/run_kineros2.py` converts them to day-of-year values.
- `--latitude` in degrees, defaulting to `33.0` if not supplied.

## Outputs

- An internal PET array in `mm/d` used by soil moisture accounting in `tools/run_kineros2.py::kineros2_lumped`.
- A runner log line such as `PET computed (Hamon method, lat=33.0): mean = ... mm/d`.

## Procedure

1. Confirm the runner exposes latitude and mode options:

   ```bash
   python tools/run_kineros2.py --help
   ```

2. Run either simulation or calibration. PET is computed automatically after forcing validation:

   ```bash
   python tools/run_kineros2.py \
     --mode simulate \
     --forcing work/forcing.json \
     --params work/params.json \
     --basin-area-km2 121330 \
     --latitude 33 \
     --output work/simulation.json
   ```

3. Do not create or pass a separate PET file. The KI's PET function is `hamon_pet` in `tools/run_kineros2.py`.

## Verification

Check the runner log in stdout or in `work/simulation.json`. It should include a PET mean in `mm/d` and should not report the forcing validation errors from `validate_forcing`. If the mean temperature is above 100, the runner returns an error before PET is used.

## Traps

- `dt_kineros2_003`: Temperature left in Kelvin can make Hamon PET absurdly high and drain the soil immediately.
- `dt_kineros2_001`: Precipitation that is too small can be misread as a PET problem because runoff disappears; verify forcing units first.
- `dt_kineros2_025`: First-year hydrograph errors can be initial soil moisture spinup, not PET; keep a spinup year out of metrics.

## Example

The PET stage is visible through the simulation log:

```bash
python tools/run_kineros2.py \
  --mode simulate \
  --forcing work/forcing_1980_1990.json \
  --params work/params_silt_loam.json \
  --basin-area-km2 121330 \
  --latitude 33 \
  --output work/simulation_with_pet_log.json
```
