---
name: pysteps
description: >-
  STEPS cascade-based stochastic nowcasting scheme (Bowler et al. 2006 / Seed 2003 S-PROG
  lineage) as realized in pysteps 1.20.0. Covers Short-term probabilistic / deterministic
  nowcasting of 2-D radar precipitation intensity fields; Motion (advection) field
  estimation from a past radar frame sequence via optical flow. Use when the task involves
  running, configuring, calibrating or interpreting pySTEPS.
version: 1.20.0
model: pySTEPS
domain: precipitation_nowcasting
not_a_hydrological_model: True
---

# pySTEPS — Knowledge Infrastructure

## Identity

pySTEPS is a Python library (not a standalone binary) for **probabilistic precipitation
nowcasting** from radar QPE sequences. It is NOT a hydrological model and cannot be
validated directly against hydrocraft.db station discharge or water-quality observations.

- Install path: `KISSPATH_HOME/.local/lib/python3.12/site-packages/pysteps/`
- Config file: `pystepsrc` (same dir)
- Version: 1.20.0 (via `importlib.metadata`; module itself has no `__version__` attr)

## Inputs

Sequence of 2-D precipitation intensity fields (mm/h) on a uniform radar grid, typically
3–4 past frames at 5–15 min cadence. Supported importers: BoM RF3, DWD HDF5, FMI PGM,
KNMI HDF5, MCH GIF, OPERA HDF5, SAF NetCDF.

## Outputs

Deterministic or ensemble nowcast of N future frames on the same grid, in mm/h.

## Validation strategy

pySTEPS is a physics/signal-processing library, not a forecasting model. It cannot be
validated against hydrocraft.db discharge or water-quality observations. The correct
validation is against a **synthetic analytical solution** with known ground truth, using
`comparison_type='analytical'`.

Because no real radar archive is mounted (downloading violates KDT offline philosophy),
this KI validates pySTEPS against a **synthetic advected precipitation sequence** where
the true future frames are known exactly. This exercises the real compiled code paths
(Proesmans motion estimation, extrapolation nowcast, det_cat_fct/fss verification)
end-to-end.

## Default test

`synthetic_advection`: 200x200 grid, Gaussian blob (sigma=18, peak=8 mm/h) translating
at (u=2, v=1) px/frame. 4 past frames → Proesmans motion → extrapolation nowcast of
5 lead times → score against held-out truth frames.

Metrics: CSI, POD, FAR (threshold 0.5 mm/h), FSS (scale 20 px). Expected: mean CSI > 0.95,
mean FSS > 0.99.

## Execution

```bash
cd KISSPATH_KI_ROOT/pySTEPS/knowledge_infrastructure
python3 preflight_check.py           # verify environment
python3 diagnostics/run_synthetic_advection.py   # run test, writes diagnostics/last_run.json
```

The runner outputs JSON to stdout and writes `diagnostics/last_run.json` with per-lead
CSI/POD/FAR/FSS scores plus timing. A `tester_result.json` is also written to the KI
root for the orchestrator.

## Units

pySTEPS operates on 2-D precipitation fields. The primary units encountered are:

| Unit | Description | Typical Range | Context |
|------|-------------|---------------|---------|
| **mm/h** | Rainfall intensity (linear) | 0 - 100 | Standard input/output unit for all pysteps nowcast routines. All motion estimation and extrapolation operate in this space or its log transform. |
| **dBZ** | Radar reflectivity (logarithmic) | -10 to 60 | Raw radar measurement unit. Must be converted to mm/h before nowcasting via the Marshall-Palmer Z-R relation: R = (10^(dBZ/10) / 200)^(1/1.6). Use `pysteps.utils.conversion.dB_transform`. |
| **dBR** | Log-transformed rainfall rate | -10 to 20 | dBR = 10 * log10(R). Used internally by STEPS cascade decomposition for spectral analysis. The log domain reduces the dynamic range and makes the precipitation field more Gaussian-like, improving FFT-based operations. |
| **mm** | Accumulated precipitation depth | 0 - 200+ | Obtained by integrating mm/h over time. Accumulation = sum(rate_mm_h * dt_hours). Common accumulation periods: 5 min, 10 min, 15 min, 1 h, 6 h, 24 h. |

**Critical unit conversion rules:**
- dBZ to mm/h: `R = (10**(dBZ/10) / 200)**(1/1.6)` (Marshall-Palmer, default Z=200*R^1.6)
- mm/h to dBR: `dBR = 10 * log10(R)` (requires R > 0; set threshold first)
- mm/h to mm (accumulated): `depth_mm = rate_mm_h * timestep_minutes / 60.0`
- Radar frame timestep (`metadata['accutime']`) is in **minutes**. Common values: 5 (OPERA, BoM), 10 (FMI), 15 (DWD).

**Accumulation period pitfalls:**
- A "5-minute rainfall rate" in mm/h means the average rate during a 5-min window, NOT 5 mm/h.
- To get 1-hour accumulation from 5-min frames: sum 12 consecutive frames (each in mm/h) and multiply each by 5/60.
- STEPS ensemble output is instantaneous rate at each lead time, not accumulated between lead times.

## Parameters

Key parameters controlling pySTEPS nowcast behavior:

### Motion estimation parameters

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| `motion_method` | `'LK'` | `'LK'`, `'VET'`, `'proesmans'`, `'DARTS'` | Optical flow algorithm. Lucas-Kanade (LK) is robust for most cases. Proesmans is faster for uniform translation. VET and DARTS handle rotational/divergent flow. |
| `fd_method` (LK) | `'shitomasi'` | `'shitomasi'`, `'blob'`, `'tstorm'` | Feature detection method for Lucas-Kanade. Shi-Tomasi corner detection is the default. |
| `maxCorners` (LK) | 500 | 100 - 5000 | Maximum features to track. Increase for large domains or sparse precipitation. |
| `qualityLevel` (LK) | 0.1 | 0.001 - 0.5 | Minimum feature quality. Lower values detect more features in weak precipitation. |
| `winSize` (LK) | (50, 50) | (10,10) - (100,100) | Lucas-Kanade window size in pixels. Larger windows capture large-scale motion but miss local variations. |
| `n_iter` (VET) | 3 | 1 - 10 | Number of VET optimization iterations. More iterations improve accuracy but increase runtime. |

### Nowcast parameters

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| `n_leadtimes` | varies | 1 - 72 | Number of forecast time steps. At 5-min resolution: 12 = 1 hour, 36 = 3 hours, 72 = 6 hours. Skill degrades significantly beyond 2-3 hours. |
| `n_ens_members` | 24 | 1 - 200 | Number of STEPS ensemble members. Minimum 20 for stable probability estimates. 48-100 for research. 1 = deterministic (no stochastic perturbation). |
| `n_cascade_levels` | 6 | 1 - 12 | Number of cascade decomposition levels (STEPS). Should satisfy 2^n_levels <= min(nx, ny). For 256x256: max 8. For 512x512: max 9. More levels capture finer spatial scales. |
| `noise_method` | `'nonparametric'` | `'nonparametric'`, `'parametric'`, `None` | Stochastic noise generation method for STEPS. Nonparametric preserves observed power spectrum. None disables noise (deterministic nowcast). |
| `ar_order` | 2 | 1 - 3 | Autoregressive model order for temporal evolution of cascade levels. AR(2) is standard. AR(1) is simpler but less accurate. |
| `extrap_method` | `'semilagrangian'` | `'semilagrangian'`, `'eulerian'` | Advection scheme. Semi-Lagrangian is standard (backwards trajectory). Eulerian is simpler but more diffusive. |
| `interp_order` | 1 | 1 - 3 | Interpolation order for semi-Lagrangian advection: 1=bilinear (fast, diffusive), 3=bicubic (sharper, may overshoot). |
| `n_iter` (extrap) | 1 | 1 - 5 | Sub-steps per advection step. Increase if max displacement exceeds grid spacing (CFL > 1). |

### Verification parameters

| Parameter | Description | Common Values |
|-----------|-------------|---------------|
| `thr` (det_cat_fct) | Rainfall threshold for categorical scores (mm/h) | 0.1 (any rain), 0.5 (light), 1.0 (moderate), 5.0 (heavy), 10.0 (intense) |
| `scale` (FSS) | Spatial scale for Fractions Skill Score in pixels | 1, 5, 10, 20, 50 — larger scales are more forgiving of spatial displacement errors |
| `scores` (det_cat_fct) | List of categorical scores to compute | `['CSI', 'POD', 'FAR', 'HSS', 'ETS']` |

### Domain size guidelines

| Domain (pixels) | Recommended n_cascade_levels | Max n_ens_members (16 GB RAM) | Typical use case |
|-----------------|------------------------------|-------------------------------|------------------|
| 128 x 128 | 4-6 | 200 | City-scale, single radar |
| 256 x 256 | 6-7 | 100 | Regional composite |
| 512 x 512 | 6-8 | 48 | National composite (small country) |
| 1024 x 1024 | 6-8 | 20 | Continental composite |
| 2048 x 2048 | 6-8 | 10 | Full OPERA European composite |

## Key variables

| Variable | Source | Unit |
|----------|--------|------|
| precipitation_intensity | nowcast grid cells | mm/h |
| CSI | `pysteps.verification.det_cat_fct` | dimensionless [0,1] |
| FSS | `pysteps.verification.fss` | dimensionless [0,1] |

For real-data extension, see `examples/README.md`.
