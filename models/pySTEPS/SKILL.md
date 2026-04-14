---
model: pySTEPS
version: 1.20.0
domain: precipitation_nowcasting
not_a_hydrological_model: true
---

# pySTEPS — Knowledge Infrastructure

## Identity

pySTEPS is a Python library (not a standalone binary) for **probabilistic precipitation
nowcasting** from radar QPE sequences. It is NOT a hydrological model and cannot be
validated directly against hydrocraft.db station discharge or water-quality observations.

- Install path: `/home/server/.local/lib/python3.12/site-packages/pysteps/`
- Config file: `pystepsrc` (same dir)
- Version: 1.20.0 (via `importlib.metadata`; module itself has no `__version__` attr)

## Inputs

Sequence of 2-D precipitation intensity fields (mm/h) on a uniform radar grid, typically
3–4 past frames at 5–15 min cadence. Supported importers: BoM RF3, DWD HDF5, FMI PGM,
KNMI HDF5, MCH GIF, OPERA HDF5, SAF NetCDF.

## Outputs

Deterministic or ensemble nowcast of N future frames on the same grid, in mm/h.

## Validation (this KI)

Because no real radar archive is mounted and downloading external data violates the
KDT offline philosophy, this KI validates pySTEPS against a **synthetic advected
precipitation sequence** with known ground truth. This is not a scientific skill-score
benchmark — it is a binary integration test that exercises the real compiled code
paths (motion estimation, extrapolation/STEPS nowcast, verification) end-to-end.

- **Reference:** synthetic translating Gaussian rainfall field (known truth at all lead times)
- **Model path exercised:** `lucaskanade` motion → `extrapolation.forecast` nowcast
- **Skill scores:** CSI, POD, FAR (threshold 0.5 mm/h) via `pysteps.verification.det_cat_fct`;
  FSS via `pysteps.verification.fss`
- **Runner:** `diagnostics/run_synthetic_advection.py`

For true skill evaluation, couple to a real radar archive (e.g., OPERA, DWD RY) or to
a downstream rainfall-runoff model that consumes the nowcast fields as forcing. See
`examples/README.md`.
