# Stage 4: PET Computation

## Purpose
Document the internal PET stage in `tools/run_velma.py`. PET is not a standalone CLI in this KI; it is computed inside `pet_hargreaves()` during every `velma_4layer()` timestep and then used for root-weighted actual ET extraction.

## Inputs
- `temp_K` from the forcing JSON.
- `srad_Wm2` from the forcing JSON.
- `pet_scale` from the parameter JSON or calibration vector.
- Layer storage, field capacity, wilting point, and `ROOT_FRAC` from `tools/run_velma.py`.
- References: `SKILL.md` Sections 4, 6, and 8; `dag.yaml` process modules `PET-Hargreaves` and `Evapotranspiration`; `diagnostics/triplets.yaml`.

## Outputs
- Internal daily PET in `mm/d`.
- Internal daily actual ET extracted from L1-L4 according to `ROOT_FRAC`.
- Run diagnostics in the execution JSON, including `mean_et_mm_d`.

## Procedure
Run PET only through the real VELMA engine:

```bash
python tools/run_velma.py \
  --mode simulate \
  --forcing forcing.json \
  --params params.json \
  --basin-area-km2 121330 \
  --output simulation.json
```

The implementation is in `tools/run_velma.py`:
- `pet_hargreaves(temp_K, srad_Wm2, pet_scale)` converts Kelvin to Celsius internally.
- `velma_4layer()` calls `pet_hargreaves()` before ET extraction.
- `ROOT_FRAC = [0.30, 0.40, 0.25, 0.05]`, so L4 also has a small ET sink in this implementation.

## Verification
- `simulation.json` has `status: success`.
- `output.diagnostics.mean_et_mm_d` is physically plausible for the basin and season.
- `final_swe_mm` does not grow indefinitely in warm basins or summer periods.
- Annual ET is not outside the broad range documented by `dt_velma_013`.
- PET-related warnings in the run log are absent.

## Traps
- `dt_velma_003`: Celsius input is treated as Kelvin, making PET zero and all precipitation snow.
- `dt_velma_004`: solar radiation in the wrong unit can produce very high PET or very low PET.
- `dt_velma_013`: `pet_scale` outside `[0.3, 2.5]` makes annual ET unrealistic.
- `dt_velma_015`: extreme parameter combinations can over-extract soil water and produce NaN or negative storage.
- `dag.yaml` warning: `ROOT_FRAC[3]=0.05` means this implementation extracts ET from L4, even though some text summarizes ET as L1-L3.

## Example
After a simulation, inspect the PET/ET diagnostic carried in the model output:

```bash
python -m json.tool simulation.json | rg "mean_et_mm_d|final_swe_mm|final_sw_mm"
```
