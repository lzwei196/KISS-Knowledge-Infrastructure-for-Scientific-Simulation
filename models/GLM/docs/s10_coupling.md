# s10 Coupling

## Purpose

Convert GLM lake outflow and overflow products into a CaMa-Flood-compatible lateral inflow file or CSV for downstream routing. This closes the intended HydroCraft coupling loop: CaMa/VIC inflow to GLM, GLM lake processing, then GLM outflow back to CaMa-Flood.

## Inputs

- `output/outlet_*.csv` and/or `output/overflow.csv` from s8.
- Downstream CaMa grid-cell index from s0/s3 coupling setup.
- Tool: `tools/s10_coupling/glm_to_cama_outflow.py`.

## Outputs

- NetCDF lateral inflow when `--output` ends in `.nc`, with variable `outflow` in `m3/s`.
- CSV with `time,total_flow` for non-NetCDF output.
- JSON summary with mean/max flow and total volume.

## Procedure

1. Convert GLM outlet and overflow to NetCDF:

```bash
python tools/s10_coupling/glm_to_cama_outflow.py \
  --glm_outlet output/outlet_1.csv \
  --overflow output/overflow.csv \
  --downstream_cell_idx 15 \
  --output outputs/run/cama_lateral/glm_outflow.nc
```

2. Convert overflow only when no managed outlet CSV exists:

```bash
python tools/s10_coupling/glm_to_cama_outflow.py \
  --overflow output/overflow.csv \
  --downstream_cell_idx 15 \
  --output outputs/run/cama_lateral/glm_outflow.csv
```

## Verification

- At least one of `--glm_outlet` or `--overflow` exists before running.
- The output has daily timestamps and nonnegative `outflow`/`total_flow`.
- Mean and total volume are hydrologically plausible relative to s3 inflow.
- The downstream CaMa cell is the outlet/downstream routing cell, not the lake inlet cell.

## Traps

- `dt_017`: wrong CaMa grid-cell alignment breaks water-balance and routing consistency.
- `dt_011` and `dt_012`: GLM output paths are relative to the run directory; point the coupling tool at actual s8 output files.
- `dt_031`: do not use GLM outflow as a substitute for catchment streamflow simulation at an arbitrary river gauge.

## Example

```bash
python tools/s10_coupling/glm_to_cama_outflow.py \
  --overflow output/overflow.csv \
  --downstream_cell_idx 0 \
  --output glm_outflow.csv
```
