# pySTEPS validation examples

## Current diagnostic
`../diagnostics/run_synthetic_advection.py` — synthetic translating Gaussian; exercises
the real motion + nowcast + verification code paths and reports CSI/POD/FAR/FSS.

## Real-data extensions (not run here)
- **OPERA / DWD RY radar archive** → set `data_sources` in `pystepsrc`, use
  `pysteps.io.archive.find_by_date` + `pysteps.io.readers.read_timeseries`, then
  `pysteps.nowcasts.steps.forecast` for ensemble nowcast; verify against held-out frames.
- **Hydrological coupling** → pipe nowcast rainfall fields as forcing into a
  rainfall-runoff model (e.g. a catchment bound to hydrocraft.db discharge stations)
  and validate the chained discharge output. pySTEPS itself is not the thing being
  scored against discharge — the coupled chain is.
